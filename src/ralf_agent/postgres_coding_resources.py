"""Versioned original resource intent and immutable native receipts (no I/O)."""

import copy
import json

from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .runner_journal_state import _MAX_RECORD, _json, _text
from .types import canonical, digest


def new_resource(key, request, runner, namespace_binding, *, owner_proof=None):
    owner = None
    if owner_proof is not None:
        owner = json.loads(_json(owner_proof, "Original Coding process owner"))
        if (
            set(owner) != {"version", "pid", "start", "deployment", "invocation_id"}
            or type(owner["version"]) is not int
            or owner["version"] != 1
            or type(owner["pid"]) is not int
            or owner["pid"] <= 0
            or type(owner["deployment"]) is not str
            or len(owner["deployment"]) != 64
            or set(owner["deployment"]) - set("0123456789abcdef")
        ):
            raise ValidationError("Coding owner requires immutable original process proof")
        _text(owner["start"], "Original process start")
        _text(owner["invocation_id"], "Original invocation")
    request = json.loads(_json(request, "Coding resource request"))
    runner = json.loads(_json(runner, "Coding resource runner"))
    namespace = json.loads(_json(namespace_binding, "Coding namespace binding"))
    dispatch = request.get("dispatch", {})
    unsigned = {k: v for k, v in request.items() if k != "request_digest"}
    if (
        set(request)
        != {
            "dispatch",
            "release_digest",
            "reservation",
            "definition_digest",
            "deadline",
            "request_digest",
        }
        or request["request_digest"] != digest(unsigned)
        or dispatch.get("scope") != {"workspace": key[0], "principal": key[1]}
        or dispatch.get("effect_key") != key[2]
        or set(namespace) != {"request", "runner", "dispatch", "environment"}
        or namespace["request"] != request
        or namespace["runner"] != runner
        or namespace["dispatch"] != dispatch
        or type(namespace["environment"]) is not dict
        or namespace["environment"].get("version") != "2"
        or namespace["environment"].get("retire_on_stop") is not True
        or (
            runner.get("configuration_readonly") is True
            and namespace["environment"].get("configuration_readonly") is not True
        )
    ):
        raise ValidationError("Coding resource intent differs from original request or namespace")
    generation = _text(namespace["environment"].get("expected_generation"), "Resource generation")
    if len(generation) != 32 or set(generation) - set("0123456789abcdef"):
        raise ValidationError("Resource generation requires the original fixed digest")
    for label in ("release_digest", "definition_digest", "request_digest"):
        _text(request[label], label)
    return {
        "version": "1",
        "scope": dispatch["scope"],
        "effect_key": key[2],
        "request": request,
        "runner": runner,
        "namespace_binding": namespace,
        "prepared": None,
        "stop": None,
        "pending_stop": True,
        "owner": owner,
        "unprepared": None,
        "namespace_absent": None,
    }


def _receipt(record, kind, evidence):
    value = json.loads(_json(evidence, "Coding resource receipt"))
    namespace = record["namespace_binding"]["environment"]
    cid = value.get("container_id")
    if (
        kind not in {"prepared", "stop"}
        or value.get("identity") != namespace
        or value.get("generation") != namespace["expected_generation"]
        or type(cid) is not str
        or len(cid) != 64
        or set(cid) - set("0123456789abcdef")
        or value.get("stopped") is not True
        or value.get("running") is not False
        or type(value.get("pid")) is not int
        or value["pid"] != 0
        or value.get("execution_admitted") is not False
        or value.get("resource_id") != namespace.get("resource_id")
        or (
            value.get("transport_closed") is not None
            and type(value.get("transport_closed")) is not bool
        )
        or (
            kind == "prepared"
            and (
                value.get("fenced") is not False
                or value.get("retired") is not False
                or value.get("container_present") is not True
            )
        )
        or (
            kind == "stop"
            and (
                value.get("fenced") is not True
                or value.get("retired") is not True
                or value.get("container_present") is not False
            )
        )
    ):
        raise IdempotencyConflict(
            "Resource receipt differs from original namespace or physical fence"
        )
    prepared = record.get("prepared")
    if prepared and any(
        value.get(k) != prepared.get(k) for k in ("identity", "container_id", "generation")
    ):
        raise IdempotencyConflict("Resource receipt replaced original prepared container")
    return value


