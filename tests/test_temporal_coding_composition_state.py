"""Original serial graph History and scoped admission without financial shortcuts."""

import copy
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope
from ralf_agent.errors import RalfError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.temporal_state import TemporalCommandRegistryState, TemporalRunState
from ralf_agent.types import digest, submission_request
from tests.test_temporal_engine import Provider, registry


def composition():
    from ralf_agent import temporal_coding_composition_state

    return temporal_coding_composition_state


def parent():
    host = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    graph = GraphWorkflowSpec(
        "g",
        [
            GraphNode("a", agent=AgentSpec("a", "answer")),
            GraphNode("b", agent=AgentSpec("b", "answer")),
        ],
        max_concurrency=1,
    )
    state = TemporalParentState(
        "root",
        asdict(Scope()),
        "submit",
        submission_request(graph, "task", budget=32),
        host.orchestration_release,
        "root-epoch",
    )
    state.manifest["coding_composition_protocol"] = {"version": 1, "topology": "serial-agent-graph"}
    state.manifest["binding_protocol"] = 12
    state.manifest["kernel"] = "temporal-3"
    composition().initialize(state, namespace="test")
    return state


def bind_namespace(state):
    return composition().initialize_namespace(
        state,
        {
            "scope": state.scope,
            "run_id": state.run_id,
            "execution_epoch": state.epoch,
            "manifest_digest": digest(state.manifest),
            "namespace": {"name": "test", "id": "12345678-1234-1234-1234-123456789abc"},
        },
    )


def leaf(state, call):
    host = TemporalRuntime(providers={"default": Provider()}, tools=registry())
    child = TemporalRunState(
        call["run_id"],
        state.scope,
        call["command_id"],
        submission_request(AgentSpec("a", "answer"), "task", budget=call["cap"]),
        host.manifest,
        "child-epoch",
    )
    child.request = copy.deepcopy(call["request"])
    child.manifest = copy.deepcopy(state.manifest)
    from ralf_agent.temporal_bindings import request_release_digest

    child.release_digest = request_release_digest(child.request, child.manifest)
    composition().initialize(child, namespace="test")
    bind_namespace(child)
    composition().validate_child_link(
        child,
        namespace="test",
        parent_namespace="test",
        parent_run_id="root",
        parent_epoch="root-epoch",
        original_epoch="child-epoch",
    )
    return child


def registry_request(command="submit", **metadata):
    return {
        "scope": asdict(Scope()),
        "command_id": command,
        "kind": "submit",
        "target": "root",
        "payload_digest": "a" * 64,
        "coding_composition": {
            "version": 1,
            "manifest_digest": "b" * 64,
            "request_digest": "a" * 64,
            **metadata,
        },
    }


def test_registry_first_acceptance_metadata_and_durable_closed_admission():
    state = TemporalCommandRegistryState(asdict(Scope()))
    first = state.reserve(registry_request())
    assert state.reserve(registry_request(manifest_digest="c" * 64)) == first
    candidates = state.composition_candidates("b" * 64)
    assert candidates == [
        {
            "command_id": "submit",
            "run_id": "root",
            "request_digest": "a" * 64,
            "manifest_digest": "b" * 64,
            "close_requested": False,
            "execution_epoch": None,
            "namespace": None,
        }
    ]
    state.close_composition_submissions("b" * 64)
    assert state.composition_admission("submit", "root", "a" * 64, "b" * 64)["admitted"] is False
    assert state.identities["submit"] == {
        "kind": "submit",
        "target": "root",
        "payload_digest": "a" * 64,
    }
    with pytest.raises(RalfError):
        state.composition_admission("submit", "foreign", "a" * 64, "b" * 64)


def test_registry_legacy_acceptance_cannot_gain_composition_metadata_later():
    state = TemporalCommandRegistryState(asdict(Scope()))
    original = registry_request()
    original.pop("coding_composition")
    state.reserve(original)
    state.reserve(registry_request())
    assert state.composition_candidates("b" * 64) == []


