"""A scoped manual observer never substitutes delivery for verified acceptance."""

import asyncio
import copy
from importlib import import_module
from types import SimpleNamespace

import pytest

from relf_agent.errors import RalfError
from relf_agent.temporal_scoped_manual_recovery import commit, configuration, prepare
from relf_agent.temporal_state import COMMAND_REGISTRY_NAME
from relf_agent.types import digest
from tests.test_temporal_scoped_manual_recovery_state import (
    SCOPE,
    expected_receipt,
    manual_request,
    original_state,
    verified,
)


def api():
    return import_module("relf_agent.temporal_scoped_manual_transport")


class FakeClient:
    def __init__(self, *, legacy=False):
        state, _ = original_state()
        self.info = SimpleNamespace(
            workflow_id="ralf-temporal-commands-" + digest(SCOPE),
            namespace="default",
            run_id="registry-epoch",
            first_execution_run_id="registry-epoch",
            original_execution_run_id="registry-epoch",
            task_queue="registry-queue",
        )
        self.reservations = []

        async def reserve(request):
            self.reservations.append(copy.deepcopy(request))
            prepared = prepare(state, request)
            if "receipt" in prepared:
                return prepared["receipt"]
            return commit(state, request, verified(prepared, request))

        self.host = SimpleNamespace(commands=state, reserve=reserve)
        self.original = configuration(state, self.info)
        self.namespace = self.info.namespace
        self.legacy = legacy
        self.handles, self.queries, self.signals, self.updates = [], [], [], []
        self.query_transform = None
        self.signal_error = None
        self.namespace_after_signal = None
        self.block_after_signal = False
        self.delivered = asyncio.Event()

    def get_workflow_handle(self, identifier, *, run_id=None):
        self.handles.append((identifier, run_id))
        return FakeHandle(self, identifier, run_id)


class FakeHandle:
    def __init__(self, client, identifier, epoch):
        self.client, self.identifier, self.epoch = client, identifier, epoch

    async def query(self, name, request):
        client = self.client
        assert name == "view" and set(request) == {"kind", "scope", "manual_observation"}
        assert request["kind"] == "scoped_manual_configuration"
        client.queries.append((self.epoch, copy.deepcopy(request)))
        if client.block_after_signal and client.delivered.is_set():
            await asyncio.Event().wait()
        value = (
            copy.deepcopy(client.original)
            if client.legacy
            else {
                "manual_observation": api().observe(
                    client.host, request["manual_observation"], client.info
                )
            }
        )
        if client.query_transform is not None:
            value = client.query_transform(len(client.queries), value, self)
        return value

    async def signal(self, name, envelope):
        client = self.client
        assert name == "reserve_scoped_manual"
        client.signals.append((self.epoch, copy.deepcopy(envelope)))
        await api().accept(client.host, envelope, client.info)
        client.delivered.set()
        if client.namespace_after_signal is not None:
            client.namespace = client.namespace_after_signal
        if client.signal_error is not None:
            raise client.signal_error

    async def execute_update(self, name, request, **options):
        assert name == "reserve"
        self.client.updates.append((self.epoch, copy.deepcopy(request), options))
        return await self.client.host.reserve(request)

    async def describe(self):
        return SimpleNamespace(
            id=self.identifier,
            namespace=self.client.info.namespace,
            run_id=self.client.info.run_id,
            workflow_type=COMMAND_REGISTRY_NAME,
            raw_info=SimpleNamespace(first_run_id=self.client.info.run_id),
        )


def test_new_observation_returns_verified_receipt_and_duplicates_keep_original_binding():
    transport = api()

    async def run():
        client = FakeClient()
        request = manual_request()
        for _ in range(2):
            result = await transport.execute(
                client, client.info.workflow_id, request, original=client.original
            )
            assert result == expected_receipt()
            result["control_binding"]["namespace"]["id"] = "mutated-client-copy"
        assert len(client.signals) == 2 and not client.updates
        assert len({e[1]["observation_id"] for e in client.signals}) == 2
        assert len(client.host.commands.identities) == 2
        assert len(client.host.commands.scoped_manual_slots) == 1
        assert (
            client.host.commands.scoped_manual_bindings["confirm"]
            == expected_receipt()["control_binding"]
        )
        assert all(epoch == "registry-epoch" for _, epoch in client.handles)

    asyncio.run(run())


