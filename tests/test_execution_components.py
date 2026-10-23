import asyncio

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.executors import EffectObservation
from relf_agent.harness import DecisionProposal, ModelRequest, NativeHarness


class RecordingProvider:
    identity = {"kind": "components-provider", "version": "1"}

    def __init__(self, response=None):
        self.response = response or ModelResponse(output={"value": 4})
        self.requests = []

    async def complete(self, messages, tools):
        self.requests.append((messages, tools))
        return self.response


class CustomHarness(NativeHarness):
    def __init__(self):
        self.version = "1"

    @property
    def identity(self):
        return {"kind": "custom-harness", "version": self.version}

    def prepare(self, spec, messages, tools):
        messages[0]["content"] = "Custom policy: " + spec.instructions
        return ModelRequest(messages, tools)

    def propose(self, spec, response):
        return DecisionProposal(output={"value": response.output["value"] + 1})


def test_custom_harness_prepares_persisted_request_and_changes_adopted_decision(tmp_path):
    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        harness=CustomHarness(),
    ) as engine:
        handle = engine.submit(AgentSpec("custom", "Return a number"), {}, command_id="start")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded" and done.result == {"value": 5}
        model = done.actions[0]
        assert model["snapshot"][0]["content"] == "Custom policy: Return a number"
        assert model["received_response"]["output"] == {"value": 4}
        assert model["response"]["output"] == {"value": 5}
        assert len(provider.requests) == 1


def test_same_custom_harness_serves_each_sequential_workflow_step(tmp_path):
    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        harness=CustomHarness(),
    ) as engine:
        handle = engine.submit(
            WorkflowSpec("flow", (AgentSpec("one", "First"), AgentSpec("two", "Second"))),
            {},
            command_id="start",
        )
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded" and done.result == {"value": 5}
        assert len(provider.requests) == 2
        assert provider.requests[1][0][1]["content"] == '{"value":5}'


class EscalatingHarness(NativeHarness):
    identity = {"kind": "invalid-proposal", "version": "1"}

    def propose(self, spec, response):
        return DecisionProposal(tool_calls=(ToolCall("forbidden", {}),))


def test_harness_cannot_grant_a_tool_outside_the_agent_spec(tmp_path):
    writes = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec("forbidden", "Forbidden", {"type": "object"}),
        lambda arguments, context: writes.append(True),
    )
    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=registry,
        harness=EscalatingHarness(),
    ) as engine:
        handle = engine.submit(AgentSpec("restricted", "Answer only"), {}, command_id="start")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "authorization_denied"
        assert not writes and len(provider.requests) == 1
        assert not any(action["kind"] == "tool" for action in done.actions)
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 1}


class RemoteExecutor:
    identity = {"kind": "remote-fixture", "version": "1"}

    def __init__(self):
        self.calls = []

    async def execute(self, envelope):
        self.calls.append(envelope)
        return EffectObservation({"updated": True}, "remote-fixture")

    async def reconcile(self, envelope):
        return None


class ToolProvider(RecordingProvider):
    async def complete(self, messages, tools):
        self.requests.append((messages, tools))
        if any(message["role"] == "tool" for message in messages):
            return ModelResponse(output="Complete")
        return ModelResponse(tool_calls=(ToolCall("change", {"value": 3}),))


def test_custom_executor_receives_only_approved_stable_dispatch_envelope(tmp_path):
    local_calls = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "change", "Change", {"type": "object"}, effect="queryable_write", requires_approval=True
        ),
        lambda arguments, context: local_calls.append(True),
    )
    executor = RemoteExecutor()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": ToolProvider()},
        tools=registry,
        tool_executor=executor,
    ) as engine:
        handle = engine.submit(
            AgentSpec("custom", "Change once", ("change",)), {}, command_id="start"
        )
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_approval" and executor.calls == []
        pending = waiting.pending[0]
        engine.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="approve")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded" and len(executor.calls) == 1 and not local_calls
        envelope = executor.calls[0]
        action = next(action for action in done.actions if action["kind"] == "tool")
        assert envelope.arguments == {"value": 3}
        assert envelope.operation_digest == pending["digest"]
        assert envelope.context.action_id == pending["action_id"]
        assert envelope.context.effect_key == action["effect_key"]
        assert action["receipt"]["source"] == "remote-fixture"


def test_changed_harness_identity_cannot_continue_an_existing_run(tmp_path):
    harness = CustomHarness()
    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        harness=harness,
    ) as engine:
        handle = engine.submit(AgentSpec("custom", "Answer"), {}, command_id="start")
        harness.version = "2"
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(handle.run_id))
        assert not provider.requests


class AsyncHarness(NativeHarness):
    async def propose(self, spec, response):
        return DecisionProposal(output="No")


def test_async_harness_is_rejected_before_acquiring_store_ownership(tmp_path):
    store = SQLiteStore(tmp_path / "run.db")
    with pytest.raises(ValidationError):
        LocalEngine(
            store,
            providers={"default": RecordingProvider()},
            tools=ToolRegistry(),
            harness=AsyncHarness(),
        )
    with LocalEngine(
        store, providers={"default": RecordingProvider()}, tools=ToolRegistry()
    ) as engine:
        assert engine


def test_unsupported_prepare_return_is_rejected_before_calling_provider(tmp_path):
    class WrappedHarness(NativeHarness):
        def prepare(self, spec, messages, tools):
            async def delayed():
                return ModelRequest(messages, tools)

            return delayed()

    provider = RecordingProvider()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": provider},
        tools=ToolRegistry(),
        harness=WrappedHarness(),
    ) as engine:
        handle = engine.submit(AgentSpec("wrapped", "Answer"), {}, command_id="start")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "validation_error"
        assert not provider.requests


def test_invalid_executor_observation_keeps_the_dispatched_effect_unknown(tmp_path):
    class BrokenExecutor(RemoteExecutor):
        async def execute(self, envelope):
            self.calls.append(envelope)
            return {"updated": True}

    registry = ToolRegistry()
    registry.register(
        ToolSpec("change", "Change", {"type": "object"}, effect="unqueryable_write"),
        lambda arguments, context: None,
    )
    executor = BrokenExecutor()
    with LocalEngine(
        SQLiteStore(tmp_path / "run.db"),
        providers={"default": ToolProvider()},
        tools=registry,
        tool_executor=executor,
    ) as engine:
        handle = engine.submit(
            AgentSpec("broken", "Change once", ("change",)), {}, command_id="start"
        )
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_reconciliation" and len(executor.calls) == 1
        action = next(action for action in waiting.actions if action["kind"] == "tool")
        assert action["status"] == "outcome_unknown"
        assert engine.store.budget(handle.run_id)["held"] == 1
