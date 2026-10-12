"""Original Tool intent and actual stop evidence, independent of effect receipt."""

import copy

from .errors import DefinitionMismatch
from .temporal_tool_execution import enabled
from .types import digest

ADMISSION_UPDATE = "admit_tool_dispatch"
END_UPDATE = "tool_execution_ended"


def prepare(state, action, request):
    if not enabled(state.manifest):
        return request
    request = copy.deepcopy(request)
    request["release_digest"] = state.release_digest
    state.tool_executions[action["id"]] = {
        "action_id": action["id"],
        "request_digest": digest(request),
        "execution_epoch": state.epoch,
        "execution_stopped": False,
        "prior_remote_uncertain": state.remote_uncertain,
        "owns_remote_uncertainty": False,
    }
    return request


def record(state, payload, *, admission=False):
    if type(payload) is not dict:
        raise DefinitionMismatch("Tool execution requires original completed proof")
    state.authorize(payload.get("scope"))
    action_id = payload.get("action_id")
    if type(action_id) is not str or action_id not in state.tool_executions:
        raise DefinitionMismatch("Tool execution requires original Tool intent")
    value = state.tool_executions[action_id]
    expected = {
        "scope": state.scope,
        "action_id": action_id,
        "release_digest": state.release_digest,
        "request_digest": value["request_digest"],
        "execution_epoch": value["execution_epoch"],
    }
    if admission:
        expected["run_id"] = state.run_id
    invocation = payload.get("invocation_id")
    if (
        type(invocation) is not str
        or len(invocation) != 32
        or any(char not in "0123456789abcdef" for char in invocation)
    ):
        raise DefinitionMismatch("Tool execution requires a fixed original invocation")
    expected["invocation_id"] = invocation
    if payload != expected:
        raise DefinitionMismatch("Tool execution proof differs from original complete intent")
    return value, next(a for a in state.actions if a["id"] == action_id)


def admit(state, payload):
    value, action = record(state, payload, admission=True)
    invocation = payload["invocation_id"]
    claim = value.get("invocation_id")
    if claim is not None:
        return {
            "run_id": state.run_id,
            "action_id": action["id"],
            "release_digest": state.release_digest,
            "invocation_id": invocation,
            "claimed": claim == invocation,
            "allowed": claim == invocation
            and value["grant_allowed"]
            and not value["execution_stopped"],
        }
    allowed = (
        not value["execution_stopped"]
        and state.state not in {"succeeded", "failed", "cancelled"}
        and state.active_action == action["id"]
        and action["status"] == "executing"
    )
    value.update(invocation_id=invocation, grant_allowed=allowed)
    state._emit("tool_dispatch_admitted", {"action_id": action["id"], "allowed": allowed})
    return {
        "run_id": state.run_id,
        "action_id": action["id"],
        "release_digest": state.release_digest,
        "allowed": allowed,
        "invocation_id": invocation,
        "claimed": True,
    }


def refresh(state):
    if not enabled(state.manifest):
        return
    # Only this Tool protocol's uncertainty is discharged by its actual end.
    own = any(value["owns_remote_uncertainty"] for value in state.tool_executions.values())
    foreign = state.remote_uncertain and not own
    state.remote_uncertain = (
        foreign
        or any(
            value["prior_remote_uncertain"]
            or (value["owns_remote_uncertainty"] and not value["execution_stopped"])
            for value in state.tool_executions.values()
        )
        or any(
            action["status"] == "outcome_unknown" and action["id"] not in state.tool_executions
            for action in state.actions
        )
    )


def unknown(state, action_id):
    value = state.tool_executions.get(action_id)
    if value is not None:
        if state.remote_uncertain and not any(
            item["owns_remote_uncertainty"] for item in state.tool_executions.values()
        ):
            value["prior_remote_uncertain"] = True
        value["owns_remote_uncertainty"] = True


def ended(state, payload):
    value, action = record(state, payload)
    if value.get("invocation_id") != payload["invocation_id"]:
        raise DefinitionMismatch("Tool end differs from its original exclusive invocation")
    if not value["execution_stopped"]:
        value["execution_stopped"] = True
        value["end_proof"] = copy.deepcopy(payload)
        state._emit("tool_execution_ended", {"action_id": action["id"]})
    refresh(state)
    return {"action_id": action["id"], "recorded": True}


def stopped(state):
    return all(value["execution_stopped"] for value in state.tool_executions.values())
