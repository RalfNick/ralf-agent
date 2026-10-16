"""SDK end observations retain the original proof and acknowledge only its handler."""

import asyncio
import copy
from importlib import import_module
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")

from ralf_agent.errors import RalfError
from ralf_agent.temporal_state import WORKFLOW_NAME
from tests.test_temporal_command_transport import fixture

OPERATIONS = (
    "tool_execution_ended",
    "context_execution_ended",
    "session_execution_ended",
    "deployment_call_ended",
)


def api():
    return import_module("ralf_agent.temporal_execution_end_transport")


def proof_for(client, operation):
    proof = {
        "scope": copy.deepcopy(client.host.state.scope),
        "action_id": "original-action",
        "release_digest": "a" * 64,
        "request_digest": "b" * 64,
    }
    if operation != "session_execution_ended":
        proof["execution_epoch"] = client.info.run_id
    if operation == "tool_execution_ended":
        proof["invocation_id"] = "c" * 32
    elif operation == "deployment_call_ended":
        proof.pop("action_id")
        proof.pop("release_digest")
        proof.update(
            version=1,
            run_id=client.host.state.run_id,
            activity_id="original-activity",
            activity_name="ralf.temporal.tool.v1",
            attempt=1,
            invocation_id="c" * 32,
            manifest_digest="a" * 64,
        )
    return proof


def ack_for(operation, proof):
    if operation == "deployment_call_ended":
        return {name: proof[name] for name in ("activity_id", "attempt", "invocation_id")} | {
            "recorded": True
        }
    return {
        "action_id": proof["action_id"],
        "execution_stopped" if operation == "session_execution_ended" else "recorded": True,
    }


class FakeClient:
    def __init__(self, *, legacy=False):
        self.host, self.info, _ = fixture()
        self.namespace = self.info.namespace
        self.legacy = legacy
        self.handles, self.queries, self.signals, self.updates, self.descriptions = (
            [],
            [],
            [],
            [],
            [],
        )
        self.calls = []
        self.query_transform = self.describe_transform = None
        self.namespace_after_signal = self.signal_error = None
        self.block_after_signal = False
        self.delivered = asyncio.Event()
        # Server tests own the real state reducers; this SDK fixture exposes the
        # four handler ports and their distinct ACKs to the real transport.
        for operation in OPERATIONS:
            setattr(self.host, operation, self.handler(operation))

    def handler(self, operation):
        async def ended(proof):
            self.calls.append((operation, copy.deepcopy(proof)))
            return ack_for(operation, proof)

        return ended

    def get_workflow_handle(self, identifier, *, run_id=None):
        self.handles.append((identifier, run_id))
        return FakeHandle(self, identifier, run_id)


class FakeHandle:
    def __init__(self, client, identifier, epoch):
        self.client, self.identifier, self.epoch = client, identifier, epoch

    async def query(self, name, request):
        client = self.client
        assert name == "view"
        assert set(request) == {"kind", "scope", "execution_end_observation"}
        assert request["kind"] == "status"
        client.host.state.authorize(request["scope"])
        client.queries.append((self.epoch, copy.deepcopy(request)))
        if client.block_after_signal and client.delivered.is_set():
            await asyncio.Event().wait()
        value = (
            client.host.state.snapshot()
            if client.legacy
            else {
                "execution_end_observation": api().observe(
                    client.host, request["execution_end_observation"], client.info
                )
            }
        )
        if client.query_transform is not None:
            value = client.query_transform(len(client.queries), value)
        return value

    async def signal(self, name, envelope):
        client = self.client
        assert name == "execution_ended"
        client.signals.append((self.epoch, copy.deepcopy(envelope)))
        await api().accept(client.host, envelope, client.info)
        client.delivered.set()
        if client.namespace_after_signal is not None:
            client.namespace = client.namespace_after_signal
        if client.signal_error is not None:
            raise client.signal_error

    async def execute_update(self, operation, proof, **options):
        self.client.updates.append((self.epoch, operation, copy.deepcopy(proof), options))
        return await getattr(self.client.host, operation)(proof)

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


async def execute(client, operation="tool_execution_ended", proof=None):
    return await api().execute(
        client,
        client.host.state.run_id,
        operation,
        proof_for(client, operation) if proof is None else proof,
        execution_epoch=client.info.run_id,
        legacy_update_id="original-fixed-end-id",
    )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_current_worker_each_retry_uses_fresh_observation_and_original_proof(operation):
    async def run():
        client = FakeClient()
        proof = proof_for(client, operation)
        before = copy.deepcopy(proof)
        expected = ack_for(operation, proof)
        first = await execute(client, operation, proof)
        assert first == expected and proof == before
        first["extra"] = "caller mutation"
        assert await execute(client, operation, proof) == expected
        assert client.calls == [(operation, before), (operation, before)]
        assert len({envelope["observation_id"] for _, envelope in client.signals}) == 2
        assert all(envelope["proof"] == before for _, envelope in client.signals)
        assert all(epoch == client.info.run_id for _, epoch in client.handles)
        assert not client.updates and not client.descriptions

    asyncio.run(run())


