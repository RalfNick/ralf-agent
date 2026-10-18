"""Uncertain public manual observations cannot retry through SDK Updates."""

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from ralf_agent.errors import RalfError
from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME
from tests.test_temporal_public_manual_transport import api, fixture


class Handle:
    def __init__(self, node, info, *, fault=None):
        self.node, self.info, self.fault = node, info, fault
        self.id, self.run_id = info.workflow_id, info.run_id
        self.signals, self.tasks, self.accepted = [], [], asyncio.Event()

    async def describe(self):
        return NS(
            id=self.id,
            run_id=self.run_id,
            namespace=self.info.namespace,
            raw_info=NS(first_run_id=self.info.first_execution_run_id),
            workflow_type=COMMAND_REGISTRY_NAME,
            parent_id=None,
            parent_run_id=None,
        )

    async def query(self, name, request):
        assert name == "view"
        value = self.node.view(request)
        if self.fault == "probe":
            return {"error": "validation_error"}
        if self.fault in {"scope", "namespace", "epoch"}:
            value[{"epoch": "execution_epoch"}.get(self.fault, self.fault)] = "changed"
        if self.fault == "receipt" and value.get("result"):
            value["result"]["receipt"]["control_binding"]["target_execution_epoch"] = "other"
        return value

    async def signal(self, name, envelope):
        assert name == "reserve_public_manual"
        self.signals.append(copy.deepcopy(envelope))
        self.tasks.append(asyncio.create_task(self.node.reserve_public_manual(envelope)))
        await asyncio.sleep(0)
        self.accepted.set()
        if self.fault == "port":
            self.query = lambda *args, **kwargs: None
        if self.fault == "lost":
            raise ConnectionError("reply lost after original signal acceptance")

    async def execute_update(self, *args, **kwargs):
        raise AssertionError("An unknown manual observation cannot fall back to Update")


def test_original_action_binding_and_duplicate_receipt_survive_fresh_observation(monkeypatch):
    async def run():
        node, info, envelope, _, calls = fixture(monkeypatch)
        handle = Handle(node, info)
        first = await api().reserve(handle, envelope["request"])
        second = await api().reserve(handle, envelope["request"])
        assert first == second and first["control_binding"]["version"] == 2
        assert len(calls) == 1 and len(node.commands.deployment.manual_recoveries) == 1
        assert (
            len(handle.signals) == 2
            and handle.signals[0]["observation_id"] != handle.signals[1]["observation_id"]
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["probe", "scope", "namespace", "epoch", "receipt", "port", "lost"]
)
def test_unknown_or_changed_reply_never_retries_or_adopts_wrong_binding(monkeypatch, fault):
    async def run():
        node, info, envelope, _, _ = fixture(monkeypatch)
        handle = Handle(node, info, fault=fault)
        with pytest.raises((RalfError, ConnectionError)):
            await api().reserve(handle, envelope["request"])
        await asyncio.gather(*handle.tasks)
        assert len(handle.signals) == (
            0 if fault in {"probe", "scope", "namespace", "epoch"} else 1
        )
        assert len(node.commands.deployment.commands) <= 2

    asyncio.run(run())


def test_observer_cancellation_preserves_pending_original_proof(monkeypatch):
    async def run():
        node, info, envelope, gate, calls = fixture(monkeypatch, hold=True)
        handle = Handle(node, info)
        task = asyncio.create_task(api().reserve(handle, envelope["request"]))
        try:
            await asyncio.wait_for(handle.accepted.wait(), 2)
            assert len(calls) == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not node.commands.deployment.manual_recoveries and not handle.tasks[0].done()
        finally:
            gate.set()
            await asyncio.gather(*handle.tasks)
        assert len(node.commands.deployment.manual_recoveries) == 1
        assert (await api().reserve(handle, envelope["request"]))["control_binding"]["version"] == 2

    asyncio.run(run())


def test_original_sdk_reset_is_refused_before_signal(monkeypatch):
    async def run():
        node, info, envelope, _, _ = fixture(monkeypatch)
        handle = Handle(node, info)
        info.first_execution_run_id = "before-reset"
        with pytest.raises(RalfError):
            await api().reserve(handle, envelope["request"])
        assert not handle.signals and not node.commands.deployment.manual_recoveries

    asyncio.run(run())
