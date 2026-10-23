"""New reads require explicit release gates; old histories retain legacy shape."""

import copy

import pytest

from relf_agent import AgentSpec, ToolRegistry
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState, validate_manifest
from relf_agent.types import submission_request

from .test_temporal_context_execution import owner
from .test_temporal_sessions import Provider


def native():
    return TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry()).manifest


def candidate(manifest=None, registration=None):
    from relf_agent.temporal_context_read_protocol import ContextExecutionRegistration, publish

    return publish(
        native() if manifest is None else manifest,
        ContextExecutionRegistration(owner()) if registration is None else registration,
    )


def test_read_release_is_explicit_and_does_not_mutate_legacy_context_or_manifest():
    manifest = native()
    before = copy.deepcopy(manifest)
    proposed = candidate(manifest)
    validate_manifest(proposed)
    assert manifest == before and "context_read_protocol" not in manifest
    assert proposed["binding_protocol"] == 2
    request = submission_request(AgentSpec("a", "Answer"), "input")
    original = TemporalRunState(
        "run-a", {"workspace": "default", "principal": "local-owner"}, "first", request, manifest
    )
    operation = original.next_operation()
    assert operation[0]["kind"] == "model"
    assert "execution_epoch" not in operation[1]


@pytest.mark.parametrize(
    "mutation",
    ["old-binding", "missing-protocol", "bad-version", "unknown-phase", "bad-hash", "bad-owner"],
)
def test_invalid_read_release_refuses_before_execution(mutation):
    proposed = candidate()
    if mutation == "old-binding":
        proposed["binding_protocol"] = 1
    elif mutation == "missing-protocol":
        proposed.pop("context_read_protocol")
    elif mutation == "bad-version":
        proposed["context_read_protocol"]["version"] = True
    elif mutation == "unknown-phase":
        proposed["context_read_protocol"]["phases"].append("write")
    elif mutation == "bad-hash":
        proposed["context_read_protocol"]["implementation"]["execute"] = "bad"
    else:
        proposed["context_read_protocol"]["owner"] = {}
    with pytest.raises(DefinitionMismatch):
        validate_manifest(proposed)


def test_registration_refuses_configuration_and_method_changes():
    from relf_agent.temporal_context_read_protocol import ContextExecutionRegistration

    component = owner()
    registered = ContextExecutionRegistration(component)
    component.max_calls = 2
    with pytest.raises(DefinitionMismatch):
        candidate(registration=registered)
    component.max_calls = 8

    async def changed(*args, **kwargs):
        return None

    component.execute = changed
    with pytest.raises(DefinitionMismatch):
        candidate(registration=registered)


def test_explicit_read_candidate_uses_original_native_authority():
    proposed = candidate()
    validate_manifest(proposed)
    state = TemporalRunState(
        "run-a",
        {"workspace": "default", "principal": "local-owner"},
        "first",
        submission_request(AgentSpec("a", "Answer"), "input"),
        proposed,
    )
    assert state.next_operation()[0]["kind"] == "model"
    assert state.diagnostics()["context_reads"] == []
