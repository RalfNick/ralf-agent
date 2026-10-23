"""Pure Session deployment DTO correlation; never admission or SDK proof."""

import base64
import json
import re
import zlib

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .session_types import SessionRef, integer
from .temporal_deployment_admission import (
    _exact,
    _namespace,
    _scope,
    _sha,
    registry_id,
    root_run_id,
)
from .temporal_deployment_execution_state import _root
from .temporal_deployment_registry import SUBMISSION_CAPACITY
from .temporal_session_identity import (
    data_resource_id,
    selected_namespace,
    selected_source,
)
from .temporal_session_state import (
    HISTORY_CHARS,
    SESSION_ACTIVITY,
    validate_history,
    workflow_id,
)
from .temporal_startup_options import validate_seconds
from .types import canonical, credits, digest

_BODY_TAG = "_ralf_session_control_body"
_BODY_THRESHOLD = 512 * 1024
_BODY_WIRE_LIMIT = SUBMISSION_CAPACITY
_BODY_LIMIT = SUBMISSION_CAPACITY * 8


def _coded_control_body(manifest):
    from .temporal_deployment_coding_state import selected

    protocol = manifest.get("deployment_admission_protocol") if type(manifest) is dict else None
    return (
        type(protocol) is dict
        and type(protocol.get("version")) is int
        and protocol["version"] == 4
        and selected(manifest)
    )


def _body_reject():
    raise DefinitionMismatch("Original Session control body encoding is invalid")


def encode_control_body(body, manifest):
    """Bounded, lossless Coding4 wire representation; never a new body authority."""
    from .temporal_state import detached

    if type(body) is not dict or _BODY_TAG in body:
        _body_reject()
    value = detached(body)
    raw = canonical(value).encode()
    if len(raw) > _BODY_LIMIT:
        raise ValidationError("Original Session control result exceeds its bounded allowance")
    if not _coded_control_body(manifest) or len(raw) <= _BODY_THRESHOLD:
        return value
    wire = {
        _BODY_TAG: {
            "version": 1,
            "encoding": "zlib-json-base64",
            "raw_size": len(raw),
            "digest": digest(value),
            "data": base64.b64encode(zlib.compress(raw)).decode("ascii"),
        }
    }
    if len(canonical(wire).encode()) > _BODY_WIRE_LIMIT:
        raise ValidationError("Original Session encoded result exceeds its wire allowance")
    return wire


