"""Original Workflow owns call/seal/release progression; no Temporal service."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")
from relf_agent.temporal_deployment_release_state import public
from relf_agent.temporal_workflow import TemporalRunWorkflow, workflow


def instance():
    value = object.__new__(TemporalRunWorkflow)
    value.state = SimpleNamespace(
        manifest={"deployment_admission_protocol": {"version": 2}},
        scope={"workspace": "w", "principal": "p"},
        run_id="run",
        epoch="epoch",
        state="succeeded",
        deployment_admission={"lineage": []},
        deployment_retirement=None,
        deployment_seal=None,
    )
    value.wake_revision = 0
    return value


def test_original_call_and_seal_updates_are_owned_and_wake_progress(monkeypatch):
    from relf_agent import temporal_deployment_release_state as state

    value = instance()
    observed = []
    for method, helper in [
        ("deployment_call_started", "begin_activity"),
        ("deployment_call_ended", "end_activity"),
        ("deployment_seal", "seal"),
    ]:
        monkeypatch.setattr(
            state,
            helper,
            lambda original, payload: observed.append((original, payload)) or {"recorded": True},
        )
        result = asyncio.run(getattr(value, method)({"scope": value.state.scope}))
        assert result == {"recorded": True}
    assert len(observed) == value.wake_revision == 3
    assert all(original is value.state for original, _ in observed)


def test_release_request_bypasses_business_carrier_only_for_fixed_release_name(monkeypatch):
    value = instance()
    captured = []

    async def execute(name, request, **options):
        captured.append(request)
        return {"ok": True}

    monkeypatch.setattr(workflow, "execute_activity", execute)
    from relf_agent.temporal_deployment_release import RELEASE_ACTIVITY

    request = {
        "mode": "release",
        "scope": value.state.scope,
        "run_id": "run",
        "execution_epoch": "epoch",
    }
    asyncio.run(value._execute_activity(RELEASE_ACTIVITY, request))
    assert captured == [request]
    asyncio.run(value._execute_activity("business", {"value": "original"}))
    assert captured[-1] == {
        "scope": value.state.scope,
        "_deployment_activity_request": {"value": "original"},
    }


def test_public_start_evidence_is_separate_from_original_request_and_receipt():
    value = instance()
    value.state.authorize = lambda scope: None
    value.state.request = {"original": "request"}
    value.state.deployment_activity_timeout = 7
    value.state.deployment_task_queue = "first"
    from relf_agent.types import digest

    result = value.view({"scope": value.state.scope, "kind": "deployment_start"})
    assert result == {
        "scope": value.state.scope,
        "run_id": "run",
        "execution_epoch": "epoch",
        "activity_timeout": 7,
        "task_queue": "first",
        "request_digest": digest(value.state.request),
        "manifest_digest": digest(value.state.manifest),
    }
    assert public(value.state.manifest)
