"""Scoped protected receipts retain original epochs through SDK retries."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from ralf_agent import Scope, TemporalRuntime
from ralf_agent.errors import RalfError
from ralf_agent.temporal import TemporalEngine
from ralf_agent.temporal_scoped_manual_recovery import commit, configuration, prepare
from ralf_agent.temporal_scoped_reservation import accept, observe
from ralf_agent.types import digest
from tests.test_temporal_engine import Provider, registry
from tests.test_temporal_scoped_manual_recovery_state import (
    manual_request,
    original_state,
    verified,
)


def fixture(*, fault=None):
    state, _ = original_state()
    request = manual_request()
    scope = Scope(**state.scope)
    info = NS(
        workflow_id="ralf-temporal-commands-" + digest(state.scope),
        run_id="registry-epoch",
        first_execution_run_id="registry-epoch",
        original_execution_run_id="registry-epoch",
        namespace="default",
    )
    host = NS(commands=state)
    calls = []

    class Registry:
        async def query(self, name, value):
            if value["kind"] == "scoped_manual_configuration":
                calls.append("capability")
                if fault == "legacy":
                    return {"scope": state.scope, "capacity": 1, "accepted_commands": 1}
                return configuration(state, info)
            return observe(host, value, info)

        async def signal(self, name, value):
            calls.append("signal")
            if fault == "transport":
                raise TimeoutError("unknown delivery")
            accept(host, value, info)

        async def execute_update(self, name, value):
            calls.append("proof")
            assert name == "reserve"
            if fault == "wait-cancel":
                raise asyncio.CancelledError
            return commit(state, value, verified(prepare(state, value), value))

    registry_handle = Registry()

    class Run:
        def __init__(self, epoch):
            self.epoch = epoch

        async def query(self, *args):
            return {
                "run_id": request["target"],
                "state": "waiting_reconciliation",
                "state_revision": 1,
                "result": None,
                "error": None,
                "pending": [],
                "actions": [],
                "consistency": "authoritative",
            }

        async def signal(self, *args):
            pytest.fail("explicit legacy fixture must not receive Signals")

        async def describe(self):
            return NS(
                id=request["target"],
                run_id="original-epoch",
                namespace="default",
                raw_info=NS(first_run_id="original-epoch"),
                workflow_type="ralf.temporal.run.v1",
            )

        async def execute_update(self, name, value):
            calls.append(("command", self.epoch))
            return {
                "command_id": value["command_id"],
                "run_id": request["target"],
                "kind": "reconcile",
                "record_state": "durably_recorded",
                "apply_state": "applied",
                "outcome": {"confirmed": True},
            }

    class Client:
        namespace = "default"

        def get_workflow_handle(self, identifier, **kwargs):
            return registry_handle if identifier == info.workflow_id else Run(kwargs.get("run_id"))

    engine = TemporalEngine(
        Client(),
        task_queue="queue",
        scope=scope,
        release=TemporalRuntime(providers={"default": Provider()}, tools=registry()).manifest,
    )
    engine._registry = registry_handle
    return engine, state, request, calls


@pytest.fixture(autouse=True)
def namespace(monkeypatch):
    async def original(client):
        return "11111111-1111-1111-1111-111111111111"

    monkeypatch.setattr("ralf_agent.temporal_session_activities.namespace_id", original)


def test_full_registry_manual_recovery_and_duplicate_command_use_original_epoch():
    async def run():
        engine, state, request, calls = fixture()
        result = await engine.reconcile(
            request["target"], "original-action", "confirmed", command_id="confirm"
        )
        assert (
            await engine.reconcile(
                request["target"], "original-action", "confirmed", command_id="confirm"
            )
            == result
        )
        assert calls.count("proof") == 1 and calls.count(("command", "original-epoch")) == 2
        assert len(state.identities) == 2

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["legacy", "transport", "wait-cancel"])
def test_unknown_transport_old_worker_or_cancel_never_falls_back_to_unpinned_business(fault):
    async def run():
        engine, state, request, calls = fixture(fault=fault)
        with pytest.raises((RalfError, TimeoutError, asyncio.CancelledError)):
            await engine.reconcile(
                request["target"], "original-action", "confirmed", command_id="confirm"
            )
        assert not any(isinstance(c, tuple) for c in calls) and len(state.identities) == 1
        if fault == "transport":
            assert "capability" not in calls and "proof" not in calls
        if fault == "legacy":
            assert "proof" not in calls

    asyncio.run(run())


def test_namespace_change_during_uuid_read_never_sends_business_command(monkeypatch):
    async def run():
        engine, state, request, calls = fixture()

        async def changed(client):
            client.namespace = "another-namespace"
            return "11111111-1111-1111-1111-111111111111"

        monkeypatch.setattr("ralf_agent.temporal_session_activities.namespace_id", changed)
        with pytest.raises(RalfError):
            await engine.reconcile(
                request["target"], "original-action", "confirmed", command_id="confirm"
            )
        assert not any(isinstance(c, tuple) for c in calls)
        # Admission may have succeeded; observation failure cannot undo its slot.
        assert len(state.identities) == 2

    asyncio.run(run())