@pytest.mark.parametrize("operation", OPERATIONS)
def test_exact_legacy_worker_retains_original_fixed_update_id_and_epoch(operation):
    async def run():
        client = FakeClient(legacy=True)
        proof = proof_for(client, operation)
        assert await execute(client, operation, proof) == ack_for(operation, proof)
        assert client.descriptions == [client.info.run_id]
        assert [epoch for epoch, _ in client.queries] == [client.info.run_id] * 2
        assert client.updates == [
            (client.info.run_id, operation, proof, {"id": "original-fixed-end-id"})
        ]
        assert client.calls == [(operation, proof)] and not client.signals

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    ["validation-error", "empty", "extra", "version", "scope", "epoch", "operation", "digest"],
)
def test_malformed_probe_does_not_authorize_signal_or_legacy_update(fault):
    async def run():
        client = FakeClient()

        def changed(index, value):
            if fault == "validation-error":
                return {"error": "validation_error"}
            if fault == "empty":
                return None
            if fault == "extra":
                return {**value, "extra": True}
            observation = value["execution_end_observation"]
            observation[
                {
                    "version": "version",
                    "scope": "scope",
                    "epoch": "execution_epoch",
                    "operation": "operation",
                    "digest": "proof_digest",
                }[fault]
            ] = {
                "version": True,
                "scope": {"workspace": "foreign", "principal": "foreign"},
                "epoch": "foreign-epoch",
                "operation": "admit_tool_dispatch",
                "digest": "d" * 64,
            }[fault]
            return value

        client.query_transform = changed
        with pytest.raises(RalfError):
            await execute(client)
        assert not client.signals and not client.updates and not client.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["reset", "namespace", "target", "type", "epoch", "second-status"]
)
def test_legacy_requires_complete_original_sdk_identity_and_second_pinned_snapshot(fault):
    async def run():
        client = FakeClient(legacy=True)

        def changed(value):
            if fault == "reset":
                value.raw_info.first_run_id = "before-reset"
            elif fault == "namespace":
                value.namespace = "foreign"
            elif fault == "target":
                value.id = "foreign"
            elif fault == "type":
                value.workflow_type = "unrelated"
            elif fault == "epoch":
                value.run_id = "foreign-epoch"

        client.describe_transform = changed
        if fault == "second-status":
            client.query_transform = lambda index, value: (
                {"error": "validation_error"} if index == 2 else value
            )
        with pytest.raises(RalfError):
            await execute(client)
        assert not client.signals and not client.updates and not client.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    ("operation", "field", "replacement"),
    [
        ("tool_execution_ended", "recorded", 1),
        ("context_execution_ended", "recorded", 1),
        ("session_execution_ended", "execution_stopped", 1),
        ("deployment_call_ended", "recorded", 1),
        ("tool_execution_ended", "action_id", "other-action"),
        ("session_execution_ended", "action_id", "other-action"),
        ("deployment_call_ended", "attempt", True),
        ("deployment_call_ended", "activity_id", "other-activity"),
        ("deployment_call_ended", "invocation_id", "d" * 32),
        ("context_execution_ended", "extra", True),
    ],
)
def test_accepted_end_requires_exact_original_typed_ack(operation, field, replacement):
    async def run():
        client = FakeClient()
        proof = proof_for(client, operation)

        def changed(index, value):
            result = value["execution_end_observation"]["result"]
            if result is not None:
                result["receipt"][field] = replacement
            return value

        client.query_transform = changed
        with pytest.raises(RalfError):
            await execute(client, operation, proof)
        assert client.calls == [(operation, proof)]
        assert len(client.signals) == 1 and not client.updates
        assert proof == proof_for(client, operation)

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["admit_tool_dispatch", "coding_owner_stopped"])
def test_operation_allowlist_does_not_expose_other_workflow_handlers(operation):
    async def run():
        client = FakeClient()
        with pytest.raises(RalfError):
            await execute(client, operation)
        assert not client.signals and not client.updates and not client.calls

    asyncio.run(run())


@pytest.mark.parametrize("port", ["client", "query", "signal", "update"])
def test_changed_transport_port_during_probe_prevents_delivery(port):
    async def run():
        client = FakeClient()

        def changed(index, value):
            if index == 1:
                if port == "client":
                    client.get_workflow_handle = lambda *args, **kwargs: None
                else:
                    name = {"query": "query", "signal": "signal", "update": "execute_update"}[port]
                    # The bound method that performed this read remains alive.
                    # Replace that precise handle's port, not the shared class.
                    setattr(client.current_handle, name, lambda *args, **kwargs: None)
            return value

        original = client.get_workflow_handle

        def get_handle(*args, **kwargs):
            handle = original(*args, **kwargs)
            client.current_handle = handle
            return handle

        client.get_workflow_handle = get_handle
        client.query_transform = changed
        with pytest.raises(RalfError):
            await execute(client)
        assert not client.signals and not client.updates and not client.calls

    asyncio.run(run())


def test_signal_unknown_keeps_recorded_end_without_update_fallback():
    async def run():
        client = FakeClient()
        failure = TimeoutError("delivery outcome unknown")
        client.signal_error = failure
        with pytest.raises(TimeoutError) as rejected:
            await execute(client)
        assert rejected.value is failure
        assert len(client.calls) == len(client.signals) == 1 and not client.updates

    asyncio.run(run())


def test_cancelled_observation_does_not_undo_end_or_fall_back():
    async def run():
        client = FakeClient()
        client.block_after_signal = True
        task = asyncio.create_task(execute(client))
        await client.delivered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(client.calls) == len(client.signals) == 1 and not client.updates

    asyncio.run(run())


def test_namespace_change_after_acceptance_does_not_confirm_or_fall_back():
    async def run():
        client = FakeClient()
        client.namespace_after_signal = "foreign"
        with pytest.raises(RalfError):
            await execute(client)
        assert len(client.calls) == len(client.signals) == 1 and not client.updates

    asyncio.run(run())
