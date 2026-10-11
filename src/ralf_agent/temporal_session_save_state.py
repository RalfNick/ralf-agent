"""Pure original Run save intents and receipt adoption; no data I/O authority."""

import json
import re

from .errors import DefinitionMismatch, ValidationError
from .session_receipts import validate_inspection
from .temporal_session_data_state import validate_snapshot
from .temporal_session_tree import execution_fields
from .types import Scope, canonical, digest

ACTIVITY = "ralf.temporal.session-save.v1"
TERMINAL = {"succeeded", "failed", "cancelled"}


def detached(value):
    return json.loads(canonical(value))


def bounded_inspection(value, scope, address, message_id, max_message_chars):
    value = validate_inspection(value, scope, address, message_id)
    receipt = value["receipt"]
    if len(canonical(value)) > max_message_chars + 4096 or (
        receipt is not None and len(canonical(receipt["message"])) > max_message_chars
    ):
        raise ValidationError("Original Session inspection exceeded fixed receipt capacity")
    return value


def validate_protocol(manifest):
    from .temporal_session_tree_protocol import validate_protocol as validate_tree_protocol

    validate_tree_protocol(manifest)
    if "session_save_protocol" not in manifest:
        return
    policy = manifest["session_save_protocol"]
    if (
        type(policy) is not dict
        or set(policy)
        != {"version", "write_credits", "max_message_chars", "dataset_ids", "dataset_ports"}
        or type(policy["version"]) is not int
        or policy["version"] not in {1, 2}
        or type(policy["write_credits"]) is not int
        or policy["write_credits"] != 1
        or type(policy["max_message_chars"]) is not int
        or not 2 <= policy["max_message_chars"] <= 65536
        or manifest.get("session_data_protocol") != 1
        or manifest["kernel"] != "temporal-3"
        or type(policy.get("dataset_ids")) is not dict
        or not policy["dataset_ids"]
        or type(policy.get("dataset_ports")) is not dict
        or set(policy["dataset_ports"]) != set(policy["dataset_ids"])
    ):
        raise DefinitionMismatch("Unsupported original Session save protocol")
    sources = ([manifest["session_data"]] if "session_data" in manifest else []) + [
        r["configuration"]["session_data"]
        for r in manifest.get("binding_catalog", {}).get("records", {}).values()
        if r.get("role") == "session"
    ]
    if set(policy["dataset_ids"]) != {digest(s["physical"]) for s in sources} or any(
        type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None
        for pair in policy["dataset_ids"].items()
        for value in pair
    ):
        raise DefinitionMismatch("Session save requires its exact original dataset catalog")


def prepare(state, result):
    if (
        "session_save_protocol" not in state.step_manifest
        or "session_data" not in state.step_manifest
    ):
        return False
    if str(state.node) in state.session_stages:
        raise DefinitionMismatch("Original Session save stage was already prepared")
    context_request = {
        "scope": state.scope,
        "run_id": state.run_id,
        "step": state.step,
        "session_data_node": state.node,
        **execution_fields(state.request),
    }
    validate_snapshot(state.context_snapshot, state.step_manifest, context_request)
    source = state.context_snapshot["session_data"]
    model = next(
        a
        for a in reversed(state.actions)
        if a["node"] == state.node and a["kind"] == "model" and a["status"] == "completed"
    )
    message = {
        "role": "assistant",
        "task": detached(state.completion_task),
        "content": detached(result),
    }
    if len(canonical(message)) > state.manifest["session_save_protocol"]["max_message_chars"]:
        state.state, state.error = "failed", {"code": "session_message_capacity"}
        state._emit("run_failed", state.error)
        return True
    intent = {
        "version": 1,
        "scope": detached(state.scope),
        "run_id": state.run_id,
        "node": state.node,
        "registration_digest": source["registration_digest"],
        "address": source["address"],
        "expected_revision": source["revision"],
        "message_id": "ralf-session-message-v1:"
        + digest([state.epoch, state.run_id, state.node, model["id"]]),
        "message": message,
        "source_action": model["id"],
        "source_response_digest": digest(model["response"]),
        "result": detached(result),
    }
    state.session_stages[str(state.node)] = {
        "node": state.node,
        "intent": intent,
        "phase": "inspect",
        "status": "preparing",
        "step_bindings": state.step_bindings,
        "operations": [],
        "execution_stopped": False,
        "prior_remote_uncertain": state.remote_uncertain,
    }
    state.pending_session = str(state.node)
    state._emit(
        "session_save_intent_recorded", {"node": state.node, "intent_digest": digest(intent)}
    )
    return True


