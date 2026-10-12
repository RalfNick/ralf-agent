"""Explicit DeepSeek thinking continuation; execution remains with the engine."""

import copy
import re

from .errors import ValidationError
from .model_continuation import ContinuedModelResponse, ModelContinuation
from .model_http import HTTPModelProvider
from .model_protocol import ModelCapabilities, json_object, response, token_count
from .types import ToolCall, digest

PROTOCOL = "deepseek-thinking-v1"
_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}")
_MESSAGE_FIELDS = {"role", "content", "reasoning_content", "tool_calls"}
_CONTINUATION_FIELDS = {"protocol", "owner_digest", "decision_digest", "data"}
# CompleteModelHistory admits at most 256 calls per complete receipt group.
# Do not accept native decisions that cannot round-trip through that contract.
_MAX_CALLS = 256


def _name(value):
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ValueError("Unsupported DeepSeek function name")
    return value


def _calls(value):
    if not isinstance(value, list) or len(value) > _MAX_CALLS:
        raise ValueError("Native calls must be a bounded list")
    calls = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "type", "function"}
            or item["type"] != "function"
            or not isinstance(item["id"], str)
            or not item["id"].strip()
            or len(item["id"]) > 1024
            or not isinstance(item["function"], dict)
            or set(item["function"]) != {"name", "arguments"}
            or not isinstance(item["function"]["arguments"], str)
        ):
            raise ValueError("Unsupported native function call")
        function = item["function"]
        calls.append(
            ToolCall(_name(function["name"]), json_object(function["arguments"]), item["id"])
        )
    if len({call.call_id for call in calls}) != len(calls):
        raise ValueError("Repeated native function identity")
    return calls


def _message(value):
    if (
        not isinstance(value, dict)
        or set(value) - _MESSAGE_FIELDS
        or value.get("role") != "assistant"
        or "content" not in value
        or "reasoning_content" not in value
        or value["reasoning_content"] is not None
        and not isinstance(value["reasoning_content"], str)
        or value["content"] is not None
        and not isinstance(value["content"], str)
    ):
        raise ValueError("Unsupported native assistant message")
    native = value.get("tool_calls")
    calls = _calls([] if native is None else native)
    completed = response(value["content"], calls)
    return completed.output, calls


def _decision(output, calls):
    return {
        "output": output,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
            for call in calls
        ],
    }


def _choice(value, *, streaming=False):
    if not isinstance(value, dict):
        raise ValueError("Invalid response choice")
    index = value.get("index", 0)
    if type(index) is not int or index != 0:
        raise ValueError("Expected choice zero")
    field = "delta" if streaming else "message"
    if set(value) - {"index", field, "finish_reason", "logprobs"}:
        raise ValueError("Unsupported response choice fields")
    reason = value.get("finish_reason")
    if reason is not None and reason not in {"stop", "tool_calls"}:
        raise ValueError("Incomplete or refused model response")
    return value[field], reason


def _usage(value):
    if value is None:
        return None
    scalar = {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    }
    details = {
        "prompt_tokens_details": "cached_tokens",
        "completion_tokens_details": "reasoning_tokens",
    }
    if not isinstance(value, dict) or set(value) - scalar - set(details):
        raise ValueError("Unsupported token usage")
    counts = {name: token_count(count) for name, count in value.items() if name in scalar}
    prompt, completion = counts["prompt_tokens"], counts["completion_tokens"]
    if "total_tokens" in counts and counts["total_tokens"] != prompt + completion:
        raise ValueError("Inconsistent total token usage")
    for name, key in details.items():
        if name in value:
            detail = value[name]
            if not isinstance(detail, dict) or set(detail) - {key}:
                raise ValueError("Unsupported token usage detail")
            if key in detail:
                count = token_count(detail[key])
                if count > (prompt if name == "prompt_tokens_details" else completion):
                    raise ValueError("Token usage detail exceeds its total")
                if (
                    key == "cached_tokens"
                    and "prompt_cache_hit_tokens" in counts
                    and count != counts["prompt_cache_hit_tokens"]
                ):
                    raise ValueError("Inconsistent cached token usage")
    cache_fields = {"prompt_cache_hit_tokens", "prompt_cache_miss_tokens"}
    if any(counts[name] > prompt for name in cache_fields & counts.keys()):
        raise ValueError("Cache token usage exceeds prompt")
    if cache_fields <= counts.keys() and sum(counts[name] for name in cache_fields) != prompt:
        raise ValueError("Inconsistent prompt cache usage")
    # DeepSeek completion_tokens already includes reasoning_tokens.
    return {"input_tokens": prompt, "output_tokens": completion}


def _declarations(tools):
    names = set()
    for tool in tools:
        if set(tool) != {"type", "function"} or tool["type"] != "function":
            raise ValueError("Only function declarations are supported")
        function = tool["function"]
        if set(function) - {"name", "description", "parameters"}:
            raise ValueError("Unsupported function declaration fields")
        name = _name(function["name"])
        if name in names:
            raise ValueError("Repeated function declaration")
        names.add(name)
        if not isinstance(function["parameters"], dict) or (
            "description" in function and not isinstance(function["description"], str)
        ):
            raise ValueError("Unsupported function schema or description")
    return copy.deepcopy(tools)


