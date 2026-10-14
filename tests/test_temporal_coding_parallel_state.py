"""Bounded original Agent children, independent capacity and stop obligations."""

import copy
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, InputMap, Scope, ValueRef
from ralf_agent.errors import RalfError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.types import submission_request
from tests.test_temporal_coding_composition_state import bind_namespace, composition, leaf
from tests.test_temporal_engine import Provider, registry


def parent(*, join=True, concurrency=2, budget=32, third=False, tools_a=(), tools_b=(), tools_c=()):
    host = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    nodes = [
        GraphNode("a", agent=AgentSpec("a", "answer", tools=tools_a)),
        GraphNode("b", agent=AgentSpec("b", "answer", tools=tools_b)),
    ]
    if third:
        nodes.append(GraphNode("c", agent=AgentSpec("c", "answer", tools=tools_c)))
    if join:
        nodes.append(
            GraphNode(
                "join",
                agent=AgentSpec("join", "answer"),
                depends_on=("a", "b"),
                input=InputMap({"a": ValueRef("a"), "b": ValueRef("b")}),
            )
        )
    graph = GraphWorkflowSpec("parallel", nodes, max_concurrency=concurrency)
    state = TemporalParentState(
        "root",
        asdict(Scope()),
        "submit",
        submission_request(graph, "task", budget=budget),
        host.orchestration_release,
        "root-epoch",
    )
    # Isolate the pure History gates from publication/factory integration tests.
    state.manifest.update(
        kernel="temporal-3",
        binding_protocol=13,
        coding_composition_protocol={"version": 2, "topology": "bounded-agent-graph"},
    )
    composition().initialize(state, namespace="test")
    return state


def start(state, call):
    entry = next(c for c in state.children if c["run_id"] == call["run_id"])
    entry["dispatch_started"] = True
    state.mark_started(call["run_id"])
    child = leaf(state, call)
    child.epoch = "child-epoch-" + call["member"]
    child.composition_original_epoch = child.epoch
    composition().pin_child_execution(
        state, call["run_id"], composition().physical_stop_view(child)
    )
    return child


def observe(state, call, child):
    proof = composition().physical_stop_view(child)
    composition().adopt_child_stop(state, call["run_id"], proof)
    state.observe(call["run_id"], {"scope": state.scope, **child.diagnostics()})
    return proof


def resource_parent(*, tools_a=("coding",), tools_b=("coding",), exclude_a=False, third=False):
    from ralf_agent import AgentBindingDescriptor, BindingSelection
    from tests.test_temporal_coding_composition_configuration import composition_manifest

    state = parent(
        join=False,
        tools_a=tools_a,
        tools_b=tools_b,
        third=third,
        tools_c=("third",) if third else (),
    )
    selected = composition_manifest()
    state.manifest.update(selected)
    # A different Tool name can refer to the exact same original Runner.
    state.manifest["tools"]["alias"] = copy.deepcopy(state.manifest["tools"]["coding"])
    state.manifest["coding_execution_protocol"]["tools"]["alias"] = copy.deepcopy(
        state.manifest["coding_execution_protocol"]["tools"]["coding"]
    )
    state.manifest["tools"]["third"] = copy.deepcopy(state.manifest["tools"]["other"])
    third_runner = state.manifest["tools"]["third"]["config"]["delegated_runner"]["runner"]
    third_runner["resource"] = "third"
    state.manifest["coding_execution_protocol"]["tools"]["third"] = copy.deepcopy(
        state.manifest["coding_execution_protocol"]["tools"]["other"]
    )
    state.manifest["coding_execution_protocol"]["tools"]["third"]["runner"] = copy.deepcopy(
        third_runner
    )
    if exclude_a:
        state.request["agent_bindings"] = {
            "graph/nodes/a": AgentBindingDescriptor(
                tool_set=BindingSelection.disabled(), runner=BindingSelection.disabled()
            ).to_dict(),
        }
    bind_namespace(state)
    return state


def test_shared_runner_backpressure_records_only_one_original_child_intent():
    state = resource_parent()
    first = state.next_calls()
    assert [c["member"] for c in first] == ["a"]
    assert state.next_calls() == first
    assert len(state.children) == 1 and state.budget["reserved"] == 8
    start(state, first[0])
    assert state.next_calls() == [] and len(state.children) == 1


def test_distinct_original_runners_keep_two_children_concurrent():
    state = resource_parent(tools_b=("other",))
    assert [c["member"] for c in state.next_calls()] == ["a", "b"]
    assert len(state.children) == 2 and state.budget["reserved"] == 16


def test_blocked_shared_runner_candidate_does_not_hide_later_independent_ready_node():
    state = resource_parent(third=True)
    assert [c["member"] for c in state.next_calls()] == ["a", "c"]
    assert state.dag["nodes"]["b"]["state"] == "pending"
    assert len(state.children) == 2 and state.budget["reserved"] == 16


