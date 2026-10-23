"""Recursive declarations retain each original parent and physical obligation."""

import copy
from dataclasses import asdict
from types import SimpleNamespace

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
    WorkflowSpec,
)
from relf_agent.errors import RalfError, ValidationError
from relf_agent.governance import TemporalExecutionPolicy
from relf_agent.orchestration_types import ChildCall
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import normalize_request, request_release_digest
from relf_agent.temporal_coding_composition_protocol import publish, validate_topology
from relf_agent.temporal_coding_composition_state import (
    adopt_child_stop,
    coding_runner_keys,
    initialize,
    physical_stop_view,
    pin_child_execution,
    request_parent_stop,
    validate_child_link,
)
from relf_agent.temporal_parent_state import TemporalParentState
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request
from tests.test_temporal_coding_composition_state import bind_namespace
from tests.test_temporal_coding_orchestration_configuration import manifest as leaf_manifest
from tests.test_temporal_engine import Provider, registry


def selected_manifest():
    value = leaf_manifest()
    value["binding_protocol"] = 22
    value["coding_execution_protocol"]["version"] = 6
    return publish(value, SimpleNamespace(coding_execution=True, coding_composition=True))


def member(kind, *, tools=()):
    agent = AgentSpec("worker", "Work", tools=tools)
    if kind == "agent":
        return agent
    if kind == "sequence":
        return WorkflowSpec("steps", (agent, AgentSpec("review", "Review", tools=tools)))
    if kind == "graph":
        return GraphWorkflowSpec("graph", (GraphNode("work", agent=agent),))
    return (TeamSpec if kind == "team" else DynamicWorkflowSpec)("nested", {"worker": agent})


@pytest.mark.parametrize("root", [TeamSpec, DynamicWorkflowSpec])
@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic"])
def test_recursive_topology_accepts_every_existing_member_kind(root, kind):
    request = submission_request(root("root", {"nested": member(kind, tools=("coding",))}), "q")
    validate_topology(request, selected_manifest())


@pytest.mark.parametrize("kind", ["team", "dynamic", "graph"])
def test_recursive_topology_checks_each_nested_concurrency(kind):
    request = submission_request(TeamSpec("root", {"nested": member(kind)}), "q")
    request["definition"]["members"]["nested"]["max_concurrency"] = 3
    value = selected_manifest()
    value["execution_policy"] = TemporalExecutionPolicy(max_concurrency=2).identity
    with pytest.raises(ValidationError, match="concurrency"):
        validate_topology(request, value)


def test_recursive_topology_checks_nested_hidden_planner_grants():
    request = submission_request(TeamSpec("root", {"nested": member("dynamic")}), "q")
    value = selected_manifest()
    value["orchestration"]["planners"]["rule"]["agent"] = asdict(
        AgentSpec("planner", "Plan", tools=("coding",))
    )
    with pytest.raises(ValidationError, match="Hidden.*Coding"):
        validate_topology(request, value)


def test_recursive_sequence_effective_bindings_reserve_only_granted_runners():
    source = TeamSpec("root", {"nested": member("sequence", tools=("coding",))})
    disabled = AgentBindingDescriptor(
        tool_set=BindingSelection.disabled(), runner=BindingSelection.disabled()
    )
    request = normalize_request(
        submission_request(
            BoundDefinition(source, {"team/members/nested/sequence/steps/0": disabled}), "q"
        ),
        selected_manifest(),
    )
    validate_topology(request, selected_manifest())
    assert len(coding_runner_keys(request, selected_manifest())) == 1
    request["agent_bindings"]["team/members/nested/sequence/steps/1"] = disabled.to_dict()
    assert coding_runner_keys(request, selected_manifest()) == frozenset()


def parent(spec=None, *, source=None, call=None):
    host = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    request = (
        submission_request(spec or TeamSpec("root", {"nested": member("team")}), "q", budget=64)
        if call is None
        else call["request"]
    )
    state = TemporalParentState(
        "root" if call is None else call["run_id"],
        asdict(Scope()),
        "submit" if call is None else call["command_id"],
        request,
        host.orchestration_release,
        "root-epoch" if call is None else "nested-epoch",
        0 if call is None else call["depth"],
    )
    state.manifest.update(
        binding_protocol=23,
        coding_composition_protocol={"version": 7, "topology": "bounded-recursive-orchestration"},
    )
    if source is not None:
        state.manifest = copy.deepcopy(source.manifest)
    state.release_digest = request_release_digest(state.request, state.manifest)
    initialize(state, namespace="test")
    bind_namespace(state)
    if call is not None:
        validate_child_link(
            state,
            namespace="test",
            parent_namespace="test",
            parent_run_id=source.run_id,
            parent_epoch=source.epoch,
            original_epoch=state.epoch,
        )
    return state


def start(parent_state, call, child):
    entry = next(c for c in parent_state.children if c["run_id"] == call["run_id"])
    entry["dispatch_started"] = True
    parent_state.mark_started(call["run_id"])
    pin_child_execution(parent_state, call["run_id"], physical_stop_view(child))


def leaf(source, call):
    host = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    child = TemporalRunState(
        call["run_id"],
        source.scope,
        call["command_id"],
        call["request"],
        host.manifest,
        "leaf-epoch",
    )
    child.manifest = copy.deepcopy(source.manifest)
    child.release_digest = request_release_digest(child.request, child.manifest)
    initialize(child, namespace="test")
    validate_child_link(
        child,
        namespace="test",
        parent_namespace="test",
        parent_run_id=source.run_id,
        parent_epoch=source.epoch,
        original_epoch=child.epoch,
    )
    return child


