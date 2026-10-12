"""Completed model evidence is distinct from an accepted model decision."""

import copy
import inspect
import json

from .errors import ValidationError
from .types import ModelResponse, ToolCall, canonical


def _close_lazy(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()
    elif isinstance(value, ToolCall):
        for item in (value.name, value.arguments, value.call_id):
            _close_lazy(item, seen)
    elif isinstance(value, dict):
        for item in value.values():
            _close_lazy(item, seen)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _close_lazy(item, seen)


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
            received[field] = json.loads(canonical(encoded))
        except ValidationError:
            _close_lazy(value)
            received[field] = fallback
            invalid.append(field)
    from .model_continuation import ContinuedModelResponse

    if isinstance(response, ContinuedModelResponse):
        try:
            received["continuation"] = response.continuation.to_dict()
        except (AttributeError, TypeError, ValidationError):
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
