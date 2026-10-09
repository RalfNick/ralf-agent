import asyncio
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentSpec,
    BudgetedContextAssembler,
    ModelResponse,
    Scope,
    ToolRegistry,
    UTF8TokenEstimator,
)
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request


class Provider:
    identity = {"kind": "custom-context-fixture", "version": "1"}

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        return ModelResponse(output="ok")


def setup(builder):
    provider = Provider()
    runtime = TemporalRuntime(
        providers={"default": provider}, tools=ToolRegistry(), context_builder=builder
    )
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "one",
        submission_request(AgentSpec("a", "Answer", max_context_chars=2048), "task", budget=4),
        runtime.manifest,
    )
    return runtime, state, provider


def test_custom_context_adopted_before_provider_and_measured():
    async def run():
        runtime, state, provider = setup(
            BudgetedContextAssembler(counter=UTF8TokenEstimator(), max_units=400)
        )
        assert "context_registration" in runtime.manifest
        assert runtime.capabilities["custom_context_builder"] is True
        action, request = state.next_operation()
        assert action["kind"] == "context" and provider.calls == 0
        evidence = await runtime.prepare_context(request)
        assert evidence["ok"] and evidence["context_identity"]["measurement"]["estimated"]
        state.accept_context(action["id"], evidence)
        action, request = state.next_operation()
        assert action["kind"] == "model" and request["context"] == evidence
        assert (await runtime.complete_model(request))["ok"] and provider.calls == 1
        assert any(e["kind"] == "context_snapshot_recorded" for e in state.event_log)

    asyncio.run(run())


def test_same_identity_context_instance_and_validator_replacement_refused():
    builder = BudgetedContextAssembler()
    runtime, _, _ = setup(builder)
    runtime.context = BudgetedContextAssembler()
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()
    runtime.context = builder
    builder.validate_request = lambda messages, max_chars: None
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_custom_context_final_request_budget_refuses_disclosure():
    async def run():
        runtime, state, provider = setup(
            BudgetedContextAssembler(counter=UTF8TokenEstimator(), max_units=1)
        )
        action, request = state.next_operation()
        evidence = await runtime.prepare_context(request)
        assert evidence == {"ok": False, "code": "validation_error"}
        assert provider.calls == 0
        state.accept_context(action["id"], evidence)
        assert state.state == "failed"

    asyncio.run(run())


def test_default_native_release_does_not_add_context_registration():
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    assert "context_registration" not in runtime.manifest