def _continued_message(message, calls, identity):
    original = message["model_continuation"]
    if not isinstance(original, dict) or set(original) != _CONTINUATION_FIELDS:
        raise ValueError("Invalid continuation envelope")
    continuation = ModelContinuation(**original).to_dict()
    if (
        continuation["protocol"] != identity["protocol"]
        or continuation["owner_digest"] != identity["owner_digest"]
        or continuation["decision_digest"] != digest(_decision(message.get("content"), calls))
    ):
        raise ValueError("Continuation owner or decision changed")
    data = continuation["data"]
    if set(data) != {"message"}:
        raise ValueError("Unsupported continuation data")
    output, native_calls = _message(data["message"])
    if digest(_decision(output, native_calls)) != continuation["decision_digest"]:
        raise ValueError("Native continuation does not match original decision")
    return copy.deepcopy(data["message"])


def _messages(messages, identity, *, tools):
    native, pending = [], set()
    for message in messages:
        role = message["role"]
        allowed = {"role", "content"}
        if role == "assistant":
            allowed |= {"tool_calls", "model_continuation"}
        elif role == "tool":
            allowed |= {"tool_call_id"}
        if set(message) - allowed:
            raise ValueError("Unsupported historical message fields")
        if pending and role != "tool":
            raise ValueError("Tool result group is incomplete")
        if role == "tool":
            identifier = message.get("tool_call_id")
            if not isinstance(identifier, str) or identifier not in pending:
                raise ValueError("Unknown or repeated tool result")
            pending.remove(identifier)
            native.append(copy.deepcopy(message))
            continue
        if role != "assistant":
            native.append(copy.deepcopy(message))
            continue
        calls = _calls(message.get("tool_calls", []))
        response(message.get("content"), calls)
        if "model_continuation" in message:
            model_message = _continued_message(message, calls, identity)
        elif tools or calls:
            # The API requires reasoning for every previous assistant turn
            # when the new request declares tools, including final answers.
            raise ValueError("Thinking tool history requires original continuation evidence")
        else:
            model_message = {"role": "assistant", "content": message["content"]}
            if "tool_calls" in message:
                model_message["tool_calls"] = []
        pending = {call.call_id for call in calls}
        native.append(model_message)
    if pending:
        raise ValueError("Tool result group is incomplete")
    return native


