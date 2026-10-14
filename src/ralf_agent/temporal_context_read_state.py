"""Original Native History owns read admission, observation and actual end."""

import copy

from .errors import DefinitionMismatch, IdempotencyConflict, RalfError, ValidationError
from .temporal_context_read_protocol import PHASES, enabled
from .types import canonical, digest

END_UPDATE = "context_execution_ended"


def owns(state, action_id):
    return enabled(state.manifest) and action_id in getattr(state, "context_read_stages", {})


def envelope(state, action, request, phase):
    if not enabled(state.manifest) or phase not in PHASES:
        return request
    request = copy.deepcopy(request)
    request.update(
        action_id=action["id"],
        release_digest=state.release_digest,
        execution_epoch=state.epoch,
        phase=phase,
    )
    identity = digest(request)
    action.update(phase=phase, request_digest=identity, dispatch_request_digest=identity)
    state.context_read_stages[action["id"]] = {
        "action_id": action["id"],
        "phase": phase,
        "request_digest": identity,
        "execution_epoch": state.epoch,
        "status": "awaiting_response_and_end",
        "response_observed": False,
        "execution_end_proof": None,
        "fenced": False,
    }
    return request


def _record(state, action_id):
    if type(action_id) is not str or not owns(state, action_id):
        raise DefinitionMismatch("Context read requires its original Native Action")
    return state.context_read_stages[action_id], next(
        a for a in state.actions if a["id"] == action_id
    )


