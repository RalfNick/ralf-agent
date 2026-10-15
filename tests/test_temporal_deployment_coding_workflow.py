"""SDK Workflow routes to its original scoped deployment/Coding authority."""

import asyncio
import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")
from ralf_agent.temporal_deployment_admission import registry_id
from ralf_agent.temporal_workflow import (
    TemporalCommandRegistryWorkflow,
    TemporalRunWorkflow,
    workflow,
)
from tests.test_temporal_deployment_coding_registry import (
    NAMESPACE,
    POLICY,
    admission_query,
    candidate_query,
    coding_request,
    scoped,
)


def original(monkeypatch):
    monkeypatch.setattr(
        workflow,
        "info",
        lambda: SimpleNamespace(
            namespace="default",
            workflow_id=registry_id(POLICY.deployment_id),
            run_id="original-registry-epoch",
            original_execution_run_id="original-registry-epoch",
            first_execution_run_id="original-registry-epoch",
        ),
    )
    return TemporalCommandRegistryWorkflow(
        {
            "deployment_admission": {
                "version": 3,
                "policy": POLICY.identity,
                "namespace": NAMESPACE,
            }
        }
    )


def test_original_registry_history_routes_scoped_close_bind_and_queries(monkeypatch):
    authority = original(monkeypatch)
    request = coding_request()
    asyncio.run(authority.reserve(request))
    candidates = authority.view(candidate_query(request))
    assert len(candidates) == 1 and candidates[0]["execution_epoch"] is None
    closed = asyncio.run(authority.close_deployment_coding_submissions(scoped(request)))
    assert closed["candidates"][0]["close_requested"] is True
    binding = {k: v for k, v in admission_query(request).items() if k != "kind"}
    result = asyncio.run(
        authority.admit_coding_composition_submission(
            {**binding, "execution_epoch": "actual-original"}
        )
    )
    assert result["admitted"] is False
    assert authority.view(admission_query(request))["execution_epoch"] == "actual-original"


def test_registry_three_foreign_scope_queries_do_not_expose_the_other_root(monkeypatch):
    authority = original(monkeypatch)
    request = coding_request()
    asyncio.run(authority.reserve(request))
    payload = admission_query(request)
    payload["scope"]["principal"] = "other"
    assert authority.view(payload) == {"error": "definition_mismatch"}


def test_closed_original_native_admission_cancels_before_any_model_operation(monkeypatch):
    from ralf_agent import temporal_deployment_execution_state as admission
    from ralf_agent import temporal_deployment_release_state as release
    from ralf_agent.temporal_state import TemporalRunState
    from ralf_agent.types import digest
    from tests.test_temporal_deployment_coding_registry import registry

    commands, request = registry(), coding_request()
    root = commands.reserve(request)["root_admission"]
    envelope = request["root_admission"]["submission"]
    value = object.__new__(TemporalRunWorkflow)
    value.state = TemporalRunState(
        request["target"],
        request["scope"],
        "one",
        envelope["request"],
        envelope["manifest"],
        "first-epoch",
    )
    value.wake_revision = 0
    metadata = {"version": 1, "root": root, "lineage": []}
    admission.initialize(
        value.state,
        metadata,
        namespace="default",
        epoch="first-epoch",
        original_epoch="first-epoch",
        parent=None,
    )
    release.initialize(value.state)
    result = {
        "version": 1,
        "run_id": request["target"],
        "execution_epoch": "first-epoch",
        "root": {**root, "state": "held-bound", "execution_epoch": "first-epoch"},
        "metadata_digest": digest(metadata),
    }
    result["proof_digest"] = digest(result)

    async def execute(name, payload, **options):
        return {
            "ok": True,
            "result": result,
            "coding_admission": {
                "namespace": NAMESPACE,
                "execution_epoch": "first-epoch",
                "admitted": False,
            },
        }

    monkeypatch.setattr(workflow, "execute_activity", execute)
    assert asyncio.run(value._ensure_deployment_admission(timedelta(seconds=5))) is True
    assert value.state.state == "cancelled"
    assert value.state.next_operation() is None
    assert not value.state.actions


def test_cold_fence_is_sdk_owned_and_preserves_unknown_effect_obligations(monkeypatch):
    from ralf_agent.temporal_deployment_coding_state import coding_call_candidate
    from tests.test_temporal_deployment_coding_state import cold

    state, action, _, identity = cold(monkeypatch, cost=0)
    value = object.__new__(TemporalRunWorkflow)
    value.state, value.wake_revision = state, 0
    state.deployment_activity_timeout, state.deployment_task_queue = 5, "original-queue"
    candidate = coding_call_candidate(state, identity)
    captured = []

    async def execute(name, payload, **options):
        captured.append((name, payload, options))
        return {
            "ok": True,
            "result": {**candidate, "process_present": False, "native_fenced": True},
        }

    monkeypatch.setattr(workflow, "execute_activity", execute)
    ack = asyncio.run(
        value.deployment_coding_call_stopped({"scope": state.scope, "identity": identity})
    )
    assert ack["recorded"] is True
    assert captured[0][0] == "ralf.temporal.deployment-coding-stop.v3"
    assert captured[0][1] == {"scope": state.scope, "identity": identity}
    assert captured[0][2]["task_queue"] == "original-queue"
    assert action["status"] == "outcome_unknown"
    assert state.reservations[action["attempts"][0]["id"]]["status"] == "unknown"


def test_cold_update_refuses_caller_attestation_before_sdk_io(monkeypatch):
    from temporalio.exceptions import ApplicationError

    from tests.test_temporal_deployment_coding_state import cold

    state, _, _, identity = cold(monkeypatch)
    value = object.__new__(TemporalRunWorkflow)
    value.state, value.wake_revision = state, 0

    async def forbidden(*args, **kwargs):
        raise AssertionError("Caller attestation reached SDK verification")

    monkeypatch.setattr(workflow, "execute_activity", forbidden)
    before = copy.deepcopy(state.deployment_calls)
    with pytest.raises(ApplicationError):
        asyncio.run(
            value.deployment_coding_call_stopped(
                {"scope": state.scope, "identity": identity, "process_present": False}
            )
        )
    assert state.deployment_calls == before
