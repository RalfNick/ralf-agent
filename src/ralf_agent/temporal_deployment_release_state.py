"""Original History owns actual calls and immutable deployment closure seals."""

import copy
import re

from . import temporal_deployment_execution_state as deployment
from .errors import DefinitionMismatch, ValidationError
from .temporal_deployment_admission import _exact, _sha, _text
from .types import canonical, digest

CALL_CAPACITY = 4096
CALL_FIELDS = {
    "version",
    "scope",
    "run_id",
    "execution_epoch",
    "activity_id",
    "activity_name",
    "attempt",
    "invocation_id",
    "request_digest",
    "manifest_digest",
}
CHILD_FIELDS = {
    "call_id",
    "run_id",
    "command_id",
    "execution_epoch",
    "request_digest",
    "admission_digest",
    "seal_digest",
}
CERTIFICATE_FIELDS = {
    "version",
    "scope",
    "run_id",
    "command_id",
    "namespace",
    "execution_epoch",
    "original_execution_epoch",
    "request_digest",
    "manifest_digest",
    "admission_digest",
    "receipt_digest",
    "terminal_state",
    "closure_digest",
    "children",
    "proof_digest",
}
TERMINAL = {"succeeded", "failed", "cancelled"}


def public(manifest):
    value = manifest.get("deployment_admission_protocol") if type(manifest) is dict else None
    return type(value) is dict and type(value.get("version")) is int and value["version"] == 2


def _detached(value):
    canonical(value)
    return copy.deepcopy(value)


def initialize(state):
    if not public(state.manifest):
        return
    if not hasattr(state, "deployment_calls"):
        state.deployment_calls = {}
        state.deployment_seal = None
        state.deployment_retirement = None


def _require(state):
    if not public(state.manifest) or not hasattr(state, "deployment_calls"):
        raise DefinitionMismatch("Original public deployment closure is unavailable")
    return deployment.view(state)


def check_unsealed(state):
    if public(state.manifest) and getattr(state, "deployment_seal", None) is not None:
        raise DefinitionMismatch("Original deployment closure is irreversible")


def _identity(state, payload):
    _exact(payload, CALL_FIELDS)
    if (
        type(payload["version"]) is not int
        or payload["version"] != 1
        or type(payload["attempt"]) is not int
        or payload["attempt"] < 1
    ):
        raise ValidationError("Actual call requires exact protocol and positive SDK attempt")
    for field in ("run_id", "execution_epoch", "activity_id", "activity_name"):
        _text(payload[field])
        if len(payload[field]) > 1024:
            raise ValidationError("Actual call identity exceeds its allowance")
    if (
        type(payload["invocation_id"]) is not str
        or re.fullmatch("[a-f0-9]{32}", payload["invocation_id"]) is None
    ):
        raise ValidationError("Actual call requires an original invocation UUID")
    _sha(payload["request_digest"])
    _sha(payload["manifest_digest"])
    if (
        payload["scope"] != state.scope
        or payload["run_id"] != state.run_id
        or payload["execution_epoch"] != state.epoch
        or payload["manifest_digest"] != digest(state.manifest)
    ):
        raise DefinitionMismatch("Actual call differs from original deployment identity")
    return digest([payload["activity_id"], payload["attempt"]])


def _ack(payload, field, value):
    return {
        "activity_id": payload["activity_id"],
        "attempt": payload["attempt"],
        "invocation_id": payload["invocation_id"],
        field: value,
    }


def begin_activity(state, payload):
    if not public(state.manifest):
        return None
    _require(state)
    if not deployment.admitted(state):
        raise DefinitionMismatch("Original deployment admission must precede call ownership")
    key = _identity(state, payload)
    previous = state.deployment_calls.get(key)
    if previous is not None:
        if previous["identity"] != payload:
            raise DefinitionMismatch("Original SDK call owner cannot be replaced")
        return _ack(
            payload,
            "allowed",
            previous["allowed"] and not previous["stopped"] and state.deployment_seal is None,
        )
    check_unsealed(state)
    if len(state.deployment_calls) >= CALL_CAPACITY:
        raise ValidationError("Original actual-call ledger capacity exhausted")
    if any(
        record["identity"]["activity_id"] == payload["activity_id"]
        and record["allowed"]
        and not record["stopped"]
        for record in state.deployment_calls.values()
    ):
        raise DefinitionMismatch("An earlier SDK attempt still owns its actual handler")
    state.deployment_calls[key] = {
        "identity": _detached(payload),
        "allowed": True,
        "stopped": False,
        "end_proof": None,
    }
    return _ack(payload, "allowed", True)


