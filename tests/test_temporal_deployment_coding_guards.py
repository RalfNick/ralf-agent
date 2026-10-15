"""Sealed original Coding facts accept duplicates without reopening native authority."""

import copy

import pytest

from ralf_agent import temporal_coding_composition_state as composition
from ralf_agent import temporal_deployment_release_state as release
from ralf_agent.errors import RalfError
from ralf_agent.types import digest

from .test_temporal_coding_state import completed_native, owner_dead_payload
from .test_temporal_deployment_coding_state import attach, cold, native
from .test_temporal_tool_execution import admission, proof


def sealed_native(monkeypatch):
    state, action, request, identity = native(monkeypatch)
    result = completed_native(state, action, request)
    state.admit_coding_stop(admission(request, "c" * 32))
    state.coding_owner_stopped(owner_dead_payload(request))
    state.accept_tool(action["id"], {"ok": True, "result": result})
    state.pending_acks = []  # The original loop has acknowledged this effect.
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    release.end_activity(state, identity)
    assert release.closure(state) == (True, [])
    release.seal(state, {"scope": state.scope, "children": []})
    return state, action, request


@pytest.mark.parametrize(
    "kind", ["owner", "prepared", "thread", "turn", "observation", "stop", "result_candidate"]
)
def test_sealed_exact_original_native_receipt_returns_ack_without_events(monkeypatch, kind):
    state, action, request = sealed_native(monkeypatch)
    value = action["delegated_execution"]
    evidence = {"result": value[kind]} if kind == "result_candidate" else value[kind]
    payload = {**admission(request), "kind": kind, "evidence": copy.deepcopy(evidence)}
    before = copy.deepcopy((action, state.event_log, state.revision, state.deployment_seal))
    assert state.coding_receipt(payload) == {"action_id": action["id"], "recorded": True}
    assert (action, state.event_log, state.revision, state.deployment_seal) == before


@pytest.mark.parametrize(
    "kind",
    ["owner", "prepared", "thread", "turn", "observation", "stop", "result_candidate", "error"],
)
def test_sealed_new_or_changed_native_receipt_refuses_before_any_mutation(monkeypatch, kind):
    state, action, request = sealed_native(monkeypatch)
    value = action["delegated_execution"]
    if kind == "error":
        evidence = {"code": "new-caller-error"}
    elif kind == "result_candidate":
        evidence = {"result": {**value[kind], "caller_extra": True}}
    else:
        evidence = {**value[kind], "caller_extra": True}
    before = copy.deepcopy((action, state.event_log))
    with pytest.raises(RalfError):
        state.coding_receipt({**admission(request), "kind": kind, "evidence": evidence})
    assert (action, state.event_log) == before


def test_sealed_new_native_permission_refuses_even_previously_recorded_grant(monkeypatch):
    state, action, request = sealed_native(monkeypatch)
    original = action["delegated_execution"]["grants"]["prepare"]
    with pytest.raises(RalfError):
        state.admit_coding_phase(
            {
                **admission(request),
                **{key: original[key] for key in ("method", "params", "binding")},
            }
        )


def test_sealed_stop_request_only_acknowledges_original_admitted_invocation(monkeypatch):
    state, action, request = sealed_native(monkeypatch)
    before = copy.deepcopy((action, state.event_log, state.revision))
    result = state.admit_coding_stop(admission(request, "c" * 32))
    assert result["admitted"] is True
    assert (action, state.event_log, state.revision) == before
    with pytest.raises(RalfError):
        state.admit_coding_stop(admission(request, "f" * 32))
    assert (action, state.event_log, state.revision) == before


def test_sealed_owner_stop_only_acknowledges_the_first_immutable_proof(monkeypatch):
    state, action, request = sealed_native(monkeypatch)
    before = copy.deepcopy((state.tool_executions, state.event_log, state.revision))
    assert state.coding_owner_stopped(owner_dead_payload(request))["recorded"] is True
    assert (state.tool_executions, state.event_log, state.revision) == before
    changed = owner_dead_payload(request)
    changed["invocation_id"] = "a" * 32
    with pytest.raises(RalfError):
        state.coding_owner_stopped(changed)
    assert (state.tool_executions, state.event_log, state.revision) == before


def test_first_v3_owner_stop_is_recorded_when_tool_already_has_actual_end(monkeypatch):
    state, action, request, _ = native(monkeypatch)
    completed_native(state, action, request)
    state.tool_execution_ended(proof(request))
    state.admit_coding_stop(admission(request, "c" * 32))
    payload = owner_dead_payload(request)
    assert state.coding_owner_stopped(payload)["recorded"] is True
    tool = state.tool_executions[action["id"]]
    assert tool["coding_owner_stop_proof"] == payload
    before = copy.deepcopy((state.tool_executions, state.event_log))
    assert state.coding_owner_stopped(copy.deepcopy(payload))["recorded"] is True
    assert (state.tool_executions, state.event_log) == before
    state.admit_coding_stop(admission(request, "f" * 32))
    before = copy.deepcopy((state.tool_executions, state.event_log))
    other = owner_dead_payload(request)
    other["invocation_id"] = "f" * 32
    assert state.coding_owner_stopped(other)["recorded"] is True
    assert (state.tool_executions, state.event_log) == before


