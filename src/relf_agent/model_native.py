"""Native Messages and GenerateContent protocols with explicit capability limits."""

import copy
import re

from .errors import ValidationError
from .model_http import HTTPModelProvider
from .model_protocol import ModelCapabilities, json_object, response, token_count
from .types import ToolCall


def _anthropic_usage(value):
    if value is None:
        return None
    inputs = token_count(value["input_tokens"])
    for key in ("cache_read_input_tokens", "cache_creation_input_tokens"):
        inputs += token_count(value.get(key, 0))
    return {"input_tokens": inputs, "output_tokens": token_count(value["output_tokens"])}


def _anthropic_response(value):
    if value.get("role") != "assistant" or value.get("stop_reason") not in {
        "end_turn",
        "tool_use",
        "stop_sequence",
    }:
        raise ValueError("Unsupported or incomplete message")
    blocks = value["content"]
    if not isinstance(blocks, list):
        raise ValueError("Invalid message content")
    text, calls = [], []
    for block in blocks:
        if block["type"] == "text" and isinstance(block.get("text"), str):
            text.append(block["text"])
        elif block["type"] == "tool_use" and isinstance(block.get("input"), dict):
            calls.append(ToolCall(block["name"], block["input"], block["id"]))
        else:
            raise ValueError("Unsupported native content block")
    if bool(calls) != (value["stop_reason"] == "tool_use"):
        raise ValueError("Tool completion does not match message")
    return response("".join(text) or None, calls, _anthropic_usage(value.get("usage")))


def _anthropic_messages(messages):
    system, native, ids, answered = [], [], set(), set()
    for message in messages:
        if set(message) - {"role", "content", "tool_calls", "tool_call_id"}:
            raise ValueError("Native protocol cannot preserve these message fields")
        role, content = message["role"], message.get("content")
        if role == "system":
            system.append(content)
            continue
        blocks = [{"type": "text", "text": content}] if content else []
        if role == "assistant":
            calls = message.get("tool_calls", [])
            if not isinstance(calls, list):
                raise ValueError("Invalid tool history")
            for call in calls:
                identifier = call["id"]
                if (
                    not isinstance(identifier, str)
                    or not identifier
                    or identifier in ids
                    or call.get("type", "function") != "function"
                ):
                    raise ValueError("Invalid tool history identity")
                ids.add(identifier)
                function = call["function"]
                if not isinstance(function["name"], str) or not function["name"]:
                    raise ValueError("Invalid historical tool name")
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": identifier,
                        "name": function["name"],
                        "input": json_object(function["arguments"]),
                    }
                )
        elif role == "tool":
            identifier = message.get("tool_call_id")
            if not isinstance(identifier, str) or identifier not in ids or identifier in answered:
                raise ValueError("Unknown or repeated tool result")
            answered.add(identifier)
            role, blocks = (
                "user",
                [{"type": "tool_result", "tool_use_id": identifier, "content": content}],
            )
        if not blocks:
            raise ValueError("Empty native message")
        if native and native[-1]["role"] == role:
            native[-1]["content"].extend(blocks)
        else:
            native.append({"role": role, "content": blocks})
    return "\n\n".join(system), native