def end_activity(state, payload):
    if not public(state.manifest):
        return None
    _require(state)
    key = _identity(state, payload)
    record = state.deployment_calls.get(key)
    if record is None or record["identity"] != payload:
        raise DefinitionMismatch("Actual end must acknowledge its original exclusive call")
    record["stopped"] = True
    record["end_proof"] = _detached(payload)
    return _ack(payload, "recorded", True)


def _retirable(stage, *, parent=False):
    return (
        type(stage) is dict
        and stage.get("status") in ({"prepared", "proposal_received"} if parent else {"prepared"})
        and stage.get("action_id") is None
        and stage.get("operation") is None
        and stage.get("child_key") is None
    )


def _obligations(state):
    fields = (
        "reservations",
        "actions",
        "active_action",
        "remote_uncertain",
        "pending_acks",
        "deferred_acks",
        "reconcile_requests",
        "active_reconciliation",
        "active_evidence_ack",
        "pending_completion",
        "pending_verification",
        "pending_session",
        "memory_recovery",
        "session_recovery",
        "tool_executions",
        "context_read_stages",
        "memory_stages",
        "session_stages",
        "managed_context_stages",
        "completion_stages",
        "limits_stages",
        "parent_completion_stages",
        "parent_completion_pending",
        "context_artifact_dispatches",
        "context_artifact_receipts",
        "input_requests",
        "root_aggregate",
        "children",
    )
    return {field: _detached(getattr(state, field, None)) for field in fields}


def closure(state):
    if not public(state.manifest):
        return False, ["public_protocol_required"]
    _require(state)
    reasons = []
    if not deployment.admitted(state):
        reasons.append("deployment_not_admitted")
    if state.state not in TERMINAL:
        reasons.append("business_not_terminal")
    if any(value.get("status") != "settled" for value in state.reservations.values()):
        reasons.append("unsettled_reservation")
    for field in (
        "active_action",
        "remote_uncertain",
        "pending_acks",
        "deferred_acks",
        "reconcile_requests",
        "active_reconciliation",
        "active_evidence_ack",
        "memory_recovery",
        "session_recovery",
    ):
        if getattr(state, field, None):
            reasons.append(field)
    if any(
        record["allowed"] and (not record["stopped"] or record["end_proof"] != record["identity"])
        for record in state.deployment_calls.values()
    ):
        reasons.append("actual_call_not_stopped")
    if any(
        action.get("status") in {"executing", "outcome_unknown", "received"}
        or any(
            attempt.get("status") in {"executing", "unknown"}
            for attempt in action.get("attempts", [])
        )
        for action in state.actions
    ):
        reasons.append("unfinished_action")
    if any(
        value.get("execution_stopped") is not True
        for value in getattr(state, "tool_executions", {}).values()
    ):
        reasons.append("tool_not_stopped")
    for value in getattr(state, "context_read_stages", {}).values():
        if not value.get("response_observed") or not (
            value.get("execution_end_proof") is not None
            or value.get("fenced") is True
            or value.get("handler_not_started") is True
        ):
            reasons.append("context_read_unfinished")
            break
    for value in getattr(state, "session_stages", {}).values():
        if (
            value.get("status") not in {"completed", "failed", "closed", "closed_no_record"}
            or value.get("write_action") is not None
            and value.get("execution_stopped") is not True
        ):
            reasons.append("session_stage_unfinished")
            break
    for value in getattr(state, "memory_stages", {}).values():
        if value.get("status") not in {"completed", "failed", "closed"} or any(
            fact.get("status") in {"writing", "outcome_unknown"} for fact in value.get("facts", [])
        ):
            reasons.append("memory_stage_unfinished")
            break
    if not set(getattr(state, "context_artifact_dispatches", {})) <= set(
        getattr(state, "context_artifact_receipts", {})
    ):
        reasons.append("artifact_effect_unconfirmed")
    for field, allowed in (
        ("managed_context_stages", {"completed", "failed", "closed"}),
        ("limits_stages", None),
        ("completion_stages", {"completed", "failed", "closed"}),
        ("parent_completion_stages", {"adopted", "failed", "closed"}),
    ):
        for stage in getattr(state, field, {}).values():
            if allowed is None:
                if "response" not in stage:
                    reasons.append("limits_stage_unfinished")
            elif stage.get("status") not in allowed and not (
                state.state in TERMINAL
                and _retirable(stage, parent=field == "parent_completion_stages")
            ):
                reasons.append(field + "_unfinished")
    for pending, stages, retire in (
        ("pending_verification", "completion_stages", True),
        ("parent_completion_pending", "parent_completion_stages", True),
        ("pending_completion", "memory_stages", False),
        ("pending_session", "session_stages", False),
    ):
        key = getattr(state, pending, None)
        if key is not None and not (
            retire
            and state.state in TERMINAL
            and _retirable(
                getattr(state, stages, {}).get(key), parent=pending == "parent_completion_pending"
            )
        ):
            reasons.append(pending)
    if any(
        value.get("state") == "pending" for value in getattr(state, "input_requests", {}).values()
    ):
        reasons.append("input_pending")
    for call in getattr(state, "children", []):
        if (
            call.get("settled") is not True
            or call.get("uncertain") is True
            or call.get("dispatch_started") is True
            and not call.get("deployment_execution_epoch")
        ):
            reasons.append("child_unfinished")
            break
    return not reasons, sorted(set(reasons))


