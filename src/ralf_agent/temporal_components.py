"""Explicit worker registries; default native releases retain their v1 identity."""

from dataclasses import asdict

from .dag_planning import ModelDAGPlanner, RuleDAGPlanner
from .errors import ValidationError
from .planning import CompleteVerifier, ModelPlanner, RulePlanner
from .teams import RouterTeam, SequentialTeam, SupervisorTeam
from .tools import _callable_identity
from .types import AgentSpec, digest


def default_components():
    return (
        {"sequential": SequentialTeam(), "router": RouterTeam(), "supervisor": SupervisorTeam()},
        {
            "rule": RulePlanner(),
            "model": ModelPlanner(),
            "dag-rule": RuleDAGPlanner(),
            "dag-model": ModelDAGPlanner(),
        },
        {"complete": CompleteVerifier()},
    )


def orchestration_identity(teams, planners, verifiers):
    from .temporal_activities import component_identity

    result = {"version": "1", "teams": {}, "planners": {}, "verifiers": {}}
    for kind, registry, methods, pure in [
        ("teams", teams, ("select",), True),
        ("planners", planners, ("plan",), False),
        ("verifiers", verifiers, ("verify",), True),
    ]:
        if not isinstance(registry, dict) or not registry:
            raise ValidationError("Orchestration registries must be named nonempty objects")
        for name, component in registry.items():
            if not isinstance(name, str) or not name.strip():
                raise ValidationError("Invalid component registration name")
            result[kind][name] = {
                "identity": component_identity(component, methods, synchronous=pure),
                "implementation_digest": digest(
                    [_callable_identity(getattr(component, method)) for method in methods]
                ),
            }
            if kind == "planners":
                agent = getattr(component, "agent", None)
                if agent is not None and (not isinstance(agent, AgentSpec) or agent.tools):
                    raise ValidationError("Managed planner must declare a tool-free AgentSpec")
                result[kind][name]["agent"] = None if agent is None else asdict(agent)
    return result
