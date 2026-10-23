"""Session4 reuses native6/22 and composition7/23 without weakening inventories."""

import asyncio
import copy

import pytest

from relf_agent import DeploymentAdmissionPolicy, Scope, TemporalProfile
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.temporal_activities import TemporalRuntime


def coding_session_manifest(*, composition=False):
    """Pure complete publication fixture; physical fingerprints are not SDK proof."""
    from relf_agent.temporal_deployment_protocol import SESSION_SOURCE_FILES
    from tests.test_temporal_coding_composition_configuration import composition_manifest
    from tests.test_temporal_deployment_coding_registry import coding_request

    value = copy.deepcopy(coding_request()["root_admission"]["submission"]["manifest"])
    value.update(session_protocol=1, session_deployment_protocol=1)
    value["deployment_admission_protocol"].update(
        version=4, implementation={name: "e" * 64 for name in SESSION_SOURCE_FILES}
    )
    if composition:
        value.update(
            binding_protocol=23,
            coding_composition_protocol=composition_manifest()["coding_composition_protocol"],
        )
    return value


@pytest.mark.parametrize("composition", [False, True])
def test_coding_session_four_validates_original_native_and_composition_publications(composition):
    from relf_agent.temporal_deployment_protocol import SESSION_SOURCE_FILES, validate_protocol

    value = coding_session_manifest(composition=composition)
    validate_protocol(value)
    assert value["coding_execution_protocol"]["version"] == 6
    assert value["binding_protocol"] == (23 if composition else 22)
    assert set(value["deployment_admission_protocol"]["implementation"]) == set(
        SESSION_SOURCE_FILES
    )
    if composition:
        assert value["coding_composition_protocol"]["version"] == 7


@pytest.mark.parametrize("mutation", ["binding", "inventory", "native", "composition"])
def test_coding_session_four_rejects_incomplete_or_unsupported_publication(mutation):
    from relf_agent.temporal_deployment_protocol import validate_protocol

    value = coding_session_manifest(composition=True)
    if mutation == "binding":
        value["binding_protocol"] = 21
    elif mutation == "inventory":
        value["deployment_admission_protocol"]["implementation"].pop("temporal_session_workflow.py")
    elif mutation == "native":
        value["coding_execution_protocol"]["version"] = 7
    else:
        value["coding_composition_protocol"]["version"] = 8
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)


@pytest.mark.parametrize("composition", [False, True])
def test_profile_accepts_explicit_coding_session_selection_and_keeps_omitted_flags(composition):
    flags = {"coding_execution": True, "enable_sessions": True, "deployment_sessions": True}
    if composition:
        flags["coding_composition"] = True
    profile = TemporalProfile(
        "coding-session", "1", {"default": {"adapter": "offline-echo"}}, execution=flags
    )
    assert all(profile.execution[key] is True for key in flags)
    original = TemporalProfile(
        "old", "1", {"default": {"adapter": "offline-echo"}}, execution={"coding_execution": True}
    )
    assert "deployment_sessions" not in original.execution
    with pytest.raises(ValidationError):
        TemporalProfile(
            "invalid",
            "1",
            {"default": {"adapter": "offline-echo"}},
            execution={"coding_execution": True, "deployment_sessions": True},
        )


@pytest.mark.parametrize("composition", [False, True])
def test_complete_coding_resources_publish_session_four_with_original_inventory(
    tmp_path, monkeypatch, composition
):
    from relf_agent.runtime_lifecycle import BuildContext
    from relf_agent.temporal_coding_factories import build
    from relf_agent.temporal_deployment_protocol import SESSION_SOURCE_FILES
    from relf_agent.temporal_journal import PostgresEffectJournal
    from tests.test_temporal_coding_factories import Connection, entry, publish_initialization
    from tests.test_temporal_deployment_public_registry import Provider

    async def run():
        events = []
        publish_initialization(monkeypatch, events)
        context = BuildContext(None, tmp_path / "unused", Scope(), tmp_path, allow_async=True)
        effect = context.own_async(PostgresEffectJournal(Connection(events), owns_connection=True))
        context.coding_execution, context.coding_composition, context.effect_journal = (
            True,
            composition,
            effect,
        )
        tools = await build(entry(tmp_path), context)
        try:
            value = TemporalRuntime(
                providers={"default": Provider()},
                tools=tools,
                journal=effect,
                coding_execution=True,
                coding_composition=composition,
                enable_sessions=True,
                deployment_sessions=True,
                admission_policy=DeploymentAdmissionPolicy("coding-session"),
            )
            release = value.orchestration_release
            assert release["deployment_admission_protocol"]["version"] == 4
            assert release["coding_execution_protocol"]["version"] == 6
            assert release["binding_protocol"] == (23 if composition else 22)
            assert set(release["deployment_admission_protocol"]["implementation"]) == set(
                SESSION_SOURCE_FILES
            )
            value.validate_release(release)
        finally:
            await context.cleanup_async()

    asyncio.run(run())


def test_coding_session_four_rechecks_original_guard_aliases(monkeypatch):
    from relf_agent import temporal_deployment_coding_state as guards
    from relf_agent.temporal_deployment_protocol import validate_protocol

    value = coding_session_manifest()
    monkeypatch.setattr(guards, "closure_reasons", lambda state: [])
    with pytest.raises(DefinitionMismatch, match="guard"):
        validate_protocol(value)