def test_tool_aliases_for_one_original_runner_share_the_same_capacity():
    state = resource_parent(tools_a=("coding", "alias"), tools_b=("alias",))
    assert [c["member"] for c in state.next_calls()] == ["a"]
    assert len(state.children) == 1


def test_effectively_disabled_coding_grant_does_not_occupy_registered_runner():
    state = resource_parent(exclude_a=True)
    calls = state.next_calls()
    assert [c["member"] for c in calls] == ["a", "b"]
    assert calls[0]["request"]["agent_bindings"]["agent"]["tool_set"]["mode"] == "disabled"
    assert state.budget["reserved"] == 16


def test_shared_runner_waits_for_normal_settlement_and_original_physical_proof():
    state = resource_parent()
    first = state.next_calls()[0]
    child = start(state, first)
    composition().adopt_child_stop(state, first["run_id"], composition().physical_stop_view(child))
    child.state, child.result = "succeeded", "result-a"
    child._emit("run_succeeded")
    # Financial diagnostics alone do not prove the original actual owner ended.
    state.observe(first["run_id"], {"scope": state.scope, **child.diagnostics()})
    assert state.children[0]["settled"] is True
    assert state.children[0]["physical_stop_proof"]["physical_stopped"] is False
    assert state.next_calls() == [] and len(state.children) == 1
    composition().adopt_child_stop(state, first["run_id"], composition().physical_stop_view(child))
    assert [c["member"] for c in state.next_calls()] == ["b"]
    assert len(state.children) == 2 and state.budget["reserved"] == 8


def test_shared_runner_physical_stop_without_financial_settlement_keeps_backpressure():
    state = resource_parent()
    first = state.next_calls()[0]
    child = start(state, first)
    child.state, child.result = "succeeded", "unknown-a"
    child.reservations["unknown"] = {
        "id": "unknown",
        "amount": 2,
        "status": "unknown",
        "actual": 0,
    }
    observe(state, first, child)
    assert state.children[0]["physical_stop_proof"]["physical_stopped"]
    assert not state.children[0]["settled"] and state.budget["unknown"] == 8
    assert state.next_calls() == [] and len(state.children) == 1


def test_settled_child_without_original_stop_proof_still_occupies_physical_concurrency_slot():
    state = resource_parent(tools_b=("other",), third=True)
    a, b = state.next_calls()
    child_a, child_b = [start(state, c) for c in (a, b)]
    composition().adopt_child_stop(state, a["run_id"], composition().physical_stop_view(child_a))
    child_a.state, child_a.result = "succeeded", "result-a"
    child_a._emit("run_succeeded")
    state.observe(a["run_id"], {"scope": state.scope, **child_a.diagnostics()})
    assert state.children[0]["settled"] and not state.children[1]["settled"]
    assert state.children[0]["physical_stop_proof"]["physical_stopped"] is False
    assert state.next_calls() == [] and len(state.children) == 2
    composition().adopt_child_stop(state, a["run_id"], composition().physical_stop_view(child_a))
    assert [c["member"] for c in state.next_calls()] == ["c"]
    assert child_b.state == "queued" and state.budget["reserved"] == 16


@pytest.mark.parametrize(
    "helper", ["child_capacity_released", "coding_runner_keys", "occupied_runner_keys"]
)
def test_original_resource_scheduler_helper_drift_is_rejected_before_history_use(
    helper, monkeypatch
):
    from ralf_agent.temporal_coding_composition_protocol import validate_protocol
    from tests.test_temporal_coding_composition_configuration import composition_manifest

    selected = composition_manifest()

    def changed(*args):
        return frozenset()

    monkeypatch.setattr(composition(), helper, changed)
    with pytest.raises(RalfError, match="pure"):
        validate_protocol(selected)


@pytest.mark.parametrize("closed", ["cancelling", "cancelled", "failed", "succeeded"])
def test_stop_recovery_keeps_blocked_business_closed_and_unknown_native_capacity(closed):
    from tests.test_temporal_coding_state import grant, ready

    state, native, request = ready()
    grant(state, request)
    blocked = copy.deepcopy(native)
    blocked.pop("delegated_execution")
    blocked.update(
        id="original-blocked-write",
        tool="write",
        effect_key="original-blocked-effect",
        status="blocked",
        attempts=[],
    )
    state.actions.append(blocked)
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    state.operation_unknown(native["id"], "original_owner_lost")
    state.state = closed
    native["delegated_execution"]["stop_retry"] = True
    acknowledgement = {"run_id": state.run_id, "action_id": native["id"]}
    state.deferred_acks.append(acknowledgement)
    budget = copy.deepcopy(state.budget)
    grants = copy.deepcopy(native["delegated_execution"]["grants"])
    before = copy.deepcopy(blocked)
    state.retry_blocked()
    assert state.state == closed
    assert blocked == before and blocked["status"] == "blocked"
    assert native["delegated_execution"]["stop_retry"] is False
    assert state.pending_acks == [acknowledgement] and state.deferred_acks == []
    assert state.budget == budget and state.budget["unknown"] == 1
    assert native["delegated_execution"]["grants"] == grants
    assert "thread/start" not in grants and "turn/start" not in grants
    operation = state.next_operation()
    assert operation[0]["kind"] == "coding_stop" and operation[1] == request
    assert state.budget == budget and blocked == before
    assert not any(e["kind"] == "blocked_write_rechecked" for e in state.event_log)


