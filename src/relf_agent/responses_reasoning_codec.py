"""Pure native Responses reasoning evidence and stateless history conversion."""

import copy
import re

from .model_continuation import ModelContinuation
from .model_protocol import json_object, response, token_count
from .types import ToolCall, digest

PROTOCOL = "openai-responses-reasoning-v1"
MAX_CALLS = 256
MAX_ITEMS = 1000
_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
_FIELDS = {
    "reasoning": {"type", "id", "summary", "content", "encrypted_content", "status"},
    "message": {"type", "id", "role", "status", "content", "phase"},
    "function_call": {
        "type",
        "id",
        "name",
        "call_id",
        "arguments",
        "status",
        "async",
        "caller",
        "namespace",
    },
}


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError("Native identity must be non-empty and bounded")
    return value


def name(value):
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise ValueError("Unsupported Responses function name")
    return value


def text_part(part, kind):
    fields = (
        {"type", "text", "annotations", "logprobs"} if kind == "output_text" else {"type", "text"}
    )
    if (
        not isinstance(part, dict)
        or set(part) - fields
        or part.get("type") != kind
        or not isinstance(part.get("text"), str)
        or kind == "output_text"
        and (part.get("annotations", []) != [] or part.get("logprobs", []) not in (None, []))
    ):
        raise ValueError("Unsupported native text content")
    return part


def item(value, *, complete=True):
    """Validate accepted item semantics without changing its original wire fields."""
    if not isinstance(value, dict) or value.get("type") not in _FIELDS:
        raise ValueError("Unsupported native output item")
    kind = value["type"]
    if set(value) - _FIELDS[kind]:
        raise ValueError("Unsupported native output fields")
    identifier(value["id"])
    status = value.get("status")
    allowed = {None, "completed"} if kind in {"reasoning", "function_call"} else {"completed"}
    if not complete:
        allowed |= {None, "in_progress"}
    if kind == "function_call" and "status" not in value:
        status = "completed"
    if not isinstance(status, (str, type(None))) or status not in allowed:
        raise ValueError("Incomplete native output item")
    if kind == "reasoning":
        summary = value["summary"]
        if not isinstance(summary, list) or len(summary) > MAX_ITEMS:
            raise ValueError("Invalid native reasoning summary")
        for part in summary:
            text_part(part, "summary_text")
        if value.get("content") is not None:
            content = value["content"]
            if not isinstance(content, list) or len(content) > MAX_ITEMS:
                raise ValueError("Invalid native reasoning content")
            for part in content:
                text_part(part, "reasoning_text")
        encrypted = value.get("encrypted_content")
        if complete:
            if not isinstance(encrypted, str) or not encrypted.strip():
                raise ValueError("Stateless reasoning requires complete encrypted content")
        elif encrypted is not None and not isinstance(encrypted, str):
            raise ValueError("Invalid partial encrypted content")
    elif kind == "message":
        if (
            value.get("role") != "assistant"
            or not isinstance(value.get("phase"), (str, type(None)))
            or value.get("phase") not in {None, "commentary", "final_answer"}
        ):
            raise ValueError("Invalid native assistant role or phase")
        content = value["content"]
        if not isinstance(content, list) or len(content) > MAX_ITEMS:
            raise ValueError("Invalid native assistant content")
        for part in content:
            text_part(part, "output_text")
    else:
        name(value["name"])
        identifier(value["call_id"])
        if not isinstance(value["arguments"], str):
            raise ValueError("Native function arguments must be text")
        if complete:
            json_object(value["arguments"])
        if "async" in value and value["async"] is not False and value["async"] is not None:
            raise ValueError("Async native functions are unsupported")
        if value.get("caller") is not None and value["caller"] != {"type": "direct"}:
            raise ValueError("Only direct native functions are supported")
        if value.get("namespace") is not None:
            raise ValueError("Function namespaces are unsupported")
    return value


def output_decision(output):
    if not isinstance(output, list) or len(output) > MAX_ITEMS:
        raise ValueError("Native output must be a bounded item list")
    texts, calls, ids = [], [], set()
    for raw in output:
        item(raw)
        if raw["id"] in ids:
            raise ValueError("Repeated native output identity")
        ids.add(raw["id"])
        if raw["type"] == "message" and raw.get("phase") != "commentary":
            texts.extend(part["text"] for part in raw["content"])
        elif raw["type"] == "function_call":
            calls.append(ToolCall(raw["name"], json_object(raw["arguments"]), raw["call_id"]))
    if len(calls) > MAX_CALLS:
        raise ValueError("Native function group exceeds its call limit")
    completed = response("".join(texts) or None, calls)
    return completed.output, completed.tool_calls


def decision(output, calls):
    return {
        "output": output,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
            for call in calls
        ],
    }


