"""Local-only coding selections never cross Temporal business admission."""

import asyncio
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, ModelResponse, Scope, ToolRegistry
from relf_agent.delegated_coding import register_coding_tool
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request

from .helpers import ScriptedProvider
from .test_local_delegated_coding import LifecycleRunner
from .test_temporal_engine import JournalContractFixture


def worker():
    tools = ToolRegistry()
    resource = LifecycleRunner()
    register_coding_tool(tools, resource)
    provider = ScriptedProvider([ModelResponse(output="done")])
    runtime = TemporalRuntime(
        providers={"default": provider}, tools=tools, journal=JournalContractFixture()
    )
    return runtime, provider, resource


def test_temporal_selected_coding_refused_before_workflow_acceptance():
    runtime, provider, resource = worker()
    request = submission_request(AgentSpec("a", "x", tools=("coding",)), "x")
    with pytest.raises(DefinitionMismatch, match="Local|delegated"):
        TemporalRunState("run", asdict(Scope()), "s", request, runtime.manifest)
    assert provider.calls == 0
    assert resource.calls == []


def test_temporal_direct_model_activity_refuses_selected_coding_before_dispatch():
    runtime, provider, resource = worker()
    response = asyncio.run(
        runtime.complete_model(
            {
                "runtime_manifest": runtime.manifest,
                "step": asdict(AgentSpec("a", "x", tools=("coding",))),
                "messages": [{"role": "user", "content": "x"}],
            }
        )
    )
    assert response["ok"] is False
    assert response["dispatched"] is False
    assert provider.calls == 0
    assert resource.calls == []


def test_unselected_registered_coding_preserves_temporal_ordinary_model():
    runtime, provider, resource = worker()
    request = submission_request(AgentSpec("a", "x"), "x")
    state = TemporalRunState("run", asdict(Scope()), "s", request, runtime.manifest)
    _, payload = state.next_operation()
    assert asyncio.run(runtime.complete_model(payload))["ok"] is True
    assert provider.calls == 1
    assert resource.calls == []
