import importlib.util
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, DAGNode, DAGProposal, DynamicWorkflowSpec, TeamSpec, ValueRef
from ralf_agent.errors import IdempotencyConflict, ValidationError
from ralf_agent.types import Scope, submission_request

from .test_temporal_engine import Provider, registry


def state(spec=None, budget=16):
    assert importlib.util.find_spec("ralf_agent.temporal_parent_state"), (
        "Missing distributed parent authority"
    )
    from ralf_agent.temporal_activities import TemporalRuntime
    from ralf_agent.temporal_parent_state import TemporalParentState

    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    spec = spec or TeamSpec("team", {"a": AgentSpec("a", "Answer")}, child_budget=8)
    return TemporalParentState(
        "parent",
        asdict(Scope()),
        "first",
        submission_request(spec, "task", budget=budget),
        runtime.orchestration_release,
    )


def observation(
    parent, call, *, revision=1, state="succeeded", result="answer", spent=1, quiet=True
):
    from ralf_agent.types import digest

    return {
        "scope": dict(parent.scope),
        "snapshot": {
            "run_id": call["run_id"],
            "state": state,
            "state_revision": revision,
            "result": result,
            "error": None,
            "pending": [],
            "actions": [],
            "consistency": "authoritative",
        },
        "manifest": parent.manifest,
        "release_digest": digest(
            {"definition": call["request"]["definition"], "manifest": parent.manifest}
        ),
        "budget": {
            "allowance": call["cap"],
            "spent": spent,
            "remaining": call["cap"] - spent,
            "reserved": 0,
            "unknown": 0,
            "reservations": [],
        },
        "workflow": {
            "quiescent": quiet,
            "remote_stop_confirmed": quiet,
            "evidence_ack_pending": False,
            "reconciliation_pending": False,
        },
    }


def test_selection_creates_stable_child_intent_and_escrow_before_dispatch():
    parent = state()
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    first = parent.next_calls()[0]
    assert first["request"]["input"] == "x" and parent.budget["reserved"] == 8
    assert parent.next_calls()[0] == first
    assert parent.snapshot()["state"] == "running"
    assert (
        parent.command(
            "first", {"kind": "submit", "scope": parent.scope, "request": parent.request}
        )["kind"]
        == "submit"
    )


def test_child_cap_is_settled_only_after_terminal_and_quiescent():
    parent = state()
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    call = parent.next_calls()[0]
    parent.observe(call["run_id"], observation(parent, call, quiet=False))
    assert parent.budget["reserved"] == 8
    parent.observe(call["run_id"], observation(parent, call, revision=2, quiet=True))
    assert parent.budget["reserved"] == 0 and parent.budget["spent"] == 1


def test_changed_same_revision_observation_cannot_settle_or_mutate():
    parent = state()
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    call = parent.next_calls()[0]
    parent.observe(call["run_id"], observation(parent, call, quiet=False))
    with pytest.raises(ValidationError):
        parent.observe(call["run_id"], observation(parent, call, quiet=True))
    assert parent.budget["reserved"] == 8 and not parent.quiescent


def test_invalid_child_output_does_not_release_escrow_or_mutate_evidence():
    parent = state(DynamicWorkflowSpec("dag", {"a": AgentSpec("a", "Answer")}, plan_mode="dag"))
    proposal = DAGProposal([DAGNode("one", "a", output_schema={"type": "integer"})])
    parent.accept_selection(proposal.to_dict())
    call = parent.next_calls()[0]
    with pytest.raises(ValidationError):
        parent.observe(call["run_id"], observation(parent, call, result="invalid"))
    assert parent.budget["reserved"] == 8 and not parent.quiescent
    assert parent.dag["nodes"]["one"]["state"] == "running"


def test_succeeded_but_nonquiescent_child_does_not_enable_successor():
    parent = state(
        DynamicWorkflowSpec(
            "dag", {"a": AgentSpec("a", "Answer")}, plan_mode="dag", max_concurrency=2
        )
    )
    parent.accept_selection(
        DAGProposal([DAGNode("one", "a"), DAGNode("two", "a", depends_on=("one",))]).to_dict()
    )
    call = parent.next_calls()[0]
    parent.mark_started(call["run_id"])
    parent.observe(call["run_id"], observation(parent, call, quiet=False))
    assert parent.dag["nodes"]["one"]["state"] == "running"
    assert parent.next_calls() == []


def test_unknown_child_evidence_is_visible_in_parent_budget():
    parent = state()
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    call = parent.next_calls()[0]
    value = observation(parent, call, state="outcome_unknown", quiet=False, spent=0)
    value["budget"].update(unknown=1, remaining=7)
    value["workflow"]["reconciliation_pending"] = True
    parent.observe(call["run_id"], value)
    assert parent.budget["unknown"] == 8 and parent.budget["reserved"] == 0


def test_planning_conclusion_is_terminal_without_dispatch():
    parent = state(DynamicWorkflowSpec("dag", {"a": AgentSpec("a", "Answer")}, plan_mode="dag"))
    parent.accept_selection({"status": "needs_input", "reason": "Specify the target"})
    assert parent.state == "succeeded" and parent.next_calls() == []


