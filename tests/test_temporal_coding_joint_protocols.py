"""Original optional capabilities retain their gates in the Coding joint release."""

import copy

import pytest

from tests.test_sandbox_bindings import registered as registered


def candidate(kind):
    if kind == "context":
        from tests.test_temporal_context_read_protocol import candidate

        return candidate()
    if kind == "tool":
        from ralf_agent import ToolExecutionOwner, ToolRegistry
        from ralf_agent.temporal_activities import TemporalRuntime
        from tests.test_temporal_engine import Provider

        return TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            tool_execution=ToolExecutionOwner(version="1"),
        ).manifest
    if kind == "artifacts":
        from tests.test_artifact_binding_temporal import host

        return host()[0].manifest
    if kind in ("continuation", "history"):
        from tests.test_temporal_model_history import setup

        return setup()[0].manifest
    if kind == "parent":
        from tests.test_temporal_parent_completion import setup

        return setup()[0].manifest
    if kind == "input":
        from tests.test_temporal_user_input import parts

        return parts()[0].manifest


@pytest.mark.parametrize(
    "kind", ["context", "tool", "artifacts", "continuation", "history", "parent", "input"]
)
def test_coding_joint_version_keeps_original_optional_capability_validation(kind):
    from ralf_agent import (
        temporal_artifact_bindings,
        temporal_context_read_protocol,
        temporal_decision_state,
        temporal_parent_completion_state,
        temporal_tool_execution,
        temporal_user_input,
    )

    validators = {
        "context": temporal_context_read_protocol.validate_protocol,
        "tool": temporal_tool_execution.validate_protocol,
        "artifacts": temporal_artifact_bindings.validate_protocol,
        "continuation": temporal_decision_state.validate_continuation_protocol,
        "history": temporal_decision_state.validate_model_history_protocol,
        "parent": temporal_parent_completion_state.validate_protocol,
        "input": temporal_user_input.validate_protocol,
    }
    release = copy.deepcopy(candidate(kind))
    validators[kind](release)
    release.update(kernel="temporal-3", binding_protocol=11, dispatch_admission="history-1")
    validators[kind](release)


def test_coding_joint_version_keeps_original_sandbox_gate(registered):
    from ralf_agent.binding_sandbox import validate_sandbox_protocol
    from tests.test_sandbox_temporal_protocol import runtime_for

    release = copy.deepcopy(runtime_for(registered[0]).manifest)
    release["binding_protocol"] = 11
    validate_sandbox_protocol(release)
