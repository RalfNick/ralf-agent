import asyncio

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, TeamSpec
from ralf_agent.errors import ValidationError
from ralf_agent.temporal import TemporalEngine
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.tools import ToolRegistry

from .test_temporal_engine import Provider


def test_composite_preflight_accepts_extended_registration_without_local_store():
    from ralf_agent.temporal_state import validate_request
    from ralf_agent.types import submission_request

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    graph = GraphWorkflowSpec("graph", [GraphNode("a", agent=AgentSpec("a", "Answer"))])
    validate_request(submission_request(graph, "task", budget=16), runtime.orchestration_release)
    validate_request(
        submission_request(TeamSpec("team", {"a": AgentSpec("a", "Answer")}), "task", budget=16),
        runtime.orchestration_release,
    )


def test_policy_rejects_forbidden_tool_before_any_provider_call():
    from ralf_agent.governance import TemporalExecutionPolicy
    from ralf_agent.temporal_state import validate_request
    from ralf_agent.types import submission_request

    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        execution_policy=TemporalExecutionPolicy(allowed_tools=[]),
    )
    with pytest.raises(ValidationError):
        validate_request(
            submission_request(AgentSpec("a", "Answer", ("write",)), "task", budget=16),
            runtime.manifest,
        )


def test_composite_without_registered_extension_is_refused_before_network():
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    engine = TemporalEngine(object(), task_queue="queue", release=runtime.manifest)
    with pytest.raises(ValidationError, match="orchestration"):
        asyncio.run(
            engine.submit(
                TeamSpec("team", {"a": AgentSpec("a", "Answer")}), "task", command_id="start"
            )
        )


def test_extended_release_survives_actual_json_history_normalization():
    import json

    from ralf_agent.types import canonical

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    wire = json.loads(canonical(runtime.orchestration_release))
    assert runtime.validate_release(wire) == runtime.manifest


def test_replacing_registry_container_cannot_bypass_pinned_implementation():
    from ralf_agent import TeamSelection
    from ralf_agent.errors import DefinitionMismatch

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())

    class Replacement:
        identity = runtime.teams["sequential"].identity

        def select(self, request):
            return TeamSelection(done=True, result="replacement")

    runtime.teams = {**runtime.teams, "sequential": Replacement()}
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


@pytest.mark.parametrize("bind_child", [False, True])
def test_child_control_reference_keeps_original_projected_binding_release(bind_child):
    from dataclasses import asdict
    from types import SimpleNamespace

    from ralf_agent import AgentBindingDescriptor, BindingCatalog, BoundDefinition, RunRef, Scope
    from ralf_agent.temporal_agent_controls import child_reference
    from ralf_agent.temporal_bindings import normalize_request, request_release_digest
    from ralf_agent.temporal_parent_state import TemporalParentState
    from ralf_agent.temporal_state import TemporalRunState
    from ralf_agent.types import submission_request

    scope = Scope()
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        binding_catalog=BindingCatalog(scope=scope),
    )
    graph = GraphWorkflowSpec(
        "graph",
        [
            GraphNode("a", agent=AgentSpec("a", "answer")),
            GraphNode("b", agent=AgentSpec("b", "answer")),
        ],
    )
    # A bound root projects an explicit empty map to unselected children too.
    declaration = BoundDefinition(
        graph, {"graph/nodes/a" if bind_child else "graph/nodes/b": AgentBindingDescriptor()}
    )
    parent = TemporalParentState(
        "root",
        asdict(scope),
        "submit",
        normalize_request(submission_request(declaration, "task", budget=16)),
        runtime.orchestration_release,
    )
    call = parent.next_calls()[0]
    native = TemporalRunState(
        call["run_id"], asdict(scope), call["command_id"], call["request"], parent.manifest
    )
    reference = child_reference(
        SimpleNamespace(scope=scope),
        RunRef("resource", scope.workspace, scope.principal, "root", parent.release_digest),
        SimpleNamespace(manifest=parent.manifest),
        call,
    )
    assert reference.release_digest == request_release_digest(call["request"], parent.manifest)
    assert reference.release_digest == native.release_digest
