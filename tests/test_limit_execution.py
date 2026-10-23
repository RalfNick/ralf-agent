"""Limits enforced by the existing Local acceptance/Action authority."""

import asyncio

import pytest

from relf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.agent_limits import AgentLimitProposal, FixedAgentLimits
from relf_agent.completion import ToolReceiptVerifier
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.harness import ModelRequest, NativeHarness
from relf_agent.types import ToolCall

from .helpers import ScriptedProvider


def engine(path, provider, limits=None, **kwargs):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": provider},
        tools=kwargs.pop("tools", ToolRegistry()),
        limits=limits,
        **kwargs,
    )


def registry(writes, *, fail=False):
    tools = ToolRegistry()

    def write(args, ctx):
        writes.append(args)
        if fail:
            raise RuntimeError("effect happened before losing response")
        return {"applied": True}

    tools.register(
        ToolSpec(
            "change",
            "Change",
            {"type": "object", "required": ["value"]},
            effect="idempotent_write",
            requires_approval=True,
        ),
        write,
    )
    return tools


def test_completion_retry_obeys_effective_decision_cap(tmp_path):
    provider = ScriptedProvider([ModelResponse(output="claimed")] * 3)
    with engine(
        tmp_path / "decisions.sqlite",
        provider,
        FixedAgentLimits(max_decisions=1),
        verifier=ToolReceiptVerifier("change"),
    ) as runtime:
        handle = runtime.submit(AgentSpec("a", "a", max_decisions=8), "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and provider.calls == 1
        assert len([a for a in done.actions if "completion_verification" in a]) == 1


@pytest.mark.parametrize("kind", ["agent", "graph", "parallel"])
def test_context_cap_refuses_before_model_dispatch(tmp_path, kind):
    provider = ScriptedProvider([ModelResponse(output="ok")])
    spec = AgentSpec("a", "a", max_context_chars=32000)
    if kind != "agent":
        spec = GraphWorkflowSpec(
            "g", [GraphNode("a", agent=spec)], max_concurrency=2 if kind == "parallel" else 1
        )
    with engine(
        tmp_path / "context.sqlite", provider, FixedAgentLimits(max_context_chars=256)
    ) as runtime:
        if kind == "agent":
            with pytest.raises(ValidationError):
                runtime.submit(spec, "x" * 600, command_id="s")
        else:
            handle = runtime.submit(spec, "x" * 600, command_id="s")
            assert asyncio.run(runtime.drive(handle.run_id)).state == "failed"
        assert provider.calls == 0


def test_custom_harness_cannot_expand_request_past_fixed_context_cap(tmp_path):
    class Expander(NativeHarness):
        identity = {"kind": "expander", "version": "1"}

        def prepare(self, spec, messages, tools):
            return ModelRequest([*messages, {"role": "user", "content": "x" * 1000}], tools)

    provider = ScriptedProvider([ModelResponse(output="ok")])
    with engine(
        tmp_path / "harness.sqlite",
        provider,
        FixedAgentLimits(max_context_chars=256),
        harness=Expander(),
    ) as runtime:
        handle = runtime.submit(AgentSpec("a", "a"), "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "failed" and provider.calls == 0


@pytest.mark.parametrize("cap,count", [(0, 1), (1, 2)])
def test_over_limit_tool_batch_adopts_nothing_and_writes_nothing(tmp_path, cap, count):
    writes = []
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=[ToolCall("change", {"value": n}) for n in range(count)])]
    )
    with engine(
        tmp_path / "batch.sqlite",
        provider,
        FixedAgentLimits(max_tool_actions=cap),
        tools=registry(writes),
    ) as runtime:
        handle = runtime.submit(AgentSpec("a", "a", ("change",)), "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "agent_limit_exceeded"
        assert writes == [] and not [a for a in done.actions if a["kind"] == "tool"]
        assert done.actions[-1]["received_response"]["tool_calls"]


def test_accepted_tool_action_survives_approval_restart_without_extra_slot(tmp_path):
    writes = []
    path = tmp_path / "approval.sqlite"
    tools = registry(writes)
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=[ToolCall("change", {"value": 1})]), ModelResponse(output="ok")]
    )
    spec = AgentSpec("a", "a", ("change",))
    limits = FixedAgentLimits(max_tool_actions=1)
    with engine(path, provider, limits, tools=tools) as runtime:
        handle = runtime.submit(spec, "q", command_id="s")
        pending = asyncio.run(runtime.drive(handle.run_id)).pending[0]
        receipt = runtime.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="a"
        )
        manifest = runtime.diagnostics(handle.run_id).manifest
    with engine(path, provider, limits, tools=tools) as runtime:
        assert runtime.submit(spec, "q", command_id="s") == handle
        assert (
            runtime.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="a")
            == receipt
        )
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded" and writes == [{"value": 1}]
        assert runtime.diagnostics(handle.run_id).manifest == manifest
        assert asyncio.run(runtime.drive(handle.run_id)) == done and provider.calls == 2


