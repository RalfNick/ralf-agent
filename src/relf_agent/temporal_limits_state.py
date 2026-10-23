"""Pure per-node limits adoption by the original Run History authority."""

from dataclasses import asdict

from .agent_limits import AgentLimitProposal
from .errors import DefinitionMismatch, ValidationError
from .types import canonical, digest

ACTIVITY = "ralf.temporal.limits.v1"
FIELDS = tuple(asdict(AgentLimitProposal()))


def validate_protocol(manifest):
    records = manifest.get("binding_catalog", {}).get("records", {}).values()
    enabled = "host_limits" in manifest or any(r.get("role") == "limits" for r in records)
    if enabled or "limits_protocol" in manifest:
        if (
            type(manifest.get("limits_protocol")) is not int
            or manifest["limits_protocol"] != 1
            or manifest.get("dispatch_admission") != "history-1"
        ):
            raise DefinitionMismatch("Unsupported Temporal Agent limits protocol")
        registrations = ([manifest["host_limits"]] if "host_limits" in manifest else []) + [
            r.get("configuration", {}).get("agent_limits")
            for r in records
            if r.get("role") == "limits"
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
                raise ValidationError("Invalid Temporal limits registration")


def policy_registrations(manifest, descriptor):
    from .binding_types import AgentBindingDescriptor
    from .temporal_bindings import key, validate_descriptor

    choices = validate_descriptor(manifest, descriptor or AgentBindingDescriptor().to_dict())
    result = {}
    if manifest.get("host_limits") is not None:
        result["host"] = manifest["host_limits"]
    if choices.limits.mode == "ref":
        result["agent"] = manifest["binding_catalog"]["records"][key("limits", choices.limits)][
            "configuration"
        ]["agent_limits"]
    return result


def effective_step(state, step):
    from .temporal_state import detached

    caps = state.limits_stages.get(str(state.node), {}).get("caps")
    return (
        step
        if caps is None
        else {**detached(step), **{k: caps[k] for k in ("max_decisions", "max_context_chars")}}
    )


def next_stage(state):
    from .temporal_state import detached

    if state.manifest.get("limits_protocol") != 1 or str(state.node) in state.limits_stages:
        return None
    registrations = policy_registrations(state.manifest, state.step_bindings)
    if not registrations:
        return None
    action = {
        "id": f"{state.run_id}:limits:{state.node}",
        "kind": "agent_limits",
        "node": state.node,
        "status": "executing",
        "attempts": [],
    }
    request = {
        "version": 1,
        "runtime_manifest": detached(state.manifest),
        "scope": state.scope,
        "run_id": state.run_id,
        "action_id": action["id"],
        "node": state.node,
        "release_digest": state.release_digest,
        "step_bindings": state.step_bindings,
        "step": detached(state.request["definition"]["steps"][state.node]),
        "policies": detached(registrations),
    }
    state.limits_stages[str(state.node)] = {"action_id": action["id"], "request": detached(request)}
    state.actions.append(action)
    state.active_action, state.state = action["id"], "running"
    state._emit(
        "agent_limits_intent_recorded",
        {"action_id": action["id"], "request_digest": digest(request)},
    )
    return action, request


def accept_stage(state, action_id, response):
    from .temporal_state import TERMINAL, detached

    action = next(a for a in state.actions if a["id"] == action_id and a["kind"] == "agent_limits")
    record = state.limits_stages[str(action["node"])]
    if action["status"] != "executing" or state.active_action != action_id:
        raise ValidationError("Limits response is not the active original operation")
    state.active_action = None
    try:
        canonical(response)
        if type(response) is not dict or type(response.get("ok")) is not bool:
            raise ValidationError("Invalid completed limits response")
        record["response"] = detached(response)
        if not response["ok"]:
            raise ValidationError("Agent limits proposal failed")
        request = record["request"]
        if (
            set(response) != {"ok", "request_digest", "proposals"}
            or response["request_digest"] != digest(request)
            or type(response["proposals"]) is not dict
            or set(response["proposals"]) != set(request["policies"])
        ):
            raise ValidationError("Limits response differs from original intent")
        proposals = []
        for proposal in response["proposals"].values():
            if type(proposal) is not dict or set(proposal) != set(FIELDS):
                raise ValidationError("Invalid limits proposal fields")
            proposals.append(asdict(AgentLimitProposal(**proposal)))
        caps = {}
        for name in FIELDS:
            values = [p[name] for p in proposals if p[name] is not None]
            if name in request["step"]:
                values.append(request["step"][name])
            caps[name] = min(values) if values else None
        action["status"] = "completed"
        if state.state in TERMINAL:
            state._emit("late_agent_limits_evidence", {"action_id": action_id})
            return
        record["caps"] = caps
        state._emit("agent_limits_adopted", {"action_id": action_id, "caps": caps})
    except (ValidationError, TypeError, ValueError) as exc:
        action["status"] = "failed"
        if state.state not in TERMINAL:
            code = response.get("code") if isinstance(response, dict) else None
            if not isinstance(code, str) or not code.strip():
                code = "validation_error"
            state.state, state.error = "failed", {"code": code}
        state._emit(
            "agent_limits_failed",
            {"action_id": action_id, "code": getattr(exc, "code", "validation_error")},
        )


def tool_batch_allowed(state, proposals):
    caps = state.limits_stages.get(str(state.node), {}).get("caps", {})
    cap = caps.get("max_tool_actions")
    used = sum(a["kind"] == "tool" and a["node"] == state.node for a in state.actions)
    return cap is None or used + len(proposals) <= cap
