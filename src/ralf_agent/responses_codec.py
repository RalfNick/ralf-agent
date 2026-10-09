"""Stateless plain-text/client-function Responses conversion, never tool execution."""

from .model_protocol import json_object, response, token_count
from .types import ToolCall


def input_items(messages):
    items, pending = [], set()
    for message in messages:
        role = message["role"]
        if role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                raise ValueError("Tool result has no pending function call")
            pending.remove(call_id)
            items.append(
                {"type": "function_call_output", "call_id": call_id, "output": message["content"]}
            )
            continue
        if pending:
            raise ValueError("Incomplete function result group")
        calls = message.get("tool_calls") or []
        if calls and (role != "assistant" or not isinstance(calls, list)):
            raise ValueError("Invalid assistant function calls")
        if message["content"] is not None and (message["content"] or not calls):
            items.append({"role": role, "content": message["content"]})
        for call in calls:
            if call.get("type") != "function":
                raise ValueError("Only client functions are supported")
            function, call_id = call["function"], call["id"]
            if not isinstance(call_id, str) or not call_id or call_id in pending:
                raise ValueError("Invalid function call identity")
            if not isinstance(function.get("name"), str) or not function["name"]:
                raise ValueError("Invalid function name")
            json_object(function["arguments"])
            pending.add(call_id)
            items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": function["name"],
                    "arguments": function["arguments"],
                }
            )
    if pending:
        raise ValueError("Function results are required before a model continuation")
    return items


def parse_response(value):
    if (
        value.get("status") != "completed"
        or value.get("error") is not None
        or value.get("incomplete_details") is not None
    ):
        raise ValueError("Response is not complete")
    output = value["output"]
    if not isinstance(output, list) or len(output) > 1000:
        raise ValueError("Invalid Responses output")
    texts, calls, ids = [], [], set()
    for item in output:
        if not isinstance(item, dict) or item.get("status", "completed") != "completed":
            raise ValueError("Incomplete output item")
        if not isinstance(item.get("id"), str) or not item["id"] or item["id"] in ids:
            raise ValueError("Invalid output item identity")
        ids.add(item["id"])
        if item.get("type") == "message":
            if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                raise ValueError("Invalid assistant content")
            for part in item["content"]:
                if (
                    not isinstance(part, dict)
                    or part.get("type") != "output_text"
                    or not isinstance(part.get("text"), str)
                    or part.get("annotations", []) != []
                ):
                    raise ValueError("Unsupported content or annotations")
                texts.append(part["text"])
        elif item.get("type") == "function_call":
            calls.append(ToolCall(item["name"], json_object(item["arguments"]), item["call_id"]))
        else:
            raise ValueError("Reasoning, media and server tools require unsupported continuation")
    usage = value.get("usage")
    if usage is not None:
        usage = {name: token_count(usage[name]) for name in ("input_tokens", "output_tokens")}
    return response("".join(texts) or None, calls, usage)
