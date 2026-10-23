"""Original read Actions keep their Turn until response and actual end agree."""

import copy
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, ManagedContextPipeline, Scope, ToolRegistry, WorkflowSpec
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import digest, submission_request

from .test_temporal_binding_isolation import LabelContext
from .test_temporal_context_read_protocol import candidate
from .test_temporal_sessions import Provider


def state_for(phase="context", *, sequence=False, epoch="original-worker-uuid"):
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        context_builder=LabelContext("label") if phase == "context" else ManagedContextPipeline(),
    )
    agent = AgentSpec("a", "Answer")
    definition = WorkflowSpec("sequence", [agent, agent]) if sequence else agent
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "submit",
        submission_request(definition, "question", budget=8),
        candidate(runtime.manifest),
        execution_epoch=epoch,
    )
    if phase not in {"context", "plan"}:
        # Previously adopted original plan; each later phase owns a distinct read Action.
        state.managed_context_stages["0:0"] = {
            "key": "0:0",
            "source_digest": digest(state.messages),
            "status": "preparing",
            "phase": phase,
            "operations": [],
            "index": 0,
            "prepared": {
                "plan": None,
                "fallback": {"messages": copy.deepcopy(state.messages)},
                "references": [],
                "offloads": [{"reference": {"artifact_id": "artifact"}}],
            },
        }
    action, request = state.next_operation()
    assert action["kind"] == ("context" if phase == "context" else "managed_context")
    return state, action, request


def admission(request):
    return {
        **{
            k: request[k]
            for k in ("scope", "run_id", "action_id", "release_digest", "execution_epoch", "phase")
        },
        "request_digest": digest(request),
    }


def proof(request):
    return {
        **{k: request[k] for k in ("scope", "action_id", "release_digest", "execution_epoch")},
        "request_digest": digest(request),
    }


def response_for(state, phase):
    if phase == "plan":
        return {
            "ok": True,
            "source_digest": digest(state.messages),
            "offloads": [],
            "references": [],
            "plan": None,
            "fallback": {"messages": state.messages},
        }
    if phase in {"read", "verify"}:
        return {"ok": True, "found": True, "reference": {"artifact_id": "artifact"}}
    return {"ok": True, "references": [], "messages": state.messages, "context_identity": {}}


def observe(state, action, response):
    method = state.accept_context if action["kind"] == "context" else state.accept_managed_context
    return method(action["id"], response)


@pytest.mark.parametrize("phase", ["context", "plan", "read", "verify", "finalize"])
@pytest.mark.parametrize("end_first", [False, True])
def test_original_read_requires_response_and_actual_end_in_either_order(phase, end_first):
    state, action, request = state_for(phase)
    granted = state.admit_context_dispatch(admission(request))
    assert granted["allowed"] is True and state.budget["spent"] == 0
    assert request["execution_epoch"] == "original-worker-uuid"
    assert request["phase"] == phase and action["request_digest"] == digest(request)
    if end_first:
        state.context_execution_ended(proof(request))
    else:
        observe(state, action, response_for(state, phase))
    assert not state.quiescent and state.next_operation() is None
    restored = copy.deepcopy(state)
    if end_first:
        observe(restored, action, response_for(restored, phase))
    else:
        restored.context_execution_ended(proof(request))
    assert restored.quiescent and restored.budget["spent"] == 0
    assert restored.diagnostics()["context_reads"][0]["status"] == "completed"
    assert restored.next_operation() is not None
    assert len([a for a in restored.actions if a.get("phase") == phase]) == 1


@pytest.mark.parametrize("phase", ["context", "plan", "read", "verify", "finalize"])
def test_cancel_and_activity_timeout_hold_read_until_actual_end(phase):
    state, action, request = state_for(phase)
    state.admit_context_dispatch(admission(request))
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    observe(state, action, {"ok": False, "code": "activity_outcome_unknown"})
    assert state.state == "cancelled" and not state.quiescent
    assert state.next_operation() is None and state.context_snapshot is None
    restored = copy.deepcopy(state)
    restored.context_execution_ended(proof(request))
    assert restored.state == "cancelled" and restored.quiescent
    assert restored.next_operation() is None and restored.budget["spent"] == 0