def test_patch_cannot_bypass_remaining_child_limit_after_replan():
    parent = state(
        DynamicWorkflowSpec(
            "dag", {"a": AgentSpec("a", "Answer")}, plan_mode="dag", max_steps=2, max_revisions=2
        )
    )
    parent.accept_selection(DAGProposal([DAGNode("one", "a")]).to_dict())
    call = parent.next_calls()[0]
    parent.observe(call["run_id"], observation(parent, call))
    parent.accept_verification({"status": "replan", "result": None})
    parent.accept_selection(DAGProposal([DAGNode("two", "a")]).to_dict())
    with pytest.raises(ValidationError):
        parent.patch(
            DAGProposal(
                [DAGNode("two", "a"), DAGNode("three", "a", depends_on=("two",))]
            ).to_dict(),
            1,
        )


def test_cancelled_parent_keeps_late_child_evidence_without_reopening():
    parent = state()
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    call = parent.next_calls()[0]
    payload = {"kind": "cancel", "scope": parent.scope}
    receipt = parent.command("stop", payload)
    assert parent.command("stop", payload) == receipt
    parent.observe(call["run_id"], observation(parent, call))
    assert parent.state == "cancelled" and parent.result is None and parent.next_calls() == []
    assert parent.budget["spent"] == 1


@pytest.mark.parametrize("mutation", ["identity", "scope", "overspent", "revision", "lazy"])
def test_invalid_observer_cannot_release_child_cap(mutation):
    parent = state()
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    call = parent.next_calls()[0]
    evidence = observation(parent, call)
    if mutation == "identity":
        evidence["snapshot"]["run_id"] = "other"
    if mutation == "scope":
        evidence["scope"]["principal"] = "other"
    if mutation == "overspent":
        evidence["budget"]["spent"] = 100
    if mutation == "revision":
        evidence["snapshot"]["state_revision"] = False
    if mutation == "lazy":
        evidence["snapshot"]["result"] = iter(())
    with pytest.raises(ValidationError):
        parent.observe(call["run_id"], evidence)
    assert parent.budget["reserved"] == 8


def test_dag_dependencies_bind_completed_child_output_and_patch_pending_only():
    parent = state(
        DynamicWorkflowSpec("dag", {"a": AgentSpec("a", "Answer")}, plan_mode="dag", child_budget=8)
    )
    proposal = DAGProposal(
        [DAGNode("one", "a"), DAGNode("two", "a", depends_on=("one",), input=ValueRef("one"))]
    )
    parent.accept_selection(proposal.to_dict())
    call = parent.next_calls()[0]
    bad = DAGProposal(
        [
            DAGNode("one", "a", input=ValueRef(default="changed")),
            DAGNode("two", "a", depends_on=("one",), input=ValueRef("one")),
        ]
    )
    with pytest.raises(ValidationError):
        parent.patch(bad.to_dict(), 0)
    parent.observe(call["run_id"], observation(parent, call, result={"bound": "evidence"}))
    following = parent.next_calls()[0]
    assert following["request"]["input"] == {"bound": "evidence"}
    with pytest.raises(ValidationError):
        parent.patch(proposal.to_dict(), 1)


def test_same_child_call_identity_rejects_changed_input():
    parent = state()
    proposal = {
        "calls": [{"id": "one", "member": "a", "input": "x"}],
        "done": False,
        "result": None,
    }
    parent.accept_selection(proposal)
    parent.next_calls()
    with pytest.raises(IdempotencyConflict):
        parent.accept_selection(
            {**proposal, "calls": [{"id": "one", "member": "a", "input": "changed"}]}
        )


def test_policy_validates_finite_limits_and_detaches_tool_allowlist():
    assert importlib.util.find_spec("ralf_agent.governance"), "Missing execution policy"
    from ralf_agent.governance import TemporalExecutionPolicy

    tools = ["read"]
    policy = TemporalExecutionPolicy(allowed_tools=tools)
    tools.append("write")
    view = policy.identity
    view["allowed_tools"].append("hidden")
    assert policy.identity["allowed_tools"] == ["read"]
    for options in [
        {"max_children": False},
        {"run_timeout_seconds": float("nan")},
        {"max_depth": 9},
        {"approval_timeout_seconds": 0},
    ]:
        with pytest.raises(ValidationError):
            TemporalExecutionPolicy(**options)


def test_patch_receipt_is_scoped_idempotent_and_preserves_dispatched_nodes():
    parent = state(DynamicWorkflowSpec("dag", {"a": AgentSpec("a", "Answer")}, plan_mode="dag"))
    proposal = DAGProposal([DAGNode("one", "a"), DAGNode("two", "a", depends_on=("one",))])
    parent.accept_selection(proposal.to_dict())
    parent.next_calls()
    patch = DAGProposal(
        [
            DAGNode("one", "a"),
            DAGNode("two", "a", depends_on=("one",)),
            DAGNode("three", "a", depends_on=("two",)),
        ]
    )
    payload = {
        "scope": parent.scope,
        "kind": "patch",
        "expected_plan_revision": 0,
        "proposal": patch.to_dict(),
    }
    receipt = parent.command("patch", payload)
    assert parent.command("patch", payload) == receipt
    assert parent.plan_revision == 1 and parent.dag["nodes"]["one"]["state"] == "running"


def test_nested_pending_approval_keeps_actual_leaf_run_identity():
    parent = state()
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    call = parent.next_calls()[0]
    value = observation(parent, call, state="waiting_approval", quiet=False)
    value["snapshot"]["pending"] = [
        {
            "run_id": "actual-leaf",
            "action_id": "action",
            "digest": "digest",
            "tool": "write",
            "arguments": {},
        }
    ]
    parent.observe(call["run_id"], value)
    assert parent.snapshot()["pending"][0]["run_id"] == "actual-leaf"
