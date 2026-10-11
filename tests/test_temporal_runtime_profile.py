"""Explicit profile provenance never changes legacy default releases."""

import pytest

from ralf_agent import TemporalRuntime, ToolRegistry
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal_profile import TemporalProfile
from ralf_agent.temporal_state import validate_manifest


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
