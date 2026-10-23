"""Root completion belongs to the actual Parent, including budget and receipts."""

import copy
from dataclasses import asdict

import pytest

from relf_agent import Scope
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.recall import RecallQuery
from relf_agent.temporal_parent_state import TemporalParentState
from relf_agent.temporal_session_state import TemporalSessionState
from relf_agent.types import digest

from .test_temporal_session_tree_admission import candidate, turn
from .test_temporal_session_tree_sources import setup


def parent(*, budget=32):
    host, request, stores = setup()
    session = TemporalSessionState(candidate(host, request))
    turn(session)
    # Actual submitted budget remains immutable; use a separate original command
    # for budget tests rather than editing the accepted Parent request.
    if budget != 32:
        session = TemporalSessionState(candidate(host, request))
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "budget",
                "session_ref": session.ref.to_dict(),
                "input": "question",
                "budget": budget,
            }
        )
    intent = session.active
    state = TemporalParentState(
        intent["run_id"], session.scope, intent["command_id"], intent["request"], intent["manifest"]
    )
    return state, session, stores[0]


def read_response(state, session, store, request):
    page = store.read_page(Scope(), session.key.storage_key, RecallQuery(**request["query"]))
    from relf_agent.temporal_session_data_state import references

    source = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "node": "root",
        "registration_digest": digest(state.manifest["session_data"]),
        "address": session.key.storage_key,
        "query": request["query"],
        "page": asdict(page),
        "revision": 0,
    }
    return {"ok": True, "session_data": source, "session_data_references": references(source)}


def prepare_read(state, session, store):
    assert state.next_calls() == []
    action, request = state.next_session_operation()
    assert action["kind"] == "session_root_read"
    assert "step" not in request and request["address"] == session.key.storage_key
    response = read_response(state, session, store, request)
    state.accept_session_root(action["id"], response)
    return response


def apply_save(state, store, *, stop=True):
    action, request = state.next_session_operation()
    phase, intent = request["phase"], request["intent"]
    assert "step" not in request and intent["source_kind"] == "parent-aggregate"
    if phase in {"inspect", "verify"}:
        response = {
            "ok": True,
            "inspection": store.inspect_message(Scope(), intent["address"], intent["message_id"]),
            "dispatched": False,
        }
    elif phase == "session-write":
        grant = state.admit_context_dispatch(
            {
                "scope": state.scope,
                "release_digest": state.release_digest,
                "action_id": action["id"],
                "phase": phase,
                "request_digest": digest(request),
            }
        )
        assert grant["allowed"]
        revision = store.append(
            Scope(),
            intent["address"],
            intent["message"],
            expected_revision=intent["expected_revision"],
            message_id=intent["message_id"],
        )
        response = {"ok": True, "revision": revision, "dispatched": True, "execution_stopped": stop}
    else:
        assert phase == "adopt"
        response = {"ok": True, "intent_digest": digest(intent), "dispatched": False}
    state.accept_session(action["id"], response)
    return action, request


def test_root_read_is_original_and_once_and_child_caps_exclude_save_allowance():
    state, session, store = parent()
    original = copy.deepcopy(state.request)
    assert state.budget["reserved"] == 1 and state.budget["remaining"] == 31
    assert not state.quiescent
    snapshot = prepare_read(state, session, store)
    assert state.request == original
    assert state.root_session_snapshot == snapshot
    assert copy.deepcopy(state).next_session_operation() is None
    state.accept_selection(
        {
            "calls": [{"id": "writer", "member": "writer", "input": "task"}],
            "done": False,
            "result": None,
        }
    )
    call = state.next_calls()[0]
    assert call["request"]["session_root_snapshot"] == snapshot
    assert call["request"]["session_lineage"]["path"] == [
        "team",
        "members",
        "writer",
        "calls",
        "writer",
    ]
    assert state.budget["reserved"] == 9 and state.budget["remaining"] == 23