def test_namespace_gate_and_immutable_link_without_session():
    state = parent()
    assert state.next_calls() == []
    bind_namespace(state)
    call = state.next_calls()[0]
    link = call["request"]["coding_parent"]
    assert link["parent_run_id"] == "root" and link["parent_execution_epoch"] == "root-epoch"
    assert link["cap"] == 8 and link["depth"] == 1 and "session_lineage" not in call["request"]
    assert call["child_request_digest"] == digest(call["request"])
    child = leaf(state, call)
    with pytest.raises(RalfError):
        composition().validate_child_link(
            child,
            namespace="test",
            parent_namespace="test",
            parent_run_id="root",
            parent_epoch="replacement",
            original_epoch="child-epoch",
        )
    with pytest.raises(RalfError):
        composition().validate_child_link(
            child,
            namespace="test",
            parent_namespace="test",
            parent_run_id="root",
            parent_epoch="root-epoch",
            original_epoch="different-first-epoch",
        )


def test_parent_unknown_cap_survives_independent_original_physical_closure():
    state = parent()
    bind_namespace(state)
    call = state.next_calls()[0]
    entry = state.children[0]
    entry["dispatch_started"] = True
    state.mark_started(call["run_id"])
    child = leaf(state, call)
    child.state = "cancelled"
    child.reservations["unknown"] = {"id": "unknown", "amount": 2, "status": "unknown", "actual": 0}
    proof = composition().physical_stop_view(child)
    assert proof["physical_stopped"] is True and child.quiescent is False
    composition().pin_child_execution(state, call["run_id"], proof)
    entry["uncertain"] = True
    composition().request_parent_stop(
        state, terminal_state="cancelled", reason={"code": "cancel_requested"}
    )
    assert state.state == "cancelling" and state.next_calls() == []
    before = state.budget
    composition().adopt_child_stop(state, call["run_id"], proof)
    composition().refresh_parent_stop(state)
    assert state.state == "cancelled" and state.budget == before
    assert state.budget["unknown"] == 8 and not entry["settled"] and not state.quiescent
    assert composition().physical_stop_view(state)["physical_stopped"] is True
    changed = copy.deepcopy(proof)
    changed["physical_stopped"] = False
    changed["proof_digest"] = digest({k: v for k, v in changed.items() if k != "proof_digest"})
    with pytest.raises(RalfError):
        composition().adopt_child_stop(state, call["run_id"], changed)


def test_uncertain_start_never_becomes_no_start_and_first_terminal_intent_wins():
    state = parent()
    bind_namespace(state)
    state.next_calls()
    state.children[0]["dispatch_started"] = True
    composition().request_parent_stop(
        state, terminal_state="cancelled", reason={"code": "deadline"}
    )
    composition().request_parent_stop(
        state, terminal_state="failed", reason={"code": "child_failed"}
    )
    composition().refresh_parent_stop(state)
    assert state.state == "cancelling"
    assert state.composition_stop_intent["terminal_state"] == "cancelled"
    assert not composition().physical_stop_view(state)["physical_stopped"]


def test_undispatched_original_child_releases_only_no_start_capacity():
    state = parent()
    bind_namespace(state)
    state.next_calls()
    composition().request_parent_stop(state, terminal_state="cancelled", reason={"code": "cancel"})
    assert state.children[0]["physical_no_start"] is True
    assert state.children[0]["settled"] is True and state.children[0]["spent"] == 0
    assert (
        state.state == "cancelled" and composition().physical_stop_view(state)["physical_stopped"]
    )


def test_missing_original_tool_owner_end_keeps_physical_proof_false():
    state = parent()
    bind_namespace(state)
    call = state.next_calls()[0]
    child = leaf(state, call)
    child.state = "cancelled"
    child.tool_executions["missing"] = {"execution_stopped": False}
    assert composition().physical_stop_view(child)["physical_stopped"] is False


