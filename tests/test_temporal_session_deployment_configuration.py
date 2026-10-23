"""Session deployment is opt-in; old public selections remain unchanged."""

import pytest

from relf_agent import DeploymentAdmissionPolicy, TemporalProfile, ToolRegistry
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.runtime_builder import EchoProvider
from relf_agent.temporal_activities import TemporalRuntime


def runtime(**options):
    return TemporalRuntime(
        providers={"default": EchoProvider("session")}, tools=ToolRegistry(), **options
    )


def test_only_explicit_session_deployment_selects_four():
    policy = DeploymentAdmissionPolicy("session-deployment")
    original = runtime(enable_sessions=True, admission_policy=policy)
    selected = runtime(enable_sessions=True, admission_policy=policy, deployment_sessions=True)
    assert original.manifest["deployment_admission_protocol"]["version"] == 2
    assert "session_deployment_protocol" not in original.manifest
    assert selected.manifest["deployment_admission_protocol"]["version"] == 4
    selected.deployment_sessions = False
    with pytest.raises(DefinitionMismatch):
        selected.validate_release()


@pytest.mark.parametrize(
    "options",
    [
        {"deployment_sessions": 1},
        {"deployment_sessions": True},
        {"deployment_sessions": True, "enable_sessions": True},
        {"deployment_sessions": True, "admission_policy": DeploymentAdmissionPolicy("no-session")},
    ],
)
def test_invalid_session_deployment_configuration_refuses_before_execution(options):
    with pytest.raises(ValidationError):
        runtime(**options)


def test_profile_declares_same_explicit_session_selection():
    profile = TemporalProfile(
        "session",
        "1",
        {"default": {"adapter": "offline-echo"}},
        execution={"enable_sessions": True, "deployment_sessions": True},
    )
    assert profile.execution["deployment_sessions"] is True
    with pytest.raises(ValidationError):
        TemporalProfile(
            "session",
            "1",
            {"default": {"adapter": "offline-echo"}},
            execution={"deployment_sessions": True},
        )
