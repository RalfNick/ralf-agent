"""Pure selected17 original child ownership for bounded Team/Dynamic parents."""

import copy
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    Scope,
    TeamSpec,
    ValueRef,
)
from ralf_agent.dag_planning import DAGNode, DAGProposal
from ralf_agent.errors import RalfError
from ralf_agent.orchestration_types import ChildCall, TeamRequest, TeamSelection
from ralf_agent.teams import RouterTeam, SequentialTeam, SupervisorTeam
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import request_release_digest
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.types import digest, submission_request
from tests.test_temporal_coding_composition_configuration import composition_manifest
from tests.test_temporal_coding_composition_state import bind_namespace, composition
from tests.test_temporal_coding_parallel_state import observe, start
from tests.test_temporal_engine import Provider, registry


def parent(kind="dynamic", *, concurrency=2, strategy="sequential", disabled=False):
    members = {
        "writer": AgentSpec("actual-writer", "write", tools=("coding",)),
        "alias": AgentSpec("actual-alias", "write", tools=("alias",)),
        "reader": AgentSpec("actual-reader", "read", tools=("other",)),
    }
    if kind == "team":
        definition = TeamSpec(
            "bounded-team", members, strategy=strategy, max_concurrency=concurrency
        )
    elif kind == "graph":
        definition = GraphWorkflowSpec(
            "bounded-graph",
            [GraphNode("writer", agent=members["writer"])],
            max_concurrency=concurrency,
        )
    else:
        definition = DynamicWorkflowSpec(
            "bounded-dynamic",
            members,
            plan_mode="dag",
            max_concurrency=concurrency,
            max_steps=16,
            max_revisions=3,
        )
    host = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    state = TemporalParentState(
        "root",
        asdict(Scope()),
        "submit",
        submission_request(definition, "task", budget=64),
        host.orchestration_release,
        "root-epoch",
    )
    state.manifest.update(composition_manifest())
    state.manifest["tools"]["alias"] = copy.deepcopy(state.manifest["tools"]["coding"])
    state.manifest["coding_execution_protocol"]["tools"]["alias"] = copy.deepcopy(
        state.manifest["coding_execution_protocol"]["tools"]["coding"]
    )
    if disabled:
        state.request["agent_bindings"] = {
            f"{kind}/members/writer": AgentBindingDescriptor(
                tool_set=BindingSelection.disabled(), runner=BindingSelection.disabled()
            ).to_dict(),
        }
    state.release_digest = request_release_digest(state.request, state.manifest)
    assert composition().enabled(state.manifest), "selected17 History composition is missing"
    composition().initialize(state, namespace="test")
    bind_namespace(state)
    return state


def plan(state, nodes=None):
    proposal = DAGProposal(
        nodes
        or [
            DAGNode("different-node-id", "writer"),
            DAGNode("blocked-alias-id", "alias"),
            DAGNode("independent-node-id", "reader"),
        ]
    )
    state.accept_selection(proposal.to_dict())
    return proposal


def settle(state, call, child, *, result="done", proof=True):
    child.state, child.result = "succeeded", result
    child._emit("run_succeeded")
    if proof:
        return observe(state, call, child)
    state.observe(call["run_id"], {"scope": state.scope, **child.diagnostics()})
    return composition().physical_stop_view(child)


@pytest.mark.parametrize("kind", ["team", "dynamic", "graph"])
def test_selected17_namespace_and_complete_original_links_cover_each_parent_kind(kind):
    state = parent(kind)
    if kind == "team":
        state.accept_selection(TeamSelection([ChildCall("step", "writer", "task")]).to_dict())
    elif kind == "dynamic":
        plan(state, [DAGNode("step", "writer")])
    call = state.next_calls()[0]
    link = call["request"]["coding_parent"]
    assert link["member"] == "writer" and link["planning_revision"] == 0
    assert link["call_id"] == call["id"] and link["cap"] == call["cap"]
    assert call["planning_revision"] == 0
    assert call["child_request_digest"] == digest(call["request"])
    assert link["child_projection_digest"] == digest(
        {name: value for name, value in call["request"].items() if name != "coding_parent"}
    )


def test_dynamic_runner_projection_uses_real_member_and_binding_not_placeholder_node():
    state = parent()
    plan(state)
    calls = state.next_calls()
    assert [call["member"] for call in calls] == ["writer", "reader"]
    assert [call["request"]["definition"]["steps"][0]["name"] for call in calls] == [
        "actual-writer",
        "actual-reader",
    ]
    assert state.dag["nodes"]["blocked-alias-id"]["state"] == "pending"
    assert state.budget["reserved"] == 16 and len(state.children) == 2
    assert state.next_calls() == calls and state.budget["reserved"] == 16