class AnthropicStream:
    def __init__(self):
        self.started, self.done, self.reason = False, False, None
        self.blocks, self.open, self.usage = {}, set(), {}

    def feed(self, event, data):
        value = json_object(data)
        kind = value["type"]
        if event is not None and event != kind:
            raise ValueError("Mismatched SSE event")
        if kind == "ping":
            return []
        if self.done or kind == "error":
            raise ValueError("Native stream error or data after completion")
        if kind == "message_start":
            if self.started or value["message"]["role"] != "assistant":
                raise ValueError("Invalid message start")
            self.started = True
            usage = value["message"].get("usage")
            if usage is not None:
                if not isinstance(usage, dict):
                    raise ValueError("Invalid stream usage")
                self.usage.update(usage)
            return []
        if not self.started:
            raise ValueError("Missing message start")
        if kind in {"content_block_start", "content_block_delta", "content_block_stop"}:
            index = value["index"]
            if type(index) is not int or not 0 <= index < 1000 or self.reason is not None:
                raise ValueError("Invalid native block index or order")
            if kind == "content_block_start":
                if index in self.blocks:
                    raise ValueError("Repeated content block")
                block = copy.deepcopy(value["content_block"])
                if block["type"] not in {"text", "tool_use"}:
                    raise ValueError("Unsupported native stream block")
                if block["type"] == "text" and not isinstance(block.get("text"), str):
                    raise ValueError("Invalid text block")
                if block["type"] == "tool_use" and not isinstance(block.get("input"), dict):
                    raise ValueError("Invalid tool block")
                block["_partial"] = ""
                block["_saw_delta"] = False
                self.blocks[index] = block
                self.open.add(index)
                return [block["text"]] if block["type"] == "text" and block["text"] else []
            if index not in self.open:
                raise ValueError("Content block is not open")
            block = self.blocks[index]
            if kind == "content_block_stop":
                self.open.remove(index)
                return []
            delta = value["delta"]
            if (
                delta["type"] == "text_delta"
                and block["type"] == "text"
                and isinstance(delta.get("text"), str)
            ):
                block["text"] += delta["text"]
                return [delta["text"]] if delta["text"] else []
            if (
                delta["type"] == "input_json_delta"
                and block["type"] == "tool_use"
                and block["input"] == {}
                and isinstance(delta.get("partial_json"), str)
            ):
                block["_partial"] += delta["partial_json"]
                block["_saw_delta"] = True
                return []
            raise ValueError("Unsupported native block delta")
        if kind == "message_delta":
            if self.open:
                raise ValueError("Message ended with open content")
            if value["delta"].get("stop_reason") is not None:
                if self.reason is not None and self.reason != value["delta"]["stop_reason"]:
                    raise ValueError("Changed stop reason")
                self.reason = value["delta"]["stop_reason"]
            if value.get("usage") is not None:
                if not isinstance(value["usage"], dict):
                    raise ValueError("Invalid stream usage")
                self.usage.update(value["usage"])
            return []
        if kind == "message_stop" and not self.open and self.reason is not None:
            self.done = True
            return []
        raise ValueError("Unsupported native stream event")

    def finish(self):
        if not self.done:
            raise ValueError("Native stream did not complete")
        blocks = []
        for _, original in sorted(self.blocks.items()):
            block = copy.deepcopy(original)
            partial = block.pop("_partial")
            saw_delta = block.pop("_saw_delta")
            if block["type"] == "tool_use" and saw_delta:
                block["input"] = json_object(partial)
            blocks.append(block)
        return _anthropic_response(
            {
                "role": "assistant",
                "content": blocks,
                "stop_reason": self.reason,
                "usage": self.usage or None,
            }
        )


class AnthropicProvider(HTTPModelProvider):
    max_temperature = 1
    allow_seed = False

    def __init__(
        self,
        model,
        *,
        api_key=None,
        base_url="https://api.anthropic.com/v1",
        api_version="2023-06-01",
        max_output_tokens=1024,
        timeout=60,
        client=None,
        temperature=None,
        top_p=None,
        stop=None,
        stream=False,
        capabilities=None,
    ):
        self.api_version = api_version
        self._configure(
            model,
            api_key,
            "ANTHROPIC_API_KEY",
            base_url,
            max_output_tokens,
            timeout,
            client,
            temperature,
            top_p,
            stop,
            None,
            stream,
            capabilities,
        )

    @property
    def identity(self):
        value = self._configuration("anthropic-messages")
        if (
            not isinstance(self.api_version, str)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.api_version) is None
        ):
            raise ValidationError("Invalid Anthropic API version")
        value["api_version"] = self.api_version
        return value

    def _headers(self, key):
        return {"x-api-key": key, "anthropic-version": self.api_version}

    def _body(self, messages, tools, config):
        system, messages = _anthropic_messages(messages)
        options = copy.deepcopy(config.get("generation", {}))
        if "stop" in options:
            options["stop_sequences"] = options.pop("stop")
        body = {
            "model": config["model"],
            "max_tokens": config["max_output_tokens"],
            "messages": messages,
            **options,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"].get("description", ""),
                    "input_schema": item["function"]["parameters"],
                }
                for item in tools
            ]
        return config["base_url"] + "/messages", body

    def _stream_body(self, url, body):
        return url, {**body, "stream": True}

    def _parse(self, text):
        return _anthropic_response(json_object(text))

    def _stream_state(self):
        return AnthropicStream()


