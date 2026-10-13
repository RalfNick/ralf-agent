"""Original History Coding permissions and independent native/actual stop gates."""

import copy
from dataclasses import asdict

import pytest

import ralf_agent as r
from ralf_agent.errors import RalfError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import digest, submission_request

from .test_temporal_engine import Provider, registry
from .test_temporal_tool_execution import admission, proof

RUNNER = {"kind": "finite-test-runner", "version": "1"}


def ready():
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=registry(),
        tool_execution=r.ToolExecutionOwner(version="1"),
    )
    state = TemporalRunState(
        "run",
        asdict(r.Scope()),
        "submit",
        submission_request(r.AgentSpec("a", "Code", tools=("read",)), "task", budget=8),
        runtime.manifest,
        execution_epoch="original-epoch",
    )
    model, _ = state.next_operation()
    state.accept_model(
        model["id"],
        {
            "ok": True,
            "output": None,
            "tool_calls": [{"name": "read", "arguments": {"task": "fix"}, "call_id": "c"}],
            "usage": None,
        },
    )
    # Pure History tests exercise a pinned selected Tool; runtime publication is
    # tested through the concrete PG/Codex integration suite.
    from ralf_agent.temporal_coding_protocol import JOURNAL_METHODS, RUNNER_METHODS, implementation

    state.manifest["coding_execution_protocol"] = {
        "version": 1,
        "implementation": implementation(),
        "tools": {
            "read": {
                "runner": RUNNER,
                "journal": {"kind": "pure-state-fixture"},
                "implementation": {name: "e" * 64 for name in RUNNER_METHODS},
                "journal_implementation": {name: "f" * 64 for name in JOURNAL_METHODS},
            }
        },
    }
    state.manifest.update(kernel="temporal-3", binding_protocol=11, dispatch_admission="history-1")
    state.manifest["tools"]["read"]["config"]["delegated_runner"] = {"version": 1, "runner": RUNNER}
    state.manifest["tools"]["read"]["requires_approval"] = True
    assert state.next_operation() is None
    pending = state.actions[-1]
    state.command(
        "approve",
        {
            "kind": "approve",
            "scope": state.scope,
            "action_id": pending["id"],
            "digest": pending["digest"],
            "approved": True,
        },
    )
    action, request = state.next_operation()
    return state, action, request


def bind(request):
    native = request["coding_request"]
    return {
        "request": native,
        "runner": RUNNER,
        "dispatch": native["dispatch"],
        "environment": {
            "expected_generation": digest({"dispatch": native["dispatch"], "runner": RUNNER})[:32]
        },
    }


def grant(state, request):
    state.admit_tool_dispatch(coding_admission(request))
    state.coding_receipt({**admission(request), "kind": "owner", "evidence": OWNER})
    return state.admit_coding_phase(
        {**admission(request), "method": "prepare", "params": {}, "binding": bind(request)}
    )


def test_native_intent_precedes_complete_tool_claim_fingerprint():
    state, action, request = ready()
    assert "coding_request" in request
    assert request["coding_request"]["reservation"]["id"] == action["attempts"][0]["id"]
    assert state.tool_executions[action["id"]]["request_digest"] == digest(request)
    assert len(action["attempts"]) == 1 and state.budget["reserved"] == 1
    assert grant(state, request)["execute"] is True
    assert grant(state, request)["execute"] is False
    recovered = copy.deepcopy(state)
    assert grant(recovered, request)["execute"] is False


def test_cancel_waits_for_native_fence_and_actual_original_invocation_end():
    state, action, request = ready()
    grant(state, request)
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    assert state.state == "cancelling"
    with pytest.raises(RalfError):
        grant(state, request)
    state.operation_unknown(action["id"], "worker-lost")
    stop_action, stop_request = state.next_operation()
    assert stop_action["kind"] == "coding_stop" and stop_request == request
    assert state.budget["unknown"] == 1
    namespace = bind(request)["environment"]
    state.coding_receipt(
        {
            **admission(request),
            "kind": "stop",
            "evidence": {
                "identity": namespace,
                "generation": namespace["expected_generation"],
                "container_id": "b" * 64,
                "fenced": True,
                "stopped": True,
                "retired": True,
                "container_present": False,
                "running": False,
            },
        }
    )
    assert state.state == "cancelling"
    state.tool_execution_ended(proof(request))
    assert state.state == "cancelled" and state.budget["unknown"] == 1


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "run_id",
        "action_id",
        "release_digest",
        "request_digest",
        "execution_epoch",
        "invocation_id",
    ],
)
def test_foreign_coding_grant_cannot_mutate_original_intent(field):
    state, action, request = ready()
    state.admit_tool_dispatch(coding_admission(request))
    payload = {**admission(request), "method": "prepare", "params": {}, "binding": bind(request)}
    payload[field] = (
        {"workspace": "foreign", "principal": "foreign"} if field == "scope" else "f" * 32
    )
    before = copy.deepcopy(action)
    with pytest.raises(RalfError):
        state.admit_coding_phase(payload)
    assert action == before


