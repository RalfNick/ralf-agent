"""Pure cap proposals, mandatory host intersection and accepted snapshots."""

import importlib
from contextlib import contextmanager
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, LocalEngine
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.types import digest


def api():
    return importlib.import_module("ralf_agent.agent_limits")


class Host:
    _component_identity = staticmethod(LocalEngine._component_identity)
    _component_result = staticmethod(LocalEngine._component_result)

    def __init__(self, limits=None):
        self.limits = limits


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_decisions", 0),
        ("max_decisions", True),
        ("max_context_chars", 255),
        ("max_context_chars", 1024.0),
        ("max_tool_actions", -1),
        ("max_tool_actions", False),
    ],
)
def test_proposals_require_valid_strict_integers(field, value):
    with pytest.raises(ValidationError):
        api().AgentLimitProposal(**{field: value})
    with pytest.raises(ValidationError):
        api().FixedAgentLimits(**{field: value})


def test_fixed_policy_and_proposal_are_detached_and_immutable():
    c = api()
    policy = c.FixedAgentLimits(max_decisions=2, max_tool_actions=0)
    policy.identity["limits"]["max_decisions"] = 99
    assert policy.propose(AgentSpec("a", "a")).max_decisions == 2
    with pytest.raises((AttributeError, TypeError)):
        policy.max_decisions = 99
    proposal = policy.propose(AgentSpec("a", "a"))
    with pytest.raises((AttributeError, TypeError)):
        proposal.max_decisions = 99


def test_spec_host_selected_caps_intersect_and_disabled_leaves_host():
    c = api()
    step = asdict(AgentSpec("a", "a", max_decisions=3, max_context_chars=4096))
    host = Host(c.FixedAgentLimits(max_decisions=2, max_context_chars=3000, max_tool_actions=2))
    selected = c.FixedAgentLimits(max_decisions=9, max_context_chars=1000, max_tool_actions=1)
    manifest = c.limit_manifest(host, [step], selected)
    assert manifest["steps"][digest(step)] == {
        "max_decisions": 2,
        "max_context_chars": 1000,
        "max_tool_actions": 1,
    }
    effective = c.apply_pinned_limits(step, {"agent_limits": manifest})
    assert effective["max_decisions"] == 2 and effective["max_context_chars"] == 1000
    assert step["max_decisions"] == 3 and c.tool_action_limit(step, {"agent_limits": manifest}) == 1
    disabled = c.limit_manifest(host, [step], None)
    assert disabled["steps"][digest(step)]["max_decisions"] == 2


def test_unconfigured_default_preserves_legacy_and_no_policy_is_called_on_use():
    c = api()
    step = asdict(AgentSpec("a", "a"))
    assert c.limit_manifest(Host(), [step], None) is None
    assert c.apply_pinned_limits(step, {}) == step

    class Policy:
        identity = {"kind": "counted", "version": "1"}
        calls = 0

        def propose(self, spec):
            self.calls += 1
            return c.AgentLimitProposal(max_decisions=1)

    policy = Policy()
    record = c.limit_manifest(Host(policy), [step], policy)
    assert policy.calls == 1
    for _ in range(3):
        assert c.apply_pinned_limits(step, {"agent_limits": record})["max_decisions"] == 1
    assert policy.calls == 1


@pytest.mark.parametrize("kind", ["dict", "lazy", "async"])
def test_policy_returns_or_methods_are_strict(kind):
    c = api()

    class Policy:
        identity = {"kind": "invalid", "version": "1"}

        def propose(self, spec):
            if kind == "dict":
                return {"max_decisions": 1}

            @contextmanager
            def lazy():
                yield c.AgentLimitProposal(max_decisions=1)

            return lazy()

    if kind == "async":

        async def propose(self, spec):
            return c.AgentLimitProposal(max_decisions=1)

        Policy.propose = propose
    with pytest.raises(ValidationError):
        c.limit_manifest(Host(Policy()), [asdict(AgentSpec("a", "a"))], None)


def test_policy_cannot_mutate_shared_schema_or_its_pinned_identity():
    c = api()
    step = asdict(AgentSpec("a", "a", output_schema={"type": "object"}))

    class Policy:
        identity = {"kind": "mutable", "version": "1"}

        def propose(self, spec):
            spec.output_schema["type"] = "integer"
            return c.AgentLimitProposal(max_decisions=1)

    policy = Policy()
    c.limit_manifest(Host(policy), [step], None)
    assert step["output_schema"] == {"type": "object"}

    class Drifting(Policy):
        def propose(self, spec):
            self.identity = {"kind": "mutable", "version": "2"}
            return c.AgentLimitProposal(max_decisions=1)

    with pytest.raises(DefinitionMismatch):
        c.limit_manifest(Host(Drifting()), [step], None)


def test_duplicate_spec_cannot_silently_overwrite_conflicting_caps():
    c = api()

    class Policy:
        identity = {"kind": "oscillating", "version": "1"}
        n = 0

        def propose(self, spec):
            self.n += 1
            return c.AgentLimitProposal(max_decisions=self.n)

    step = asdict(AgentSpec("same", "same"))
    with pytest.raises(ValidationError):
        c.limit_manifest(Host(Policy()), [step, step], None)


def test_limits_for_other_effective_step_are_not_reused():
    c = api()
    original = asdict(AgentSpec("a", "a"))
    manifest = c.limit_manifest(Host(c.FixedAgentLimits(max_decisions=1)), [original], None)
    with pytest.raises(DefinitionMismatch):
        c.apply_pinned_limits({**original, "instructions": "changed"}, {"agent_limits": manifest})