def test_completed_action_still_counts_against_later_proposal(tmp_path):
    writes = []
    provider = ScriptedProvider(
        [
            ModelResponse(tool_calls=[ToolCall("change", {"value": 1})]),
            ModelResponse(tool_calls=[ToolCall("change", {"value": 2})]),
        ]
    )
    with engine(
        tmp_path / "count.sqlite",
        provider,
        FixedAgentLimits(max_tool_actions=1),
        tools=registry(writes),
    ) as runtime:
        handle = runtime.submit(AgentSpec("a", "a", ("change",)), "q", command_id="s")
        pending = asyncio.run(runtime.drive(handle.run_id)).pending[0]
        runtime.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="a")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "agent_limit_exceeded"
        assert (
            writes == [{"value": 1}] and len([a for a in done.actions if a["kind"] == "tool"]) == 1
        )


def test_unknown_effect_reconciliation_does_not_create_another_action(tmp_path):
    writes = []
    path = tmp_path / "unknown.sqlite"
    tools = registry(writes, fail=True)
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=[ToolCall("change", {"value": 1})]), ModelResponse(output="ok")]
    )
    limits = FixedAgentLimits(max_tool_actions=1)
    with engine(path, provider, limits, tools=tools) as runtime:
        handle = runtime.submit(AgentSpec("a", "a", ("change",)), "q", command_id="s")
        pending = asyncio.run(runtime.drive(handle.run_id)).pending[0]
        runtime.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="a")
        unknown = asyncio.run(runtime.drive(handle.run_id))
        assert unknown.state == "waiting_reconciliation"
    with engine(path, provider, limits, tools=tools) as runtime:
        runtime.reconcile(handle.run_id, pending["action_id"], {"applied": True}, command_id="r")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded" and writes == [{"value": 1}]


def test_accepted_caps_are_used_without_reinvoking_oscillating_policy(tmp_path):
    class Policy:
        identity = {"kind": "oscillating", "version": "1"}
        calls = 0

        def propose(self, spec):
            self.calls += 1
            return AgentLimitProposal(max_decisions=1 if self.calls == 1 else 8)

    policy = Policy()
    provider = ScriptedProvider([])
    with engine(tmp_path / "oscillating.sqlite", provider, policy) as runtime:
        handle = runtime.submit(AgentSpec("a", "a"), "q", command_id="s")
        assert policy.calls == 1
        assert runtime._agent_step(runtime.store.run(handle.run_id))["max_decisions"] == 1
        assert policy.calls == 1
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(handle.run_id))
        assert provider.calls == 0


def test_drift_during_model_call_preserves_response_and_blocks_effect(tmp_path):
    writes = []

    class Provider:
        identity = {"kind": "drift-provider", "version": "1"}

        async def complete(self, messages, tools):
            runtime.limits = FixedAgentLimits(max_tool_actions=99)
            return ModelResponse(tool_calls=[ToolCall("change", {"value": 1})])

    with engine(
        tmp_path / "drift.sqlite",
        Provider(),
        FixedAgentLimits(max_tool_actions=1),
        tools=registry(writes),
    ) as runtime:
        handle = runtime.submit(AgentSpec("a", "a", ("change",)), "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "definition_mismatch"
        assert writes == [] and done.actions[-1]["received_response"]["tool_calls"]
