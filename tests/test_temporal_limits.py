import asyncio
import copy
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentLimitProposal,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    FixedAgentLimits,
    ModelResponse,
    Scope,
    ToolRegistry,
)
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request


class Provider:
    identity = {"kind": "limits-test", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output="answer")


class ByNameLimits:
    identity = {"kind": "by-name-limits", "version": "1"}

    def __init__(self):
        self.calls = []

    def propose(self, spec):
        self.calls.append(spec.name)
        return AgentLimitProposal(2 if spec.name == "limited" else 3, 1000, 1)


def setup(selection="ref", policy=None):
    agent_policy = policy or ByNameLimits()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("limits", "selected", "1", agent_policy)
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        limits=FixedAgentLimits(max_decisions=4, max_context_chars=2000, max_tool_actions=2),
        binding_catalog=catalog,
    )
    choice = (
        BindingSelection.ref("selected", "1") if selection == "ref" else BindingSelection.disabled()
    )
    definition = AgentDefinition(
        AgentSpec("limited", "answer", max_decisions=3, max_context_chars=4096),
        AgentBindingDescriptor(limits=choice),
    )
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "submit",
        normalize_request(submission_request(definition, "task")),
        runtime.manifest,
    )
    return runtime, state, agent_policy


def test_history_adopts_custom_intersection_once_and_restore_keeps_caps():
    async def run():
        runtime, state, policy = setup()
        action, request = state.next_operation()
        assert action["kind"] == "agent_limits"
        state.accept_limits(action["id"], await runtime.propose_limits(request))
        restored = copy.deepcopy(state)
        assert restored.step["max_decisions"] == 2
        assert restored.step["max_context_chars"] == 1000
        assert restored.limits_stages["0"]["caps"]["max_tool_actions"] == 1
        assert restored.next_operation()[0]["kind"] == "model"
        assert policy.calls == ["limited"]

    asyncio.run(run())


def test_disabled_agent_policy_retains_host_and_spec_caps():
    async def run():
        runtime, state, policy = setup("disabled")
        action, request = state.next_operation()
        state.accept_limits(action["id"], await runtime.propose_limits(request))
        assert state.step["max_decisions"] == 3
        assert state.step["max_context_chars"] == 2000
        assert state.limits_stages["0"]["caps"]["max_tool_actions"] == 2
        assert not policy.calls

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["identity", "method", "instance"])
def test_registration_drift_cannot_adopt_limits(mutation):
    async def run():
        runtime, state, policy = setup()
        action, request = state.next_operation()
        if mutation == "identity":
            policy.identity = {"kind": "changed"}
        elif mutation == "method":
            policy.propose = lambda spec: AgentLimitProposal()
        else:
            runtime.limits = FixedAgentLimits()
        response = await runtime.propose_limits(request)
        assert not response["ok"]
        state.accept_limits(action["id"], response)
        assert state.state == "failed"
        assert state.next_operation() is None

    asyncio.run(run())


@pytest.mark.parametrize("field", ["request_digest", "proposals"])
def test_history_rejects_forged_limits_response(field):
    async def run():
        runtime, state, _ = setup()
        action, request = state.next_operation()
        response = await runtime.propose_limits(request)
        if field == "request_digest":
            response[field] = "wrong"
        else:
            response[field]["agent"]["max_decisions"] = True
        state.accept_limits(action["id"], response)
        assert state.state == "failed"
        assert "caps" not in state.limits_stages["0"]

    asyncio.run(run())


def test_cancelled_limits_adoption_never_starts_model():
    async def run():
        runtime, state, _ = setup()
        action, request = state.next_operation()
        state.command("cancel", {"scope": state.scope, "kind": "cancel"})
        state.accept_limits(action["id"], await runtime.propose_limits(request))
        assert state.state == "cancelled"
        assert state.next_operation() is None
        assert state.quiescent

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["dict", "coroutine", "generator", "contextmanager"])
def test_lazy_or_untyped_policy_result_fails_closed(kind):
    from contextlib import contextmanager

    class Invalid(ByNameLimits):
        def propose(self, spec):
            async def coroutine():
                return AgentLimitProposal()

            @contextmanager
            def context():
                yield AgentLimitProposal()

            return {
                "dict": lambda: {"max_decisions": 1},
                "coroutine": coroutine,
                "generator": lambda: (v for v in [AgentLimitProposal()]),
                "contextmanager": context,
            }[kind]()

    async def run():
        runtime, state, _ = setup(policy=Invalid())
        action, request = state.next_operation()
        state.accept_limits(action["id"], await runtime.propose_limits(request))
        assert state.state == "failed"
        assert not [a for a in state.actions if a["kind"] == "model"]

    asyncio.run(run())


