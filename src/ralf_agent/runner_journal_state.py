"""Pure native startup evidence rules shared by Local and PostgreSQL stores.

These transitions grant at most one submission permission; they never authorize
business work, schedule execution, or interpret a cancellation as stop proof.
"""

import json
import math

from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .types import canonical

_STAGES = ("intent", "thread_submitted", "thread_confirmed", "turn_submitted", "turn_confirmed")
_MAX_JSON = 65536
_MAX_RECORD = 1048576
_MAX_OBSERVATIONS = 1000


def _text(value, label, *, limit=1024):
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        raise ValidationError(f"{label} requires bounded nonempty text")
    return value


def _json(value, label, *, limit=_MAX_JSON):
    """Reject coercion, unbounded traversal, and non-finite values before serialization."""
    if type(value) is not dict or not value:
        raise ValidationError(f"{label} requires a nonempty JSON object")
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 10000 or depth > 32:
            raise ValidationError(f"{label} exceeds JSON structural limits")
        if type(item) is dict:
            if nodes + len(pending) + len(item) > 10000:
                raise ValidationError(f"{label} exceeds JSON structural limits")
            for key, child in item.items():
                _text(key, f"{label} key")
                pending.append((child, depth + 1))
        elif type(item) is list:
            if nodes + len(pending) + len(item) > 10000:
                raise ValidationError(f"{label} exceeds JSON structural limits")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            if len(item) > limit or any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                raise ValidationError(f"{label} exceeds JSON text limits")
        elif type(item) is int:
            if not -(2**63) <= item < 2**63:
                raise ValidationError(f"{label} exceeds JSON numeric limits")
        elif type(item) is float:
            if not math.isfinite(item) or abs(item) > 2**63 - 1:
                raise ValidationError(f"{label} requires bounded finite numbers")
        elif item is not None and type(item) is not bool:
            raise ValidationError(f"{label} requires strict finite JSON")
    encoded = canonical(value)
    if len(encoded.encode("utf-8")) > limit:
        raise ValidationError(f"{label} exceeds JSON byte limit")
    return encoded


def validate_record(encoded_record, key, binding):
    try:
        if len(encoded_record.encode("utf-8")) > _MAX_RECORD:
            raise ValidationError("Runner record exceeds byte limit")
        record = json.loads(encoded_record)
        _json(record, "Saved Runner record", limit=_MAX_RECORD)
        if (
            set(record)
            != {
                "scope",
                "effect_key",
                "binding",
                "stage",
                "thread_id",
                "process_epoch",
                "turn_id",
                "cancel_requested",
                "observations",
            }
            or record["scope"] != {"workspace": key[0], "principal": key[1]}
            or record["effect_key"] != key[2]
            or record["stage"] not in _STAGES
            or type(record["cancel_requested"]) is not bool
            or type(record["observations"]) is not list
            or len(record["observations"]) > _MAX_OBSERVATIONS
        ):
            raise ValidationError("Runner record shape changed")
        has_thread = record["stage"] in _STAGES[2:]
        for name in ("thread_id", "process_epoch"):
            if has_thread:
                _text(record[name], name)
            elif record[name] is not None:
                raise ValidationError("Runner stage precedes recorded native Thread")
        if record["stage"] == "turn_confirmed":
            _text(record["turn_id"], "Turn ID")
        elif record["turn_id"] is not None:
            raise ValidationError("Runner stage precedes recorded native Turn")
        _json(record["binding"], "Saved Runner binding")
        for observation in record["observations"]:
            _json(observation, "Saved Runner observation")
            for name in ("thread_id", "turn_id", "process_epoch"):
                if name in observation:
                    _text(observation[name], name)
            if any(
                name in observation and observation[name] != record[name]
                for name in ("thread_id", "turn_id", "process_epoch")
            ):
                raise ValidationError("Runner observation handle changed")
    except (ValueError, TypeError, KeyError, RecursionError):
        raise DefinitionMismatch("Original Runner startup evidence is inconsistent") from None
    if canonical(record["binding"]) != binding:
        raise IdempotencyConflict("Runner effect key pins another binding")
    return record


def new_record(key, binding_json):
    record = {
        "scope": {"workspace": key[0], "principal": key[1]},
        "effect_key": key[2],
        "binding": json.loads(binding_json),
        "stage": "intent",
        "thread_id": None,
        "process_epoch": None,
        "turn_id": None,
        "cancel_requested": False,
        "observations": [],
    }
    return json.loads(_json(record, "Runner record", limit=_MAX_RECORD))


def submit_record(record, previous, stage):
    if _STAGES.index(record["stage"]) >= _STAGES.index(stage):
        return record, False
    if record["stage"] != previous or record["cancel_requested"]:
        raise ValidationError("Runner startup submission is out of order or cancelled")
    record["stage"] = stage
    return record, True


def receive_record(record, native, previous, stage):
    if any(record[k] is not None and record[k] != v for k, v in native.items()):
        raise IdempotencyConflict("Runner native receipt identity is immutable")
    if all(record[k] == v for k, v in native.items()):
        return record
    if record["stage"] != previous:
        raise ValidationError("Native receipt requires durable submission intent")
    record.update(native)
    record["stage"] = stage
    return record


def append_observation(record, encoded):
    evidence = json.loads(encoded)
    for name in ("thread_id", "turn_id", "process_epoch"):
        if name in evidence:
            _text(evidence[name], name)
            if evidence[name] != record[name]:
                raise IdempotencyConflict(
                    "Runner observation does not identify the recorded native handle"
                )
    if any(canonical(item) == encoded for item in record["observations"]):
        return record
    if len(record["observations"]) >= _MAX_OBSERVATIONS:
        raise ValidationError("Runner observation capacity is full")
    record["observations"].append(evidence)
    _json(record, "Runner record", limit=_MAX_RECORD)
    return record


def cancel_record(record):
    record["cancel_requested"] = True
    return record