def test_dynamic_disabled_actual_member_binding_releases_runner_alias_capacity():
    state = parent(disabled=True)
    plan(state, [DAGNode("unrelated-node", "writer"), DAGNode("alias-node", "alias")])
    calls = state.next_calls()
    assert [call["member"] for call in calls] == ["writer", "alias"]
    assert calls[0]["request"]["agent_bindings"]["agent"]["tool_set"]["mode"] == "disabled"


def test_team_stable_queue_skips_conflict_without_reserving_it_and_runs_later_independent():
    state = parent("team")
    state.accept_selection(
        TeamSelection(
            [
                ChildCall("first", "writer", "a"),
                ChildCall("second", "alias", "b"),
                ChildCall("third", "reader", "c"),
            ]
        ).to_dict()
    )
    calls = state.next_calls()
    assert [call["member"] for call in calls] == ["writer", "reader"]
    assert state.queue == [{"id": "second", "member": "alias", "input": "b"}]
    assert state.budget["reserved"] == 16 and len(state.children) == 2
    first, independent = [start(state, call) for call in calls]
    assert state.next_calls() == []
    settle(state, calls[0], first)
    assert [call["member"] for call in state.next_calls()] == ["alias"]
    assert independent.state == "queued" and len(state.children) == 3


@pytest.mark.parametrize("strategy", [SequentialTeam(), RouterTeam(), SupervisorTeam()])
def test_builtin_team_selection_only_advances_after_both_settlement_and_original_stop(strategy):
    name = {SequentialTeam: "sequential", RouterTeam: "router", SupervisorTeam: "supervisor"}[
        type(strategy)
    ]
    state = parent("team", strategy=name)
    config = {"routes": {"chosen": "writer"}} if name == "router" else {"supervisor": "reader"}
    task = {"route": "chosen"}
    request = TeamRequest(task, state.definition["member_order"], {}, config)
    state.accept_selection(strategy.select(request).to_dict())
    calls = state.next_calls()
    child = start(state, calls[0])
    proof = settle(state, calls[0], child, proof=False)
    assert state.children[0]["settled"] is True
    assert state.children_quiescent is False
    with pytest.raises(RalfError):
        state.accept_selection(TeamSelection(done=True, result="premature").to_dict())
    assert state.result is None
    composition().adopt_child_stop(state, calls[0]["run_id"], proof)
    assert state.results["writer"] == "done"


def test_dynamic_settled_without_stop_does_not_unlock_dependency_verifier_or_replan():
    state = parent()
    plan(
        state,
        [
            DAGNode("first", "writer"),
            DAGNode("dependent", "reader", depends_on=("first",), input=ValueRef("first")),
        ],
    )
    call = state.next_calls()[0]
    child = start(state, call)
    proof = settle(state, call, child, proof=False)
    assert state.children[0]["settled"] and not state.children_quiescent
    assert state.dag["nodes"]["first"]["state"] == "running"
    assert state.next_calls() == [] and state.stage == "execute"
    with pytest.raises(RalfError):
        state.accept_verification({"status": "replan"})
    assert state.planning_revision == 0
    composition().adopt_child_stop(state, call["run_id"], proof)
    next_call = state.next_calls()[0]
    assert next_call["member"] == "reader" and next_call["input"] == "done"


def test_replan_preserves_original_children_and_late_old_output_proof_cannot_replace_current_dag():
    state = parent(concurrency=1)
    plan(state, [DAGNode("same-node", "writer")])
    original = state.next_calls()[0]
    old_child = start(state, original)
    settle(state, original, old_child, result="original-result")
    assert state.next_calls() == [] and state.stage == "verify"
    frozen = copy.deepcopy(state.children[0])
    state.accept_verification({"status": "replan"})
    assert state.planning_revision == 1 and state.stage == "plan" and len(state.children) == 1
    plan(state, [DAGNode("same-node", "writer")])
    current = state.next_calls()[0]
    assert current["request"]["coding_parent"]["planning_revision"] == 1
    assert current["id"] == "1:same-node" and original["id"] == "0:same-node"
    current_child = start(state, current)
    settle(state, current, current_child, result="current-result")
    old_child.result = "late-old-result"
    old_child._emit("late_receipt")
    proof = observe(state, original, old_child)
    assert proof["request"]["coding_parent"]["planning_revision"] == 0
    assert state.results["writer"] == "current-result"
    assert state.dag["nodes"]["same-node"]["result"] == "current-result"
    for name in (
        "id",
        "request",
        "child_request_digest",
        "child_execution",
        "cap",
        "planning_revision",
    ):
        assert state.children[0][name] == frozen[name]