@pytest.mark.parametrize("change", ["boolean_protocol", "missing_registration"])
def test_invalid_release_is_refused_before_workflow_start(change):
    from ralf_agent.errors import RalfError
    from ralf_agent.temporal_state import validate_manifest

    runtime, _, _ = setup()
    manifest = runtime.manifest
    if change == "boolean_protocol":
        manifest["limits_protocol"] = True
    else:
        for record in manifest["binding_catalog"]["records"].values():
            if record["role"] == "limits":
                record["configuration"].pop("agent_limits")
    with pytest.raises(RalfError):
        validate_manifest(manifest)


def test_complete_tool_batch_is_rejected_before_creating_any_action():
    from ralf_agent import ToolCall, ToolSpec
    from tests.test_temporal_memory_bindings import grant

    async def handler(arguments, context):
        pytest.fail("over-limit batch must not execute")

    class Batch(Provider):
        async def complete(self, messages, tools):
            return ModelResponse(tool_calls=[ToolCall("lookup", {}, str(i)) for i in range(2)])

    async def run():
        tools = ToolRegistry()
        tools.register(ToolSpec("lookup", "read", {"type": "object"}), handler)
        runtime = TemporalRuntime(
            providers={"default": Batch()}, tools=tools, limits=FixedAgentLimits(max_tool_actions=1)
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "submit",
            submission_request(AgentSpec("a", "answer", ("lookup",)), "task"),
            runtime.manifest,
        )
        action, request = state.next_operation()
        state.accept_limits(action["id"], await runtime.propose_limits(request))
        action, request = state.next_operation()
        state.accept_model(
            action["id"],
            await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
        )
        assert state.state == "failed"
        assert not [a for a in state.actions if a["kind"] == "tool"]
        assert state.error["code"] == "agent_limit_exceeded"
        assert state.budget["spent"] == 1
        assert state.next_operation() is None

    asyncio.run(run())


def test_foreign_catalog_scope_and_selectors_are_rejected():
    from ralf_agent.errors import AuthorizationDenied, ValidationError

    runtime, state, _ = setup()
    with pytest.raises(AuthorizationDenied):
        TemporalRunState(
            "foreign",
            asdict(Scope("other", "principal")),
            "submit",
            state.request,
            runtime.manifest,
        )
    request = copy.deepcopy(state.request)
    request["agent_bindings"]["agent"]["limits"]["selector"] = {"namespace": "private"}
    with pytest.raises(ValidationError):
        TemporalRunState("selector", state.scope, "submit", request, runtime.manifest)


