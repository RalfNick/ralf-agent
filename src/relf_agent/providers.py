"""Chat Completions text/function protocol; no tool execution or hidden retries."""

import os
from typing import Protocol

from .errors import ValidationError
from .model_http import HTTPModelProvider
from .model_protocol import (  # noqa: F401
    ModelCapabilities,
    ModelStreamEvent,
    StreamingModelProvider,
    json_object,
    response,
    token_count,
)
from .types import ModelResponse, ToolCall


class ModelProvider(Protocol):
    identity: dict

    async def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse: ...


def _usage(value):
    if value is None:
        return None
    return {
        "input_tokens": token_count(value["prompt_tokens"]),
        "output_tokens": token_count(value["completion_tokens"]),
    }


def _chat_response(choice, usage):
    message = choice["message"]
    if not isinstance(message, dict) or message.get("role", "assistant") != "assistant":
        raise ValueError("Unsupported message")
    if message.get("refusal") is not None or choice.get("finish_reason", "stop") not in {
        "stop",
        "tool_calls",
    }:
        raise ValueError("Refused or incomplete response")
    native = message.get("tool_calls")
    native = [] if native is None else native
    if not isinstance(native, list):
        raise ValueError("Invalid tool calls")
    calls = []
    for call in native:
        if not isinstance(call, dict) or call.get("type", "function") != "function":
            raise ValueError("Unsupported tool type")
        function = call["function"]
        calls.append(ToolCall(function["name"], json_object(function["arguments"]), call["id"]))
    if "finish_reason" in choice and bool(calls) != (choice["finish_reason"] == "tool_calls"):
        raise ValueError("Tool completion does not match response")
    if calls and message.get("reasoning_content"):
        raise ValueError("Opaque reasoning tool continuation is unsupported")
    return response(message.get("content"), calls, _usage(usage))


class ChatStream:
    def __init__(self):
        self.text, self.calls, self.usage, self.reason, self.done = [], {}, None, None, False
        self.reasoning = False

    def feed(self, event, data):
        if self.done or event == "error":
            raise ValueError("Data after stream completion")
        if data == "[DONE]":
            self.done = True
            return []
        value = json_object(data)
        if "error" in value:
            raise ValueError("Upstream stream error")
        if value.get("usage") is not None:
            self.usage = _usage(value["usage"])
        choices = value["choices"]
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError("Unsupported stream choices")
        if not choices:
            return []
        choice = choices[0]
        if choice.get("index", 0) != 0:
            raise ValueError("Unsupported stream choice")
        delta = choice["delta"]
        if (
            not isinstance(delta, dict)
            or delta.get("role", "assistant") != "assistant"
            or delta.get("refusal") is not None
        ):
            raise ValueError("Unsupported stream delta")
        if self.reason is not None and (
            delta or choice.get("finish_reason") not in {None, self.reason}
        ):
            raise ValueError("Content after final choice")
        text = delta.get("content")
        if delta.get("reasoning_content") is not None:
            if not isinstance(delta["reasoning_content"], str):
                raise ValueError("Unsupported reasoning delta")
            self.reasoning = self.reasoning or bool(delta["reasoning_content"])
        if text is not None:
            if not isinstance(text, str):
                raise ValueError("Unsupported stream text")
            self.text.append(text)
        calls = delta.get("tool_calls")
        calls = [] if calls is None else calls
        if not isinstance(calls, list):
            raise ValueError("Invalid tool deltas")
        for item in calls:
            index = item["index"]
            if type(index) is not int or not 0 <= index < 1000:
                raise ValueError("Invalid tool index")
            call = self.calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if item.get("type", "function") != "function":
                raise ValueError("Unsupported tool type")
            fields = {"id": item.get("id"), **item.get("function", {})}
            for key in ("id", "name", "arguments"):
                if fields.get(key) is not None:
                    if not isinstance(fields[key], str):
                        raise ValueError("Invalid tool fragment")
                    call[key] += fields[key]
        if choice.get("finish_reason") is not None:
            self.reason = choice["finish_reason"]
        return [text] if text else []

    def finish(self):
        if not self.done or self.reason not in {"stop", "tool_calls"}:
            raise ValueError("Stream did not finish successfully")
        calls = [
            ToolCall(value["name"], json_object(value["arguments"]), value["id"])
            for _, value in sorted(self.calls.items())
        ]
        if (calls and self.reason != "tool_calls") or (not calls and self.reason != "stop"):
            raise ValueError("Tool completion does not match response")
        if calls and self.reasoning:
            raise ValueError("Opaque reasoning tool continuation is unsupported")
        return response("".join(self.text) or None, calls, self.usage)