def test_timeout_without_admission_permanently_fences_late_read():
    state, action, request = state_for()
    observe(state, action, {"ok": False, "code": "activity_outcome_unknown"})
    assert state.state == "failed" and state.quiescent
    assert state.admit_context_dispatch(admission(request))["allowed"] is False
    with pytest.raises(DefinitionMismatch):
        state.context_execution_ended(proof(request))
    assert state.next_operation() is None


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("execution_epoch", "another-worker", DefinitionMismatch),
        ("request_digest", "0" * 64, DefinitionMismatch),
        ("release_digest", "1" * 64, DefinitionMismatch),
        ("scope", {"workspace": "other", "principal": "local-owner"}, AuthorizationDenied),
        ("action_id", "another-action", DefinitionMismatch),
    ],
)
def test_foreign_end_cannot_discharge_original_reader(field, value, error):
    state, action, request = state_for()
    state.admit_context_dispatch(admission(request))
    observe(state, action, response_for(state, "context"))
    forged = proof(request)
    forged[field] = value
    before = copy.deepcopy(state.diagnostics())
    with pytest.raises(error):
        state.context_execution_ended(forged)
    assert state.diagnostics() == before and not state.quiescent


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_epoch", "another-worker"),
        ("phase", "write"),
        ("request_digest", "0" * 64),
        ("run_id", "another-run"),
    ],
)
def test_read_admission_requires_exact_original_intent(field, value):
    state, _, request = state_for()
    payload = admission(request)
    payload[field] = value
    with pytest.raises(DefinitionMismatch):
        state.admit_context_dispatch(payload)
    assert not state.quiescent


def test_rejected_snapshot_is_failure_evidence_and_still_holds_reader():
    state, action, request = state_for()
    state.admit_context_dispatch(admission(request))
    observe(state, action, {"ok": True, "references": [], "messages": "wrong"})
    assert state.state == "failed" and state.error["code"] == "validation_error"
    assert state.context_snapshot is None and not state.quiescent
    assert state.diagnostics()["context_reads"][0]["response_rejected"] is True
    state.context_execution_ended(proof(request))
    assert state.quiescent and state.next_operation() is None


def test_duplicate_end_and_response_do_not_repeat_adoption_or_clear_next_action():
    state, action, request = state_for(sequence=True)
    state.admit_context_dispatch(admission(request))
    evidence = response_for(state, "context")
    observe(state, action, evidence)
    first = state.context_execution_ended(proof(request))
    model, _ = state.next_operation()
    before = copy.deepcopy(state.diagnostics())
    assert state.context_execution_ended(proof(request)) == first
    observe(state, action, evidence)
    assert state.diagnostics() == before and state.active_action == model["id"]
    with pytest.raises(IdempotencyConflict):
        observe(state, action, {"ok": False, "code": "different"})


def test_success_after_cancellation_only_records_late_evidence():
    state, action, request = state_for()
    state.admit_context_dispatch(admission(request))
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    observe(state, action, response_for(state, "context"))
    assert state.state == "cancelled" and state.context_snapshot is None and not state.quiescent
    state.context_execution_ended(proof(request))
    assert state.quiescent and state.state == "cancelled" and state.next_operation() is None


@pytest.mark.parametrize("epoch", [True, {}, " ", "x" * 1025])
def test_new_read_protocol_rejects_invalid_execution_epoch_before_dispatch(epoch):
    from relf_agent.errors import ValidationError

    with pytest.raises(ValidationError):
        state_for(epoch=epoch)


def test_read_protocol_keeps_original_parent_non_read_admission_validation():
    from relf_agent.temporal_parent_state import TemporalParentState

    from .test_temporal_composites import state as legacy_parent

    original = legacy_parent()
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        context_builder=LabelContext("leaf"),
    )
    parent = TemporalParentState(
        original.run_id,
        original.scope,
        "first",
        original.request,
        candidate(runtime.orchestration_release),
    )
    payload = {
        "scope": parent.scope,
        "action_id": "absent-original-action",
        "release_digest": parent.release_digest,
        "phase": "select",
        "request_digest": "0" * 64,
    }
    with pytest.raises(DefinitionMismatch):
        parent.admit_context_dispatch(payload)