def test_dynamic_patch_only_changes_pending_nodes_and_preserves_all_dispatched_intents():
    state = parent(concurrency=1)
    original_plan = plan(
        state, [DAGNode("first", "writer"), DAGNode("future", "alias", depends_on=("first",))]
    )
    call = state.next_calls()[0]
    start(state, call)
    original = copy.deepcopy(state.children)
    changed = DAGProposal(
        [
            DAGNode.from_dict(original_plan.nodes[0]),
            DAGNode("future", "reader", depends_on=("first",)),
        ]
    )
    state.patch(changed.to_dict(), state.plan_revision)
    assert state.children == original
    assert state.dag["nodes"]["first"]["state"] == "running"
    invalid = DAGProposal(
        [DAGNode("first", "reader"), DAGNode("future", "reader", depends_on=("first",))]
    )
    with pytest.raises(RalfError):
        state.patch(invalid.to_dict(), state.plan_revision)
    assert state.children == original


def test_stop_intent_blocks_dynamic_patch_selection_and_replan_without_new_cap():
    state = parent()
    proposal = plan(state, [DAGNode("first", "writer")])
    call = state.next_calls()[0]
    start(state, call)
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    before = copy.deepcopy(state.children), copy.deepcopy(state.budget), state.planning_revision
    for operation in (
        lambda: state.patch(proposal.to_dict(), state.plan_revision),
        lambda: state.accept_selection(proposal.to_dict()),
        lambda: state.accept_verification({"status": "replan"}),
    ):
        with pytest.raises(RalfError):
            operation()
    assert state.next_calls() == []
    assert (state.children, state.budget, state.planning_revision) == before


def test_static_graph_patch_remains_refused_under_current_orchestration_protocol():
    state = parent("graph")
    with pytest.raises(RalfError):
        state.patch(DAGProposal([DAGNode("writer", "writer")]).to_dict(), state.plan_revision)


def enable_hidden_verifier(state):
    state.definition["completion_policy"] = "fixed-verifier"
    state.parent_completion_enabled = True
    state.parent_completion_pending = {"id": "original-verdict"}
    state.manifest["parent_completion_protocol"] = 1
    state.manifest["parent_completion_policies"] = {
        "fixed-verifier": {
            "identity": {"verifier_budget": 3},
            "effective_agent_release": {
                "definition": submission_request(AgentSpec("fixed-verifier", "verify"), None)[
                    "definition"
                ],
                "agent_bindings": {"agent": AgentBindingDescriptor().to_dict()},
            },
        },
    }
    state.release_digest = request_release_digest(state.request, state.manifest)


@pytest.mark.parametrize("kind", ["team", "dynamic", "graph"])
def test_original_hidden_verifier_projects_fixed_agent_and_keeps_stop_obligation(kind):
    state = parent(kind)
    enable_hidden_verifier(state)
    call = state.delegate(ChildCall("verdict", "@verifier", {"source": "original"}), verifier=True)
    assert call["request"]["definition"]["kind"] == "agent"
    assert call["request"]["definition"]["steps"][0]["name"] == "fixed-verifier"
    assert call["request"]["definition"]["steps"][0]["tools"] == []
    assert call["request"]["coding_parent"]["member"] == "@verifier"
    assert call["cap"] == 3 and not state.children_quiescent
    start(state, call)
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    assert (
        state.state == "cancelling"
        and not composition().physical_stop_view(state)["physical_stopped"]
    )


@pytest.mark.parametrize("kind,call_id", [("team", "planner"), ("dynamic", "invented")])
def test_hidden_planner_cannot_be_selected_outside_original_dynamic_slot(kind, call_id):
    state = parent(kind)
    if kind == "team":
        # An unrelated registered planner must not create a Team child slot.
        state.definition["planner"] = "dag-rule"
    state.manifest["orchestration"]["planners"]["dag-rule"]["agent"] = asdict(
        AgentSpec("planner", "plan")
    )
    with pytest.raises(RalfError):
        state.delegate(ChildCall(call_id, "@planner", {}))
    assert state.children == [] and state.budget["reserved"] == 0