def _gemini_usage(value):
    if value is None:
        return None
    return {
        "input_tokens": token_count(value["promptTokenCount"]),
        "output_tokens": token_count(value["candidatesTokenCount"])
        + token_count(value.get("thoughtsTokenCount", 0)),
    }


def _gemini_candidate(value):
    if value.get("promptFeedback", {}).get("blockReason"):
        raise ValueError("Blocked model response")
    candidates = value["candidates"]
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("Expected one model candidate")
    candidate = candidates[0]
    content = candidate["content"]
    if content.get("role", "model") != "model" or not isinstance(content["parts"], list):
        raise ValueError("Unsupported native content")
    text = []
    for part in content["parts"]:
        if set(part) - {"text", "thought", "thoughtSignature"} or not isinstance(
            part.get("text"), str
        ):
            raise ValueError("This Gemini adapter supports text responses only")
        if type(part.get("thought", False)) is not bool:
            raise ValueError("Invalid thought marker")
        if not part.get("thought"):
            text.append(part["text"])
    return text, candidate.get("finishReason")


class GeminiStream:
    def __init__(self):
        self.text, self.usage, self.reason = [], None, None

    def feed(self, event, data):
        value = json_object(data)
        if "error" in value or event == "error":
            raise ValueError("Upstream stream error")
        if value.get("usageMetadata") is not None:
            self.usage = _gemini_usage(value["usageMetadata"])
        if "candidates" not in value and value.get("usageMetadata") is not None:
            return []
        if self.reason is not None:
            raise ValueError("Content after final candidate")
        text, reason = _gemini_candidate(value)
        self.text.extend(text)
        self.reason = reason
        return [item for item in text if item]

    def finish(self):
        if self.reason != "STOP":
            raise ValueError("Native stream did not finish successfully")
        return response("".join(self.text), [], self.usage)


class GeminiProvider(HTTPModelProvider):
    supported = ModelCapabilities(tools=False)

    def __init__(
        self,
        model,
        *,
        api_key=None,
        base_url="https://generativelanguage.googleapis.com/v1beta",
        max_output_tokens=1024,
        timeout=60,
        client=None,
        temperature=None,
        top_p=None,
        stop=None,
        seed=None,
        stream=False,
        capabilities=None,
    ):
        self._configure(
            model,
            api_key,
            "GEMINI_API_KEY",
            base_url,
            max_output_tokens,
            timeout,
            client,
            temperature,
            top_p,
            stop,
            seed,
            stream,
            capabilities,
        )

    @property
    def identity(self):
        value = self._configuration("gemini-generate-content-text")
        if re.fullmatch(r"[A-Za-z0-9_.-]+", self.model) is None:
            raise ValidationError("Use a Gemini Developer API model name without a path")
        return value

    def _headers(self, key):
        return {"x-goog-api-key": key}

    def _body(self, messages, tools, config):
        system, native = [], []
        for item in messages:
            if set(item) - {"role", "content"}:
                raise ValueError("Native text protocol cannot preserve these message fields")
            if item["role"] == "system":
                system.append(item["content"])
            else:
                role = "model" if item["role"] == "assistant" else "user"
                part = {"text": item["content"]}
                if native and native[-1]["role"] == role:
                    native[-1]["parts"].append(part)
                else:
                    native.append({"role": role, "parts": [part]})
        names = {
            "temperature": "temperature",
            "top_p": "topP",
            "stop": "stopSequences",
            "seed": "seed",
        }
        options = {names[key]: value for key, value in config.get("generation", {}).items()}
        body = {
            "contents": native,
            "generationConfig": {"maxOutputTokens": config["max_output_tokens"], **options},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        return config["base_url"] + "/models/" + config["model"] + ":generateContent", body

    def _stream_body(self, url, body):
        return url.removesuffix(":generateContent") + ":streamGenerateContent?alt=sse", body

    def _parse(self, text):
        value = json_object(text)
        parts, reason = _gemini_candidate(value)
        if reason != "STOP":
            raise ValueError("Incomplete or refused model response")
        return response("".join(parts), [], _gemini_usage(value.get("usageMetadata")))

    def _stream_state(self):
        return GeminiStream()