def test_success_response_cannot_settle_without_history_native_candidate():
    state, action, request = ready()
    grant(state, request)
    state.accept_tool(action["id"], {"ok": True, "result": {"native": {"status": "completed"}}})
    assert action["status"] == "outcome_unknown" and state.budget["unknown"] == 1
    assert state.next_operation()[0]["kind"] == "coding_stop"


def test_stop_admission_recovers_original_only_and_never_claims_new_business():
    state, action, request = ready()
    grant(state, request)
    original = admission(request)
    recovery = {**original, "invocation_id": "c" * 32}
    result = state.admit_coding_stop(recovery)
    assert result["original_invocation_id"] == original["invocation_id"]
    assert state.tool_executions[action["id"]]["invocation_id"] == original["invocation_id"]
    assert state.coding_state(recovery)["request"] == request["coding_request"]
    with pytest.raises(RalfError):
        state.admit_coding_phase(
            {**recovery, "method": "prepare", "params": {}, "binding": bind(request)}
        )


def test_workflow_routes_original_stop_before_next_business(monkeypatch):
    import asyncio

    from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow

    state, action, request = ready()
    grant(state, request)
    state.operation_unknown(action["id"], "worker-lost")
    wf = object.__new__(TemporalRunWorkflow)
    wf.state, wf.wake_revision = state, 0

    # External SDK boundary only: keep the actual Workflow loop/state logic.
    async def notify():
        return None

    wf._notify_session = notify
    calls = []

    async def execute(name, payload, **options):
        calls.append((name, payload, options))
        return {"ok": False, "code": "stop-query-failed"}

    async def waiting(predicate, **options):
        raise RuntimeError("durable receiver waiting")

    monkeypatch.setattr(workflow, "execute_activity", execute)
    monkeypatch.setattr(workflow, "wait_condition", waiting)
    with pytest.raises(RuntimeError, match="durable receiver waiting"):
        asyncio.run(wf.run({"activity_timeout": 3}))
    assert len(calls) == 1 and calls[0][0] == "ralf_coding_stop"
    assert calls[0][1] == request
    assert calls[0][2]["retry_policy"].maximum_attempts == 1
    assert state.budget["unknown"] == 1 and action["status"] == "outcome_unknown"
    assert wf.coding_state(admission(request))["state"]["fenced"] is False


@pytest.mark.parametrize(
    "field,value", [("arguments", {"task": "replace original task"}), ("digest", "foreign")]
)
def test_changed_original_action_refuses_native_phase(field, value):
    state, action, request = ready()
    state.admit_tool_dispatch(coding_admission(request))
    action[field] = value
    with pytest.raises(RalfError):
        state.admit_coding_phase(
            {**admission(request), "method": "prepare", "params": {}, "binding": bind(request)}
        )


def completed_native(state, action, request):
    grant(state, request)
    namespace = bind(request)["environment"]
    state.coding_receipt(
        {
            **admission(request),
            "kind": "prepared",
            "evidence": {
                "identity": namespace,
                "generation": namespace["expected_generation"],
                "container_id": "b" * 64,
            },
        }
    )
    binding = state.coding_state(admission(request))["state"]["binding"]
    params = {
        "cwd": "/workspace",
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "ephemeral": False,
    }
    assert (
        state.admit_coding_phase(
            {**admission(request), "method": "thread/start", "params": params, "binding": binding}
        )["execute"]
        is True
    )
    state.coding_receipt({**admission(request), "kind": "thread", "evidence": {"thread_id": "t"}})
    params.pop("ephemeral")
    params.update(threadId="t", input=[{"type": "text", "text": "fix", "text_elements": []}])
    assert (
        state.admit_coding_phase(
            {**admission(request), "method": "turn/start", "params": params, "binding": binding}
        )["execute"]
        is True
    )
    state.coding_receipt(
        {**admission(request), "kind": "turn", "evidence": {"thread_id": "t", "turn_id": "u"}}
    )
    state.coding_receipt(
        {
            **admission(request),
            "kind": "observation",
            "evidence": {
                "thread_id": "t",
                "turn_id": "u",
                "native_status": "completed",
                "final_thread_read": True,
            },
        }
    )
    stop = {
        "identity": namespace,
        "generation": namespace["expected_generation"],
        "container_id": "b" * 64,
        "fenced": True,
        "stopped": True,
        "retired": True,
        "container_present": False,
        "running": False,
    }
    state.coding_receipt({**admission(request), "kind": "stop", "evidence": stop})
    candidate = {
        "native": {"status": "completed", "thread_id": "t", "turn_id": "u"},
        "stop": {
            "container_id": "b" * 64,
            "generation": namespace["expected_generation"],
            "fenced": True,
        },
    }
    state.coding_receipt(
        {**admission(request), "kind": "result_candidate", "evidence": {"result": candidate}}
    )
    return candidate