def receive_resource(record, kind, evidence):
    record = copy.deepcopy(record)
    if kind == "unprepared":
        value = json.loads(_json(evidence, "Original ungranted resource receipt"))
        if (
            set(value) != {"namespace_binding", "prepare_granted"}
            or value["namespace_binding"] != record["namespace_binding"]
            or value["prepare_granted"] is not False
            or record["prepared"] is not None
            or record["stop"] is not None
            or record["namespace_absent"] is not None
        ):
            raise IdempotencyConflict("Original ungranted resource receipt changed")
        if record["unprepared"] is not None and record["unprepared"] != value:
            raise IdempotencyConflict("Original resource tombstone is immutable")
        record["unprepared"] = value
        record["pending_stop"] = False
        return record
    if kind == "namespace_absent":
        value = json.loads(_json(evidence, "Original namespace absence receipt"))
        namespace = record["namespace_binding"]["environment"]
        if (
            set(value)
            != {
                "identity",
                "generation",
                "container_present",
                "namespace_confirmed",
                "owner",
                "process_present",
            }
            or value["identity"] != namespace
            or value["generation"] != namespace["expected_generation"]
            or value["container_present"] is not False
            or value["namespace_confirmed"] is not True
            or value["process_present"] is not False
            or record["owner"] is None
            or value["owner"] != record["owner"]
            or record["prepared"] is not None
            or record["stop"] is not None
            or record["unprepared"] is not None
        ):
            raise IdempotencyConflict("Original namespace absence receipt changed")
        if record["namespace_absent"] is not None and record["namespace_absent"] != value:
            raise IdempotencyConflict("Original namespace absence receipt is immutable")
        record["namespace_absent"] = value
        record["pending_stop"] = False
        return record
    if record["unprepared"] is not None or record["namespace_absent"] is not None:
        raise IdempotencyConflict("Ungrantable original resource cannot receive native receipts")
    value = _receipt(record, kind, evidence)
    previous = record[kind]
    if previous is not None:
        # A cold reader cannot invent or erase the original live transport end.
        comparable = {k: v for k, v in value.items() if k != "transport_closed"}
        saved = {k: v for k, v in previous.items() if k != "transport_closed"}
        if comparable != saved or (
            value.get("transport_closed") is True and previous.get("transport_closed") is not True
        ):
            raise IdempotencyConflict("Coding resource receipt is immutable")
        return record
    record[kind] = value
    if kind == "stop":
        record["pending_stop"] = False
    _json(record, "Coding resource record", limit=_MAX_RECORD)
    return record


def validate_resource(encoded, key, request=None):
    try:
        if type(encoded) is not str or len(encoded.encode()) > _MAX_RECORD:
            raise ValueError
        record = json.loads(encoded)
        _json(record, "Saved Coding resource", limit=_MAX_RECORD)
        if set(record) != {
            "version",
            "scope",
            "effect_key",
            "request",
            "runner",
            "namespace_binding",
            "prepared",
            "stop",
            "pending_stop",
            "owner",
            "unprepared",
            "namespace_absent",
        }:
            raise ValueError
        expected = new_resource(
            key,
            record["request"],
            record["runner"],
            record["namespace_binding"],
            owner_proof=record["owner"],
        )
        for kind in ("prepared", "stop", "unprepared", "namespace_absent"):
            if record[kind] is not None:
                expected = receive_resource(expected, kind, record[kind])
        if expected != record:
            raise ValueError
    except (ValueError, TypeError, KeyError, RecursionError, ValidationError, IdempotencyConflict):
        raise DefinitionMismatch("Original Coding resource evidence is inconsistent") from None
    if request is not None and canonical(record["request"]) != canonical(request):
        raise IdempotencyConflict("Coding resource effect key pins another original request")
    return record
