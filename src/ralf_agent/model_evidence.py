"""Completed model evidence is distinct from an accepted model decision."""

import asyncio
import copy
import inspect
import json

from .errors import ValidationError
from .types import ModelResponse, ToolCall, canonical

_MAX_MODEL_RESPONSE_NESTING = 128


def _check_container_depth(value):
    """Bound newly returned evidence, not the definition of finite JSON.

    Response fields later sit inside Actions, Runs and public snapshots. A
    fixed conservative container limit keeps all their durable detachments
    safe instead of depending on the interpreter's current recursion margin.
    Already received records are not revalidated or rewritten by this policy.
    """
    pending, visited = [(value, 0)], {}
    while pending:
        item, depth = pending.pop()
        if not isinstance(item, (dict, tuple, list)):
            continue
        depth += 1
        if depth > _MAX_MODEL_RESPONSE_NESTING:
            raise ValidationError("New model response evidence exceeds container nesting limit")
        if visited.get(id(item), -1) >= depth:
            continue
        visited[id(item)] = depth
        children = item.values() if isinstance(item, dict) else item
        pending.extend((child, depth) for child in children)


def _close_lazy(value):
    # Invalid completed evidence may exceed the JSON encoder's recursion limit
    # or contain cycles. Cleanup must not lose the known completion as well.
    pending, seen = [value], set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        if inspect.iscoroutine(item) or inspect.isgenerator(item):
            try:
                item.close()
            except (Exception, asyncio.CancelledError):
                # A supplier generator's finally block can fail during close.
                # The original value remains completed-invalid evidence, and
                # its failure must not strand other lazy descendants.
                pass
        elif isinstance(item, ToolCall):
            pending.extend((item.name, item.arguments, item.call_id))
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (tuple, list)):
            pending.extend(item)


def snapshot_model_response(response):
    if not isinstance(response, ModelResponse):
        raise ValidationError("ModelProvider.complete must return ModelResponse")
    received, invalid = {}, []
    for field, fallback in (("output", None), ("tool_calls", []), ("usage", None)):
        value = getattr(response, field)
        encoded = value
        if field == "tool_calls" and isinstance(value, (tuple, list)):
            encoded = [
                {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
                if isinstance(call, ToolCall)
                else call
                for call in value
            ]
        try:
            _check_container_depth(encoded)
            # The durable authority detaches received evidence before recording
            # it. Some Python JSON encoders accept a deeper tree than deepcopy;
            # verify that boundary here while completion is still known.
            serialized = canonical(encoded)
            # Durable SQLite text and response digests both require UTF-8.
            # Python's JSON encoder can otherwise retain unpaired surrogates.
            serialized.encode("utf-8")
            received[field] = copy.deepcopy(json.loads(serialized))
        except (ValidationError, RecursionError, UnicodeError):
            _close_lazy(value)
            received[field] = fallback
            invalid.append(field)
    from .model_continuation import ContinuedModelResponse

    if isinstance(response, ContinuedModelResponse):
        try:
            continuation = response.continuation.to_dict()
            _check_container_depth(continuation)
            canonical(continuation).encode("utf-8")
            received["continuation"] = continuation
        except (AttributeError, TypeError, ValidationError, RecursionError, UnicodeError):
            received["continuation"] = None
            invalid.append("continuation")
    if invalid:
        received["invalid_fields"] = invalid
    return received


def validate_received_response(received):
    if received.get("invalid_fields"):
        raise ValidationError("Provider response contains invalid JSON fields")


def validate_model_usage(usage):
    canonical(usage)
    if usage is not None:
        if not isinstance(usage, dict):
            raise ValidationError("Provider usage must be JSON object")
        for field in ("input_tokens", "output_tokens"):
            if field in usage and (type(usage[field]) is not int or usage[field] < 0):
                raise ValidationError("Provider token usage must be non-negative integers")
    return copy.deepcopy(usage)


def settlement_usage(usage):
    """Unknown token accounting does not make completed execution uncertain."""
    try:
        return validate_model_usage(usage) or {"usage": "unknown"}
    except ValidationError:
        return {"usage": "unknown"}