def test_original_session_coordinator_holds_turn_after_cancel_until_read_end():
    from relf_agent.temporal_session_state import TemporalSessionState

    from .test_temporal_sessions import session, submit

    old, runtime = session(context_builder=LabelContext("session-context"))
    manifest = candidate(runtime.manifest)
    coordinator = TemporalSessionState(
        {
            **old.binding,
            "manifest": manifest,
            "scope": old.scope,
            "namespace_id": old.namespace_id,
            "session_namespace": "chat",
            "session_id": "same",
            "command_id": "open",
        }
    )
    submit(coordinator)
    intent = coordinator.start_intent()
    run = TemporalRunState(
        intent["run_id"],
        coordinator.scope,
        intent["command_id"],
        intent["request"],
        manifest,
        execution_epoch="original-uuid",
    )
    action, request = run.next_operation()
    run.admit_context_dispatch(admission(request))
    run.command("cancel", {"kind": "cancel", "scope": run.scope})
    observe(run, action, {"ok": False, "code": "activity_outcome_unknown"})
    evidence = {"scope": run.scope, "request": run.request, **run.diagnostics()}
    assert coordinator.adopt_observation(evidence) is False
    assert coordinator.snapshot()["busy"] is True
    assert submit(coordinator, "second", "follow up")["apply_state"] == "rejected"
    restored = copy.deepcopy(run)
    restored.context_execution_ended(proof(request))
    assert (
        coordinator.adopt_observation(
            {"scope": restored.scope, "request": restored.request, **restored.diagnostics()}
        )
        is True
    )
    assert submit(coordinator, "third", "follow up")["outcome"]["turn"]["turn_seq"] == 2
    assert runtime.providers["default"].calls == []


def test_original_parent_holds_child_escrow_until_native_read_end():
    from relf_agent.temporal_parent_state import TemporalParentState

    from .test_temporal_composites import state as legacy_parent

    original = legacy_parent()
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        context_builder=LabelContext("leaf"),
    )
    parent = TemporalParentState(
        original.run_id,
        original.scope,
        "first",
        original.request,
        candidate(runtime.orchestration_release),
    )
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    call = parent.next_calls()[0]
    child = TemporalRunState(
        call["run_id"], parent.scope, call["command_id"], call["request"], parent.manifest
    )
    action, request = child.next_operation()
    child.admit_context_dispatch(admission(request))
    child.command("cancel", {"kind": "cancel", "scope": child.scope})
    observe(child, action, {"ok": False, "code": "activity_outcome_unknown"})
    parent.observe(child.run_id, {"scope": child.scope, **child.diagnostics()})
    assert parent.budget["reserved"] == call["cap"] and not parent.children_quiescent
    child.context_execution_ended(proof(request))
    parent.observe(child.run_id, {"scope": child.scope, **child.diagnostics()})
    assert parent.budget["reserved"] == 0 and parent.children_quiescent


@pytest.mark.parametrize("phase", ["read", "verify"])
def test_artifact_read_response_requires_boolean_found(phase):
    state, action, request = state_for(phase)
    state.admit_context_dispatch(admission(request))
    response = response_for(state, phase)
    response["found"] = 1
    observe(state, action, response)
    assert state.state == "failed" and state.error["code"] == "validation_error"
    assert state.context_artifact_receipts == {} and not state.quiescent
    state.context_execution_ended(proof(request))
    assert state.quiescent


def test_malformed_start_refusal_is_rejected_without_losing_read_ownership():
    state, action, request = state_for()
    state.admit_context_dispatch(admission(request))
    observe(state, action, {"ok": False, "code": "full", "handler_not_started": 1})
    assert state.error["code"] == "validation_error" and not state.quiescent
    assert state.diagnostics()["context_reads"][0]["response_rejected"] is True
    state.context_execution_ended(proof(request))
    assert state.quiescent