def test_running_blocked_business_still_rechecks_original_action_without_dispatch_retry():
    from tests.test_temporal_engine import state_with_tool

    state, action = state_with_tool()
    state.accept_failure(
        action["id"],
        {
            "ok": False,
            "dispatched": False,
            "blocked": True,
            "prior": {},
            "code": "prior_effect_unknown",
        },
    )
    original_id, original_effect = action["id"], action["effect_key"]
    state.retry_blocked()
    assert state.state == "running" and action["status"] == "ready"
    assert action["id"] == original_id and action["effect_key"] == original_effect
    assert state.event_log[-1]["kind"] == "blocked_write_rechecked"


def test_original_stop_only_recovery_implementation_drift_is_refused_before_history_use(
    monkeypatch,
):
    from ralf_agent.temporal_coding_composition_protocol import validate_protocol
    from ralf_agent.temporal_state import TemporalRunState
    from tests.test_temporal_coding_composition_configuration import composition_manifest

    selected = composition_manifest()

    def changed(self):
        self.state = "running"

    monkeypatch.setattr(TemporalRunState, "retry_blocked", changed)
    with pytest.raises(RalfError, match="pure"):
        validate_protocol(selected)


def test_parallel_namespace_gate_records_no_child_or_cap_before_binding():
    state = parent()
    assert state.next_calls() == []
    assert state.children == [] and state.budget["reserved"] == 0
    bind_namespace(state)
    assert [c["member"] for c in state.next_calls()] == ["a", "b"]
    assert state.budget["reserved"] == 16 and state.budget["remaining"] == 16


def test_repeated_drive_returns_only_original_unstarted_intents_without_extra_cap():
    state = parent()
    bind_namespace(state)
    first = state.next_calls()
    assert state.next_calls() == first
    assert len(state.children) == 2 and state.budget["reserved"] == 16
    for call in first:
        start(state, call)
    for index in range(3):
        state.command("drive-" + str(index), {"scope": state.scope, "kind": "drive"})
        assert state.next_calls() == []
    assert len(state.children) == 2 and state.budget["reserved"] == 16


def test_join_uses_both_original_results_after_out_of_order_settlement():
    state = parent()
    bind_namespace(state)
    a, b = state.next_calls()
    children = [start(state, c) for c in (a, b)]
    children[1].state, children[1].result = "succeeded", "result-b"
    observe(state, b, children[1])
    assert state.next_calls() == [] and state.budget["reserved"] == 8
    children[0].state, children[0].result = "succeeded", "result-a"
    observe(state, a, children[0])
    calls = state.next_calls()
    assert len(calls) == 1 and calls[0]["member"] == "join"
    assert calls[0]["input"] == {"a": "result-a", "b": "result-b"}
    assert state.budget["reserved"] == 8 and len(state.children) == 3


def test_settled_sibling_releases_one_slot_while_other_original_child_remains_live():
    state = parent(join=False, third=True)
    bind_namespace(state)
    a, b = state.next_calls()
    child_a, child_b = [start(state, c) for c in (a, b)]
    assert state.next_calls() == []
    child_b.state, child_b.result = "succeeded", "result-b"
    observe(state, b, child_b)
    calls = state.next_calls()
    assert [c["member"] for c in calls] == ["c"]
    assert child_a.state == "queued" and not state.children[0]["settled"]
    assert state.budget["reserved"] == 16 and state.budget["remaining"] == 16
    assert len(state.children) == 3


def test_physical_stop_with_unknown_child_cap_does_not_open_dependent_join():
    state = parent()
    bind_namespace(state)
    a, b = state.next_calls()
    child_a, child_b = [start(state, c) for c in (a, b)]
    child_a.state, child_a.result = "succeeded", "unsettled-a"
    child_a.reservations["unknown"] = {
        "id": "unknown",
        "amount": 2,
        "status": "unknown",
        "actual": 0,
    }
    proof = observe(state, a, child_a)
    child_b.state, child_b.result = "succeeded", "result-b"
    child_b.reservations["charged"] = {
        "id": "charged",
        "amount": 3,
        "status": "settled",
        "actual": 2,
    }
    observe(state, b, child_b)
    assert proof["physical_stopped"] is True
    assert state.budget["unknown"] == 8 and state.budget["reserved"] == 0
    assert state.budget["spent"] == 2 and state.budget["remaining"] == 22
    assert not state.children[0]["settled"] and state.children[1]["settled"]
    assert state.next_calls() == [] and len(state.children) == 2


