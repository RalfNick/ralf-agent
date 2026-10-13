"""Original Parent root snapshot and aggregate save gate; no extra executor."""

from .errors import DefinitionMismatch, RalfError, ValidationError
from .temporal_session_data_state import validate_snapshot
from .temporal_session_save_state import next_stage
from .temporal_session_tree import require_tree_admission, root_source, validate_lineage
from .temporal_state import TERMINAL, detached
from .types import canonical, digest

ROOT_READ_ACTIVITY = "ralf.temporal.session-root-read.v1"


def initialize(state):
    state.root_session_snapshot = None
    state.root_read_request = None
    state.root_write_allowance = None
    state.root_aggregate = None
    state.root_session_required = False
    state.root_context_ready = True
    if "session_tree_protocol" not in state.manifest:
        return
    require_tree_admission(state.request, state.manifest)
    if "session_lineage" not in state.request:
        return
    accepted = validate_lineage(state.request, state.manifest, state.scope)
    if accepted["run_id"] != state.run_id:
        raise DefinitionMismatch("Parent tree belongs to another original Run")
    if accepted["parent_run_id"] is not None:
        state.root_session_snapshot = detached(state.request.get("session_root_snapshot"))
        return
    state.root_session_required = root_source(state.manifest) is not None
    if not state.root_session_required:
        return
    state.root_context_ready = False
    if state.request["budget"] < 1:
        state.state, state.error = "failed", {"code": "budget_exceeded"}
        state._emit("run_failed", state.error)
        return
    state.root_write_allowance = state.run_id + ":session-root-allowance"
    state.reservations[state.root_write_allowance] = {
        "id": state.root_write_allowance,
        "amount": 1,
        "status": "reserved",
    }
    state._emit("session_root_allowance_reserved", {"amount": 1})


def release_allowance(state):
    key = state.root_write_allowance
    if key is not None and state.reservations[key]["status"] != "settled":
        state.reservations[key].update(status="settled", actual=0)
        state._emit("session_root_allowance_released", {"amount": 1})


def _read_request(state):
    registration = state.manifest["session_data"]
    lineage = state.request["session_lineage"]
    return {
        "runtime_manifest": detached(state.manifest),
        "scope": state.scope,
        "run_id": state.run_id,
        "release_digest": state.release_digest,
        "session_source": "root",
        "session_data_node": "root",
        "session_lineage": detached(lineage),
        "session_declaration": {
            "definition": detached(state.definition),
            "agent_bindings": detached(state.request.get("agent_bindings", {})),
        },
        "query": detached(registration["query"]),
        "address": lineage["root_turn"]["session_ref"]["key"]["session_id"],
    }


def next_operation(state):
    if state.active_action is not None:
        return None
    if state.state in TERMINAL:
        release_allowance(state)
    operation = next_stage(state)
    if operation is not None:
        return operation
    if state.state in TERMINAL or state.root_context_ready:
        return None
    from .session_types import SessionRef

    request = _read_request(state)
    request["address"] = SessionRef.from_dict(
        state.request["session_lineage"]["root_turn"]["session_ref"]
    ).key.storage_key
    action = {
        "id": f"{state.run_id}:session-root-read:{len(state.actions)}",
        "kind": "session_root_read",
        "phase": "session-root-read",
        "node": "root",
        "status": "executing",
        "attempts": [],
    }
    request.update(action_id=action["id"], phase=action["phase"])
    action["request_digest"] = digest(request)
    state.actions.append(action)
    state.active_action, state.state = action["id"], "running"
    state.root_read_request = detached(request)
    state._emit(
        "session_root_read_intent_recorded",
        {"action_id": action["id"], "request_digest": digest(request)},
    )
    return action, request


def _settle_reader(state, action):
    if (
        not action.get("dispatch_grant", {}).get("allowed")
        or "execution_end_proof" in action
        or action.get("response", {}).get("handler_not_started") is True
    ):
        state.active_action = None


def end_read(state, action, proof):
    if "execution_end_proof" not in action:
        action["execution_end_proof"] = detached(proof)
        state._emit("session_execution_ended", {"action_id": action["id"]})
    if "response" in action or action["status"] == "rejected":
        _settle_reader(state, action)
    return {"action_id": action["id"], "execution_stopped": True}