def test_identical_sequence_steps_keep_distinct_policy_caps_after_restore():
    from ralf_agent import BoundDefinition, WorkflowSpec
    from tests.test_temporal_memory_bindings import grant

    async def run():
        runtime, _, policy = setup()
        runtime.binding_catalog.register(
            "limits",
            "other",
            "1",
            FixedAgentLimits(max_decisions=1, max_context_chars=1500, max_tool_actions=0),
        )
        # Register the complete deployment before accepting any Run.
        runtime = TemporalRuntime(
            providers=runtime.providers,
            tools=runtime.tools,
            limits=runtime.limits,
            binding_catalog=runtime.binding_catalog,
        )
        spec = AgentSpec("limited", "answer", max_decisions=3, max_context_chars=4096)
        definition = BoundDefinition(
            WorkflowSpec("same", [spec, spec]),
            {
                "sequence/steps/0": AgentBindingDescriptor(
                    limits=BindingSelection.ref("selected", "1")
                ),
                "sequence/steps/1": AgentBindingDescriptor(
                    limits=BindingSelection.ref("other", "1")
                ),
            },
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "submit",
            normalize_request(submission_request(definition, "task")),
            runtime.manifest,
        )
        for _ in range(8):
            operation = state.next_operation()
            if operation is None:
                break
            action, request = operation
            if action["kind"] == "agent_limits":
                state.accept_limits(action["id"], await runtime.propose_limits(request))
                state = copy.deepcopy(state)
            else:
                state.accept_model(
                    action["id"],
                    await runtime.complete_model(
                        request, dispatch_guard=lambda r, state=state: grant(state, r)
                    ),
                )
        assert state.state == "succeeded"
        assert state.limits_stages["0"]["caps"] == {
            "max_decisions": 2,
            "max_context_chars": 1000,
            "max_tool_actions": 1,
        }
        assert state.limits_stages["1"]["caps"] == {
            "max_decisions": 1,
            "max_context_chars": 1500,
            "max_tool_actions": 0,
        }
        assert policy.calls == ["limited"]

    asyncio.run(run())


@pytest.mark.parametrize("disabled", [False, True])
def test_host_only_limits_accepts_explicit_bindings_without_catalog(disabled):
    async def run():
        runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            limits=FixedAgentLimits(max_decisions=1),
        )
        definition = AgentDefinition(
            AgentSpec("a", "answer"),
            AgentBindingDescriptor(
                limits=BindingSelection.disabled() if disabled else BindingSelection.inherit()
            ),
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "submit",
            normalize_request(submission_request(definition, "task")),
            runtime.manifest,
        )
        action, request = state.next_operation()
        state.accept_limits(action["id"], await runtime.propose_limits(request))
        assert state.step["max_decisions"] == 1
        assert set(state.limits_stages["0"]["response"]["proposals"]) == {"host"}

    asyncio.run(run())


@pytest.mark.parametrize("code", [None, True, {}, "", " "])
def test_invalid_failure_code_keeps_stable_public_error(code):
    runtime, state, _ = setup()
    action, _ = state.next_operation()
    state.accept_limits(action["id"], {"ok": False, "code": code})
    assert state.state == "failed"
    assert state.error["code"] == "validation_error"
    assert state.quiescent


@pytest.mark.parametrize("field", ["max_decisions", "max_context_chars", "max_tool_actions"])
def test_fixed_cap_is_enforced_after_restore(field):
    from ralf_agent import ToolCall, ToolSpec
    from tests.test_temporal_memory_bindings import grant

    calls = []

    class Repeat(Provider):
        async def complete(self, messages, tools):
            calls.append(copy.deepcopy(messages))
            return ModelResponse(tool_calls=[ToolCall("lookup", {}, str(len(calls)))])

    async def handler(arguments, context):
        return "evidence"

    async def run():
        tools = ToolRegistry()
        tools.register(ToolSpec("lookup", "read", {"type": "object"}), handler)
        cap = {field: 256 if field == "max_context_chars" else 1}
        runtime = TemporalRuntime(
            providers={"default": Repeat()}, tools=tools, limits=FixedAgentLimits(**cap)
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "submit",
            submission_request(AgentSpec("a", "answer", ("lookup",)), "x" * 900),
            runtime.manifest,
        )
        action, request = state.next_operation()
        state.accept_limits(action["id"], await runtime.propose_limits(request))
        state = copy.deepcopy(state)
        for _ in range(10):
            operation = state.next_operation()
            if operation is None:
                break
            action, request = operation
            if action["kind"] == "model":
                state.accept_model(
                    action["id"],
                    await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
                )
            else:
                state.accept_tool(action["id"], await runtime.execute_tool(request))
        assert state.state == "failed", state.snapshot()
        if field == "max_decisions":
            assert state.error["code"] == "decision_limit"
            assert len(calls) == 1
        elif field == "max_context_chars":
            assert all(len(str(m)) <= 256 for m in calls)
        else:
            assert len([a for a in state.actions if a["kind"] == "tool"]) == 1

    asyncio.run(run())