def view(state):
    if not public(state.manifest):
        return None
    proof = _require(state)
    ready, reasons = closure(state)
    return _detached(
        {
            "version": 1,
            "deployment": proof,
            "ready": ready,
            "reasons": reasons,
            "calls": state.deployment_calls,
            "seal": state.deployment_seal,
        }
    )


def _children(state, entries):
    calls = getattr(state, "children", [])
    if type(entries) is not list or len(entries) != len(calls):
        raise DefinitionMismatch("Closure must pin every original direct child")
    by_id = {}
    for entry in entries:
        _exact(entry, CHILD_FIELDS)
        if entry["call_id"] in by_id:
            raise DefinitionMismatch("Closure child identity is repeated")
        by_id[entry["call_id"]] = entry
    for call in calls:
        child = by_id.get(call["id"])
        if child is None or any(
            child[key] != value
            for key, value in (
                ("run_id", call["run_id"]),
                ("command_id", call["command_id"]),
                ("request_digest", digest(call["request"])),
                ("admission_digest", digest(call["deployment_admission"])),
            )
        ):
            raise DefinitionMismatch("Child seal differs from original intent")
        if call.get("settled") is not True or call.get("uncertain") is True:
            raise DefinitionMismatch("Original child still owns unresolved work")
        if call.get("dispatch_started") is True or call.get("started") is True:
            epoch = call.get("deployment_execution_epoch")
            if not epoch or child["execution_epoch"] != epoch:
                raise DefinitionMismatch("Original child SDK epoch is not closed")
            _sha(child["seal_digest"])
        elif (
            child["execution_epoch"] is not None
            or child["seal_digest"] is not None
            or call.get("deployment_execution_epoch") is not None
            or call.get("state") not in TERMINAL
        ):
            raise DefinitionMismatch("Original undispatched child proof changed")
    return _detached([by_id[call["id"]] for call in calls])


def seal(state, payload):
    if not public(state.manifest):
        return None
    proof = _require(state)
    _exact(payload, {"scope", "children"})
    if payload["scope"] != state.scope:
        raise DefinitionMismatch("Closure belongs to another original Scope")
    children = _children(state, payload["children"])
    if state.deployment_seal is not None:
        if state.deployment_seal["children"] != children:
            raise DefinitionMismatch("Original child seals cannot change")
        return _detached(state.deployment_seal)
    ready, _ = closure(state)
    if not ready:
        raise DefinitionMismatch("Original deployment obligations remain held")
    for field, pending in (
        ("completion_stages", "pending_verification"),
        ("parent_completion_stages", "parent_completion_pending"),
    ):
        for stage in getattr(state, field, {}).values():
            if _retirable(stage, parent=field == "parent_completion_stages"):
                stage["status"] = "closed"
        if getattr(state, pending, None) is not None:
            setattr(state, pending, None)
    certificate = {
        "version": 1,
        **{
            key: proof[key]
            for key in (
                "scope",
                "run_id",
                "command_id",
                "namespace",
                "execution_epoch",
                "original_execution_epoch",
                "request_digest",
                "manifest_digest",
            )
        },
        "admission_digest": digest(proof["admission"]),
        "receipt_digest": digest(proof["admission_receipt"]),
        "terminal_state": state.state,
        "closure_digest": digest(
            {"obligations": _obligations(state), "calls": state.deployment_calls}
        ),
        "children": children,
    }
    state.deployment_seal = _detached({**certificate, "proof_digest": digest(certificate)})
    return _detached(state.deployment_seal)