def test_original_aggregate_receipt_is_adopted_before_success_and_turn_release():
    state, session, store = parent()
    prepare_read(state, session, store)
    state.accept_selection({"calls": [], "done": True, "result": "answer"})
    assert state.state != "succeeded" and state.result is None
    assert not state.quiescent
    apply_save(state, store)  # inspect
    apply_save(state, store)  # actual write
    assert store.read(Scope(), session.key.storage_key)[0] == 1
    assert state.state != "succeeded"
    apply_save(state, store)  # receipt received
    restored = copy.deepcopy(state)
    assert restored.state != "succeeded"
    apply_save(restored, store)  # separate adoption
    assert restored.state == "succeeded" and restored.result == "answer"
    assert restored.budget["spent"] == 1
    assert restored.budget["reserved"] == restored.budget["unknown"] == 0 and restored.quiescent
    assert session.adopt_observation(
        {"scope": restored.scope, "request": restored.request, **restored.diagnostics()}
    )
    assert not session.snapshot()["busy"]


def test_cancel_before_any_root_write_releases_only_preallocated_allowance():
    state, _, _ = parent()
    state.command("stop", {"kind": "cancel", "scope": state.scope})
    assert state.next_session_operation() is None
    assert state.state == "cancelled" and state.quiescent
    assert state.budget["reserved"] == state.budget["unknown"] == state.budget["spent"] == 0


def test_read_failure_cannot_dispatch_children_or_leak_root_allowance():
    state, _, _ = parent()
    action, _ = state.next_session_operation()
    state.accept_session_root(action["id"], {"ok": False, "code": "source-unavailable"})
    assert state.state == "failed" and state.next_calls() == []
    assert state.next_session_operation() is None and state.quiescent
    assert state.budget["reserved"] == 0


def test_root_write_reservation_is_required_before_children_even_on_zero_budget():
    state, _, _ = parent(budget=0)
    assert state.state == "failed" and state.error["code"] == "budget_exceeded"
    assert state.next_calls() == [] and state.next_session_operation() is None
    assert state.quiescent and state.budget["reserved"] == 0


def test_forged_root_read_is_refused_without_adoption():
    state, session, store = parent()
    action, request = state.next_session_operation()
    response = read_response(state, session, store, request)
    response["session_data"]["address"] = "other-member"
    with pytest.raises((DefinitionMismatch, ValidationError)):
        state.accept_session_root(action["id"], response)
    assert state.root_session_snapshot is None
    assert state.next_calls() == []


def test_committed_root_receipt_does_not_release_a_live_handler_and_cancel_is_final():
    state, session, store = parent()
    prepare_read(state, session, store)
    state.accept_selection({"calls": [], "done": True, "result": "answer"})
    apply_save(state, store)
    writer, request = apply_save(state, store, stop=False)
    apply_save(state, store)
    apply_save(state, store)
    assert state.state == "waiting_reconciliation"
    assert state.budget["unknown"] == 1 and not state.quiescent
    state.command("stop", {"kind": "cancel", "scope": state.scope})
    assert state.state == "cancelled" and not state.quiescent
    proof = {
        "scope": state.scope,
        "action_id": writer["id"],
        "release_digest": state.release_digest,
        "request_digest": digest(request),
    }
    state.session_execution_ended(proof)
    state.retry_blocked()  # The inherited SDK end Update invokes this exact hook.
    state.command("recover", {"kind": "drive", "scope": state.scope})
    apply_save(state, store)
    apply_save(state, store)
    assert state.state == "cancelled" and state.result is None and state.quiescent
    assert state.budget["unknown"] == state.budget["reserved"] == 0
    assert state.budget["spent"] == 1
    assert store.read(Scope(), session.key.storage_key)[0] == 1


def test_parent_root_read_cancel_waits_for_read_observation_then_releases_allowance():
    state, session, store = parent()
    action, request = state.next_session_operation()
    state.command("stop", {"kind": "cancel", "scope": state.scope})
    assert not state.quiescent and state.next_session_operation() is None
    state.accept_session_root(action["id"], read_response(state, session, store, request))
    assert state.state == "cancelled" and state.root_session_snapshot is None
    assert state.quiescent and state.budget["reserved"] == 0