def test_child_failure_freezes_every_original_dispatched_child_until_all_stop():
    state = parent()
    bind_namespace(state)
    a, b = state.next_calls()
    child_a, child_b = [start(state, c) for c in (a, b)]
    child_a.state, child_a.error = "failed", {"code": "business_failed"}
    observe(state, a, child_a)
    assert state.state == "cancelling" and state.next_calls() == []
    intent = copy.deepcopy(state.composition_stop_intent)
    assert intent["child_intent_ids"] == ["0:a", "0:b"]
    assert not composition().physical_stop_view(state)["physical_stopped"]
    child_b.state = "cancelled"
    observe(state, b, child_b)
    assert state.state == "failed" and state.composition_stop_intent == intent
    assert composition().physical_stop_view(state)["physical_stopped"]
    assert len(state.children) == 2


def test_cancel_keeps_uncertain_start_obligation_and_releases_only_undispatched_cap():
    state = parent()
    bind_namespace(state)
    state.next_calls()
    state.children[0]["dispatch_started"] = True
    state.command("cancel", {"scope": state.scope, "kind": "cancel"})
    assert state.state == "cancelling" and state.next_calls() == []
    assert not state.children[0].get("physical_no_start")
    assert state.children[1]["physical_no_start"] and state.children[1]["settled"]
    assert state.budget["reserved"] == 8 and state.budget["remaining"] == 24
    assert not composition().physical_stop_view(state)["physical_stopped"]


def test_independent_stops_preserve_unknown_cap_and_first_terminal_intent():
    state = parent()
    bind_namespace(state)
    a, b = state.next_calls()
    child_a, child_b = [start(state, c) for c in (a, b)]
    child_a.reservations["unknown"] = {
        "id": "unknown",
        "amount": 2,
        "status": "unknown",
        "actual": 0,
    }
    child_a.state, child_b.state = "cancelled", "cancelled"
    state.command("cancel", {"scope": state.scope, "kind": "cancel"})
    composition().request_parent_stop(state, terminal_state="failed", reason={"code": "late"})
    observe(state, b, child_b)
    assert state.state == "cancelling" and state.budget["reserved"] == 8
    observe(state, a, child_a)
    assert state.state == "cancelled" and state.budget["unknown"] == 8
    assert composition().physical_stop_view(state)["physical_stopped"]
    assert not state.quiescent and state.next_calls() == []


def test_stop_proof_is_per_original_child_and_stale_evidence_cannot_reopen_it():
    from ralf_agent.types import digest

    state = parent()
    bind_namespace(state)
    a, b = state.next_calls()
    child_a, child_b = [start(state, c) for c in (a, b)]
    early = composition().physical_stop_view(child_a)
    child_a.state, child_a.revision = "cancelled", 3
    later = composition().physical_stop_view(child_a)
    composition().adopt_child_stop(state, a["run_id"], later)
    composition().adopt_child_stop(state, a["run_id"], early)
    assert state.children[0]["physical_stop_proof"] == later
    assert "physical_stop_proof" not in state.children[1]
    with pytest.raises(RalfError):
        composition().adopt_child_stop(state, b["run_id"], later)
    changed = {**later, "physical_stopped": False}
    changed["proof_digest"] = digest({k: v for k, v in changed.items() if k != "proof_digest"})
    with pytest.raises(RalfError):
        composition().adopt_child_stop(state, a["run_id"], changed)
    child_b.state = "cancelled"
    state.command("cancel", {"scope": state.scope, "kind": "cancel"})
    observe(state, b, child_b)
    assert state.state == "cancelled"


def test_parallel_parent_requires_its_distinct_history_marker(monkeypatch):
    import asyncio

    from temporalio.exceptions import ApplicationError

    from ralf_agent import temporal_parent_workflow

    instance = object.__new__(temporal_parent_workflow.TemporalParentWorkflow)
    instance.state, instance.wake_revision = parent(), 0
    seen = []

    def unavailable(name):
        seen.append(name)
        return False

    monkeypatch.setattr(temporal_parent_workflow.workflow, "patched", unavailable)
    with pytest.raises(ApplicationError, match="History marker"):
        asyncio.run(instance.run({"activity_timeout": 5}))
    assert seen == ["ralf-coding-composition-v2"]