def test_selected_parent_cancel_command_defers_terminal_and_blocks_selection_and_patch():
    state = parent()
    bind_namespace(state)
    state.next_calls()
    state.children[0]["dispatch_started"] = True
    receipt = state.command("cancel", {"kind": "cancel", "scope": state.scope})
    assert receipt["apply_state"] == "applied" and state.state == "cancelling"
    with pytest.raises(RalfError):
        state.accept_selection({"calls": [], "done": True, "result": "forbidden"})
    with pytest.raises(RalfError):
        state.patch({}, state.plan_revision)


def test_namespace_initialization_is_exact_idempotent_and_foreign_binding_refused():
    state = parent()
    first = bind_namespace(state)
    assert bind_namespace(state) == first
    with pytest.raises(RalfError):
        composition().initialize_namespace(
            state,
            {
                "scope": state.scope,
                "run_id": state.run_id,
                "execution_epoch": state.epoch,
                "manifest_digest": digest(state.manifest),
                "namespace": {"name": "test", "id": "22345678-1234-1234-1234-123456789abc"},
            },
        )


def test_successful_original_sdk_start_pins_epoch_without_fabricating_physical_receipt():
    state = parent()
    bind_namespace(state)
    call = state.next_calls()[0]
    state.children[0]["dispatch_started"] = True
    evidence = {
        "namespace": state.composition_namespace,
        "execution_epoch": "child-epoch",
        "original_execution_epoch": "child-epoch",
        "request_digest": digest(call["request"]),
        "parent_run_id": "root",
        "parent_execution_epoch": "root-epoch",
    }
    composition().pin_child_execution(state, call["run_id"], evidence)
    assert state.children[0]["child_execution"]["execution_epoch"] == "child-epoch"
    assert "physical_stop_proof" not in state.children[0]
    with pytest.raises(RalfError):
        composition().pin_child_execution(
            state,
            call["run_id"],
            {
                **evidence,
                "execution_epoch": "replacement",
                "original_execution_epoch": "replacement",
            },
        )


def test_closed_root_admission_stops_original_graph_before_any_child_intent():
    state = parent()
    composition().adopt_admission(
        state,
        {
            "namespace": {"name": "test", "id": "12345678-1234-1234-1234-123456789abc"},
            "execution_epoch": state.epoch,
            "admitted": False,
        },
    )
    assert state.state == "cancelled" and state.children == [] and state.next_calls() == []
    assert composition().physical_stop_view(state)["physical_stopped"]


def test_selected_workflow_queries_original_proof_and_registry_close_scope():
    import asyncio

    from temporalio.exceptions import ApplicationError

    from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow, TemporalRunWorkflow

    state = parent()
    workflow = object.__new__(TemporalRunWorkflow)
    workflow.state, workflow.wake_revision = state, 0
    value = workflow.view({"scope": state.scope, "kind": "coding_composition_proof"})
    assert value["namespace"]["id"] is None and value["execution_epoch"] == "root-epoch"
    registry = object.__new__(TemporalCommandRegistryWorkflow)
    registry.commands = TemporalCommandRegistryState(state.scope)
    registry.commands.reserve(registry_request())
    assert (
        len(
            registry.view(
                {
                    "scope": state.scope,
                    "kind": "coding_composition_candidates",
                    "manifest_digest": "b" * 64,
                }
            )
        )
        == 1
    )
    with pytest.raises(ApplicationError):
        asyncio.run(
            registry.close_coding_composition_submissions(
                {"scope": {"tenant": "foreign"}, "manifest_digest": "b" * 64}
            )
        )
    assert registry.commands.composition_admission("submit", "root", "a" * 64, "b" * 64)["admitted"]


