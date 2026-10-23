"""Coding4 request validation retains independent entry and final binding checks."""

import json

import pytest

from relf_agent import (
    AgentSpec,
    BindingSelection,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    TeamSpec,
)
from relf_agent.binding_paths import agent_paths
from relf_agent.binding_types import AgentBindingDescriptor
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.temporal_coding_composition_protocol import validate_topology
from relf_agent.temporal_state import validate_request
from relf_agent.types import canonical, submission_request
from tests.test_temporal_binding_validation_pass import descriptor_calls
from tests.test_temporal_session_deployment_coding_configuration import coding_session_manifest


def inputs(kind="graph"):
    manifest = json.loads(canonical(coding_session_manifest(composition=True)))
    manifest["orchestration"] = {
        "teams": {"sequential": {}},
        "planners": {"rule": {}, "dag-rule": {}},
        "verifiers": {"complete": {}},
    }
    graph = GraphWorkflowSpec(
        "graph",
        [
            GraphNode(name, agent=AgentSpec(name, "Task", tools=("coding",)))
            for name in ("a", "b", "c")
        ],
    )
    if kind == "team":
        graph = TeamSpec(
            "team", {name: AgentSpec(name, "Task", tools=("coding",)) for name in ("a", "b", "c")}
        )
    elif kind == "dynamic":
        graph = DynamicWorkflowSpec(
            "dynamic",
            {name: AgentSpec(name, "Task", tools=("coding",)) for name in ("a", "b", "c")},
        )
    elif kind == "nested":
        graph = TeamSpec("outer", {"nested": graph})
    request = submission_request(graph, "question", budget=64)
    request["agent_bindings"] = {
        path: AgentBindingDescriptor(runner=BindingSelection.ref("native", "1")).to_dict()
        for path in agent_paths(request["definition"])
    }
    return request, manifest


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic", "nested"])
def test_complete_request_reuses_initial_binding_results_only_inside_topology(kind):
    request, manifest = inputs(kind)
    before = canonical([request, manifest])
    calls, result = descriptor_calls(lambda: validate_request(request, manifest))
    assert result is None
    assert calls == 18  # Initial and final complete passes; no duplicate middle pass.
    assert canonical([request, manifest]) == before


def test_public_topology_remains_an_independent_complete_binding_boundary():
    request, manifest = inputs()
    before = canonical([request, manifest])
    calls, result = descriptor_calls(lambda: validate_topology(request, manifest))
    assert result is None
    assert calls == 9
    assert canonical([request, manifest]) == before


@pytest.mark.parametrize("custom", ["request", "manifest", "input"])
def test_custom_python_inputs_preserve_the_original_validation_sequence(custom):
    class CustomDict(dict):
        pass

    request, manifest = inputs()
    if custom == "request":
        request = CustomDict(request)
    elif custom == "manifest":
        manifest = CustomDict(manifest)
    else:
        request["input"] = CustomDict(question="question")
    calls, result = descriptor_calls(lambda: validate_request(request, manifest))
    assert result is None
    assert calls == (27 if custom == "input" else 36)


def test_legacy_coding_three_keeps_the_original_three_groups():
    from relf_agent.temporal_deployment_protocol import CODING_SOURCE_FILES

    request, manifest = inputs()
    manifest.pop("session_deployment_protocol")
    manifest["deployment_admission_protocol"].update(
        version=3,
        implementation={name: "e" * 64 for name in CODING_SOURCE_FILES},
    )
    calls, result = descriptor_calls(lambda: validate_request(request, manifest))
    assert result is None
    assert calls == 36


def test_shared_python_input_containers_keep_the_original_middle_pass():
    request, manifest = inputs()
    item = {"question": "question"}
    request["input"] = {"first": item, "second": item}
    calls, result = descriptor_calls(lambda: validate_request(request, manifest))
    assert result is None
    assert calls == 27


@pytest.mark.parametrize("fault", ["concurrency", "runner", "missing_path", "source"])
def test_reused_topology_still_refuses_invalid_original_grants_and_bounds(fault):
    request, manifest = inputs()
    if fault == "concurrency":
        request["definition"]["max_concurrency"] = 33
    elif fault == "runner":
        request["agent_bindings"]["graph/nodes/a"]["tool_set"] = (
            BindingSelection.disabled().to_dict()
        )
    elif fault == "missing_path":
        request["agent_bindings"]["graph/nodes/foreign"] = request["agent_bindings"].pop(
            "graph/nodes/a"
        )
    else:
        manifest["coding_composition_protocol"]["implementation"]["protocol"][
            "_topology_definitions"
        ] = "0" * 64
    before = canonical([request, manifest])
    with pytest.raises((AuthorizationDenied, DefinitionMismatch, ValidationError)):
        validate_request(request, manifest)
    assert canonical([request, manifest]) == before


def test_private_structure_helper_is_part_of_the_original_source_inventory(monkeypatch):
    from relf_agent import temporal_coding_composition_protocol as protocol

    request, manifest = inputs()
    monkeypatch.setattr(protocol, "_topology_definitions", lambda *args: [])
    with pytest.raises(DefinitionMismatch, match="History changed"):
        validate_request(request, manifest)


def test_reused_dynamic_topology_still_refuses_hidden_coding_planner():
    from dataclasses import asdict

    request, manifest = inputs("dynamic")
    planner = request["definition"]["planner"]
    manifest["orchestration"]["planners"][planner]["agent"] = asdict(
        AgentSpec("hidden", "Task", tools=("coding",))
    )
    with pytest.raises(ValidationError, match="Hidden.*Coding"):
        validate_request(request, manifest)


def test_final_independent_binding_check_rejects_a_change_after_topology():
    import sys

    from relf_agent import temporal_coding_composition_protocol as protocol

    request, manifest = inputs()
    code = protocol._topology_definitions.__code__
    changed = []
    previous = sys.getprofile()

    def change(frame, event, arg):
        if event == "return" and frame.f_code is code:
            request["agent_bindings"]["graph/nodes/a"]["tool_set"] = (
                BindingSelection.disabled().to_dict()
            )
            changed.append(True)

    sys.setprofile(change)
    try:
        with pytest.raises(AuthorizationDenied, match="already-granted Coding tool"):
            validate_request(request, manifest)
    finally:
        sys.setprofile(previous)
    assert changed == [True]


def test_request_without_bindings_still_uses_the_independent_topology_entry():
    import sys

    request, manifest = inputs()
    request.pop("agent_bindings")
    code = validate_topology.__code__
    calls = []
    previous = sys.getprofile()

    def observe(frame, event, arg):
        if event == "call" and frame.f_code is code:
            calls.append(True)

    sys.setprofile(observe)
    try:
        validate_request(request, manifest)
    finally:
        sys.setprofile(previous)
    assert calls == [True]
