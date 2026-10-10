"""Worker-owned pure policy proposals; no business I/O or execution authority."""

from dataclasses import asdict

from .agent_limits import AgentLimitProposal
from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, ValidationError
from .task_controls import _binding
from .types import AgentSpec, Scope, digest


def registration(policy):
    if policy is None:
        return None
    from .temporal_activities import component_identity

    return {
        "identity": component_identity(policy, ("propose",), synchronous=True),
        "implementation_digest": executable_digest(policy.propose),
    }


def pin(policy):
    return policy, _binding(policy.propose), registration(policy)


def check_pin(original):
    policy, method, identity = original
    if _binding(policy.propose) != method or registration(policy) != identity:
        raise DefinitionMismatch("Temporal Agent limits registration changed")


async def evaluate(runtime, request):
    from .binding_types import AgentBindingDescriptor
    from .temporal_activities import _close_lazy, _code
    from .temporal_limits_state import policy_registrations
    from .temporal_state import detached

    try:
        runtime.validate_release(request["runtime_manifest"])
        if request.get("version") != 1 or runtime.manifest.get("limits_protocol") != 1:
            raise DefinitionMismatch("Limits require their original protocol")
        registrations = policy_registrations(runtime.manifest, request["step_bindings"])
        if registrations != request["policies"] or not registrations:
            raise DefinitionMismatch("Limits intent differs from original registrations")
        policies = {}
        if runtime.limits is not None:
            policies["host"] = runtime.limits
        choice = AgentBindingDescriptor.from_dict(request["step_bindings"]).limits
        if choice.mode == "ref":
            policies["agent"], _ = runtime.binding_catalog.resolve(
                "limits", choice, Scope(**request["scope"])
            )
        proposals = {}
        for role, policy in policies.items():
            if registration(policy) != registrations[role]:
                raise DefinitionMismatch("Limits policy differs from accepted release")
            value = policy.propose(AgentSpec(**detached(request["step"])))
            if type(value) is not AgentLimitProposal:
                _close_lazy(value)
                raise ValidationError(
                    "AgentLimitsPolicy.propose must return completed AgentLimitProposal"
                )
            proposals[role] = asdict(AgentLimitProposal(**asdict(value)))
            runtime.validate_release(request["runtime_manifest"])
        return {"ok": True, "request_digest": digest(request), "proposals": proposals}
    except Exception as exc:
        return {"ok": False, "code": _code(exc, "limits_failed"), "dispatched": False}