def test_workflow_rejects_selected_reset_and_unlinked_child_before_scheduling():
    from types import SimpleNamespace

    from temporalio.exceptions import ApplicationError

    from ralf_agent.temporal_workflow import TemporalRunWorkflow

    workflow = object.__new__(TemporalRunWorkflow)
    workflow.state = parent()
    with pytest.raises(ApplicationError):
        workflow._check_composition_parent(
            SimpleNamespace(
                namespace="test",
                run_id="root-epoch",
                original_execution_run_id="replacement",
                parent=None,
            )
        )
    with pytest.raises(ApplicationError):
        workflow._check_composition_parent(
            SimpleNamespace(
                namespace="test",
                run_id="root-epoch",
                original_execution_run_id="root-epoch",
                parent=SimpleNamespace(
                    namespace="test", workflow_id="foreign", run_id="foreign-epoch"
                ),
            )
        )


def test_root_workflow_adopts_closed_admission_before_scheduling():
    import asyncio
    from datetime import timedelta

    from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow

    state = parent()
    workflow = object.__new__(TemporalParentWorkflow)
    workflow.state, workflow.wake_revision = state, 0

    async def receipt(name, request, activity_timeout):
        assert request["run_id"] == "root" and request["execution_epoch"] == "root-epoch"
        return {
            "ok": True,
            "result": {
                "namespace": {"name": "test", "id": "12345678-1234-1234-1234-123456789abc"},
                "execution_epoch": "root-epoch",
                "admitted": False,
            },
        }

    workflow._activity = receipt
    assert (
        asyncio.run(workflow._admit_composition({"command_id": "submit"}, timedelta(seconds=5)))
        is True
    )
    assert state.state == "cancelled" and not state.children


def test_registry_original_root_epoch_namespace_are_immutable_after_admission():
    state = TemporalCommandRegistryState(asdict(Scope()))
    state.reserve(registry_request())
    namespace = {"name": "test", "id": "12345678-1234-1234-1234-123456789abc"}
    first = state.bind_composition_submission(
        "submit", "root", "a" * 64, "b" * 64, "root-epoch", namespace
    )
    assert first["execution_epoch"] == "root-epoch" and first["namespace"] == namespace
    assert (
        state.bind_composition_submission(
            "submit", "root", "a" * 64, "b" * 64, "root-epoch", namespace
        )
        == first
    )
    state.close_composition_submissions("b" * 64)
    assert not state.bind_composition_submission(
        "submit", "root", "a" * 64, "b" * 64, "root-epoch", namespace
    )["admitted"]
    with pytest.raises(RalfError):
        state.bind_composition_submission(
            "submit", "root", "a" * 64, "b" * 64, "replacement", namespace
        )
    with pytest.raises(RalfError):
        state.bind_composition_submission(
            "submit",
            "root",
            "a" * 64,
            "b" * 64,
            "root-epoch",
            {**namespace, "id": "22345678-1234-1234-1234-123456789abc"},
        )


@pytest.mark.parametrize("owner", ["active_reconciliation", "active_evidence_ack"])
def test_actual_receipt_operation_keeps_physical_stop_pending(owner):
    state = parent()
    bind_namespace(state)
    child = leaf(state, state.next_calls()[0])
    child.state = "cancelled"
    setattr(child, owner, "original-action")
    assert composition().physical_stop_view(child)["physical_stopped"] is False


def test_context_read_without_actual_end_is_not_physical_closure():
    state = parent()
    bind_namespace(state)
    child = leaf(state, state.next_calls()[0])
    child.state = "cancelled"
    child.context_read_stages["read"] = {
        "execution_end_proof": None,
        "fenced": False,
        "handler_not_started": False,
        "status": "failed",
    }
    assert composition().physical_stop_view(child)["physical_stopped"] is False


