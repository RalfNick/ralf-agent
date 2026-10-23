"""Pinned retirement observations never fall back to a fresh SDK Update."""

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from relf_agent.errors import DefinitionMismatch, RalfError
from relf_agent.temporal_state import COMMAND_REGISTRY_NAME
from tests.test_temporal_deployment_retirement_transport import api, fixture


class Client:
    def __init__(self, node, info, *, fault=None):
        self.node, self.info, self.namespace, self.fault = node, info, info.namespace, fault
        self.signals, self.tasks = [], []
        self.accepted = asyncio.Event()

    def get_workflow_handle(self, target, **options):
        assert target == self.info.workflow_id
        assert not options or options == {"run_id": self.info.run_id}
        return Handle(self)


class Handle:
    def __init__(self, client):
        self.client = client

    async def describe(self):
        info = self.client.info
        return NS(
            id=info.workflow_id,
            run_id=info.run_id,
            namespace=info.namespace,
            workflow_type=COMMAND_REGISTRY_NAME,
            raw_info=NS(first_run_id=info.first_execution_run_id),
            parent_id=None,
            parent_run_id=None,
        )

    async def query(self, name, request):
        assert name == "view"
        value = self.client.node.view(request)
        fault = self.client.fault
        if fault == "probe":
            return {"error": "validation_error"}
        if fault in ("scope", "epoch", "namespace"):
            value[
                {"scope": "scope", "epoch": "execution_epoch", "namespace": "namespace"}[fault]
            ] = "changed"
        if self.client.signals and value.get("result"):
            if fault == "receipt":
                value["result"]["receipt"]["released"] = 1
            elif fault == "certificate":
                value["result"]["receipt"]["certificate"]["terminal_state"] = "succeeded"
        return value

    async def signal(self, name, envelope):
        assert name == "retire_deployment_root"
        self.client.signals.append(copy.deepcopy(envelope))
        task = asyncio.create_task(self.client.node.retire_deployment_root(envelope))
        self.client.tasks.append(task)
        await asyncio.sleep(0)
        self.client.accepted.set()
        if self.client.fault == "port":
            self.client.get_workflow_handle = lambda *args, **kwargs: self
        if self.client.fault == "lost":
            raise ConnectionError("reply lost after actual signal acceptance")

    async def execute_update(self, *args, **kwargs):
        raise AssertionError("Retirement observations must not fall back to Update")


def original_root(node, request):
    return node.commands.prepare_deployment_release(request)["root"]


def test_client_reuses_original_retirement_and_typed_receipt(monkeypatch):
    async def run():
        node, info, envelope, _, calls = fixture(monkeypatch)
        client = Client(node, info)
        root = original_root(node, envelope["request"])
        first = await api().execute(client, root, envelope["request"])
        second = await api().execute(client, root, envelope["request"])
        assert first == second and first["released"] is True and len(calls) == 1
        assert (
            len(client.signals) == 2
            and client.signals[0]["observation_id"] != client.signals[1]["observation_id"]
        )
        assert not node.commands.deployment.roots

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["probe", "scope", "epoch", "namespace", "receipt", "certificate", "port", "lost"]
)
def test_client_refuses_changed_or_unknown_reply_without_fallback(monkeypatch, fault):
    async def run():
        node, info, envelope, _, _ = fixture(monkeypatch)
        client = Client(node, info, fault=fault)
        root = original_root(node, envelope["request"])
        with pytest.raises((RalfError, ConnectionError)):
            await api().execute(client, root, envelope["request"])
        await asyncio.gather(*client.tasks)
        assert len(client.signals) == (
            0 if fault in {"probe", "scope", "epoch", "namespace"} else 1
        )

    asyncio.run(run())


def test_cancelled_observation_does_not_cancel_original_verification(monkeypatch):
    async def run():
        node, info, envelope, gate, calls = fixture(monkeypatch, hold=True)
        client = Client(node, info)
        root = original_root(node, envelope["request"])
        observer = asyncio.create_task(api().execute(client, root, envelope["request"]))
        try:
            await asyncio.wait_for(client.accepted.wait(), 2)
            assert calls
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert node.commands.deployment.roots and not client.tasks[0].done()
        finally:
            gate.set()
            await asyncio.gather(*client.tasks)
        assert not node.commands.deployment.roots
        assert (await api().execute(client, root, envelope["request"]))["released"] is True

    asyncio.run(run())


def test_reset_registry_is_rejected_before_signal(monkeypatch):
    async def run():
        node, info, envelope, _, _ = fixture(monkeypatch)
        root = original_root(node, envelope["request"])
        info.first_execution_run_id = "pre-reset"
        client = Client(node, info)
        with pytest.raises(DefinitionMismatch):
            await api().execute(client, root, envelope["request"])
        assert not client.signals and node.commands.deployment.roots

    asyncio.run(run())
