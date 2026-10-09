"""Pure proposals, mandatory host intersection and immutable accepted Agent caps."""

import copy
from dataclasses import asdict, dataclass
from typing import Protocol

from .errors import DefinitionMismatch, RalfError, ValidationError
from .orchestration_types import _JsonValue
from .types import AgentSpec, canonical, digest


@dataclass(frozen=True)
class AgentLimitProposal:
    max_decisions: int | None = None
    max_context_chars: int | None = None
    max_tool_actions: int | None = None

    def __post_init__(self):
        for name, minimum in (
            ("max_decisions", 1),
            ("max_context_chars", 256),
            ("max_tool_actions", 0),
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < minimum):
                raise ValidationError(f"{name} must be an integer of at least {minimum}, or None")


class AgentLimitsPolicy(Protocol):
    identity: dict

    def propose(self, spec: AgentSpec) -> AgentLimitProposal: ...


class FixedAgentLimits(_JsonValue):
    def __init__(self, *, max_decisions=None, max_context_chars=None, max_tool_actions=None):
        self._data_json = canonical(
            asdict(AgentLimitProposal(max_decisions, max_context_chars, max_tool_actions))
        )

    @property
    def identity(self):
        return {"kind": "fixed-agent-limits", "version": "1", "limits": self.to_dict()}

    def propose(self, spec):
        return AgentLimitProposal(**self.to_dict())


def limit_manifest(engine, steps, selected=None):
    host = engine.limits
    agent = None if selected is host else selected
    if host is None and agent is None:
        return None
    policies = [
        (name, policy) for name, policy in (("host", host), ("agent", agent)) if policy is not None
    ]
    identities = {
        name: engine._component_identity(policy, ("propose",), True, "Agent limits")
        for name, policy in policies
    }
    resolved = {}
    for step in steps:
        proposals = []
        for name, policy in policies:
            try:
                value = engine._component_result(
                    policy.propose(AgentSpec(**copy.deepcopy(step))),
                    AgentLimitProposal,
                    "AgentLimitsPolicy.propose",
                )
                if type(value) is not AgentLimitProposal:
                    raise ValidationError("Agent limits require a concrete proposal")
                proposals.append(AgentLimitProposal(**asdict(value)))
            except RalfError:
                raise
            except Exception as exc:
                raise ValidationError("Agent limits policy failed to produce a proposal") from exc
            if digest(
                engine._component_identity(policy, ("propose",), True, "Agent limits")
            ) != digest(identities[name]):
                raise DefinitionMismatch("The executing Agent limits policy changed")
        caps = {}
        for field in ("max_decisions", "max_context_chars", "max_tool_actions"):
            candidates = [getattr(p, field) for p in proposals if getattr(p, field) is not None]
            if field in step:
                candidates.append(step[field])
            caps[field] = min(candidates) if candidates else None
        key = digest(step)
        if key in resolved and resolved[key] != caps:
            raise ValidationError("Equal Agent definitions received inconsistent limits")
        resolved[key] = caps
    return {
        "schema_version": 1,
        "host": identities.get("host"),
        "agent": identities.get("agent"),
        "steps": resolved,
    }


def _lookup(step, manifest):
    record = manifest.get("agent_limits")
    if record is None:
        return None
    try:
        caps = copy.deepcopy(record["steps"][digest(step)])
    except (KeyError, TypeError) as exc:
        raise DefinitionMismatch("The Agent step has no accepted limits snapshot") from exc
    if not isinstance(caps, dict) or set(caps) != set(AgentLimitProposal.__dataclass_fields__):
        raise ValidationError("Invalid accepted Agent limits snapshot")
    AgentLimitProposal(**caps)
    if any(
        caps[field] is None or caps[field] > step[field]
        for field in ("max_decisions", "max_context_chars")
    ):
        raise ValidationError("Accepted caps cannot relax the Agent definition")
    return caps


def apply_pinned_limits(step, manifest):
    caps = _lookup(step, manifest)
    return (
        copy.deepcopy(step)
        if caps is None
        else {
            **copy.deepcopy(step),
            **{name: caps[name] for name in ("max_decisions", "max_context_chars")},
        }
    )


def tool_action_limit(step, manifest):
    caps = _lookup(step, manifest)
    return None if caps is None else caps["max_tool_actions"]


def pin_projection_limits(target, source):
    """A virtual node frame projects accepted facts; it never accepts new caps."""
    accepted, proposed = source.get("agent_limits"), target.get("agent_limits")
    if accepted is None and proposed is None:
        return
    if accepted is None or proposed is None:
        raise DefinitionMismatch("The node projection changed its limits capability")
    try:
        projected = {key: copy.deepcopy(accepted["steps"][key]) for key in proposed["steps"]}
    except (KeyError, TypeError) as exc:
        raise DefinitionMismatch("The node projection has no original accepted limits") from exc
    target["agent_limits"] = {**copy.deepcopy(accepted), "steps": projected}


def has_agent_limits(manifest):
    if "agent_limits" in manifest:
        return True
    return any(
        has_agent_limits(entry["manifest"])
        for entry in manifest.get("agent_bindings", {}).get("steps", {}).values()
    ) or any(
        has_agent_limits(member)
        for member in manifest.get("orchestration", {}).get("members", {}).values()
    )


def validate_inherited_limits(target, source):
    """A managed child may accept only caps fixed by its declared parent member."""
    expected = copy.deepcopy(target)
    pin_projection_limits(expected, source)
    if expected.get("agent_limits") != target.get("agent_limits"):
        raise DefinitionMismatch("Child limits differ from its parent's accepted member caps")
    for path, entry in target.get("agent_bindings", {}).get("steps", {}).items():
        try:
            original = source["agent_bindings"]["steps"][path]["manifest"]
        except (KeyError, TypeError) as exc:
            raise DefinitionMismatch("Child limits have no original bound member") from exc
        validate_inherited_limits(entry["manifest"], original)
    for name, member in target.get("orchestration", {}).get("members", {}).items():
        try:
            original = source["orchestration"]["members"][name]
        except (KeyError, TypeError) as exc:
            raise DefinitionMismatch("Child limits have no original nested member") from exc
        validate_inherited_limits(member, original)