def test_true_physical_proof_cannot_claim_a_running_original_child():
    state = parent()
    bind_namespace(state)
    call = state.next_calls()[0]
    state.children[0]["dispatch_started"] = True
    child = leaf(state, call)
    child.state = "running"
    evidence = composition().physical_stop_view(child)
    evidence["physical_stopped"] = True
    evidence["proof_digest"] = digest({k: v for k, v in evidence.items() if k != "proof_digest"})
    with pytest.raises(RalfError):
        composition().pin_child_execution(state, call["run_id"], evidence)


def test_native_fence_waits_for_original_actual_owner_and_keeps_unknown_credits():
    from tests.test_temporal_coding_state import grant, native_stop, owner_dead_payload, ready
    from tests.test_temporal_tool_execution import admission

    child, action, request = ready()
    grant(child, request)
    child.command("cancel", {"kind": "cancel", "scope": child.scope})
    child.operation_unknown(action["id"], "worker_lost")
    child.admit_coding_stop(admission(request, "c" * 32))
    native_stop(child, request)
    child.manifest["binding_protocol"] = 17
    from ralf_agent.temporal_coding_composition_protocol import implementation

    child.manifest["coding_composition_protocol"] = {
        "version": 4,
        "topology": "bounded-agent-orchestration",
        "implementation": implementation(),
    }
    composition().initialize(child, namespace="test")
    bind_namespace(child)
    assert composition().physical_stop_view(child)["physical_stopped"] is False
    before = child.budget
    child.coding_owner_stopped(owner_dead_payload(request))
    assert composition().physical_stop_view(child)["physical_stopped"] is True
    assert child.budget == before and child.budget["unknown"] == 1 and not child.quiescent
    assert composition().coding_requests(child) == [request]
    action["arguments"] = {"task": "replaced"}
    with pytest.raises(RalfError):
        composition().coding_requests(child)


def test_invalid_root_admission_receipt_stays_closed_to_business():
    import asyncio
    from datetime import timedelta

    from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow

    state = parent()
    workflow = object.__new__(TemporalParentWorkflow)
    workflow.state, workflow.wake_revision = state, 0

    async def receipt(name, request, activity_timeout):
        return {
            "ok": True,
            "result": {
                "namespace": {"name": "test", "id": "12345678-1234-1234-1234-123456789abc"},
                "execution_epoch": "foreign",
                "admitted": True,
            },
        }

    workflow._activity = receipt
    assert (
        asyncio.run(workflow._admit_composition({"command_id": "submit"}, timedelta(seconds=5)))
        is False
    )
    assert state.composition_admission is None and state.next_calls() == []


def test_foreign_child_epoch_observation_fails_closed_without_workflow_task_failure():
    from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow

    state = parent()
    bind_namespace(state)
    call = state.next_calls()[0]
    state.children[0]["dispatch_started"] = True
    child = leaf(state, call)
    proof = composition().physical_stop_view(child)
    composition().pin_child_execution(state, call["run_id"], proof)
    bad = copy.deepcopy(proof)
    bad["execution_epoch"] = bad["original_execution_epoch"] = "foreign"
    bad["proof_digest"] = digest({k: v for k, v in bad.items() if k != "proof_digest"})
    workflow = object.__new__(TemporalParentWorkflow)
    workflow.state = state
    assert workflow._observe_composition(call["run_id"], {"coding_composition_proof": bad}) is False
    assert state.state == "cancelling" and state.next_calls() == []
    assert state.children[0]["child_execution"]["execution_epoch"] == "child-epoch"


def test_true_physical_proof_refuses_a_live_original_tool_owner():
    state = parent()
    bind_namespace(state)
    call = state.next_calls()[0]
    state.children[0]["dispatch_started"] = True
    child = leaf(state, call)
    child.state = "cancelled"
    evidence = composition().physical_stop_view(child)
    evidence["action_stops"] = [
        {
            "action_id": "tool",
            "attempts": [],
            "effect_key": None,
            "native_request_digest": None,
            "native_fenced": None,
            "pending_stop": None,
            "owner": {"execution_stopped": False},
        }
    ]
    evidence["proof_digest"] = digest({k: v for k, v in evidence.items() if k != "proof_digest"})
    with pytest.raises(RalfError):
        composition().pin_child_execution(state, call["run_id"], evidence)


