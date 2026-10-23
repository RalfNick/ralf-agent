"""Pinned pure request/decision policies; Run History alone adopts proposals."""

from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, ValidationError
from .task_controls import _binding
from .types import canonical, digest


def default_policy(policy):
    from .harness import NativeHarness

    return (
        type(policy) is NativeHarness
        and policy.identity == NativeHarness.identity
        and getattr(policy.prepare, "__func__", None) is NativeHarness.prepare
        and getattr(policy.propose, "__func__", None) is NativeHarness.propose
    )


def registration(policy):
    from .temporal_activities import component_identity

    return {
        "identity": component_identity(policy, ("prepare", "propose"), synchronous=True),
        "prepare_digest": executable_digest(policy.prepare),
        "propose_digest": executable_digest(policy.propose),
    }


def pin(policy):
    return policy, (_binding(policy.prepare), _binding(policy.propose)), registration(policy)


def check_pin(original):
    policy, methods, identity = original
    if (_binding(policy.prepare), _binding(policy.propose)) != methods or registration(
        policy
    ) != identity:
        raise DefinitionMismatch("Temporal DecisionPolicy registration changed")


def validate_prepared_tools(tools, authorized):
    if type(tools) is not list:
        raise ValidationError("Prepared tools must be completed JSON descriptions")
    values = [canonical(t) for t in tools]
    if len(set(values)) != len(values) or not set(values) <= {canonical(t) for t in authorized}:
        raise ValidationError("Prepared tools exceed original descriptions and grants")


def evidence(runtime, request, prepared, received, proposal):
    from .temporal_state import detached

    return {
        "registration": detached(runtime.manifest["decision_registration"]),
        "request_digest": digest(request),
        "prepared_request": detached(prepared),
        "received_response_digest": digest(received),
        "proposal_digest": digest(proposal),
    }