def test_persisted_candidate_lost_response_is_adopted_without_second_attempt():
    state, action, request = ready()
    candidate = completed_native(state, action, request)
    state.tool_execution_ended(proof(request))
    state.operation_unknown(action["id"], "activity-response-lost")
    operation = state.next_operation()
    assert action["status"] == "completed" and action["result"] == candidate
    assert state.budget["unknown"] == 0 and state.budget["spent"] == 2
    assert len(action["attempts"]) == 1 and operation[0]["kind"] == "model"
    assert state.pending_acks[0]["coding_request"] == request["coding_request"]


def test_stop_query_candidate_adoption_keeps_missing_actual_owner_end_gate():
    state, action, request = ready()
    candidate = completed_native(state, action, request)
    state.operation_unknown(action["id"], "activity-response-lost")
    stop_action, _ = state.next_operation()
    state.accept_coding_stop(
        action["id"], {"ok": True, "result": candidate, "source": "original-native-query"}
    )
    assert action["status"] == "completed" and state.next_operation() is None
    assert state.tool_executions[action["id"]]["execution_stopped"] is False
    state.tool_execution_ended(proof(request))
    assert state.next_operation()[0]["kind"] == "model"


def test_repeated_stop_admission_still_checks_original_action():
    state, action, request = ready()
    grant(state, request)
    recovery = {**admission(request), "invocation_id": "c" * 32}
    state.admit_coding_stop(recovery)
    action["arguments"] = {"task": "foreign"}
    with pytest.raises(RalfError):
        state.admit_coding_stop(recovery)


OWNER = {
    "version": 1,
    "pid": 12345,
    "start": "original-process-birth",
    "deployment": "d" * 64,
    "invocation_id": "a" * 32,
}


def test_first_native_grant_requires_prior_original_process_owner_receipt():
    state, action, request = ready()
    with pytest.raises(RalfError):
        state.admit_tool_dispatch(admission(request))
    with pytest.raises(RalfError):
        state.admit_coding_phase(
            {**admission(request), "method": "prepare", "params": {}, "binding": bind(request)}
        )


def owner_dead_payload(request, *, owner=OWNER, present=False, fenced=True):
    return {
        **admission(request, "c" * 32),
        "evidence": {
            "owner": copy.deepcopy(owner),
            "process_present": present,
            "native_fenced": fenced,
        },
    }


def native_stop(state, request):
    namespace = bind(request)["environment"]
    state.coding_receipt(
        {
            **admission(request),
            "kind": "stop",
            "evidence": {
                "identity": namespace,
                "generation": namespace["expected_generation"],
                "container_id": "b" * 64,
                "fenced": True,
                "stopped": True,
                "retired": True,
                "container_present": False,
                "running": False,
            },
        }
    )


@pytest.mark.parametrize("fault", ["unfenced", "foreign_owner", "not_admitted", "alive"])
def test_process_death_adoption_rejects_incomplete_or_foreign_original_proof(fault):
    state, action, request = ready()
    grant(state, request)
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    state.operation_unknown(action["id"], "worker-lost")
    payload = owner_dead_payload(request)
    if fault != "not_admitted":
        state.admit_coding_stop(admission(request, "c" * 32))
    if fault != "unfenced":
        native_stop(state, request)
    if fault == "foreign_owner":
        payload["evidence"]["owner"]["start"] = "other-process"
    if fault == "alive":
        payload["evidence"]["process_present"] = True
    before = copy.deepcopy(state.tool_executions)
    with pytest.raises(RalfError):
        state.coding_owner_stopped(payload)
    assert state.tool_executions == before and state.state == "cancelling"