def test_sequence_member_retains_one_original_run_and_full_step_projection():
    root = parent(TeamSpec("root", {"nested": member("sequence")}))
    call = root.delegate(ChildCall("step", "nested", "q"))
    child = leaf(root, call)
    start(root, call, child)
    assert child.request["definition"]["kind"] == "sequence"
    assert [s["name"] for s in child.request["definition"]["steps"]] == ["worker", "review"]
    assert child.request["coding_parent"]["depth"] == 1
    assert root.budget["reserved"] == 8


def test_nested_stop_is_adopted_one_immediate_edge_at_a_time():
    root = parent()
    outer = root.delegate(ChildCall("outer", "nested", "q"))
    nested = parent(source=root, call=outer)
    start(root, outer, nested)
    inner = nested.delegate(ChildCall("inner", "worker", "q"))
    child = leaf(nested, inner)
    start(nested, inner, child)
    assert inner["request"]["coding_parent"]["depth"] == 2
    assert inner["request"]["coding_parent"]["parent_run_id"] == nested.run_id
    request_parent_stop(root, terminal_state="cancelled", reason={"code": "cancel"})
    request_parent_stop(nested, terminal_state="cancelled", reason={"code": "cancel"})
    assert not physical_stop_view(root)["physical_stopped"]
    assert not physical_stop_view(nested)["physical_stopped"]
    child.state = "cancelled"
    proof = physical_stop_view(child)
    with pytest.raises(RalfError):
        adopt_child_stop(root, outer["run_id"], proof)
    adopt_child_stop(nested, inner["run_id"], proof)
    assert physical_stop_view(nested)["physical_stopped"]
    assert not physical_stop_view(root)["physical_stopped"]
    adopt_child_stop(root, outer["run_id"], physical_stop_view(nested))
    assert physical_stop_view(root)["physical_stopped"]


def test_nested_child_depth_cannot_exceed_policy_before_cap_reservation():
    root = parent()
    root.policy = TemporalExecutionPolicy(max_depth=1)
    root.manifest["execution_policy"] = root.policy.identity
    with pytest.raises(RalfError, match="depth"):
        root.delegate(ChildCall("outer", "nested", "q"))
    assert root.children == [] and root.budget["reserved"] == 0


def test_parent_link_depth_cannot_disagree_with_original_sdk_parent_state():
    root = parent()
    outer = root.delegate(ChildCall("outer", "nested", "q"))
    nested = parent(source=root, call=outer)
    nested.depth = 2
    with pytest.raises(RalfError, match="depth"):
        validate_child_link(
            nested,
            namespace="test",
            parent_namespace="test",
            parent_run_id=root.run_id,
            parent_epoch=root.epoch,
            original_epoch=nested.epoch,
        )


def test_nested_definition_depth_is_checked_before_any_runner_selection():
    spec = TeamSpec("outer", {"nested": TeamSpec("inner", {"worker": member("agent")})})
    value = selected_manifest()
    value["execution_policy"] = TemporalExecutionPolicy(max_depth=2).identity
    with pytest.raises(ValidationError, match="depth"):
        validate_topology(submission_request(spec, "q"), value)


def test_original_root_sdk_execution_cannot_claim_nested_depth_without_a_parent():
    root = parent()
    root.depth = 1
    with pytest.raises(RalfError, match="depth"):
        validate_child_link(
            root,
            namespace="test",
            parent_namespace=None,
            parent_run_id=None,
            parent_epoch=None,
            original_epoch=root.epoch,
        )


@pytest.mark.parametrize("binding,version", [(12, 1), (13, 2), (15, 3), (17, 4), (19, 5), (21, 6)])
def test_previous_history_fixtures_cannot_gain_recursive_member_permissions(binding, version):
    root = parent(TeamSpec("root", {"nested": member("sequence")}))
    root.manifest.update(binding_protocol=binding, coding_composition_protocol={"version": version})
    with pytest.raises(RalfError):
        root.delegate(ChildCall("outer", "nested", "q"))
    assert root.children == [] and root.budget["reserved"] == 0


def test_nested_hidden_verifier_cannot_receive_a_coding_grant():
    request = submission_request(TeamSpec("root", {"nested": member("team")}), "q")
    request["definition"]["members"]["nested"]["completion_policy"] = "policy"
    value = selected_manifest()
    value["parent_completion_policies"] = {
        "policy": {
            "effective_agent_release": {
                "definition": submission_request(
                    AgentSpec("verifier", "Verify", tools=("coding",)), "q"
                )["definition"],
                "agent_bindings": {},
            }
        }
    }
    with pytest.raises(ValidationError, match="Hidden.*Coding"):
        validate_topology(request, value)


def test_nested_subtree_holds_shared_runner_until_its_entire_physical_closure():
    root = parent(
        TeamSpec(
            "root",
            {
                "nested": member("team", tools=("coding",)),
                "peer": member("agent", tools=("coding",)),
            },
            max_concurrency=2,
        )
    )
    root.manifest = selected_manifest()
    call = root.delegate(ChildCall("outer", "nested", "q"))
    # A nested child retains its union of effective Runner resources even when
    # finance has settled; its descendants' physical proof is still absent.
    root.children[0]["settled"] = True
    root.queue = [ChildCall("peer", "peer", "q").to_dict()]
    root.stage = "execute"
    assert root.next_calls() == []
    assert len(root.children) == 1 and root.queue[0]["member"] == "peer"
    assert call["request"]["coding_parent"]["member"] == "nested"


def test_original_immediate_child_proof_cannot_change_accepted_depth():
    root = parent()
    outer = root.delegate(ChildCall("outer", "nested", "q"))
    nested = parent(source=root, call=outer)
    start(root, outer, nested)
    nested.state = "cancelled"
    root.children[0]["depth"] = 2
    with pytest.raises(RalfError, match="depth"):
        adopt_child_stop(root, outer["run_id"], physical_stop_view(nested))
