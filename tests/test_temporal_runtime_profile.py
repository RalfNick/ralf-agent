"""Explicit profile provenance never changes legacy default releases."""

import pytest

from relf_agent import AgentSpec, TemporalRuntime, ToolRegistry
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.runtime_builder import EchoProvider
from relf_agent.temporal_profile import TemporalProfile
from relf_agent.temporal_state import TemporalRunState, validate_manifest
from relf_agent.types import submission_request


def runtime(**options):
    return TemporalRuntime(
        providers={"default": EchoProvider("offline")}, tools=ToolRegistry(), **options
    )


def identity():
    return TemporalProfile("worker", "1", {"default": {"adapter": "offline-echo"}}).identity


def test_legacy_runtime_has_no_profile_marker():
    original = runtime()
    assert "runtime_profile" not in original.manifest
    assert runtime(runtime_profile=None).manifest == original.manifest


@pytest.mark.parametrize("profiled", [False, True])
def test_stateless_profile_model_request_has_trusted_scope_and_legacy_payload_stays_exact(profiled):
    manifest = runtime(**({"runtime_profile": identity()} if profiled else {})).manifest
    scope = {"workspace": "profile", "principal": "operator"}
    state = TemporalRunState(
        "run",
        scope,
        "submit",
        submission_request(AgentSpec("answer", "Answer"), "task", budget=16),
        manifest,
    )
    action, request = state.next_operation()
    assert action["kind"] == "model"
    if profiled:
        assert request["scope"] == scope
    else:
        assert set(request) == {"runtime_manifest", "step", "messages"}


def test_explicit_profile_is_detached_and_pinned():
    supplied = identity()
    first = runtime(runtime_profile=supplied)
    supplied["name"] = "changed"
    assert first.manifest["runtime_profile"] == identity()
    first.runtime_profile["name"] = "other"
    with pytest.raises(DefinitionMismatch):
        first.validate_release()


@pytest.mark.parametrize("value", [{}, False, {"name": "worker"}])
def test_malformed_profile_refuses_constructor_and_manifest(value):
    with pytest.raises(ValidationError):
        runtime(runtime_profile=value)
    release = runtime().manifest
    release["runtime_profile"] = value
    with pytest.raises((ValidationError, DefinitionMismatch)):
        validate_manifest(release)