def test_same_member_late_first_call_cannot_replace_latest_original_result():
    state = parent("team", concurrency=1)
    state.accept_selection(
        TeamSelection(
            [
                ChildCall("first", "writer", "a"),
                ChildCall("second", "writer", "b"),
            ]
        ).to_dict()
    )
    first = state.next_calls()[0]
    first_child = start(state, first)
    settle(state, first, first_child, result="first-result")
    second = state.next_calls()[0]
    second_child = start(state, second)
    settle(state, second, second_child, result="second-result")
    first_child.result = "late-first-result"
    first_child._emit("late_receipt")
    observe(state, first, first_child)
    assert state.results["writer"] == "second-result"
    assert state.children[0]["snapshot"]["result"] == "late-first-result"
    assert state.children[0]["adopted_result"] == "first-result"


def test_replanning_input_keeps_original_adopted_result_after_late_diagnostics():
    state = parent(concurrency=1)
    plan(state, [DAGNode("same-node", "writer")])
    original = state.next_calls()[0]
    child = start(state, original)
    settle(state, original, child, result="original-result")
    assert state.next_calls() == [] and state.stage == "verify"
    state.accept_verification({"status": "replan"})
    child.result = "late-diagnostic-result"
    child._emit("late_receipt")
    observe(state, original, child)
    assert state.children[0]["adopted_result"] == "original-result"
    assert state.planning_request()["results"][0]["result"] == "original-result"


def test_completion_source_keeps_original_adopted_result_after_late_diagnostics():
    from ralf_agent.temporal_parent_completion_state import source
    from tests.test_temporal_parent_completion import setup

    state = parent("team", concurrency=1)
    runtime, _, _, _ = setup()
    state.definition["completion_policy"] = "checked"
    state.manifest["parent_completion_policies"] = runtime.orchestration_release[
        "parent_completion_policies"
    ]
    state.release_digest = request_release_digest(state.request, state.manifest)
    state.accept_selection(
        TeamSelection([ChildCall("first", "writer", "original-input")]).to_dict()
    )
    call = state.next_calls()[0]
    child = start(state, call)
    messages = [
        {"role": "system", "content": "write"},
        {"role": "user", "content": "original-input"},
    ]
    child.actions.append(
        {
            "id": "final-model",
            "kind": "model",
            "node": 0,
            "status": "completed",
            "dispatch_request": {"messages": messages},
            "response": {
                "output": "original-result",
                "tool_calls": [],
                "decision_evidence": {"prepared_request": {"messages": messages, "tools": []}},
            },
        }
    )
    settle(state, call, child, result="original-result")
    child.result = "late-diagnostic-result"
    child._emit("late_receipt")
    observe(state, call, child)
    current = source(state, state.results["writer"])
    assert current["candidate"] == "original-result"
    assert current["children"][0]["result"] == "original-result"
    assert current["children"][0]["result_digest"] == digest("original-result")


def test_hidden_verifier_delayed_stop_keeps_proposal_and_defers_interpretation():
    from tests.test_temporal_parent_completion import setup

    state = parent("team", concurrency=1)
    runtime, _, _, _ = setup(stage=True)
    state.definition["completion_policy"] = "checked"
    state.manifest["parent_completion_policies"] = runtime.orchestration_release[
        "parent_completion_policies"
    ]
    state.parent_completion_enabled = True
    state.manifest["parent_completion_protocol"] = 1
    state.release_digest = request_release_digest(state.request, state.manifest)
    state.accept_selection(TeamSelection([ChildCall("first", "writer", "input")]).to_dict())
    worker = state.next_calls()[0]
    child = start(state, worker)
    messages = [{"role": "system", "content": "write"}, {"role": "user", "content": "input"}]
    child.actions.append(
        {
            "id": "final-model",
            "kind": "model",
            "node": 0,
            "status": "completed",
            "dispatch_request": {"messages": messages},
            "response": {
                "output": "original",
                "tool_calls": [],
                "decision_evidence": {"prepared_request": {"messages": messages, "tools": []}},
            },
        }
    )
    settle(state, worker, child, result="original")
    state.accept_selection(TeamSelection(done=True, result="original").to_dict())
    action, request = state.next_parent_completion_operation()
    verdict = {"status": "accept", "feedback": None, "evidence_ids": []}
    state.accept_parent_completion(
        action["id"],
        {
            "ok": True,
            "request_digest": digest(request),
            "gate_verdict": verdict,
            "prepared_input": request["source"],
        },
    )
    verifier = next(c for c in state.next_calls() if c["member"] == "@verifier")
    verification = start(state, verifier)
    proof = settle(state, verifier, verification, result=verdict, proof=False)
    stage = state.parent_completion_stages["r0"]
    assert stage["status"] == "proposal_received"
    assert stage["received_proposal"] == verdict
    assert not state.children_quiescent
    before = len(state.actions)
    assert state.next_parent_completion_operation() is None
    assert len(state.actions) == before and state.composition_stop_intent is None
    composition().adopt_child_stop(state, verifier["run_id"], proof)
    action, request = state.next_parent_completion_operation()
    assert request["mode"] == "interpret" and request["output"] == verdict
    state.accept_parent_completion(
        action["id"],
        {
            "ok": True,
            "request_digest": digest(request),
            "verdict": verdict,
        },
    )
    assert state.state == "succeeded" and state.result == "original"
    assert state.composition_stop_intent is None


