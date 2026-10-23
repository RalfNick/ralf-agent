"""Text/function protocol contracts and pure validation; no execution authority."""

import copy
import json
import math
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Protocol
from urllib.parse import urlsplit

from .errors import ValidationError
from .types import ModelResponse, ToolCall, canonical


@dataclass(frozen=True)
class ModelCapabilities:
    text: bool = True
    tools: bool = True
    streaming: bool = True

    def __post_init__(self):
        if any(type(value) is not bool for value in asdict(self).values()):
            raise ValidationError("Model capabilities must be booleans")


@dataclass(frozen=True)
class ModelStreamEvent:
    kind: str
    text: str = ""
    response: ModelResponse | None = None

    def __post_init__(self):
        if self.kind == "text":
            if not isinstance(self.text, str) or self.response is not None:
                raise ValidationError("Text event requires text only")
        elif self.kind == "response":
            if self.text or not isinstance(self.response, ModelResponse):
                raise ValidationError("Response event requires a complete ModelResponse")
            canonical(asdict(self.response))
            object.__setattr__(self, "response", copy.deepcopy(self.response))
        else:
            raise ValidationError("Unsupported model stream event")


class StreamingModelProvider(Protocol):
    capabilities: ModelCapabilities

    def stream(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[ModelStreamEvent]: ...


def json_object(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate response key")
            value[key] = item
        return value

    def invalid(value):
        raise ValueError("Non-finite response number")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    try:
        canonical(value)
    except ValidationError as exc:
        raise ValueError("Invalid JSON response") from exc
    return value


def token_count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Invalid token usage")
    return value


def response(output, calls, usage=None):
    if not calls and (not isinstance(output, str) or not output.strip()):
        raise ValueError("No final content or tool calls")
    if output is not None and not isinstance(output, str):
        raise ValueError("Unsupported content")
    ids = set()
    for call in calls:
        if (
            not isinstance(call, ToolCall)
            or not isinstance(call.name, str)
            or not call.name.strip()
            or not isinstance(call.arguments, dict)
            or not isinstance(call.call_id, str)
            or not call.call_id
            or call.call_id in ids
        ):
            raise ValueError("Invalid tool call")
        ids.add(call.call_id)
    if usage is not None:
        token_count(usage["input_tokens"])
        token_count(usage["output_tokens"])
    return ModelResponse(output, tuple(calls), usage)


def configuration(model, base_url, max_output_tokens, timeout):
    if not isinstance(model, str) or not model.strip():
        raise ValidationError("Model must be a non-empty string")
    if not isinstance(base_url, str):
        raise ValidationError("Base URL must be HTTP(S) without credentials or query")
    try:
        url = urlsplit(base_url)
    except ValueError as exc:
        raise ValidationError("Invalid model base URL") from exc
    if (
        url.scheme not in {"http", "https"}
        or not url.netloc
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValidationError("Base URL must be HTTP(S) without credentials or query")
    if type(max_output_tokens) is not int or max_output_tokens < 1:
        raise ValidationError("Output tokens must be a positive integer")
    if timeout is not None and (
        type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0
    ):
        raise ValidationError("Timeout must be positive finite seconds or None")


def generation(temperature, top_p, stop, seed, *, max_temperature=2, allow_seed=True):
    values = {}
    for key, value, maximum in [("temperature", temperature, max_temperature), ("top_p", top_p, 1)]:
        if value is not None:
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not 0 <= value <= maximum
            ):
                raise ValidationError("Invalid model generation parameter")
            values[key] = value
    if stop is not None:
        values["stop"] = (
            [stop]
            if isinstance(stop, str)
            else list(stop)
            if isinstance(stop, (tuple, list))
            else None
        )
        if (
            not values["stop"]
            or len(values["stop"]) > 4
            or any(not isinstance(value, str) or not value for value in values["stop"])
        ):
            raise ValidationError("Stop must contain one to four non-empty strings")
    if seed is not None:
        if not allow_seed or type(seed) is not int or not -(2**63) <= seed < 2**63:
            raise ValidationError("Invalid generation seed")
        values["seed"] = seed
    return values


def request(messages, tools, capabilities):
    if not capabilities.text or (tools and not capabilities.tools):
        raise ValidationError("The configured model capability does not support this request")
    if (
        not isinstance(messages, list)
        or not isinstance(tools, list)
        or any(not isinstance(item, dict) for item in messages + tools)
    ):
        raise ValidationError("Model messages/tools must be lists of JSON objects")
    canonical(messages)
    canonical(tools)
    for message in messages:
        if message.get("role") not in {"system", "user", "assistant", "tool"}:
            raise ValidationError("Unsupported model message role")
        content = message.get("content")
        if not isinstance(content, str) and not (content is None and message.get("tool_calls")):
            raise ValidationError("This adapter supports text messages only")
        if not capabilities.tools and (message.get("tool_calls") or message["role"] == "tool"):
            raise ValidationError("Tool history requires tool capability")
    for tool in tools:
        function = tool.get("function")
        if (
            tool.get("type") != "function"
            or not isinstance(function, dict)
            or not isinstance(function.get("name"), str)
            or not function["name"]
            or not isinstance(function.get("parameters"), dict)
        ):
            raise ValidationError("This adapter supports function tools only")
    return copy.deepcopy(messages), copy.deepcopy(tools)