class DeepSeekThinkingProvider(HTTPModelProvider):
    """Native thinking text/functions with explicit model-owned continuation."""

    supported = ModelCapabilities()
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
        reasoning_effort="high",
        top_p=None,
        stop=None,
        stream=False,
        capabilities=None,
    ):
        self.reasoning_effort, self.json_mode = reasoning_effort, json_mode
        self._configure(
            model,
            api_key,
            "DEEPSEEK_API_KEY",
            base_url,
            max_output_tokens,
            timeout,
            client,
            None,
            top_p,
            stop,
            None,
            stream,
            capabilities,
        )

    @property
    def identity(self):
        value = self._configuration("deepseek-thinking-completions")
        if (
            not isinstance(self.reasoning_effort, str)
            or self.reasoning_effort not in {"low", "high", "max"}
            or self.top_p is not None
            and self.top_p < 0.95
            or self.temperature is not None
        ):
            raise ValidationError("Invalid DeepSeek thinking generation parameter")
        if type(self.json_mode) is not bool or self.json_mode and self.stream_response:
            raise ValidationError("JSON object mode requires non-streaming completion")
        value.update(thinking="enabled", reasoning_effort=self.reasoning_effort)
        if self.json_mode:
            value["json_mode"] = True
        return value

    @property
    def continuation_identity(self):
        return {"protocol": PROTOCOL, "owner_digest": digest(self.identity)}

    def _body(self, messages, tools, config):
        declarations = _declarations(tools)
        native = _messages(
            messages,
            {"protocol": PROTOCOL, "owner_digest": digest(config)},
            tools=bool(declarations),
        )
        body = {
            "model": config["model"],
            "messages": native,
            "max_tokens": config["max_output_tokens"],
            "thinking": {"type": "enabled"},
            "reasoning_effort": config["reasoning_effort"],
            **config.get("generation", {}),
        }
        if declarations:
            body["tools"] = declarations
        if config.get("json_mode"):
            if not any(
                message["role"] in {"system", "user"} and "json" in message["content"].lower()
                for message in messages
            ):
                raise ValueError("JSON object mode requires an explicit JSON prompt")
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

    def _completed(self, message, usage):
        output, calls = _message(message)
        completed = response(output, calls, usage)
        if self.json_mode and not calls:
            json_object(output)
        continuation = ModelContinuation(
            protocol=PROTOCOL,
            owner_digest=digest(self.identity),
            decision_digest=digest(_decision(output, calls)),
            data={"message": message},
        )
        return ContinuedModelResponse(
            completed.output, completed.tool_calls, completed.usage, continuation=continuation
        )

    def _parse(self, text):
        value = json_object(text)
        if "error" in value:
            raise ValueError("Upstream thinking response failed")
        choices = value["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("Expected one completed choice")
        message, reason = _choice(choices[0])
        _, calls = _message(message)
        if reason is None or bool(calls) != (reason == "tool_calls"):
            raise ValueError("Tool completion does not match response")
        return self._completed(message, _usage(value.get("usage")))

    def _stream_state(self):
        return DeepSeekThinkingStream(self)


class DeepSeekThinkingStream:
    """Collect native text, reasoning, and call arguments until complete SSE."""

    def __init__(self, provider):
        self.provider = provider
        self.text, self.reasoning, self.calls = [], [], {}
        self.reasoning_present = False
        self.reason, self.usage, self.done = None, None, False

    def _tool_delta(self, values):
        if not isinstance(values, list):
            raise ValueError("Invalid tool deltas")
        seen = set()
        for item in values:
            if not isinstance(item, dict) or set(item) - {"index", "id", "type", "function"}:
                raise ValueError("Unsupported native tool delta")
            index = item["index"]
            if type(index) is not int or not 0 <= index < _MAX_CALLS or index in seen:
                raise ValueError("Invalid or repeated tool delta index")
            seen.add(index)
            function = item.get("function", {})
            if not isinstance(function, dict) or set(function) - {"name", "arguments"}:
                raise ValueError("Unsupported native function delta")
            if "type" in item and item["type"] != "function":
                raise ValueError("Unsupported streamed tool type")
            if index not in self.calls:
                # DeepSeek documents id/type/function in the first tool chunk;
                # subsequent chunks carry only argument fragments. The name
                # and id identify the call rather than being text fragments.
                # https://api-docs.deepseek.com/api/create-chat-completion/
                if (
                    not isinstance(item.get("id"), str)
                    or not item["id"].strip()
                    or len(item["id"]) > 1024
                    or item.get("type") != "function"
                ):
                    raise ValueError("Missing native tool identity")
                name = _name(function["name"])
                if any(call["id"] == item["id"] for call in self.calls.values()):
                    raise ValueError("Repeated native tool identity")
                self.calls[index] = {
                    "id": item["id"],
                    "type": "function",
                    "function": {"name": name, "arguments": ""},
                }
            call = self.calls[index]
            if (
                "id" in item
                and item["id"] != call["id"]
                or "name" in function
                and function["name"] != call["function"]["name"]
            ):
                raise ValueError("Changed streamed function identity")
            if "arguments" in function:
                if not isinstance(function["arguments"], str):
                    raise ValueError("Invalid function argument fragment")
                call["function"]["arguments"] += function["arguments"]

    def feed(self, event, data):
        if self.done or event == "error":
            raise ValueError("Data after stream completion or upstream error")
        if data == "[DONE]":
            self.done = True
            return []
        value = json_object(data)
        if "error" in value:
            raise ValueError("Upstream thinking stream failed")
        usage = value.get("usage")
        if usage is not None:
            if self.usage is not None:
                raise ValueError("Repeated stream token usage")
            self.usage = _usage(usage)
        choices = value["choices"]
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError("Expected one streamed choice")
        if not choices:
            if usage is None or self.reason is None:
                raise ValueError("Unexpected empty stream choice")
            return []
        if self.reason is not None:
            raise ValueError("Content or completion after final choice")
        delta, reason = _choice(choices[0], streaming=True)
        if (
            not isinstance(delta, dict)
            or set(delta) - _MESSAGE_FIELDS
            or delta.get("role") not in {None, "assistant"}
        ):
            raise ValueError("Unsupported native assistant delta")
        if "reasoning_content" in delta:
            self.reasoning_present = True
        for name, parts in (("content", self.text), ("reasoning_content", self.reasoning)):
            fragment = delta.get(name)
            if fragment is not None:
                if not isinstance(fragment, str):
                    raise ValueError("Invalid native text fragment")
                parts.append(fragment)
        if delta.get("tool_calls") is not None:
            self._tool_delta(delta["tool_calls"])
        if reason is not None:
            if bool(self.calls) != (reason == "tool_calls"):
                raise ValueError("Tool completion does not match stream")
            self.reason = reason
        text = delta.get("content")
        return [text] if text else []

    def finish(self):
        if not self.done or self.reason is None or not self.reasoning_present:
            raise ValueError("Thinking stream did not complete")
        if sorted(self.calls) != list(range(len(self.calls))):
            raise ValueError("Native tool indices are incomplete")
        message = {
            "role": "assistant",
            "content": "".join(self.text) if self.text else None,
            "reasoning_content": "".join(self.reasoning) if self.reasoning else None,
        }
        if self.calls:
            message["tool_calls"] = [self.calls[index] for index in sorted(self.calls)]
        return self.provider._completed(message, self.usage)
