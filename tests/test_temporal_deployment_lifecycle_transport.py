"""Original actual-call admission and seal remain authoritative at Update exhaustion."""

import asyncio
import copy
from importlib import import_module
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("temporalio")

from ralf_agent.errors import RalfError
from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow
from tests.test_temporal_deployment_release_state import identity, module, original


def fixture(monkeypatch, *, parent=False, operation="deployment_call_started"):
    state = original(monkeypatch, parent=parent)
    state.authorize = lambda scope: TemporalRunState.authorize(state, scope)
    owner = object.__new__(TemporalParentWorkflow if parent else TemporalRunWorkflow)
    owner.state, owner.wake_revision = state, 0
    info = NS(
        workflow_id=state.run_id,
        namespace="original",
        run_id=state.epoch,
        first_execution_run_id=state.epoch,
        original_execution_run_id=state.epoch,
    )
    monkeypatch.setattr(workflow, "info", lambda: info)
    proof = (
        identity(state)
        if operation == "deployment_call_started"
        else {"scope": state.scope, "children": []}
    )
    envelope = dict(
        version=1,
        scope=state.scope,
        run_id=state.run_id,
        namespace="original",
        execution_epoch=state.epoch,
        observation_id="one",
        operation=operation,
        proof=proof,
    )
    return owner, info, envelope


def api():
    return import_module("ralf_agent.temporal_deployment_lifecycle_transport")


@pytest.mark.parametrize("parent", [False, True])
def test_begin_keeps_exclusive_owner_and_fresh_repeat_rechecks_stopped_call(monkeypatch, parent):
    async def run():
        owner, info, envelope = fixture(monkeypatch, parent=parent)
        before = copy.deepcopy(vars(owner.state))
        assert api().observe(owner, envelope, info)["result"] is None
        assert vars(owner.state) == before
        await api().accept(owner, envelope, info)
        assert api().observe(owner, envelope, info)["result"] == {
            "ok": True,
            "receipt": {
                "activity_id": "activity",
                "attempt": 1,
                "invocation_id": "a" * 32,
                "allowed": True,
            },
        }
        wake = owner.wake_revision
        assert wake == (0 if parent else 1)
        await api().accept(owner, envelope, info)
        assert owner.wake_revision == wake
        module().end_activity(owner.state, envelope["proof"])
        again = {**envelope, "observation_id": "again"}
        await api().accept(owner, again, info)
        assert api().observe(owner, again, info)["result"]["receipt"]["allowed"] is False
        assert len(owner.state.deployment_calls) == 1
        assert all(record["stopped"] for record in owner.state.deployment_calls.values())
        assert owner.wake_revision == (0 if parent else 2)

    asyncio.run(run())


@pytest.mark.parametrize("parent", [False, True])
def test_seal_refuses_live_call_then_commits_original_certificate_without_clearing_end_debt(
    monkeypatch, parent
):
    async def run():
        owner, info, envelope = fixture(monkeypatch, parent=parent, operation="deployment_seal")
        call = identity(owner.state)
        module().begin_activity(owner.state, call)
        await api().accept(owner, envelope, info)
        assert api().observe(owner, envelope, info)["result"] == {
            "ok": False,
            "error": "definition_mismatch",
        }
        assert owner.state.deployment_seal is None
        module().end_activity(owner.state, call)
        again = {**envelope, "observation_id": "closed"}
        await api().accept(owner, again, info)
        certificate = api().observe(owner, again, info)["result"]["receipt"]
        assert certificate["run_id"] == "original" and certificate["execution_epoch"] == "epoch"
        assert certificate["terminal_state"] == "succeeded" and certificate["children"] == []
        assert owner.state.deployment_seal == certificate and owner.wake_revision == 1
        certificate["terminal_state"] = "failed"
        assert owner.state.deployment_seal["terminal_state"] == "succeeded"
        other = {**again, "observation_id": "repeat"}
        await api().accept(owner, other, info)
        assert owner.wake_revision == 2
        assert api().observe(owner, other, info)["result"]["receipt"] == owner.state.deployment_seal
        new = {
            **envelope,
            "operation": "deployment_call_started",
            "observation_id": "late",
            "proof": identity(owner.state, activity="new"),
        }
        await api().accept(owner, new, info)
        assert api().observe(owner, new, info)["result"]["ok"] is False
        assert len(owner.state.deployment_calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["scope", "epoch", "reset", "namespace", "operation", "private", "default"]
)
def test_untrusted_envelope_cannot_grant_or_seal(monkeypatch, fault):
    async def run():
        owner, info, envelope = fixture(monkeypatch)
        if fault == "scope":
            envelope["scope"] = {"workspace": "other", "principal": "p"}
        elif fault == "epoch":
            envelope["execution_epoch"] = "other"
        elif fault == "reset":
            info.first_execution_run_id = "pre-reset"
        elif fault == "namespace":
            envelope["namespace"] = "other"
        elif fault == "operation":
            envelope["operation"] = "command"
        elif fault == "private":
            owner.state.manifest["deployment_admission_protocol"]["version"] = 1
        else:
            owner.state.manifest = {}
        before = copy.deepcopy(vars(owner.state))
        await api().accept(owner, envelope, info)
        assert vars(owner.state) == before
        with pytest.raises(RalfError):
            api().observe(owner, envelope, info)
        assert not getattr(owner, "_deployment_lifecycle_observations", {})

    asyncio.run(run())


def test_observation_eviction_preserves_grant_and_full_handler_wake(monkeypatch):
    async def run():
        owner, info, envelope = fixture(monkeypatch)
        for i in range(70):
            await api().accept(owner, {**envelope, "observation_id": str(i)}, info)
        assert len(owner._deployment_lifecycle_observations) == 64
        assert api().observe(owner, {**envelope, "observation_id": "0"}, info)["result"] is None
        assert len(owner.state.deployment_calls) == 1 and owner.wake_revision == 70
        changed = copy.deepcopy(envelope)
        changed["observation_id"], changed["proof"]["invocation_id"] = "69", "c" * 32
        before = copy.deepcopy(vars(owner.state))
        await api().accept(owner, changed, info)
        assert vars(owner.state) == before
        with pytest.raises(RalfError):
            api().observe(owner, changed, info)

    asyncio.run(run())