def test_original_process_death_plus_native_fence_cancels_without_settling_unknown_effect():
    state, action, request = ready()
    grant(state, request)
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    state.operation_unknown(action["id"], "worker-lost")
    state.admit_coding_stop(admission(request, "c" * 32))
    native_stop(state, request)
    state.coding_owner_stopped(owner_dead_payload(request))
    original = state.tool_executions[action["id"]]
    assert state.state == "cancelled" and original["execution_stopped"] is True
    assert original["invocation_id"] == "a" * 32 and "end_proof" not in original
    assert state.budget["unknown"] == 1 and action["status"] == "outcome_unknown"
    assert state.quiescent is False
    events = len(state.event_log)
    state.coding_owner_stopped(owner_dead_payload(request))
    assert len(state.event_log) == events


def no_prepare_recovery():
    state, action, request = ready()
    state.admit_tool_dispatch(coding_admission(request))
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    state.operation_unknown(action["id"], "worker-lost-before-history-owner")
    state.admit_coding_stop(admission(request, "c" * 32))
    return state, action, request


def test_cold_original_pg_owner_adoption_preserves_original_process_identity():
    state, action, request = no_prepare_recovery()
    state.coding_receipt({**admission(request, "c" * 32), "kind": "owner", "evidence": OWNER})
    assert action["delegated_execution"]["owner"] == OWNER
    assert state.tool_executions[action["id"]]["invocation_id"] == "a" * 32
    with pytest.raises(RalfError):
        state.coding_receipt(
            {
                **admission(request, "c" * 32),
                "kind": "owner",
                "evidence": {**OWNER, "invocation_id": "c" * 32},
            }
        )


def test_no_prepare_resource_tombstone_recovers_without_fake_container_receipt():
    state, action, request = no_prepare_recovery()
    state.coding_receipt({**admission(request, "c" * 32), "kind": "owner", "evidence": OWNER})
    state.coding_receipt(
        {
            **admission(request, "c" * 32),
            "kind": "unprepared",
            "evidence": {"namespace_binding": bind(request), "prepare_granted": False},
        }
    )
    native = action["delegated_execution"]
    assert native["fenced"] is True and native["pending_stop"] is False
    assert "prepared" not in native and "stop" not in native and native["grants"] == {}
    state.coding_owner_stopped(owner_dead_payload(request))
    assert state.state == "cancelled" and state.budget["unknown"] == 1


@pytest.mark.parametrize("fault", ["foreign_namespace", "granted_prepare", "business_invocation"])
def test_unprepared_tombstone_cannot_clear_started_or_foreign_resource(fault):
    state, action, request = ready()
    if fault == "granted_prepare":
        grant(state, request)
    else:
        state.admit_tool_dispatch(coding_admission(request))
    payload = {
        **admission(request, "c" * 32),
        "kind": "unprepared",
        "evidence": {"namespace_binding": bind(request), "prepare_granted": False},
    }
    if fault != "business_invocation":
        state.admit_coding_stop(admission(request, "c" * 32))
    else:
        payload["invocation_id"] = "a" * 32
    if fault == "foreign_namespace":
        payload["evidence"]["namespace_binding"]["environment"]["expected_generation"] = "foreign"
    before = copy.deepcopy(action["delegated_execution"])
    with pytest.raises(RalfError):
        state.coding_receipt(payload)
    assert action["delegated_execution"] == before


def test_lost_response_before_first_grant_still_queries_original_pg_resource():
    state, action, request = ready()
    state.admit_tool_dispatch(coding_admission(request))
    state.tool_execution_ended(proof(request))
    state.operation_unknown(action["id"], "pg-intent-response-lost")
    operation = state.next_operation()
    assert operation is not None and operation[0]["kind"] == "coding_stop"
    assert operation[1] == request
    state.accept_coding_stop(action["id"], {"ok": False, "code": "query_failed"})
    assert state.next_operation() is None
    state.retry_blocked()
    assert state.next_operation()[0]["kind"] == "coding_stop"


def test_scoped_workflow_cleanup_reads_immutable_original_coding_requests():
    from ralf_agent.temporal_workflow import TemporalRunWorkflow

    state, action, request = ready()
    wf = object.__new__(TemporalRunWorkflow)
    wf.state, wf.wake_revision = state, 0
    response = wf.view({"scope": state.scope, "kind": "coding_requests"})
    assert response == [request]
    response[0]["coding_request"]["dispatch"]["arguments"]["task"] = "foreign"
    assert wf.view({"scope": state.scope, "kind": "coding_requests"}) == [request]
    assert wf.view(
        {"scope": {"workspace": "foreign", "principal": "foreign"}, "kind": "coding_requests"}
    ) == {"error": "authorization_denied"}
    state.manifest.pop("coding_execution_protocol")
    assert wf.view({"scope": state.scope, "kind": "coding_requests"}) == {
        "error": "definition_mismatch"
    }


