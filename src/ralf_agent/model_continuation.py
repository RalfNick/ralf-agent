"""Detached model-owned continuation evidence; never tool execution authority."""

import copy
import inspect
import json
import re
from dataclasses import dataclass, field

from .errors import ValidationError
from .harness import DecisionProposal
from .types import ModelResponse, ToolCall, canonical, digest

_FIELDS = {"protocol", "owner_digest", "decision_digest", "data"}
_IDENTITY_FIELDS = {"protocol", "owner_digest"}


def _identity(value):
    if not isinstance(value, dict) or set(value) != _IDENTITY_FIELDS:
        raise ValidationError("Model continuation identity requires protocol and owner digest")
    protocol, owner = value["protocol"], value["owner_digest"]
    if not isinstance(protocol, str) or not protocol.strip() or len(protocol) > 128:
        raise ValidationError("Model continuation protocol must be non-empty and bounded")
    if not isinstance(owner, str) or re.fullmatch("[0-9a-f]{64}", owner) is None:
        raise ValidationError("Model continuation owner must be a SHA-256 digest")
    return copy.deepcopy(value)


def _continuation(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValidationError("Model continuation requires exactly four fields")
    _identity({name: value[name] for name in _IDENTITY_FIELDS})
    decision = value["decision_digest"]
    if not isinstance(decision, str) or re.fullmatch("[0-9a-f]{64}", decision) is None:
        raise ValidationError("Model continuation decision must be a SHA-256 digest")
    if not isinstance(value["data"], dict):
        raise ValidationError("Model continuation data must be a JSON object")
    encoded = canonical(value)
    if len(encoded.encode("utf-8")) > 131072:
        raise ValidationError("Model continuation exceeds its UTF-8 evidence limit")
    return json.loads(encoded)


@dataclass(frozen=True)
class ModelContinuation:
    """Opaque Provider protocol data bound to one complete original decision."""

    protocol: str
    owner_digest: str
    decision_digest: str
    data: dict

    def __post_init__(self):
        value = _continuation({name: getattr(self, name) for name in _FIELDS})
        for name, detached in value.items():
            object.__setattr__(self, name, detached)

    def to_dict(self):
        return _continuation({name: getattr(self, name) for name in _FIELDS})


@dataclass(frozen=True)
class ContinuedModelResponse(ModelResponse):
    """Explicit response extension; the original ModelResponse codec is unchanged."""

    continuation: ModelContinuation = field(kw_only=True)

    def __post_init__(self):
        if not isinstance(self.continuation, ModelContinuation):
            raise ValidationError("Continued response requires ModelContinuation")
        object.__setattr__(self, "continuation", ModelContinuation(**self.continuation.to_dict()))


def decode_received_response(received):
    """Decode completed evidence without accepting the Harness decision."""
    if not isinstance(received, dict) or received.get("invalid_fields"):
        raise ValidationError("Provider response contains invalid JSON fields")
    canonical(received)
    try:
        calls = received["tool_calls"]
        if not isinstance(calls, list):
            raise ValidationError("Provider tool calls must be a list")
        response = {
            "output": copy.deepcopy(received["output"]),
            "tool_calls": tuple(ToolCall(**copy.deepcopy(call)) for call in calls),
            "usage": copy.deepcopy(received["usage"]),
        }
        if "continuation" not in received:
            return ModelResponse(**response)
        return ContinuedModelResponse(
            **response, continuation=ModelContinuation(**_continuation(received["continuation"]))
        )
    except (KeyError, TypeError) as exc:
        raise ValidationError("Provider response contains malformed decision fields") from exc


def provider_continuation_identity(provider):
    """Read a pure declaration, leaving component I/O and lifecycle to its host."""
    value = getattr(provider, "continuation_identity", None)
    try:
        return None if value is None else _identity(value)
    except ValidationError:
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise


def _decision(received):
    return {"output": received["output"], "tool_calls": received["tool_calls"]}


def validate_continuation(received, proposed, identity, *, enabled):
    """Check model ownership and original Harness proposal before any Action exists."""
    if type(enabled) is not bool:
        raise ValidationError("Model continuation enablement must be boolean")
    if not isinstance(received, dict):
        raise ValidationError("Provider response must be completed JSON evidence")
    if "continuation" not in received:
        return None
    if not enabled:
        raise ValidationError("Model continuation requires explicit enablement")
    value = _continuation(received["continuation"])
    if identity is None or _identity(identity) != {
        "protocol": value["protocol"],
        "owner_digest": value["owner_digest"],
    }:
        raise ValidationError("Model continuation does not belong to the pinned Provider")
    if not isinstance(proposed, DecisionProposal):
        raise ValidationError("Model continuation requires a Harness decision proposal")
    raw = _decision(received)
    if digest(raw) != value["decision_digest"]:
        raise ValidationError("Model continuation does not match the received decision")
    proposal = {
        "output": proposed.output,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments, "call_id": call.call_id}
            for call in proposed.tool_calls
        ],
    }
    if digest(raw) != digest(proposal):
        raise ValidationError("Harness changed a model-owned continuation decision")
    return value


def assistant_message(output, proposals, *, received=None, continuation=None):
    """Build the original assistant group, preserving signed pre-default arguments."""
    calls = proposals
    if continuation is not None:
        value = _continuation(continuation)
        if (
            not isinstance(received, dict)
            or value != _continuation(received.get("continuation"))
            or value["decision_digest"] != digest(_decision(received))
            or digest(output) != digest(received["output"])
            or len(proposals) != len(received["tool_calls"])
        ):
            raise ValidationError("Assistant continuation differs from original model evidence")
        calls = []
        for actual, raw in zip(proposals, received["tool_calls"], strict=True):
            name = actual.get("tool", actual.get("name"))
            if name != raw["name"] or (
                raw["call_id"] is not None and actual["call_id"] != raw["call_id"]
            ):
                raise ValidationError(
                    "Assistant tool identity differs from original model evidence"
                )
            calls.append({**raw, "call_id": actual["call_id"]})
    result = {
        "role": "assistant",
        "content": output if isinstance(output, str) else None,
        "tool_calls": [
            {
                "id": item["call_id"],
                "type": "function",
                "function": {
                    "name": item.get("tool", item.get("name")),
                    "arguments": canonical(item["arguments"]),
                },
            }
            for item in calls
        ],
    }
    if continuation is not None:
        result["model_continuation"] = value
    return result
