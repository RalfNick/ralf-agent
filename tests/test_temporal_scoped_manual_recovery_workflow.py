"""Only the original Registry's verified asynchronous Update admits manual proof."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from temporalio.exceptions import ApplicationError

from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow, workflow
from ralf_agent.types import digest
from tests.test_temporal_scoped_manual_recovery_state import (
    manual_request,
    original_state,
    verified,
)


def test_scoped_update_invokes_only_original_control_verifier_then_rechecks(monkeypatch):
    from ralf_agent.temporal_scoped_manual_recovery import prepare

    state, _ = original_state()
    request = manual_request()
    host = object.__new__(TemporalCommandRegistryWorkflow)
    host.commands = state
    host._deployment_registry_initialization_error = host._deployment_registry_epoch = None
    info = NS(
        workflow_id="ralf-temporal-commands-" + digest(state.scope),
        run_id="registry-epoch",
        first_execution_run_id="registry-epoch",
        original_execution_run_id="registry-epoch",
        namespace="default",
        task_queue="original-registry-queue",
    )
    monkeypatch.setattr(workflow, "info", lambda: info)
    calls = []

    async def execute(name, value, **options):
        calls.append((name, value, options))
        assert (
            value["mode"] == "scoped_manual"
            and value["submission"] == prepare(state, request)["submission"]
        )
        assert options["task_queue"] == info.task_queue
        return {"ok": True, "result": verified(prepare(state, request), request)}

    monkeypatch.setattr(workflow, "execute_activity", execute)

    async def run():
        first = await host.reserve(request)
        assert first["control_binding"]["target_execution_epoch"] == "original-epoch"
        assert await host.reserve(request) == first

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize("fault", ["epoch", "foreign", "failure", "race"])
def test_scoped_control_failure_never_creates_unverified_slot(monkeypatch, fault):
    from ralf_agent.temporal_scoped_manual_recovery import prepare

    state, _ = original_state()
    request = manual_request()
    host = object.__new__(TemporalCommandRegistryWorkflow)
    host.commands = state
    host._deployment_registry_initialization_error = host._deployment_registry_epoch = None
    info = NS(
        workflow_id="ralf-temporal-commands-" + digest(state.scope),
        run_id="registry-epoch",
        first_execution_run_id="registry-epoch",
        original_execution_run_id="registry-epoch",
        namespace="default",
        task_queue="queue",
    )
    monkeypatch.setattr(workflow, "info", lambda: info)

    async def execute(name, value, **options):
        proof = verified(prepare(state, request), request)
        if fault == "epoch":
            info.run_id = "reset"
        if fault == "foreign":
            proof["scope"] = {"workspace": "other"}
        if fault == "race":
            state.identities["confirm"] = {
                "kind": "cancel",
                "target": request["target"],
                "payload_digest": "a" * 64,
            }
        return (
            {"ok": False, "code": "definition_mismatch"}
            if fault == "failure"
            else {"ok": True, "result": proof}
        )

    monkeypatch.setattr(workflow, "execute_activity", execute)

    async def run():
        with pytest.raises(ApplicationError):
            await host.reserve(request)

    asyncio.run(run())
    assert not state.scoped_manual_slots