def test_exact_legacy_v1_configuration_twice_allows_only_original_epoch_update():
    transport = api()

    async def run():
        client = FakeClient(legacy=True)
        request = manual_request()
        result = await transport.execute(
            client, client.info.workflow_id, request, original=client.original
        )
        assert result == expected_receipt()
        assert len(client.queries) == 2 and not client.signals
        assert client.updates == [("registry-epoch", request, {})]
        assert all(epoch == "registry-epoch" for _, epoch in client.handles)

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["validation-error", "empty", "extra", "version", "scope", "epoch", "digest"]
)
def test_bad_new_probe_cannot_authorize_any_write_or_update_fallback(fault):
    transport = api()

    async def run():
        client = FakeClient()

        def changed(index, value, handle):
            if fault == "validation-error":
                return {"error": "validation_error"}
            if fault == "empty":
                return None
            if fault == "extra":
                return {**value, "extra": True}
            observation = value["manual_observation"]
            if fault == "version":
                observation["version"] = True
            elif fault == "scope":
                observation["scope"] = {**SCOPE, "principal": "foreign"}
            elif fault == "epoch":
                observation["execution_epoch"] = "foreign"
            else:
                observation["request_digest"] = "a" * 64
            return value

        client.query_transform = changed
        with pytest.raises(RalfError):
            await transport.execute(
                client, client.info.workflow_id, manual_request(), original=client.original
            )
        assert not client.signals and not client.updates and not client.reservations

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["version", "scope", "namespace", "epoch", "extra", "second-read"]
)
def test_legacy_configuration_must_match_exact_original_twice(fault):
    transport = api()

    async def run():
        client = FakeClient(legacy=True)

        def changed(index, value, handle):
            if fault == "second-read":
                return {"error": "validation_error"} if index == 2 else value
            if fault == "version":
                value["version"] = True
            elif fault == "scope":
                value["scope"] = {**SCOPE, "principal": "foreign"}
            elif fault == "namespace":
                value["namespace"] = "foreign"
            elif fault == "epoch":
                value["registry_execution_epoch"] = "foreign"
            else:
                value["extra"] = True
            return value

        client.query_transform = changed
        with pytest.raises(RalfError):
            await transport.execute(
                client, client.info.workflow_id, manual_request(), original=client.original
            )
        assert not client.updates and not client.signals and not client.reservations

    asyncio.run(run())


@pytest.mark.parametrize("port", ["client", "query", "signal", "update"])
def test_port_drift_during_preflight_is_rejected_before_a_write(port):
    transport = api()

    async def run():
        client = FakeClient()

        def changed(index, value, handle):
            async def replaced(*args, **kwargs):
                pytest.fail("changed transport port must not be invoked")

            if port == "client":
                client.get_workflow_handle = lambda *args, **kwargs: handle
            else:
                setattr(handle, {"update": "execute_update"}.get(port, port), replaced)
            return value

        client.query_transform = changed
        with pytest.raises(RalfError):
            await transport.execute(
                client, client.info.workflow_id, manual_request(), original=client.original
            )
        assert not client.signals and not client.updates and not client.reservations

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["command", "target", "binding-epoch", "binding-scope", "epoch", "scope", "typed-ok"]
)
def test_bad_result_cannot_confirm_an_already_accepted_manual_slot(fault):
    transport = api()

    async def run():
        client = FakeClient()

        def changed(index, value, handle):
            if index != 2:
                return value
            observation = value["manual_observation"]
            result = observation["result"]
            receipt = result["receipt"]
            if fault == "command":
                receipt["command_id"] = "foreign"
            elif fault == "target":
                receipt["target"] = "foreign"
            elif fault == "binding-epoch":
                receipt["control_binding"]["target_execution_epoch"] = True
            elif fault == "binding-scope":
                receipt["control_binding"]["scope"] = {**SCOPE, "principal": "foreign"}
            elif fault == "epoch":
                observation["execution_epoch"] = "foreign"
            elif fault == "scope":
                observation["scope"] = {**SCOPE, "principal": "foreign"}
            else:
                result["ok"] = 1
            return value

        client.query_transform = changed
        with pytest.raises(RalfError):
            await transport.execute(
                client, client.info.workflow_id, manual_request(), original=client.original
            )
        assert len(client.host.commands.scoped_manual_slots) == 1
        assert len(client.signals) == 1 and not client.updates
        assert (
            client.host.commands.scoped_manual_bindings["confirm"]
            == expected_receipt()["control_binding"]
        )

    asyncio.run(run())


def test_signal_reply_loss_preserves_original_acceptance_without_update_fallback():
    transport = api()

    async def run():
        client = FakeClient()
        failure = TimeoutError("signal reply unavailable")
        client.signal_error = failure
        with pytest.raises(TimeoutError) as rejected:
            await transport.execute(
                client, client.info.workflow_id, manual_request(), original=client.original
            )
        assert rejected.value is failure
        assert len(client.host.commands.scoped_manual_slots) == 1
        assert len(client.signals) == 1 and not client.updates

    asyncio.run(run())


def test_caller_cancel_during_observation_preserves_slot_and_never_uses_update():
    transport = api()

    async def run():
        client = FakeClient()
        client.block_after_signal = True
        task = asyncio.create_task(
            transport.execute(
                client, client.info.workflow_id, manual_request(), original=client.original
            )
        )
        async with asyncio.timeout(2):
            await client.delivered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(client.host.commands.scoped_manual_slots) == 1
        assert len(client.signals) == 1 and not client.updates

    asyncio.run(run())


def test_namespace_change_after_acceptance_keeps_slot_without_confirming_reply():
    transport = api()

    async def run():
        client = FakeClient()
        client.namespace_after_signal = "foreign"
        with pytest.raises(RalfError):
            await transport.execute(
                client, client.info.workflow_id, manual_request(), original=client.original
            )
        assert len(client.host.commands.scoped_manual_slots) == 1
        assert len(client.signals) == 1 and len(client.queries) == 1 and not client.updates

    asyncio.run(run())
