"""Selected Local composition releases retain original Coding grants and bindings."""

import copy

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    Scope,
    TeamSpec,
)
from relf_agent.binding_catalog import BindingCatalog
from relf_agent.binding_manifests import all_step_manifests, step_manifest
from relf_agent.binding_runtime import unwrap_definition
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.types import submission_request

from .test_binding_execution import engine
from .test_runner_bindings import BorrowedRunner, registry


@pytest.mark.parametrize("concurrency", [1, 2])
def test_direct_graph_coding_selection_is_released_with_composition_protocol(tmp_path, concurrency):
    runner = BorrowedRunner()
    graph = GraphWorkflowSpec(
        "coding", [GraphNode("work", tool="coding_0")], max_concurrency=concurrency
    )
    with engine(
        tmp_path / "run.db", BindingCatalog(scope=Scope()), tools=registry(runner)
    ) as runtime:
        definition = submission_request(graph, None)["definition"]
        manifest = runtime._workflow.manifest(runtime._workflow.compile(definition))
        assert manifest["kernel"] == "local-11"
        assert manifest["delegated_composition_protocol"] == 1
        assert manifest["delegated_execution_protocol"] == 1
        assert set(manifest["delegated_coding_tools"]) == {"coding_0"}
        assert set(manifest["tools"]) == {"coding_0"}
    assert runner.calls == []


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic", "nested"])
def test_selected_bound_member_coding_keeps_exact_runner_and_new_parent_release(tmp_path, kind):
    runner = BorrowedRunner()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("runner", "chosen", "1", runner)
    worker = AgentSpec("worker", "Work", tools=("coding_0",))
    if kind == "graph":
        spec = GraphWorkflowSpec("graph", [GraphNode("work", agent=worker)])
        path = "graph/nodes/work"
    elif kind == "nested":
        spec = TeamSpec("outer", {"inner": TeamSpec("inner", {"work": worker})})
        path = "team/members/inner/team/members/work"
    else:
        spec = (TeamSpec if kind == "team" else DynamicWorkflowSpec)(kind, {"work": worker})
        path = f"{kind}/members/work"
    bound = BoundDefinition(
        spec, {path: AgentBindingDescriptor(runner=BindingSelection.ref("chosen", "1"))}
    )
    with engine(tmp_path / "run.db", catalog, tools=registry(runner)) as runtime:
        manifest = runtime._bindings.manifest(unwrap_definition(bound.to_dict()))
        assert manifest["kernel"] == "local-bindings-19"
        assert manifest["runner_binding_protocol"] == 1
        assert manifest["delegated_composition_protocol"] == 1
        assert manifest["delegated_execution_protocol"] == 1
        assert set(manifest["delegated_coding_tools"]) == {"coding_0"}
        entry = manifest["agent_bindings"]["steps"][path]
        assert entry["resolved"]["runner"]["component_id"] == "chosen"
        assert entry["resolved"]["runner"]["identity"]["runner"] == runner.identity
        if kind == "graph":
            assert step_manifest(manifest, 0) == entry["manifest"]
    assert runner.calls == []