def admit(state, payload):
    state.authorize(payload.get("scope"))
    record, action = _record(state, payload.get("action_id"))
    expected = {
        "run_id": state.run_id,
        "release_digest": state.release_digest,
        "execution_epoch": record["execution_epoch"],
        "phase": record["phase"],
        "request_digest": record["request_digest"],
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise DefinitionMismatch("Read admission differs from its original complete intent")
    if "dispatch_grant" in action:
        grant = copy.deepcopy(action["dispatch_grant"])
        if record["execution_end_proof"] is not None or record.get("handler_not_started") is True:
            grant["allowed"] = False
        return grant
    allowed = (
        not record["fenced"]
        and state.state not in {"succeeded", "failed", "cancelled"}
        and state.active_action == action["id"]
        and action["status"] == "executing"
    )
    grant = {
        "run_id": state.run_id,
        "action_id": action["id"],
        "release_digest": state.release_digest,
        "allowed": allowed,
    }
    action["dispatch_grant"] = grant
    record["fenced"] = not allowed
    state._emit("context_read_dispatch_admitted", {"action_id": action["id"], "allowed": allowed})
    return copy.deepcopy(grant)


def _finish(state, record, action):
    if record["response_observed"] and (
        record["execution_end_proof"] is not None
        or record["fenced"]
        or record.get("handler_not_started") is True
    ):
        record["status"] = (
            "not_dispatched"
            if record["fenced"] or record.get("handler_not_started") is True
            else "completed"
        )
        if state.active_action == action["id"]:
            state.active_action = None
    else:
        state.active_action = action["id"]


def ended(state, payload):
    if type(payload) is not dict:
        raise DefinitionMismatch("Context read end requires a completed original proof")
    state.authorize(payload.get("scope"))
    record, action = _record(state, payload.get("action_id"))
    expected = {
        "scope": state.scope,
        "action_id": action["id"],
        "release_digest": state.release_digest,
        "request_digest": record["request_digest"],
        "execution_epoch": record["execution_epoch"],
    }
    if (
        type(payload) is not dict
        or payload != expected
        or action.get("dispatch_grant", {}).get("allowed") is not True
        or record["fenced"]
        or record.get("handler_not_started") is True
    ):
        raise DefinitionMismatch("Context read end differs from its original admitted handler")
    if record["execution_end_proof"] is not None:
        return copy.deepcopy(record["end_ack"])
    record["execution_end_proof"] = copy.deepcopy(payload)
    state._emit("context_read_execution_ended", {"action_id": action["id"]})
    record["end_ack"] = {"action_id": action["id"], "recorded": True}
    _finish(state, record, action)
    return copy.deepcopy(record["end_ack"])


def observe(state, action_id, response, receiver):
    """Validate/adopt atomically; observed errors never discharge an active handler."""
    record, action = _record(state, action_id)
    canonical(response)
    identity = digest(response)
    if record["response_observed"]:
        if record["response_digest"] != identity:
            raise IdempotencyConflict("Context read already observed different response evidence")
        return
    terminal = state.state in {"succeeded", "failed", "cancelled"}
    trial = copy.deepcopy(state)
    trial.state = "running"  # Validate late evidence by the same original receiver.
    if (
        state.step_manifest.get("model_history_protocol") in (1, 2)
        and state.manifest.get("binding_protocol")
        in (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)
        and type(response) is dict
        and response.get("ok") is False
        and response.get("code") == "activity_outcome_unknown"
        and record["phase"] in {"context", "plan"}
        and action.get("dispatch_grant", {}).get("allowed") is not True
    ):
        # Fence the original Action before the receiver can recreate a safe read.
        # A late Activity's admission must now be denied by this same History.
        trial.context_read_stages[action_id]["fenced"] = True
    rejected, code = False, None
    try:
        if type(response) is not dict or type(response.get("ok")) is not bool:
            raise ValidationError("Context read requires a completed response")
        if "handler_not_started" in response and type(response["handler_not_started"]) is not bool:
            raise ValidationError("Context start rejection requires a completed boolean")
        if response["ok"] and action.get("dispatch_grant", {}).get("allowed") is not True:
            raise DefinitionMismatch("Context response lacks original read admission")
        if response["ok"] and record["phase"] in {"context", "finalize"}:
            from .temporal_context import validate_context

            validate_context(
                response.get("messages"),
                response.get("context_identity"),
                trial.step["max_context_chars"],
            )
        if response["ok"] and record["phase"] in {"read", "verify"}:
            if type(response.get("found")) is not bool:
                raise ValidationError("Artifact read requires a completed boolean observation")
        receiver(trial, action_id, copy.deepcopy(response))
    except (RalfError, KeyError, TypeError, ValueError) as exc:
        rejected = True
        code = exc.code if isinstance(exc, RalfError) else "validation_error"
    if not rejected and not terminal:
        state.__dict__.update(trial.__dict__)
        record, action = _record(state, action_id)
    else:
        action.update(response=copy.deepcopy(response), status="failed" if rejected else "closed")
        if rejected and not terminal:
            state.state, state.error = "failed", {"code": code}
        state._emit(
            "context_read_response_rejected" if rejected else "late_context_evidence",
            {"action_id": action_id, **({"code": code} if rejected else {})},
        )
    record.update(response_observed=True, response_digest=identity, response_rejected=rejected)
    if not rejected and type(response) is dict and response.get("ok") is False:
        if "handler_not_started" in response:
            record["handler_not_started"] = response["handler_not_started"]
    if action.get("dispatch_grant", {}).get("allowed") is not True:
        record["fenced"] = True
    _finish(state, record, action)
    state._emit("context_read_response_observed", {"action_id": action_id})


def recreate_unadmitted(state, action, response):
    """One new read after original History proves/fences absent dispatch permission."""
    record = getattr(state, "context_read_stages", {}).get(action["id"], {})
    phase = record.get("phase")
    if (
        state.manifest.get("binding_protocol")
        not in (7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)
        or state.step_manifest.get("model_history_protocol") not in (1, 2)
        or state.state in {"succeeded", "failed", "cancelled"}
        or response.get("ok") is not False
        or response.get("code") != "activity_outcome_unknown"
        or phase not in {"context", "plan"}
        or record.get("fenced") is not True
        or action.get("dispatch_grant", {}).get("allowed") is True
    ):
        return False
    retries = getattr(state, "unadmitted_context_retries", {})
    key = f"{state.node}:{state.decisions}:{phase}"
    if retries.get(key, 0) >= 1:
        return False
    retries[key] = 1
    state.unadmitted_context_retries = retries
    action["status"] = "not_dispatched"
    state.active_action = None
    state._emit("context_read_recreated", {"action_id": action["id"], "phase": phase})
    return True