def next_stage(state):
    key = state.pending_session
    if key is None and state.session_recovery:
        key = state.session_recovery.pop(0)
        state.pending_session = key
    if key is None:
        return None
    stage = state.session_stages[key]
    phase = stage["phase"]
    if phase is None:
        return None
    if stage.get("source_kind") == "parent-aggregate" and phase == "session-write":
        from .temporal_parent_session import release_allowance

        release_allowance(state)
    if state.state in TERMINAL and phase == "session-write":
        stage.update(phase=None, status="closed")
        state.pending_session = None
        return None
    action = {
        "id": f"{state.run_id}:session:{stage['node']}:{len(stage['operations'])}",
        "kind": "managed_session",
        "node": stage["node"],
        "phase": phase,
        "stage_key": key,
        "status": "executing",
        "attempts": [],
    }
    if phase == "session-write" and state.budget["remaining"] < 1:
        state.state, state.error = "failed", {"code": "budget_exceeded"}
        state._emit("run_failed", state.error)
        stage.update(phase=None, status="failed")
        state.pending_session = None
        return None
    state.actions.append(action)
    stage["operations"].append(action["id"])
    if phase == "session-write":
        stage["execution_stopped"] = False
        state._reserve(action, 1)
        stage["write_action"] = action["id"]
    else:
        state.active_action = action["id"]
    request = {
        "runtime_manifest": detached(state.manifest),
        "scope": detached(state.scope),
        "run_id": state.run_id,
        "release_digest": state.release_digest,
        "action_id": action["id"],
        "phase": phase,
        "intent": detached(stage["intent"]),
        **(
            {
                k: detached(stage["read_request"][k])
                for k in (
                    "session_source",
                    "session_data_node",
                    "session_lineage",
                    "session_declaration",
                    "query",
                    "address",
                )
            }
            if stage.get("source_kind") == "parent-aggregate"
            else {
                "step": state.step,
                "session_data_node": stage["node"],
                "step_bindings": detached(stage["step_bindings"]),
            }
        ),
        **execution_fields(state.request),
    }
    if phase == "adopt":
        request["received_inspection"] = detached(stage["received_inspection"])
    action["request_digest"] = digest(request)
    state._emit(
        "session_save_operation_recorded",
        {"action_id": action["id"], "phase": phase, "request_digest": digest(request)},
    )
    return action, request


def _hold(state, stage, code):
    stage.update(status="outcome_unknown", phase=None, error={"code": code})
    state.pending_session = None
    if "write_action" in stage:
        action = next(a for a in state.actions if a["id"] == stage["write_action"])
        action["status"] = "outcome_unknown"
        action["attempts"][0]["status"] = "unknown"
        state.reservations[action["attempts"][0]["id"]]["status"] = "unknown"
        if not stage["execution_stopped"]:
            state.remote_uncertain = True
            stage["owns_remote_uncertainty"] = True
    if state.state not in TERMINAL:
        state.state, state.error = "waiting_reconciliation", {"code": code}
    state._emit("session_save_unconfirmed", {"node": stage["node"], "code": code})


def _receipt(stage, value):
    intent = stage["intent"]
    value = validate_inspection(
        value, Scope(**intent["scope"]), intent["address"], intent["message_id"]
    )
    receipt = value["receipt"]
    if receipt is not None and (
        receipt["message"] != intent["message"]
        or receipt["revision"] != intent["expected_revision"] + 1
    ):
        raise DefinitionMismatch("Session receipt differs from original accepted save intent")
    return value