def decode_control_body(body, manifest):
    """Decode before semantic validation or ledger mutation, with bounded output."""
    from .temporal_state import detached

    if type(body) is not dict:
        _body_reject()
    if _BODY_TAG not in body:
        value = detached(body)
        if len(canonical(value).encode()) > _BODY_LIMIT:
            raise ValidationError("Original Session control result exceeds its bounded allowance")
        return value
    if not _coded_control_body(manifest):
        _body_reject()
    _exact(body, {_BODY_TAG})
    wire = body[_BODY_TAG]
    _exact(wire, {"version", "encoding", "raw_size", "digest", "data"})
    if (
        type(wire["version"]) is not int
        or wire["version"] != 1
        or wire["encoding"] != "zlib-json-base64"
        or type(wire["raw_size"]) is not int
        or not _BODY_THRESHOLD < wire["raw_size"] <= _BODY_LIMIT
        or type(wire["data"]) is not str
        or len(wire["data"]) > _BODY_WIRE_LIMIT
    ):
        _body_reject()
    _sha(wire["digest"])
    if len(canonical(body).encode()) > _BODY_WIRE_LIMIT:
        _body_reject()
    try:
        compressed = base64.b64decode(wire["data"], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, _BODY_LIMIT + 1)
        if (
            len(raw) != wire["raw_size"]
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            _body_reject()
        value = json.loads(raw)
        if (
            type(value) is not dict
            or canonical(value).encode() != raw
            or digest(value) != wire["digest"]
        ):
            _body_reject()
    except (ValueError, UnicodeError, RecursionError, zlib.error) as exc:
        raise DefinitionMismatch("Original Session control body decoding failed") from exc
    return value


INTENT_FIELDS = frozenset(
    {
        "version",
        "scope",
        "namespace",
        "coordinator_id",
        "coordinator_execution_epoch",
        "session_ref",
        "binding",
        "session_command_id",
        "turn_id",
        "turn_seq",
        "run_command_id",
        "run_id",
        "submission",
        "intent_digest",
    }
)
ORIGIN_FIELDS = frozenset(
    {
        "version",
        "namespace",
        "coordinator_id",
        "coordinator_execution_epoch",
        "coordinator_first_execution_epoch",
        "coordinator_original_execution_epoch",
        "session_ref",
        "session_command_id",
        "turn_id",
        "turn_seq",
        "intent_digest",
    }
)
START_VIEW_FIELDS = frozenset(
    {
        "version",
        "intent",
        "phase",
        "reservation",
        "execution_epoch",
        "run_receipt",
        "last_error",
        "start_refusal",
    }
)
NEVER_CLAIMED_FIELDS = frozenset(
    {
        "version",
        "scope",
        "namespace",
        "registry_id",
        "registry_execution_epoch",
        "session_origin",
        "run_command_id",
        "run_id",
        "request_digest",
        "manifest_digest",
        "start_barrier_digest",
        "code",
        "never_claimed",
        "proof_digest",
    }
)
CALL_IDENTITY_FIELDS = frozenset(
    {
        "version",
        "scope",
        "namespace",
        "coordinator_id",
        "coordinator_execution_epoch",
        "session_command_id",
        "turn_id",
        "intent_digest",
        "mode",
        "activity_id",
        "activity_name",
        "attempt",
        "invocation_id",
        "request_digest",
        "manifest_digest",
    }
)
CALL_END_FIELDS = frozenset({"identity", "body_result_digest", "body_stopped", "recorded"})
_BINDING_FIELDS = frozenset({"request", "manifest", "task_queue", "activity_timeout"})
_SUBMISSION_FIELDS = _BINDING_FIELDS | {"version"}
_RESERVATION_FIELDS = frozenset(
    {"command_id", "target", "record_state", "apply_state", "root_admission"}
)
_RECEIPT_FIELDS = frozenset(
    {"command_id", "run_id", "kind", "record_state", "apply_state", "outcome"}
)
_TURN_ADDITIONS = frozenset(
    {
        "session_history",
        "session_turn",
        "session_native_history",
        "session_data_binding",
        "session_lineage",
    }
)
_PHASES = frozenset(
    {
        "intent-accepted",
        "capacity-deferred",
        "reserve-unknown",
        "held-unbound",
        "start-uncertain",
        "started",
        "start-refused",
    }
)


def _reject():
    raise DefinitionMismatch("Session deployment DTO differs from its original identity")


def _version(value):
    if type(value) is not int or value != 1:
        raise ValidationError("Session deployment DTO requires version1")


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 1024:
        raise ValidationError("Session deployment identity requires bounded text")


def _code(value):
    # Format only: the SDK/Registry contract must define the finite permanent
    # refusal classification before any refusal path is enabled.
    if type(value) is not str or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", value) is None:
        raise ValidationError("Session deployment error requires a sanitized code")


def _same(left, right):
    if canonical(left) != canonical(right):
        _reject()


def _detached(value):
    return json.loads(canonical(value))


def _binding(value):
    _exact(value, _BINDING_FIELDS)
    for key in ("request", "manifest"):
        if type(value[key]) is not dict:
            raise ValidationError("Session binding requires plain request/manifest")
    if type(value["request"].get("definition")) is not dict:
        raise ValidationError("Session binding requires its original definition")
    if any(
        key in value["request"]
        for key in _TURN_ADDITIONS | {"session_observer", "session_origin", "intent_digest"}
    ):
        _reject()
    _text(value["task_queue"])
    validate_seconds(value["activity_timeout"], strict=True)
    canonical(value)


def _intent(value, deployment_id):
    _exact(value, INTENT_FIELDS)
    _version(value["version"])
    canonical(value)
    _text(deployment_id)
    _scope(value["scope"])
    _namespace(value["namespace"])
    for key in (
        "coordinator_id",
        "coordinator_execution_epoch",
        "session_command_id",
        "turn_id",
        "run_command_id",
        "run_id",
    ):
        _text(value[key])
    integer(value["turn_seq"])
    _sha(value["intent_digest"])
    _same(
        value["intent_digest"],
        digest({k: v for k, v in value.items() if k != "intent_digest"}),
    )
    _binding(value["binding"])
    ref = SessionRef.from_dict(value["session_ref"])
    key = ref.key
    if {"workspace": key.workspace, "principal": key.principal} != value["scope"]:
        raise AuthorizationDenied("Session reference belongs to another Scope")
    try:
        source = selected_source(value["binding"]["request"], value["binding"]["manifest"])
    except (KeyError, TypeError, AttributeError, IndexError):
        raise ValidationError("Malformed original Session binding data") from None
    if (
        ref.definition_digest != digest(value["binding"])
        or ref.coordination_ref
        != digest(["temporal-session-coordination-v1", key.resource_id, value["scope"]])
        or key.resource_id != data_resource_id(value["namespace"]["id"], source)
        or key.namespace != selected_namespace(source, key.namespace)
        or value["coordinator_id"] != workflow_id(key)
        or value["turn_id"] != "ralf-turn-" + digest([key.to_dict(), value["session_command_id"]])
        or value["run_command_id"]
        != "ralf-session-run:" + digest([key.to_dict(), value["session_command_id"]])
        or value["run_id"] != root_run_id(deployment_id, value["scope"], value["run_command_id"])
    ):
        _reject()
    submission = value["submission"]
    _exact(submission, _SUBMISSION_FIELDS)
    _version(submission["version"])
    if len(canonical(submission).encode()) > SUBMISSION_CAPACITY:
        raise ValidationError("Session original submission exceeds its allowance")
    for field in ("manifest", "task_queue", "activity_timeout"):
        _same(submission[field], value["binding"][field])
    request, original = submission["request"], value["binding"]["request"]
    if type(request) is not dict or not {
        "input",
        "budget",
        "session_turn",
        "session_history",
    } <= set(request):
        raise ValidationError("Session intent requires its complete original Turn request")
    if set(request) - set(original) - _TURN_ADDITIONS:
        _reject()
    for field, item in original.items():
        if field not in {"input", "budget"}:
            if field not in request:
                _reject()
            _same(request[field], item)
    credits(request["budget"])
    if len(canonical(request["input"])) > HISTORY_CHARS // 2:
        raise ValidationError("Session input exceeds its existing conversation allowance")
    validate_history(request, submission["manifest"], value["scope"])
    _same(
        request["session_turn"],
        {
            "session_ref": value["session_ref"],
            "turn_id": value["turn_id"],
            "turn_seq": value["turn_seq"],
            "coordinator_id": value["coordinator_id"],
        },
    )
    return value


def validate_intent(value, *, deployment_id, scope, namespace, coordinator_execution_epoch):
    """Correlate the DTO to original context; actual SDK proof is external."""
    _scope(scope)
    _namespace(namespace)
    _text(coordinator_execution_epoch)
    value = _intent(value, deployment_id)
    if value["scope"] != scope or value["namespace"] != namespace:
        raise AuthorizationDenied("Session intent belongs to another original authority")
    _same(value["coordinator_execution_epoch"], coordinator_execution_epoch)
    return _detached(value)


def validate_origin(value, *, intent, deployment_id):
    _intent(intent, deployment_id)
    _exact(value, ORIGIN_FIELDS)
    _version(value["version"])
    for field in ORIGIN_FIELDS - {
        "coordinator_first_execution_epoch",
        "coordinator_original_execution_epoch",
    }:
        _same(value[field], intent[field])
    for field in (
        "coordinator_first_execution_epoch",
        "coordinator_original_execution_epoch",
    ):
        _same(value[field], intent["coordinator_execution_epoch"])
    return _detached(value)


def validate_never_claimed(value, *, intent, deployment_id, registry_execution_epoch):
    """Validate correlation only, never establish no-start/fence evidence."""
    _intent(intent, deployment_id)
    _exact(value, NEVER_CLAIMED_FIELDS)
    _version(value["version"])
    _text(registry_execution_epoch)
    _text(value["registry_execution_epoch"])
    _code(value["code"])
    for name in (
        "request_digest",
        "manifest_digest",
        "start_barrier_digest",
        "proof_digest",
    ):
        _sha(value[name])
    if value["never_claimed"] is not True:
        _reject()
    validate_origin(value["session_origin"], intent=intent, deployment_id=deployment_id)
    for name in ("scope", "namespace", "run_command_id", "run_id"):
        _same(value[name], intent[name])
    _same(value["registry_id"], registry_id(deployment_id))
    _same(value["registry_execution_epoch"], registry_execution_epoch)
    _same(value["request_digest"], digest(intent["submission"]["request"]))
    _same(value["manifest_digest"], digest(intent["submission"]["manifest"]))
    _same(
        value["proof_digest"],
        digest({k: v for k, v in value.items() if k != "proof_digest"}),
    )
    return _detached(value)


def _reservation(value, intent, deployment_id):
    _exact(value, _RESERVATION_FIELDS)
    _root(value["root_admission"])
    if (
        value["command_id"] != intent["run_command_id"]
        or value["target"] != intent["run_id"]
        or value["record_state"] != "durably_recorded"
        or value["apply_state"] != "not_applied"
    ):
        _reject()
    root = value["root_admission"]
    for name in ("scope", "namespace", "run_id"):
        _same(root[name], intent[name])
    _same(root["command_id"], intent["run_command_id"])
    _same(root["registry_id"], registry_id(deployment_id))
    _same(root["request_digest"], digest(intent["submission"]["request"]))
    _same(root["manifest_digest"], digest(intent["submission"]["manifest"]))


def validate_start_view(
    value, *, intent, deployment_id, registry_execution_epoch, execution_epoch=None
):
    _intent(intent, deployment_id)
    _exact(value, START_VIEW_FIELDS)
    _version(value["version"])
    _same(value["intent"], intent)
    if type(value["phase"]) is not str or value["phase"] not in _PHASES:
        raise ValidationError("Unknown Session start phase")
    phase = value["phase"]
    if value["last_error"] is not None:
        _exact(value["last_error"], {"code"})
        _code(value["last_error"]["code"])
    if phase in {"held-unbound", "start-uncertain", "started"}:
        _reservation(value["reservation"], intent, deployment_id)
    elif value["reservation"] is not None:
        _reject()
    if phase == "started":
        _text(execution_epoch)
        _text(value["execution_epoch"])
        _same(value["execution_epoch"], execution_epoch)
        receipt = value["run_receipt"]
        _exact(receipt, _RECEIPT_FIELDS)
        if (
            receipt["command_id"] != intent["run_command_id"]
            or receipt["run_id"] != intent["run_id"]
            or receipt["kind"] != "submit"
            or receipt["record_state"] != "durably_recorded"
            or receipt["apply_state"] != "applied"
            or type(receipt["outcome"]) is not dict
        ):
            _reject()
    elif value["execution_epoch"] is not None or value["run_receipt"] is not None:
        _reject()
    if phase == "start-refused":
        refusal = validate_never_claimed(
            value["start_refusal"],
            intent=intent,
            deployment_id=deployment_id,
            registry_execution_epoch=registry_execution_epoch,
        )
        if value["last_error"] is not None and value["last_error"]["code"] != refusal["code"]:
            _reject()
    elif value["start_refusal"] is not None:
        _reject()
    return _detached(value)


def _call(value):
    _exact(value, CALL_IDENTITY_FIELDS)
    _version(value["version"])
    _scope(value["scope"])
    _namespace(value["namespace"])
    for key in (
        "coordinator_id",
        "coordinator_execution_epoch",
        "session_command_id",
        "turn_id",
        "activity_id",
        "invocation_id",
    ):
        _text(value[key])
    integer(value["attempt"])
    for key in ("intent_digest", "request_digest", "manifest_digest"):
        _sha(value[key])
    _text(value["activity_name"])
    _text(value["mode"])
    if value["activity_name"] != SESSION_ACTIVITY or value["mode"] not in {
        "register",
        "observe",
    }:
        _reject()


def validate_call_identity(value, *, intent, deployment_id, request_digest):
    _intent(intent, deployment_id)
    _call(value)
    _sha(request_digest)
    for name in (
        "scope",
        "namespace",
        "coordinator_id",
        "coordinator_execution_epoch",
        "session_command_id",
        "turn_id",
        "intent_digest",
    ):
        _same(value[name], intent[name])
    _same(value["request_digest"], request_digest)
    _same(value["manifest_digest"], digest(intent["binding"]["manifest"]))
    return _detached(value)


def validate_call_end(value, *, identity, body_result):
    _call(identity)
    _exact(value, CALL_END_FIELDS)
    _same(value["identity"], identity)
    _sha(value["body_result_digest"])
    if value["body_stopped"] is not True or value["recorded"] is not True:
        _reject()
    _same(value["body_result_digest"], digest(body_result))
    return _detached(value)