class OpenAIChatProvider(HTTPModelProvider):
    def __init__(
        self,
        model,
        *,
        api_key=None,
        base_url="https://api.openai.com/v1",
        max_output_tokens=1024,
        token_parameter="max_completion_tokens",
        json_mode=False,
        timeout=60,
        client=None,
        temperature=None,
        top_p=None,
        stop=None,
        seed=None,
        stream=False,
        capabilities=None,
    ):
        self.token_parameter = token_parameter
        self.json_mode = json_mode
        self._configure(
            model,
            api_key,
            "OPENAI_API_KEY",
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
        value = self._configuration("openai-chat-completions")
        if not isinstance(self.token_parameter, str) or self.token_parameter not in {
            "max_tokens",
            "max_completion_tokens",
        }:
            raise ValidationError("Invalid output token parameter")
        value["token_parameter"] = self.token_parameter
        if type(self.json_mode) is not bool or self.json_mode and self.stream_response:
            raise ValidationError(
                "JSON object mode requires a boolean and non-streaming completion"
            )
        if self.json_mode:
            value["json_mode"] = True
        return value

    def _body(self, messages, tools, config):
        if any(item.get("reasoning_content") for item in messages):
            raise ValidationError("Opaque reasoning history is unsupported")
        body = {
            "model": config["model"],
            "messages": messages,
            config["token_parameter"]: config["max_output_tokens"],
            **config.get("generation", {}),
        }
        if tools:
            body["tools"] = tools
        if config.get("json_mode"):
            if not any(
                m.get("role") in {"system", "user"}
                and isinstance(m.get("content"), str)
                and "json" in m["content"].lower()
                for m in messages
            ):
                raise ValidationError("JSON object mode requires an explicit JSON prompt")
            body["response_format"] = {"type": "json_object"}
        return config["base_url"] + "/chat/completions", body

    def _prepared(self, messages, tools, *, streaming=False):
        if streaming and self.json_mode:
            raise ValidationError("JSON object mode supports only non-streaming completion")
        return super()._prepared(messages, tools, streaming=streaming)

    def _headers(self, key):
        return {"Authorization": f"Bearer {key}"}

    def _stream_body(self, url, body):
        return url, {**body, "stream": True, "stream_options": {"include_usage": True}}

    def _parse(self, text):
        value = json_object(text)
        if not isinstance(value["choices"], list) or len(value["choices"]) != 1:
            raise ValueError("Expected one response choice")
        result = _chat_response(value["choices"][0], value.get("usage"))
        if self.json_mode and not result.tool_calls:
            json_object(result.output)
        return result

    def _stream_state(self):
        return ChatStream()


class DeepSeekChatProvider(OpenAIChatProvider):
    """Explicit non-thinking preset; opaque reasoning continuations are unsupported."""

    allow_seed = False

    def __init__(
        self,
        model,
        *,
        api_key=None,
        base_url="https://api.deepseek.com",
        json_mode=False,
        max_output_tokens=1024,
        timeout=60,
        client=None,
        temperature=None,
        top_p=None,
        stop=None,
        stream=False,
        capabilities=None,
    ):
        key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not isinstance(key, str) or not key:
            raise ValidationError("Provide api_key or set DEEPSEEK_API_KEY")
        super().__init__(
            model,
            api_key=key,
            base_url=base_url,
            max_output_tokens=max_output_tokens,
            token_parameter="max_tokens",
            json_mode=json_mode,
            timeout=timeout,
            client=client,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
            stream=stream,
            capabilities=capabilities,
        )

    @property
    def identity(self):
        value = super().identity
        if self.top_p == 0:
            raise ValidationError("DeepSeek top_p must be greater than zero")
        value.update(kind="deepseek-chat-completions", thinking="disabled")
        return value

    def _body(self, messages, tools, config):
        url, body = super()._body(messages, tools, config)
        body["thinking"] = {"type": "disabled"}
        return url, body