def accept_stage(state, action_id, response):
    action = next(a for a in state.actions if a["id"] == action_id)
    stage = state.session_stages[action["stage_key"]]
    phase = action["phase"]
    state.active_action = None
    if phase in {"inspect", "verify"} and response.get("ok"):
        intent = stage["intent"]
        try:
            bounded_inspection(
                response["inspection"],
                Scope(**intent["scope"]),
                intent["address"],
                intent["message_id"],
                state.manifest["session_save_protocol"]["max_message_chars"],
            )
        except (ValidationError, KeyError, TypeError):
            response = {"ok": False, "code": "session_inspection_invalid", "dispatched": False}
    action.update(status="completed", response=detached(response))
    state._emit("session_save_response_recorded", {"action_id": action_id})
    if phase == "session-write":
        if response.get("execution_stopped") is True:
            stage["execution_stopped"] = True
        if not response.get("ok"):
            if not response.get("dispatched"):
                state._settle(action, undispatched=True)
                stage.update(status="failed", phase=None)
                state.pending_session = None
                if state.state not in TERMINAL:
                    state.state, state.error = (
                        "failed",
                        {"code": response.get("code", "session_save_failed")},
                    )
            else:
                if not action.get("dispatch_grant", {}).get("allowed"):
                    # History admits append before any handler starts. Once
                    # this action is held, late admission is permanently denied.
                    stage["execution_stopped"] = True
                    action["dispatch_fenced_without_grant"] = True
                _hold(state, stage, response.get("code", "session_save_unknown"))
            return
        if (
            type(response.get("revision")) is not int
            or response["revision"] != stage["intent"]["expected_revision"] + 1
        ):
            _hold(state, stage, "session_ack_invalid")
            return
        stage["phase"] = "verify"
        return
    if not response.get("ok"):
        _hold(state, stage, response.get("code", "session_inspection_failed"))
        return
    try:
        if phase in {"inspect", "verify"}:
            value = _receipt(stage, response["inspection"])
            if value["receipt"] is None:
                if (
                    phase == "inspect"
                    and value["revision"] == stage["intent"]["expected_revision"]
                    and state.state not in TERMINAL
                ):
                    stage["phase"] = "session-write"
                elif (
                    phase == "verify"
                    and stage["execution_stopped"]
                    and value["revision"] == stage["intent"]["expected_revision"]
                ):
                    write = next(a for a in state.actions if a["id"] == stage["write_action"])
                    state._settle(
                        write, undispatched=write.get("dispatch_fenced_without_grant", False)
                    )
                    write["status"] = "completed_no_record"
                    if state.state not in TERMINAL:
                        stage["phase"] = "session-write"
                    else:
                        _close_unwritten(state, stage, value)
                elif (
                    phase == "inspect"
                    and "write_action" not in stage
                    and state.state in TERMINAL
                    and value["revision"] == stage["intent"]["expected_revision"]
                ):
                    _close_unwritten(state, stage, value)
                else:
                    _hold(state, stage, "session_receipt_missing")
                return
            stage["received_inspection"] = value
            stage["phase"] = "adopt"
            state._emit(
                "session_receipt_received", {"node": stage["node"], "receipt_digest": digest(value)}
            )
            return
        if phase != "adopt" or response.get("intent_digest") != digest(stage["intent"]):
            raise DefinitionMismatch("Session adoption lost original save intent")
        _receipt(stage, stage["received_inspection"])
        if "write_action" in stage and not stage["execution_stopped"]:
            _hold(state, stage, "session_execution_unconfirmed")
            return
        if "write_action" in stage:
            write = next(a for a in state.actions if a["id"] == stage["write_action"])
            state._settle(write)
            write["status"] = "completed"
        stage.update(status="completed", phase=None)
        stage["owns_remote_uncertainty"] = False
        state.remote_uncertain = stage["prior_remote_uncertain"]
        state.pending_session = None
        state._emit(
            "session_save_adopted",
            {"node": stage["node"], "message_id": stage["intent"]["message_id"]},
        )
        if state.state not in TERMINAL:
            state.state, state.error = "running", None
            state._complete_node(stage["intent"]["result"])
    except (DefinitionMismatch, ValidationError, KeyError, TypeError) as exc:
        _hold(state, stage, getattr(exc, "code", "validation_error"))


def request_recovery(state):
    for key, stage in state.session_stages.items():
        if stage["status"] == "outcome_unknown" and key not in state.session_recovery:
            stage["phase"] = "verify" if "write_action" in stage else "inspect"
            state.session_recovery.append(key)


def _close_unwritten(state, stage, inspection):
    stage.update(status="closed_no_record", phase=None, no_record_inspection=detached(inspection))
    state.pending_session = None
    if stage.get("owns_remote_uncertainty"):
        state.remote_uncertain = stage["prior_remote_uncertain"]
        stage["owns_remote_uncertainty"] = False
    state._emit(
        "session_save_closed_no_record",
        {
            "node": stage["node"],
            "inspection_digest": digest(inspection),
        },
    )