def test_v3_owner_proof_is_detached_and_unselected_tool_end_behavior_is_unchanged(monkeypatch):
    state, action, request, _ = cold(monkeypatch)
    stored = copy.deepcopy(state.tool_executions[action["id"]]["coding_owner_stop_proof"])
    requested = owner_dead_payload(request)
    state.coding_owner_stopped(requested)
    requested["evidence"]["owner"]["pid"] = 99
    assert state.tool_executions[action["id"]]["coding_owner_stop_proof"] == stored

    from .test_temporal_coding_state import ready

    ordinary, action, request = ready()
    completed_native(ordinary, action, request)
    ordinary.tool_execution_ended(proof(request))
    ordinary.admit_coding_stop(admission(request, "c" * 32))
    ordinary.coding_owner_stopped(owner_dead_payload(request))
    assert "coding_owner_stop_proof" not in ordinary.tool_executions[action["id"]]


def sealed_parent(monkeypatch):
    from ralf_agent.temporal_bindings import request_release_digest

    from .test_temporal_coding_composition_state import bind_namespace, leaf, parent

    state = parent()
    bind_namespace(state)
    call = state.next_calls()[0]
    call = state.children[0]
    call["dispatch_started"] = True
    state.mark_started(call["run_id"])
    child = leaf(state, call)
    attach(state, monkeypatch)
    state.manifest["binding_protocol"] = 23
    state.manifest["coding_execution_protocol"] = {"version": 6}
    state.manifest["coding_composition_protocol"] = {
        "version": 7,
        "topology": "bounded-recursive-orchestration",
    }
    # This pure fixture uses its actual old namespace/edge, never an SDK locator.
    from ralf_agent import temporal_deployment_execution_state as deployment

    original_view = deployment.view

    def view(current):
        result = original_view(current)
        result["namespace"] = copy.deepcopy(state.composition_namespace)
        return result

    monkeypatch.setattr(deployment, "view", view)
    child.manifest = copy.deepcopy(state.manifest)
    child.release_digest = request_release_digest(child.request, child.manifest)
    child.state = "cancelled"
    physical = composition.physical_stop_view(child)
    composition.pin_child_execution(state, call["run_id"], physical)
    composition.adopt_child_stop(state, call["run_id"], physical)
    call.update(
        settled=True,
        uncertain=False,
        state="cancelled",
        spent=0,
        deployment_execution_epoch=child.epoch,
        deployment_admission={"original": "fixed-child"},
    )
    response = {
        "namespace": copy.deepcopy(state.composition_namespace),
        "execution_epoch": state.epoch,
        "admitted": False,
    }
    composition.adopt_admission(state, response)
    assert release.closure(state) == (True, [])
    children = [
        {
            "call_id": call["id"],
            "run_id": call["run_id"],
            "command_id": call["command_id"],
            "execution_epoch": child.epoch,
            "request_digest": digest(call["request"]),
            "admission_digest": digest(call["deployment_admission"]),
            "seal_digest": "b" * 64,
        }
    ]
    release.seal(state, {"scope": state.scope, "children": children})
    return state, call, physical, response


def test_sealed_child_exact_proof_and_epoch_ack_without_mutating_adopted_state(monkeypatch):
    state, call, physical, _ = sealed_parent(monkeypatch)
    before = copy.deepcopy((state.children, state.event_log, state.revision))
    assert composition.pin_child_execution(state, call["run_id"], physical)["recorded"]
    assert composition.adopt_child_stop(state, call["run_id"], physical)["recorded"]
    assert (state.children, state.event_log, state.revision) == before
    changed = copy.deepcopy(physical)
    changed["revision"] += 1
    changed["proof_digest"] = digest({k: v for k, v in changed.items() if k != "proof_digest"})
    with pytest.raises(RalfError):
        composition.adopt_child_stop(state, call["run_id"], changed)
    assert (state.children, state.event_log, state.revision) == before


def test_sealed_composition_admission_and_stop_only_accept_exact_original_facts(monkeypatch):
    state, _, _, response = sealed_parent(monkeypatch)
    before = copy.deepcopy(
        (state.composition_admission, state.composition_stop_intent, state.event_log)
    )
    composition.adopt_admission(state, copy.deepcopy(response))
    intent = state.composition_stop_intent
    composition.request_parent_stop(
        state, terminal_state=intent["terminal_state"], reason=intent["reason"]
    )
    assert (state.composition_admission, state.composition_stop_intent, state.event_log) == before
    with pytest.raises(RalfError):
        composition.request_parent_stop(state, terminal_state="failed", reason={"code": "new"})
    assert (state.composition_admission, state.composition_stop_intent, state.event_log) == before


def test_sealed_original_runner_candidate_wrapper_is_a_duplicate_fact(monkeypatch):
    state, action, request = sealed_native(monkeypatch)
    result = copy.deepcopy(action["delegated_execution"]["result_candidate"])
    payload = {
        **admission(request),
        "kind": "result_candidate",
        "evidence": {"kind": "result_candidate", "result": result},
    }
    before = copy.deepcopy((action, state.event_log))
    assert state.coding_receipt(payload)["recorded"] is True
    assert (action, state.event_log) == before
