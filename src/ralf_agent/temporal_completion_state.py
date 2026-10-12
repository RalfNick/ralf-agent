"""Original History acceptance of pure completion verdicts; no secondary authority."""

from .completion import CompletionRequest, CompletionVerdict
from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest

ACTIVITY = "ralf.temporal.completion.v1"


def validate_protocol(manifest):
    records = manifest.get("binding_catalog", {}).get("records", {}).values()
    enabled = "completion_verifier" in manifest or any(r.get("role") == "verifier" for r in records)
    if not enabled and "completion_protocol" not in manifest:
        return
    if (
        type(manifest.get("completion_protocol")) is not int
        or manifest["completion_protocol"] != 1
        or manifest.get("kernel") != "temporal-3"
    ):
        raise DefinitionMismatch("Unsupported Temporal completion protocol")
    registrations = (
        [manifest["completion_verifier"]] if "completion_verifier" in manifest else []
    ) + [
        r.get("configuration", {}).get("completion_verifier")
        for r in records
        if r.get("role") == "verifier"
    ]
    for value in registrations:
        if (
            type(value) is not dict
            or set(value) != {"identity", "implementation_digest"}
            or type(value["identity"]) is not dict
            or not value["identity"]
            or type(value["implementation_digest"]) is not str
            or len(value["implementation_digest"]) != 64
            or any(c not in "0123456789abcdef" for c in value["implementation_digest"])
        ):
            raise ValidationError("Invalid completion verifier registration")


def prepare(state, action, result):
    from .temporal_state import detached

    registration = state.step_manifest.get("completion_verifier")
    if registration is None:
        return False
    completion = CompletionRequest(
        state.completion_task,
        result,
        [
            {
                k: detached(a[k])
                for k in ("id", "tool", "arguments", "result", "receipt", "effect_key")
            }
            for a in state.actions
            if a["kind"] == "tool" and a["node"] == state.node and a["status"] == "completed"
        ],
    ).to_dict()
    source = {
        "model_action_id": action["id"],
        "node": state.node,
        "response_digest": digest(action["response"]),
        "completion": completion,
    }
    stage = {
        "source": source,
        "registration": detached(registration),
        "step_bindings": state.step_bindings,
        "status": "prepared",
    }
    state.completion_stages[action["id"]] = stage
    state.pending_verification = action["id"]
    state._emit(
        "completion_source_recorded",
        {"model_action_id": action["id"], "source_digest": digest(source)},
    )
    return True


def close_pending(state):
    key = state.pending_verification
    if key is not None and state.completion_stages[key]["status"] == "prepared":
        state.completion_stages[key]["status"] = "closed"
        state.pending_verification = None


def next_stage(state):
    from .temporal_state import detached

    key = state.pending_verification
    if key is None:
        return None
    stage = state.completion_stages[key]
    if stage["status"] != "prepared":
        raise DefinitionMismatch("Completion intent was already dispatched")
    action = {
        "id": key + ":completion",
        "kind": "agent_completion",
        "node": state.node,
        "status": "executing",
        "attempts": [],
    }
    request = {
        "version": 1,
        "runtime_manifest": detached(state.manifest),
        "scope": detached(state.scope),
        "run_id": state.run_id,
        "release_digest": state.release_digest,
        "action_id": action["id"],
        "source": detached(stage["source"]),
        "completion": detached(stage["source"]["completion"]),
        "registration": detached(stage["registration"]),
        "step_bindings": detached(stage["step_bindings"]),
    }
    stage.update(status="executing", action_id=action["id"], request=detached(request))
    action["request_digest"] = digest(request)
    state.actions.append(action)
    state.active_action = action["id"]
    state._emit(
        "completion_intent_recorded", {"action_id": action["id"], "request_digest": digest(request)}
    )
    return action, request


def accept_stage(state, action_id, response):
    from .temporal_state import TERMINAL, detached

    action = next(
        a for a in state.actions if a["id"] == action_id and a["kind"] == "agent_completion"
    )
    key = state.pending_verification
    if (
        key is None
        or state.completion_stages[key].get("action_id") != action_id
        or state.active_action != action_id
    ):
        raise ValidationError("Completion is not the original active intent")
    stage = state.completion_stages[key]
    state.active_action, state.pending_verification = None, None
    try:
        canonical(response)
        if type(response) is not dict or type(response.get("ok")) is not bool:
            raise ValidationError("Invalid completed verifier response")
        stage["response"] = detached(response)
        if not response["ok"]:
            raise ValidationError("Completion verifier failed")
        if (
            set(response) != {"ok", "request_digest", "verdict"}
            or response["request_digest"] != digest(stage["request"])
            or type(response["verdict"]) is not dict
            or set(response["verdict"]) != {"status", "feedback"}
        ):
            raise ValidationError("Completion response differs from original intent")
        verdict = CompletionVerdict(**response["verdict"]).to_dict()
        stage.update(status="completed", verdict=verdict)
        action.update(status="completed", response=detached(response))
        if state.state in TERMINAL:
            state._emit("late_completion_evidence", {"action_id": action_id})
            return
        source = stage["source"]
        model = next(a for a in state.actions if a["id"] == source["model_action_id"])
        if model["node"] != state.node or digest(model["response"]) != source["response_digest"]:
            raise DefinitionMismatch("Completion source changed before adoption")
        model["completion_verification"] = {
            "schema_version": 1,
            "request": detached(source["completion"]),
            "request_digest": digest(source["completion"]),
            "verdict": detached(verdict),
        }
        state._emit(
            "completion_verified",
            {
                "action_id": action_id,
                "status": verdict["status"],
                "request_digest": digest(source["completion"]),
            },
        )
        if verdict["status"] == "reject":
            state.state, state.error = "failed", {"code": "completion_rejected"}
            state._emit("run_failed", state.error)
        elif verdict["status"] == "retry":
            result = source["completion"]["output"]
            if state.step_manifest.get("model_history_protocol") in (1, 2):
                message = {
                    "role": "user",
                    "content": "Completion verification: " + verdict["feedback"],
                }
                if state.step_manifest.get("model_history_protocol") == 2:
                    action["native_history_message"] = {
                        "order": len(state.messages),
                        "message": detached(message),
                    }
                state.messages.append(message)
                return
            state.messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": result if isinstance(result, str) else canonical(result),
                    },
                    {"role": "user", "content": "Completion verification: " + verdict["feedback"]},
                ]
            )
        else:
            state.finish_output(model, source["completion"]["output"])
    except (ValidationError, DefinitionMismatch, TypeError, ValueError) as exc:
        action["status"], stage["status"] = "failed", "failed"
        code = response.get("code") if type(response) is dict else None
        if not isinstance(code, str) or not code.strip():
            code = getattr(exc, "code", "validation_error")
        if state.state not in TERMINAL:
            state.state, state.error = "failed", {"code": code}
        state._emit("completion_failed", {"action_id": action_id, "code": code})