def test_original_child_link_survives_actual_sdk_tuple_to_list_wire_conversion():
    import asyncio

    from temporalio.converter import DataConverter

    state = parent()
    bind_namespace(state)
    # Actual AgentSpec submission produces tuple-backed tools, including nested
    # caller input. The original child intent must use the SDK wire shape.
    raw = submission_request(
        AgentSpec("a", "answer", tools=("read",)), {"parts": ("a", "b")}, budget=8
    )
    assert raw["definition"]["steps"][0]["tools"] == ("read",)
    call = state.next_calls()[0]
    linked = composition().project_child_link(state, call, raw)
    state.children[0]["request"] = linked
    state.children[0]["child_request_digest"] = digest(linked)
    state.children[0]["dispatch_started"] = True

    async def wire(value):
        converter = DataConverter.default
        encoded = await converter.encode([value])
        return (await converter.decode(encoded))[0]

    received = asyncio.run(wire(linked))
    child = leaf(state, {**call, "request": received})
    proof = composition().physical_stop_view(child)
    composition().pin_child_execution(state, call["run_id"], proof)
    assert state.children[0]["request"] == received
    assert received["definition"]["steps"][0]["tools"] == ["read"]
    assert received["input"]["parts"] == ["a", "b"]


def test_terminal_financially_settled_parent_polls_until_original_physical_proof(monkeypatch):
    import asyncio

    from ralf_agent import temporal_parent_workflow as scheduler
    from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow

    state = parent()
    bind_namespace(state)
    state.composition_admission = {
        "namespace": state.composition_namespace,
        "execution_epoch": state.epoch,
        "admitted": True,
    }
    call = state.next_calls()[0]
    entry = state.children[0]
    entry.update(
        dispatch_started=True, started=True, settled=True, cancel_confirmed=True, state="succeeded"
    )
    state.state = "succeeded"
    child = leaf(state, call)
    child.state = "running"
    earlier = composition().physical_stop_view(child)
    composition().pin_child_execution(state, call["run_id"], earlier)
    composition().adopt_child_stop(state, call["run_id"], earlier)
    child.state, child.result = "succeeded", "done"
    child._emit("run_succeeded")
    later = composition().physical_stop_view(child)
    diagnostics = {**child.diagnostics(), "scope": child.scope}
    assert state.quiescent and not composition().physical_stop_view(state)["physical_stopped"]

    instance = object.__new__(TemporalParentWorkflow)
    instance.state, instance.wake_revision = state, 0
    observations = []

    async def control(mode, recorded_call, activity_timeout):
        assert mode == "observe" and recorded_call["run_id"] == call["run_id"]
        observations.append(mode)
        # The first History proof is read before the final model response;
        # its diagnostics are read afterward. A second original read closes it.
        proof = earlier if len(observations) == 1 else later
        return {"ok": True, "result": {**diagnostics, "coding_composition_proof": proof}}

    class SchedulerSleep(Exception):
        pass

    async def wait(predicate, **options):
        if "timeout" in options:
            raise TimeoutError
        assert composition().physical_stop_view(state)["physical_stopped"], (
            "A financially quiescent parent must not sleep forever with stale physical evidence"
        )
        raise SchedulerSleep

    instance._control = control
    monkeypatch.setattr(scheduler.workflow, "patched", lambda _: True)
    monkeypatch.setattr(scheduler.workflow, "wait_condition", wait)
    with pytest.raises(SchedulerSleep):
        asyncio.run(instance.run({"activity_timeout": 5, "command_id": "submit"}))
    assert observations == ["observe", "observe"]
    assert state.state == "succeeded"
    assert state.quiescent and composition().physical_stop_view(state)["physical_stopped"]