def test_coding_claim_atomically_records_owner_before_any_pg_or_native_grant():
    state, action, request = ready()
    result = state.admit_tool_dispatch({**admission(request), "owner": OWNER})
    assert result["claimed"] is True and result["allowed"] is True
    native = action["delegated_execution"]
    assert native["owner"] == OWNER and native["grants"] == {}
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    state.operation_unknown(action["id"], "killed-immediately-after-claim")
    state.admit_coding_stop(admission(request, "c" * 32))
    state.coding_owner_stopped(owner_dead_payload(request))
    assert state.state == "cancelled" and state.budget["unknown"] == 1
    assert "prepared" not in native and "stop" not in native


@pytest.mark.parametrize("fault", ["missing", "wrong_invocation", "changed_original"])
def test_invalid_coding_claim_owner_never_mutates_original_claim(fault):
    state, action, request = ready()
    payload = {**admission(request), "owner": copy.deepcopy(OWNER)}
    if fault == "missing":
        payload.pop("owner")
    elif fault == "wrong_invocation":
        payload["owner"]["invocation_id"] = "c" * 32
    else:
        state.admit_tool_dispatch(payload)
        payload["owner"]["start"] = "replacement-process"
    before = copy.deepcopy(state.tool_executions)
    with pytest.raises(RalfError):
        state.admit_tool_dispatch(payload)
    assert state.tool_executions == before


def test_foreign_coding_claim_cannot_replace_original_atomic_process_owner():
    state, action, request = ready()
    state.admit_tool_dispatch({**admission(request), "owner": OWNER})
    foreign = {**OWNER, "pid": 54321, "start": "another-process", "invocation_id": "c" * 32}
    result = state.admit_tool_dispatch({**admission(request, "c" * 32), "owner": foreign})
    assert result["claimed"] is False and result["allowed"] is False
    assert action["delegated_execution"]["owner"] == OWNER


def coding_admission(request, invocation_id="a" * 32):
    return {**admission(request, invocation_id), "owner": {**OWNER, "invocation_id": invocation_id}}


def namespace_absence(request):
    namespace = bind(request)["environment"]
    return {
        "identity": namespace,
        "generation": namespace["expected_generation"],
        "container_present": False,
        "namespace_confirmed": True,
        "owner": OWNER,
        "process_present": False,
    }


def test_namespace_absence_adopts_lost_prepare_grant_without_fake_container_fence():
    state, action, request = ready()
    grant(state, request)
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    state.operation_unknown(action["id"], "prepare-grant-response-lost")
    state.admit_coding_stop(admission(request, "c" * 32))
    state.coding_receipt(
        {
            **admission(request, "c" * 32),
            "kind": "namespace_absent",
            "evidence": namespace_absence(request),
        }
    )
    native = action["delegated_execution"]
    assert native["fenced"] is True and native["pending_stop"] is False
    assert "prepared" not in native and "stop" not in native and "result_candidate" not in native
    assert state.state == "cancelling" and state.budget["unknown"] == 1
    state.coding_owner_stopped(owner_dead_payload(request))
    assert state.state == "cancelled" and state.budget["unknown"] == 1


@pytest.mark.parametrize(
    "fault", ["missing_prepare", "foreign_owner", "foreign_namespace", "not_admitted", "prepared"]
)
def test_namespace_absence_requires_original_prepare_without_prepared_native_resource(fault):
    state, action, request = ready()
    if fault == "missing_prepare":
        state.admit_tool_dispatch(coding_admission(request))
    else:
        grant(state, request)
    if fault == "prepared":
        namespace = bind(request)["environment"]
        state.coding_receipt(
            {
                **admission(request),
                "kind": "prepared",
                "evidence": {
                    "identity": namespace,
                    "generation": namespace["expected_generation"],
                    "container_id": "b" * 64,
                },
            }
        )
    payload = {
        **admission(request, "c" * 32),
        "kind": "namespace_absent",
        "evidence": namespace_absence(request),
    }
    if fault != "not_admitted":
        state.admit_coding_stop(admission(request, "c" * 32))
    if fault == "foreign_owner":
        payload["evidence"]["owner"] = {**OWNER, "pid": 54321}
    if fault == "foreign_namespace":
        payload["evidence"]["identity"] = {"expected_generation": "foreign"}
    before = copy.deepcopy(action["delegated_execution"])
    with pytest.raises(RalfError):
        state.coding_receipt(payload)
    assert action["delegated_execution"] == before