def test_no_start_marker_alone_cannot_release_unsettled_parent_capacity():
    state = parent("team")
    state.accept_selection(TeamSelection([ChildCall("first", "writer", "task")]).to_dict())
    state.next_calls()
    state.children[0]["physical_no_start"] = True
    assert state.children[0]["settled"] is False
    assert state.children_quiescent is False


@pytest.mark.parametrize("stage", ["select", "plan", "verify"])
def test_workflow_stage_activity_waits_for_original_stop_after_financial_settlement(
    stage, monkeypatch
):
    import asyncio

    from ralf_agent import temporal_parent_workflow as scheduler

    state = parent("team" if stage == "select" else "dynamic")
    if state.kind == "team":
        state.accept_selection(TeamSelection([ChildCall("first", "writer", "task")]).to_dict())
    else:
        plan(state, [DAGNode("first", "writer")])
    call = state.next_calls()[0]
    child = start(state, call)
    settle(state, call, child, proof=False)
    state.stage = stage
    state.composition_admission = {
        "namespace": state.composition_namespace,
        "execution_epoch": state.epoch,
        "admitted": True,
    }
    instance = object.__new__(scheduler.TemporalParentWorkflow)
    instance.state, instance.wake_revision = state, 0
    selections = []

    async def control(mode, original, activity_timeout):
        assert mode == "observe" and original["run_id"] == call["run_id"]
        return {"ok": False, "code": "original-proof-unavailable"}

    async def activity(name, request, activity_timeout):
        selections.append(name)
        pytest.fail("Stage Activity bypassed original child physical closure")

    async def notify():
        return None

    class SchedulerPaused(Exception):
        pass

    async def wait(predicate, **options):
        assert "timeout" in options and not state.children_quiescent
        raise SchedulerPaused

    instance._control, instance._activity, instance._notify_session = control, activity, notify
    monkeypatch.setattr(scheduler.workflow, "patched", lambda marker: True)
    monkeypatch.setattr(scheduler.workflow, "wait_condition", wait)
    with pytest.raises(SchedulerPaused):
        asyncio.run(instance.run({"activity_timeout": 5, "command_id": "submit"}))
    assert selections == [] and state.planning_revision == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "0:foreign"),
        ("member", "alias"),
        ("planning_revision", 1),
        ("command_id", "foreign"),
    ],
)
def test_original_physical_proof_must_match_each_frozen_child_link_field(field, value):
    state = parent()
    plan(state, [DAGNode("first", "writer")])
    call = state.next_calls()[0]
    child = start(state, call)
    child.state = "succeeded"
    proof = composition().physical_stop_view(child)
    state.children[0][field] = value
    with pytest.raises(RalfError):
        composition().adopt_child_stop(state, call["run_id"], proof)
    assert "physical_stop_proof" not in state.children[0]


def test_original_dynamic_planner_links_fixed_non_coding_agent_and_blocks_next_stage_until_stop():
    state = parent()
    state.manifest["orchestration"]["planners"]["dag-rule"]["agent"] = asdict(
        AgentSpec("fixed-planner", "plan")
    )
    state.release_digest = request_release_digest(state.request, state.manifest)
    call = state.delegate(ChildCall("planner", "@planner", state.planning_request()))
    assert call["request"]["definition"]["steps"][0]["name"] == "fixed-planner"
    assert call["request"]["definition"]["steps"][0]["tools"] == []
    assert call["request"]["coding_parent"]["member"] == "@planner"
    child = start(state, call)
    proof = settle(state, call, child, proof=False)
    with pytest.raises(RalfError):
        plan(state, [DAGNode("business", "writer")])
    composition().adopt_child_stop(state, call["run_id"], proof)
    plan(state, [DAGNode("business", "writer")])
    assert [c["member"] for c in state.next_calls()] == ["writer"]