def accept_read(state, action_id, response):
    action = next((a for a in state.actions if a["id"] == action_id), None)
    if action is None or action["kind"] != "session_root_read" or state.active_action != action_id:
        raise DefinitionMismatch("Root read response lost original active Action")
    if not response.get("ok"):
        action.update(
            status="outcome_unknown"
            if action.get("dispatch_grant", {}).get("allowed")
            and "execution_end_proof" not in action
            and response.get("handler_not_started") is not True
            else "failed",
            response=detached(response),
        )
        _settle_reader(state, action)
        if state.state not in TERMINAL:
            state.state, state.error = (
                "failed",
                {"code": response.get("code", "session_read_failed")},
            )
        release_allowance(state)
        state._emit("session_root_read_failed", {"action_id": action_id})
        return
    try:
        validate_snapshot(response, state.manifest, state.root_read_request)
    except RalfError:
        action["status"] = "rejected"
        _settle_reader(state, action)
        if state.state not in TERMINAL:
            state.state, state.error = "failed", {"code": "session_read_invalid"}
        release_allowance(state)
        raise
    action.update(status="completed", response=detached(response))
    _settle_reader(state, action)
    state._emit(
        "session_root_snapshot_received",
        {"action_id": action_id, "snapshot_digest": digest(response)},
    )
    if state.state in TERMINAL:
        release_allowance(state)
        return
    state.root_session_snapshot = detached(response)
    state.root_context_ready = True
    state._emit(
        "session_root_snapshot_adopted",
        {"action_id": action_id, "snapshot_digest": digest(response)},
    )


def prepare_result(state, result):
    if not state.root_session_required:
        return False
    if not state.root_context_ready or not state.children_quiescent:
        raise ValidationError("Original root and actual descendants must settle before aggregate")
    if state.root_aggregate is not None:
        raise DefinitionMismatch("Original Parent aggregate was already prepared")
    validate_snapshot(state.root_session_snapshot, state.manifest, state.root_read_request)
    message = {
        "role": "assistant",
        "task": detached(state.request["input"]),
        "content": detached(result),
    }
    if len(canonical(message)) > state.manifest["session_save_protocol"]["max_message_chars"]:
        state.state, state.error = "failed", {"code": "session_message_capacity"}
        release_allowance(state)
        state._emit("run_failed", state.error)
        return True
    evidence = {
        "kind": "parent-aggregate",
        "parent_kind": state.kind,
        "request_digest": digest(state.request),
        "result": detached(result),
        "root_snapshot_digest": digest(state.root_session_snapshot),
        "children": [
            {
                "id": c["id"],
                "run_id": c["run_id"],
                "request_digest": digest(c["request"]),
                "observation_digest": c.get("observation_digest"),
                "snapshot_digest": digest(c.get("snapshot")),
            }
            for c in state.children
            if not (
                state.manifest.get("parent_completion_protocol") == 1
                and c.get("role") == "verifier"
            )
        ],
    }
    aggregate_id = state.run_id + ":aggregate"
    state.root_aggregate = detached(evidence)
    state.actions.append(
        {
            "id": aggregate_id,
            "kind": "aggregate",
            "status": "completed",
            "attempts": [],
            "response": detached(evidence),
        }
    )
    state._emit(
        "parent_aggregate_adopted", {"action_id": aggregate_id, "source_digest": digest(evidence)}
    )
    source = state.root_session_snapshot["session_data"]
    intent = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "node": "root",
        "registration_digest": source["registration_digest"],
        "address": source["address"],
        "expected_revision": source["revision"],
        "message_id": "ralf-session-message-v1:"
        + digest([state.epoch, state.run_id, "root", aggregate_id]),
        "message": message,
        "source_kind": "parent-aggregate",
        "source_action": aggregate_id,
        "source_response_digest": digest(evidence),
        "result": detached(result),
    }
    state.session_stages["root"] = {
        "node": "root",
        "source_kind": "parent-aggregate",
        "intent": detached(intent),
        "read_request": detached(state.root_read_request),
        "phase": "inspect",
        "status": "preparing",
        "operations": [],
        "execution_stopped": False,
        "prior_remote_uncertain": state.remote_uncertain,
    }
    state.pending_session, state.stage = "root", "session-save"
    state.state = "running"
    state._emit("session_save_intent_recorded", {"node": "root", "intent_digest": digest(intent)})
    return True
