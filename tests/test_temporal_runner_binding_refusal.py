"""A Local Runner role must never be silently ignored by Temporal."""

import asyncio
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, Scope
from ralf_agent.binding_catalog import BindingCatalog
from ralf_agent.binding_definitions import AgentDefinition
from ralf_agent.binding_types import AgentBindingDescriptor, BindingSelection
from ralf_agent.errors import ValidationError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request, validate_descriptor
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request

from .test_temporal_delegated_coding_refusal import worker
from .test_temporal_engine import JournalContractFixture

CHOICES = [
    BindingSelection.inherit(),
    BindingSelection.disabled(),
    BindingSelection.ref("coding", "1"),
]


@pytest.mark.parametrize("choice", CHOICES)
def test_temporal_descriptor_refuses_local_runner_even_when_no_coding_tool_is_selected(choice):
    descriptor = AgentBindingDescriptor(runner=choice).to_dict()
    with pytest.raises(ValidationError):
        validate_descriptor({}, descriptor, Scope())


@pytest.mark.parametrize("choice", CHOICES)
def test_temporal_run_cannot_accept_an_ignored_runner_binding(choice):
    runtime, provider, resource = worker()
    runtime = TemporalRuntime(
        providers=runtime.providers,
        tools=runtime.tools,
        journal=JournalContractFixture(),
        binding_catalog=BindingCatalog(scope=Scope()),
    )
    legacy = normalize_request(submission_request(AgentDefinition(AgentSpec("a", "Answer")), "q"))
    TemporalRunState("legacy", asdict(Scope()), "s", legacy, runtime.manifest)
    definition = AgentDefinition(AgentSpec("a", "Answer"), AgentBindingDescriptor(runner=choice))
    request = submission_request(definition, "q")
    with pytest.raises(ValidationError):
        normalized = normalize_request(request)
        TemporalRunState("run", asdict(Scope()), "s", normalized, runtime.manifest)
    assert provider.calls == 0 and resource.calls == []


def test_direct_temporal_model_activity_refuses_runner_binding_before_provider():
    runtime, provider, resource = worker()
    ordinary = submission_request(AgentSpec("a", "Answer"), "q")
    state = TemporalRunState("run", asdict(Scope()), "s", ordinary, runtime.manifest)
    _, payload = state.next_operation()
    payload["step_bindings"] = AgentBindingDescriptor(runner=BindingSelection.inherit()).to_dict()
    response = asyncio.run(runtime.complete_model(payload))
    assert response["ok"] is False
    assert response["dispatched"] is False
    assert provider.calls == 0 and resource.calls == []