def test_root_save_allowance_is_released_when_original_receipt_already_exists():
    state, session, store = parent()
    prepare_read(state, session, store)
    state.accept_selection({"calls": [], "done": True, "result": "answer"})
    intent = state.session_stages["root"]["intent"]
    store.append(
        Scope(),
        intent["address"],
        intent["message"],
        expected_revision=0,
        message_id=intent["message_id"],
    )
    apply_save(state, store)
    apply_save(state, store)
    assert state.state == "succeeded" and state.quiescent
    assert state.budget["reserved"] == state.budget["unknown"] == state.budget["spent"] == 0


def test_legacy_planning_conclusion_preserves_original_revision_for_control_replay():
    from relf_agent import AgentSpec, DynamicWorkflowSpec, ToolRegistry
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.types import submission_request

    from .test_temporal_sessions import Provider

    host = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    definition = DynamicWorkflowSpec("d", {"writer": AgentSpec("writer", "Write")})
    state = TemporalParentState(
        "legacy",
        asdict(Scope()),
        "submit",
        submission_request(definition, "task"),
        host.orchestration_release,
    )
    before = state.revision
    state.accept_selection({"status": "refused", "reason": "insufficient evidence"})
    assert state.state == "succeeded" and state.result["status"] == "refused"
    assert state.revision == before + 1  # Original accepted conclusion is one transition.


def test_initial_root_inspection_failure_recovers_original_aggregate_without_new_plan():
    state, session, store = parent()
    prepare_read(state, session, store)
    state.accept_selection({"calls": [], "done": True, "result": "answer"})
    original = copy.deepcopy(state.root_aggregate)
    action, _ = state.next_session_operation()
    state.accept_session(
        action["id"], {"ok": False, "code": "temporary-inspection-failure", "dispatched": False}
    )
    assert not state.quiescent and state.state != "succeeded"
    restored = copy.deepcopy(state)
    restored.command("recover", {"kind": "drive", "scope": restored.scope})
    for _ in range(4):
        apply_save(restored, store)
    assert restored.state == "succeeded" and restored.quiescent
    assert restored.root_aggregate == original
    assert restored.budget["spent"] == 1
    assert store.read(Scope(), session.key.storage_key)[0] == 1


@pytest.mark.parametrize("damage", ["missing", "message", "oversized"])
def test_invalid_root_receipt_never_confirms_parent_success(damage):
    state, session, store = parent()
    prepare_read(state, session, store)
    state.accept_selection({"calls": [], "done": True, "result": "answer"})
    apply_save(state, store)
    apply_save(state, store)
    action, request = state.next_session_operation()
    inspection = store.inspect_message(
        Scope(), request["intent"]["address"], request["intent"]["message_id"]
    )
    if damage == "missing":
        inspection["receipt"] = None
    elif damage == "oversized":
        inspection["receipt"]["message"]["content"] = "x" * 1048576
    else:
        inspection["receipt"]["message"]["content"] = "changed"
    state.accept_session(action["id"], {"ok": True, "inspection": inspection, "dispatched": False})
    assert state.state == "waiting_reconciliation" and not state.quiescent
    assert state.budget["unknown"] == 1
    assert store.read(Scope(), session.key.storage_key)[0] == 1
    assert copy.deepcopy(state).root_aggregate == state.root_aggregate


def test_previous_root_attempt_end_does_not_stop_the_current_original_write():
    state, session, store = parent()
    prepare_read(state, session, store)
    state.accept_selection({"calls": [], "done": True, "result": "answer"})
    apply_save(state, store)
    previous, previous_request = state.next_session_operation()

    def grant(action, request):
        return state.admit_context_dispatch(
            {
                "scope": state.scope,
                "action_id": action["id"],
                "release_digest": state.release_digest,
                "phase": request["phase"],
                "request_digest": digest(request),
            }
        )

    assert grant(previous, previous_request)["allowed"]
    state.accept_session(
        previous["id"],
        {
            "ok": False,
            "code": "stopped-before-commit",
            "dispatched": True,
            "execution_stopped": True,
        },
    )
    state.retry_blocked()
    apply_save(state, store)
    current, current_request = state.next_session_operation()
    assert grant(current, current_request)["allowed"]
    state.accept_session(
        current["id"],
        {"ok": False, "code": "unknown", "dispatched": True, "execution_stopped": False},
    )
    proof = {
        "scope": state.scope,
        "action_id": previous["id"],
        "release_digest": state.release_digest,
        "request_digest": digest(previous_request),
    }
    assert state.session_execution_ended(proof)["execution_stopped"]
    assert state.session_execution_ended(proof)["execution_stopped"]
    assert not state.session_stages["root"]["execution_stopped"]
    assert state.remote_uncertain and state.budget["unknown"] == 1
    assert not state.quiescent