def test_bound_direct_only_graph_records_root_grant_without_fabricating_agent_steps(tmp_path):
    runner = BorrowedRunner()
    bound = BoundDefinition(GraphWorkflowSpec("graph", [GraphNode("work", tool="coding_0")]), {})
    with engine(
        tmp_path / "run.db", BindingCatalog(scope=Scope()), tools=registry(runner)
    ) as runtime:
        manifest = runtime._bindings.manifest(unwrap_definition(bound.to_dict()))
        assert manifest["kernel"] == "local-bindings-19"
        assert manifest["agent_bindings"]["steps"] == {}
        assert step_manifest(manifest, 0) is manifest
        assert all_step_manifests(manifest) == [manifest]
        assert set(manifest["delegated_coding_tools"]) == {"coding_0"}
        forged = copy.deepcopy(manifest)
        forged.pop("delegated_composition_protocol")
        with pytest.raises(ValidationError, match="recorded steps"):
            all_step_manifests(forged)


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic"])
def test_complex_explicit_disabled_runner_marks_release_without_native_authority(tmp_path, kind):
    worker = AgentSpec("worker", "Work")
    spec = (
        GraphWorkflowSpec("graph", [GraphNode("work", agent=worker)])
        if kind == "graph"
        else (TeamSpec if kind == "team" else DynamicWorkflowSpec)(kind, {"work": worker})
    )
    path = f"{kind}/{'nodes' if kind == 'graph' else 'members'}/work"
    bound = BoundDefinition(
        spec, {path: AgentBindingDescriptor(runner=BindingSelection.disabled())}
    )
    with engine(tmp_path / "run.db", BindingCatalog(scope=Scope())) as runtime:
        manifest = runtime._bindings.manifest(unwrap_definition(bound.to_dict()))
        assert manifest["kernel"] == "local-bindings-19"
        assert manifest["delegated_composition_protocol"] == 1
        assert "delegated_coding_tools" not in manifest
        assert "delegated_execution_protocol" not in manifest


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic", "nested"])
def test_complex_bound_tool_subset_does_not_release_unselected_host_coding(tmp_path, kind):
    runner = BorrowedRunner()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("tool_set", "plain", "1", ["plain"])
    worker = AgentSpec("worker", "Work", tools=("plain", "coding_0"))
    if kind == "graph":
        spec = GraphWorkflowSpec("graph", [GraphNode("work", agent=worker)])
        path = "graph/nodes/work"
    elif kind == "nested":
        spec = TeamSpec("outer", {"inner": TeamSpec("inner", {"work": worker})})
        path = "team/members/inner/team/members/work"
    else:
        spec = (TeamSpec if kind == "team" else DynamicWorkflowSpec)(kind, {"work": worker})
        path = f"{kind}/members/work"
    bound = BoundDefinition(
        spec, {path: AgentBindingDescriptor(tool_set=BindingSelection.ref("plain", "1"))}
    )
    with engine(tmp_path / "run.db", catalog, tools=registry(runner)) as runtime:
        manifest = runtime._bindings.manifest(unwrap_definition(bound.to_dict()))
        assert manifest["kernel"] == "local-bindings-2"
        assert set(manifest["tools"]) == {"plain"}
        assert "delegated_composition_protocol" not in manifest
        assert "delegated_coding_tools" not in manifest
        assert "runner_binding_protocol" not in manifest


def test_conflicting_selected_graph_coding_declarations_refuse_before_io(tmp_path):
    runner = BorrowedRunner()
    graph = GraphWorkflowSpec("graph", [GraphNode("work", tool="coding_0")])
    with engine(
        tmp_path / "run.db", BindingCatalog(scope=Scope()), tools=registry(runner)
    ) as runtime:
        definition = submission_request(graph, None)["definition"]
        agent = submission_request(AgentSpec("a", "Work", ("coding_0",)), None)["definition"]
        declared = runtime._manifest(agent["steps"])
        altered = copy.deepcopy(declared)
        altered["delegated_coding_tools"]["coding_0"]["version"] = "forged"
        with pytest.raises(DefinitionMismatch):
            runtime._workflow.manifest(
                runtime._workflow.compile(definition), agent_manifests=[altered]
            )
    assert runner.calls == []


def test_bound_nested_direct_graph_keeps_actual_recursive_grant_without_agent_bindings(tmp_path):
    runner = BorrowedRunner()
    bound = BoundDefinition(
        TeamSpec(
            "outer", {"inner": GraphWorkflowSpec("graph", [GraphNode("work", tool="coding_0")])}
        ),
        {},
    )
    with engine(
        tmp_path / "run.db", BindingCatalog(scope=Scope()), tools=registry(runner)
    ) as runtime:
        manifest = runtime._bindings.manifest(unwrap_definition(bound.to_dict()))
        assert manifest["kernel"] == "local-bindings-19"
        assert manifest["agent_bindings"]["steps"] == {}
        assert set(manifest["delegated_coding_tools"]) == {"coding_0"}
        child = manifest["orchestration"]["members"]["inner"]
        assert child["kernel"] == "local-bindings-19"
        assert manifest["delegated_coding_tools"] == child["delegated_coding_tools"]
        assert all_step_manifests(manifest) == [manifest]


@pytest.mark.parametrize("selection", ["disabled", "other_resource"])
def test_complex_bound_selection_cannot_grant_disabled_or_replaced_runner(tmp_path, selection):
    runner, other = BorrowedRunner(), BorrowedRunner()
    catalog = BindingCatalog(scope=Scope())
    catalog.register("runner", "other", "1", other)
    choice = (
        BindingSelection.disabled()
        if selection == "disabled"
        else BindingSelection.ref("other", "1")
    )
    bound = BoundDefinition(
        TeamSpec("team", {"work": AgentSpec("worker", "Work", tools=("coding_0",))}),
        {"team/members/work": AgentBindingDescriptor(runner=choice)},
    )
    with engine(tmp_path / "run.db", catalog, tools=registry(runner)) as runtime:
        expected = AuthorizationDenied if selection == "disabled" else DefinitionMismatch
        with pytest.raises(expected):
            runtime._bindings.manifest(unwrap_definition(bound.to_dict()))
    assert runner.calls == other.calls == []
