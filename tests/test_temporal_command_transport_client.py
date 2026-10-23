"""SDK observations confirm this wake without replacing original Run receipts."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent.errors import RalfError
from relf_agent.temporal_command_transport import accept, execute, observe
from relf_agent.temporal_state import WORKFLOW_NAME
from tests.test_temporal_command_transport import fixture


class FakeClient:
    def __init__(self, *, legacy=False):
        self.host, self.info, self.envelope = fixture()
        self.namespace = self.info.namespace
        self.legacy = legacy
        self.handles, self.queries, self.signals, self.updates, self.descriptions = (
            [],
            [],
            [],
            [],
            [],
        )
        self.query_transform = self.describe_transform = None
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
        assert name == "view" and set(request) == {"kind", "scope", "command_observation"}
        assert request["kind"] == "status"
        client.host.state.authorize(request["scope"])
        client.queries.append((self.epoch, copy.deepcopy(request)))
        if client.block_after_signal and client.delivered.is_set():
            await asyncio.Event().wait()
        value = (
            client.host.state.snapshot()
            if client.legacy
            else {
                "command_observation": observe(
                    client.host, request["command_observation"], client.info
                )
            }
        )
        if client.query_transform is not None:
            value = client.query_transform(len(client.queries), value)
        return value

    async def signal(self, name, value):
        client = self.client
        assert name == "control_command"
        client.signals.append((self.epoch, copy.deepcopy(value)))
        await accept(client.host, value, client.info)
        client.delivered.set()
        if client.namespace_after_signal is not None:
            client.namespace = client.namespace_after_signal
        if client.signal_error is not None:
            raise client.signal_error

    async def execute_update(self, name, request, **options):
        assert name == "command"
        self.client.updates.append((self.epoch, copy.deepcopy(request), options))
        return await self.client.host.command(request)

    async def describe(self):
        client = self.client
        client.descriptions.append(self.epoch)
        value = SimpleNamespace(
            id=client.host.state.run_id,
            run_id=client.info.run_id,
            namespace=client.info.namespace,
            workflow_type=WORKFLOW_NAME,
            raw_info=SimpleNamespace(first_run_id=client.info.run_id),
        )
        if client.describe_transform is not None:
            client.describe_transform(value)
        return value


def command(client, kind="drive"):
    request = copy.deepcopy(client.envelope["request"])
    request["payload"]["kind"] = kind
    if kind == "reconcile":
        action = next(a for a in client.host.state.actions if a["status"] == "outcome_unknown")
        request["payload"].update(action_id=action["id"], query=False, result="operator evidence")
    return request


def test_each_new_observer_reaches_complete_handler_but_preserves_original_receipt():
    async def run():
        client = FakeClient()
        request = command(client)
        first = await execute(client, "run", request)
        original = copy.deepcopy(first)
        first["outcome"]["state_revision"] = -100
        client.host._deployment_parent_notification_attempts = 7
        assert await execute(client, "run", request) == original
        assert client.host.wake_revision == 2
        assert client.host._deployment_parent_notification_attempts == 0
        assert len(client.host.state.receipts) == 2
        assert client.host.state.receipts[request["command_id"]] == original
        assert len({e[1]["observation_id"] for e in client.signals}) == 2
        assert all(epoch == client.info.run_id for epoch, _ in client.signals)
        assert not client.updates and not client.descriptions
        assert client.handles == [("run", None), ("run", client.info.run_id)] * 2

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["cancel", "drive", "reconcile"])
def test_current_worker_necessary_commands_use_only_pinned_signal_receipts(kind):
    async def run():
        client = FakeClient()
        request = command(client, kind)
        receipt = await execute(client, "run", request, execution_epoch=client.info.run_id)
        assert receipt == client.host.state.receipts[request["command_id"]]
        assert receipt["kind"] == kind and receipt["record_state"] == "durably_recorded"
        assert client.host.wake_revision == 1 and len(client.signals) == 1
        assert all(epoch == client.info.run_id for _, epoch in client.handles)
        assert not client.updates

    asyncio.run(run())


def test_exact_legacy_snapshot_requires_description_and_second_pinned_status_before_update():
    async def run():
        client = FakeClient(legacy=True)
        request = command(client)
        result = await execute(client, "run", request)
        assert result == client.host.state.receipts[request["command_id"]]
        assert client.descriptions == [None]
        assert [epoch for epoch, _ in client.queries] == [None, client.info.run_id]
        assert client.updates == [(client.info.run_id, request, {})]
        assert not client.signals and client.host.wake_revision == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["validation-error", "empty", "extra", "scope", "epoch", "digest"]
)
def test_bad_preflight_never_authorizes_any_write_or_legacy_fallback(fault):
    async def run():
        client = FakeClient()

        def changed(index, value):
            if fault == "validation-error":
                return {"error": "validation_error"}
            if fault == "empty":
                return None
            if fault == "extra":
                return {**value, "extra": True}
            observation = value["command_observation"]
            if fault == "scope":
                observation["scope"] = {"workspace": "foreign", "principal": "foreign"}
            elif fault == "epoch":
                observation["execution_epoch"] = "foreign-epoch"
            else:
                observation["request_digest"] = "a" * 64
            return value

        client.query_transform = changed
        with pytest.raises(RalfError):
            await execute(client, "run", command(client), execution_epoch=client.info.run_id)
        assert not client.signals and not client.updates and client.host.wake_revision == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["reset", "namespace", "target", "workflow-type", "second-status"]
)
def test_legacy_discovery_must_remain_original_before_update(fault):
    async def run():
        client = FakeClient(legacy=True)

        def changed(value):
            if fault == "reset":
                value.raw_info.first_run_id = "before-reset"
            elif fault == "namespace":
                value.namespace = "foreign"
            elif fault == "target":
                value.id = "foreign"
            elif fault == "workflow-type":
                value.workflow_type = "unrelated"

        client.describe_transform = changed
        if fault == "second-status":
            client.query_transform = lambda index, value: (
                {"error": "validation_error"} if index == 2 else value
            )
        with pytest.raises(RalfError):
            await execute(client, "run", command(client))
        assert not client.updates and not client.signals and client.host.wake_revision == 0

    asyncio.run(run())


def test_unknown_signal_outcome_preserves_acceptance_without_update_fallback():
    async def run():
        client = FakeClient()
        failure = TimeoutError("signal outcome unknown")
        client.signal_error = failure
        request = command(client)
        with pytest.raises(TimeoutError) as rejected:
            await execute(client, "run", request)
        assert rejected.value is failure
        assert (
            client.host.wake_revision == 1 and request["command_id"] in client.host.state.receipts
        )
        assert len(client.signals) == 1 and not client.updates

    asyncio.run(run())


def test_caller_cancel_stops_observation_without_undoing_command_or_using_update():
    async def run():
        client = FakeClient()
        client.block_after_signal = True
        request = command(client)
        task = asyncio.create_task(execute(client, "run", request))
        await client.delivered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (
            client.host.wake_revision == 1 and request["command_id"] in client.host.state.receipts
        )
        assert len(client.signals) == 1 and not client.updates

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["command-id", "run-id", "kind", "record", "apply", "outcome", "epoch", "scope"]
)
def test_changed_result_is_not_confirmed_even_when_original_command_was_accepted(fault):
    async def run():
        client = FakeClient()

        def changed(index, value):
            if index != 2:
                return value
            observation = value["command_observation"]
            receipt = observation["result"]["receipt"]
            if fault == "command-id":
                receipt["command_id"] = "foreign"
            elif fault == "run-id":
                receipt["run_id"] = "foreign"
            elif fault == "kind":
                receipt["kind"] = "cancel"
            elif fault == "record":
                receipt["record_state"] = "unrecorded"
            elif fault == "apply":
                receipt["apply_state"] = "unknown"
            elif fault == "outcome":
                receipt["outcome"] = []
            elif fault == "epoch":
                observation["execution_epoch"] = "foreign-epoch"
            else:
                observation["scope"] = {"workspace": "foreign", "principal": "foreign"}
            return value

        client.query_transform = changed
        request = command(client)
        with pytest.raises(RalfError):
            await execute(client, "run", request)
        assert client.host.state.receipts[request["command_id"]]["kind"] == "drive"
        assert client.host.wake_revision == 1 and not client.updates

    asyncio.run(run())


def test_namespace_change_after_signal_keeps_accepted_command_but_does_not_confirm_it():
    async def run():
        client = FakeClient()
        client.namespace_after_signal = "foreign"
        request = command(client)
        with pytest.raises(RalfError):
            await execute(client, "run", request)
        assert (
            client.host.wake_revision == 1 and request["command_id"] in client.host.state.receipts
        )
        assert len(client.signals) == 1 and len(client.queries) == 1 and not client.updates

    asyncio.run(run())