def test_root_timeout_without_admission_fences_late_dispatch_before_retry():
    state, session, store = parent()
    prepare_read(state, session, store)
    state.accept_selection({"calls": [], "done": True, "result": "answer"})
    apply_save(state, store)
    old, request = state.next_session_operation()
    state.accept_session(
        old["id"],
        {
            "ok": False,
            "code": "activity_outcome_unknown",
            "dispatched": True,
            "execution_stopped": False,
        },
    )
    assert state.session_stages["root"]["execution_stopped"]
    assert not state.admit_context_dispatch(
        {
            "scope": state.scope,
            "action_id": old["id"],
            "release_digest": state.release_digest,
            "phase": request["phase"],
            "request_digest": digest(request),
        }
    )["allowed"]
    state.retry_blocked()
    apply_save(state, store)
    apply_save(state, store)
    apply_save(state, store)
    apply_save(state, store)
    assert state.state == "succeeded" and state.quiescent
    assert state.budget["spent"] == 1
    assert store.read(Scope(), session.key.storage_key)[0] == 1


@pytest.mark.parametrize("cancel", [False, True])
def test_admitted_root_read_timeout_retains_turn_until_exact_handler_end(cancel):
    state, session, _ = parent()
    action, request = state.next_session_operation()
    proof = {
        "scope": state.scope,
        "release_digest": state.release_digest,
        "action_id": action["id"],
        "request_digest": digest(request),
    }
    assert state.admit_context_dispatch({**proof, "phase": "session-root-read"})["allowed"]
    if cancel:
        state.command("stop", {"kind": "cancel", "scope": state.scope})
    state.accept_session_root(
        action["id"],
        {
            "ok": False,
            "code": "activity_outcome_unknown",
            "dispatched": False,
            "execution_stopped": False,
        },
    )
    assert not state.quiescent
    assert not {"scope": state.scope, "request": state.request, **state.diagnostics()}["workflow"][
        "remote_stop_confirmed"
    ]
    assert not session.adopt_observation(
        {"scope": state.scope, "request": state.request, **state.diagnostics()}
    )
    assert state.next_session_operation() is None
    with pytest.raises(DefinitionMismatch):
        state.session_execution_ended({**proof, "request_digest": "0" * 64})
    assert state.session_execution_ended(proof)["execution_stopped"]
    assert state.session_execution_ended(proof)["execution_stopped"]
    assert state.quiescent and session.adopt_observation(
        {"scope": state.scope, "request": state.request, **state.diagnostics()}
    )
    assert state.state == ("cancelled" if cancel else "failed")
    assert state.budget["reserved"] == state.budget["unknown"] == 0


def test_root_read_timeout_without_grant_fences_late_dispatch():
    state, _, _ = parent()
    action, request = state.next_session_operation()
    state.accept_session_root(
        action["id"], {"ok": False, "code": "activity_outcome_unknown", "execution_stopped": False}
    )
    assert state.quiescent
    assert not state.admit_context_dispatch(
        {
            "scope": state.scope,
            "release_digest": state.release_digest,
            "action_id": action["id"],
            "request_digest": digest(request),
            "phase": "session-root-read",
        }
    )["allowed"]


def test_admitted_root_read_owner_refusal_without_start_can_settle():
    state, _, _ = parent()
    action, request = state.next_session_operation()
    assert state.admit_context_dispatch(
        {
            "scope": state.scope,
            "release_digest": state.release_digest,
            "action_id": action["id"],
            "request_digest": digest(request),
            "phase": "session-root-read",
        }
    )["allowed"]
    state.accept_session_root(
        action["id"], {"ok": False, "code": "memory_backend_error", "handler_not_started": True}
    )
    assert state.state == "failed" and state.quiescent
