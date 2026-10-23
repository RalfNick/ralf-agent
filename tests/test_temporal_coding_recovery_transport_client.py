"""Uncertain Coding proof observation cannot grant work or retry via Updates."""

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from relf_agent.errors import RalfError
from relf_agent.temporal_state import WORKFLOW_NAME
from tests.test_temporal_coding_recovery_transport import OPERATIONS, api, fixture


class Client:
    def __init__(self, node, info, fault=None):
        self.node, self.info, self.fault = node, info, fault
        self.namespace = info.namespace
        self.signals, self.tasks, self.updates = [], [], []
        self.delivered = asyncio.Event()

    def get_workflow_handle(self, identifier, *, run_id=None):
        assert identifier == self.info.workflow_id and run_id == self.info.run_id
        return Handle(self)


class Handle:
    def __init__(self, client):
        self.client = client

    async def describe(self):
        c = self.client
        return NS(
            id=c.info.workflow_id,
            namespace=c.namespace,
            run_id=c.info.run_id,
            raw_info=NS(first_run_id="reset" if c.fault == "reset" else c.info.run_id),
            workflow_type=WORKFLOW_NAME,
        )

    async def query(self, name, request):
        c = self.client
        assert name == "view"
        result = c.node.view(request)
        if c.fault == "legacy":
            return {"run_id": c.info.workflow_id, "state": "running"}
        observation = result.get("coding_recovery_observation", {})
        if c.fault in {"scope", "namespace", "epoch"}:
            observation[{"epoch": "execution_epoch"}.get(c.fault, c.fault)] = "changed"
        if c.fault == "receipt" and observation.get("result"):
            observation["result"]["receipt"]["recorded"] = 1
        return result

    async def signal(self, name, envelope):
        c = self.client
        assert name == "coding_recovery"
        c.signals.append(copy.deepcopy(envelope))
        c.tasks.append(asyncio.create_task(c.node.coding_recovery(envelope)))
        await asyncio.sleep(0)
        c.delivered.set()
        if c.fault == "lost":
            raise ConnectionError("original delivery response lost")
        if c.fault == "port":
            self.query = lambda *args: None

    async def execute_update(self, *args, **kwargs):
        self.client.updates.append(args)
        raise AssertionError("No Coding recovery fallback to Update")


@pytest.mark.parametrize("operation", OPERATIONS)
def test_original_complete_handler_receipt_is_reobserved_without_new_grant(monkeypatch, operation):
    async def run():
        node, info, e = fixture(monkeypatch, operation)
        client = Client(node, info)
        first = await api().execute(
            client, info.workflow_id, operation, e["proof"], execution_epoch=info.run_id
        )
        second = await api().execute(
            client, info.workflow_id, operation, e["proof"], execution_epoch=info.run_id
        )
        assert first == second and len(client.signals) == 2 and not client.updates

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["legacy", "scope", "namespace", "epoch", "reset", "receipt", "lost", "port"]
)
def test_changed_or_unknown_response_does_not_adopt_or_use_update(monkeypatch, fault):
    async def run():
        node, info, e = fixture(monkeypatch)
        client = Client(node, info, fault)
        with pytest.raises((RalfError, ConnectionError)):
            await api().execute(
                client, info.workflow_id, e["operation"], e["proof"], execution_epoch=info.run_id
            )
        await asyncio.gather(*client.tasks)
        assert not client.updates
        assert len(client.signals) == (
            0 if fault in {"legacy", "scope", "namespace", "epoch", "reset"} else 1
        )

    asyncio.run(run())


def test_cancelled_observer_preserves_pending_original_handler(monkeypatch):
    async def run():
        node, info, e = fixture(monkeypatch)
        client = Client(node, info)
        original = node.coding_receipt
        gate = asyncio.Event()

        async def held(proof):
            await gate.wait()
            return await original(proof)

        node.coding_receipt = held
        task = asyncio.create_task(
            api().execute(
                client, info.workflow_id, e["operation"], e["proof"], execution_epoch=info.run_id
            )
        )
        try:
            await asyncio.wait_for(client.delivered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not client.tasks[0].done() and node.wake_revision == 0
        finally:
            gate.set()
            await asyncio.gather(*client.tasks)
        assert node.wake_revision == 1 and not client.updates

    asyncio.run(run())