def usage(value):
    if value is None:
        return None
    details = {
        "input_tokens_details": {"cached_tokens", "cache_write_tokens"},
        "output_tokens_details": {"reasoning_tokens"},
    }
    if (
        not isinstance(value, dict)
        or set(value) - {"input_tokens", "output_tokens", "total_tokens"} - details.keys()
    ):
        raise ValueError("Unsupported native token usage")
    counts = {field: token_count(value[field]) for field in ("input_tokens", "output_tokens")}
    if "total_tokens" in value and token_count(value["total_tokens"]) != sum(counts.values()):
        raise ValueError("Inconsistent total token usage")
    for field, fields in details.items():
        if field not in value:
            continue
        detail = value[field]
        if not isinstance(detail, dict) or set(detail) - fields:
            raise ValueError("Unsupported token usage detail")
        limit = counts["input_tokens" if field == "input_tokens_details" else "output_tokens"]
        if any(token_count(count) > limit for count in detail.values()):
            raise ValueError("Token usage detail exceeds its total")
    return counts


def parse_response(value):
    if (
        value.get("status") != "completed"
        or value.get("error") is not None
        or value.get("incomplete_details") is not None
    ):
        raise ValueError("Native response is not complete")
    identifier(value["id"])
    output, calls = output_decision(value["output"])
    return response(output, calls, usage(value.get("usage")))


def declarations(tools):
    native, names = [], set()
    for tool in tools:
        if set(tool) != {"type", "function"} or tool["type"] != "function":
            raise ValueError("Only client functions are supported")
        function = tool["function"]
        if not isinstance(function, dict) or set(function) - {"name", "description", "parameters"}:
            raise ValueError("Unsupported function declaration fields")
        current = name(function["name"])
        if (
            current in names
            or not isinstance(function["parameters"], dict)
            or not isinstance(function.get("description", ""), str)
        ):
            raise ValueError("Invalid or repeated function declaration")
        names.add(current)
        native.append(
            {
                "type": "function",
                "name": current,
                "description": function.get("description", ""),
                "parameters": copy.deepcopy(function["parameters"]),
                "strict": False,
            }
        )
    return native


def _history_calls(values):
    if not isinstance(values, list) or len(values) > MAX_CALLS:
        raise ValueError("Historical functions must be a bounded list")
    calls = []
    for raw in values:
        if (
            not isinstance(raw, dict)
            or set(raw) != {"id", "type", "function"}
            or raw["type"] != "function"
        ):
            raise ValueError("Invalid historical function call")
        function = raw["function"]
        if not isinstance(function, dict) or set(function) != {"name", "arguments"}:
            raise ValueError("Invalid historical function fields")
        calls.append(
            ToolCall(
                name(function["name"]), json_object(function["arguments"]), identifier(raw["id"])
            )
        )
    if len({call.call_id for call in calls}) != len(calls):
        raise ValueError("Repeated historical function identity")
    return calls


def input_items(messages, identity, *, tools):
    native, pending = [], set()
    for message in messages:
        role = message["role"]
        allowed = {"role", "content"} | (
            {"tool_calls", "model_continuation"}
            if role == "assistant"
            else {"tool_call_id"}
            if role == "tool"
            else set()
        )
        if set(message) - allowed:
            raise ValueError("Unsupported historical message fields")
        if pending and role != "tool":
            raise ValueError("Function receipt group is incomplete")
        if role == "tool":
            call_id = identifier(message.get("tool_call_id"))
            if call_id not in pending:
                raise ValueError("Unknown or repeated function receipt")
            pending.remove(call_id)
            native.append(
                {"type": "function_call_output", "call_id": call_id, "output": message["content"]}
            )
        elif role != "assistant":
            native.append(copy.deepcopy(message))
        else:
            calls = _history_calls(message.get("tool_calls", []))
            response(message.get("content"), calls)
            if "model_continuation" not in message:
                if calls or tools:
                    raise ValueError("Reasoning tool history requires original continuation")
                native.append({"role": "assistant", "content": message["content"]})
            else:
                envelope = message["model_continuation"]
                if not isinstance(envelope, dict) or set(envelope) != {
                    "protocol",
                    "owner_digest",
                    "decision_digest",
                    "data",
                }:
                    raise ValueError("Invalid continuation envelope")
                continued = ModelContinuation(**envelope).to_dict()
                if (
                    {key: continued[key] for key in ("protocol", "owner_digest")} != identity
                    or continued["decision_digest"]
                    != digest(decision(message.get("content"), calls))
                    or set(continued["data"]) != {"output"}
                ):
                    raise ValueError("Continuation owner or original decision changed")
                output, raw_calls = output_decision(continued["data"]["output"])
                if digest(decision(output, raw_calls)) != continued["decision_digest"]:
                    raise ValueError("Native continuation differs from its original decision")
                native.extend(copy.deepcopy(continued["data"]["output"]))
            pending = {call.call_id for call in calls}
    if pending:
        raise ValueError("Function receipt group is incomplete")
    return native
