"""Original begin and seal receipts remain authoritative across SDK observations."""

import asyncio
import copy
from importlib import import_module
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("temporalio")

from ralf_agent.errors import RalfError
from ralf_agent.temporal_parent_state import PARENT_WORKFLOW_NAME
from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import digest
from tests.test_temporal_deployment_release_state import identity, module, original


def api():
    return import_module("ralf_agent.temporal_deployment_lifecycle_transport")


class Client:
    def __init__(self, monkeypatch, *, legacy=False):
        state = original(monkeypatch, parent=True)
        state.authorize = lambda scope: TemporalRunState.authorize(state, scope)
        self.host = object.__new__(TemporalParentWorkflow)
        self.host.state, self.host.wake_revision = state, 0
        self.namespace, self.legacy = "original", legacy
        self.info = NS(
            workflow_id=state.run_id,
            run_id=state.epoch,
            first_execution_run_id=state.epoch,
            original_execution_run_id=state.epoch,
            namespace=self.namespace,
        )
        self.handles, self.queries, self.signals, self.updates, self.descriptions = (
            [],
            [],
            [],
            [],
            [],
        )
        self.transform = self.describe_transform = self.signal_error = None
        self.namespace_after_signal = None
        self.block_after_signal = False
        self.delivered = asyncio.Event()

    def get_workflow_handle(self, identifier, *, run_id):
        self.handles.append((identifier, run_id))
        self.current_handle = Handle(self, identifier, run_id)
        return self.current_handle


class Handle:
    def __init__(self, client, identifier, epoch):
        self.client, self.identifier, self.epoch = client, identifier, epoch

    async def query(self, name, request):
        c, state = self.client, self.client.host.state
        assert name == "view" and request["kind"] == "status"
        assert set(request) == {"kind", "scope", "deployment_lifecycle_observation"}
        state.authorize(request["scope"])
        c.queries.append(copy.deepcopy(request))
        if c.block_after_signal and c.delivered.is_set():
            await asyncio.Event().wait()
        value = (
            {
                "run_id": state.run_id,
                "state": state.state,
                "state_revision": state.revision,
                "result": None,
                "error": None,
                "pending": [],
                "actions": copy.deepcopy(state.actions),
                "consistency": "authoritative",
            }
            if c.legacy
            else {
                "deployment_lifecycle_observation": api().observe(
                    c.host, request["deployment_lifecycle_observation"], c.info
                )
            }
        )
        return value if c.transform is None else c.transform(len(c.queries), value)

    async def signal(self, name, envelope):
        c = self.client
        assert name == "deployment_lifecycle"
        c.signals.append(copy.deepcopy(envelope))
        await api().accept(c.host, envelope, c.info)
        c.delivered.set()
        if c.namespace_after_signal is not None:
            c.namespace = c.namespace_after_signal
        if c.signal_error is not None:
            raise c.signal_error

    async def execute_update(self, operation, proof, **options):
        self.client.updates.append((self.epoch, operation, copy.deepcopy(proof), options))
        return await getattr(self.client.host, operation)(proof)

    async def describe(self):
        c = self.client
        c.descriptions.append(self.epoch)
        value = NS(
            id=c.host.state.run_id,
            run_id=c.info.run_id,
            namespace=c.info.namespace,
            workflow_type=PARENT_WORKFLOW_NAME,
            raw_info=NS(first_run_id=c.info.run_id),
        )
        if c.describe_transform is not None:
            c.describe_transform(value)
        return value


async def execute(client, operation="deployment_call_started", proof=None):
    return await api().execute(
        client,
        client.host.state.run_id,
        operation,
        identity(client.host.state) if proof is None else proof,
        execution_epoch=client.info.run_id,
        legacy_update_id="original-fixed-lifecycle-id",
    )


def seal_payload(client):
    state = client.host.state
    call = {
        "id": "original-child-call",
        "run_id": "original-child",
        "command_id": "child-command",
        "request": {"input": "child"},
        "deployment_admission": {"root": "original"},
        "deployment_execution_epoch": "child-epoch",
        "dispatch_started": True,
        "settled": True,
        "state": "succeeded",
    }
    state.children.append(call)
    return {
        "scope": copy.deepcopy(state.scope),
        "children": [
            {
                "call_id": call["id"],
                "run_id": call["run_id"],
                "command_id": call["command_id"],
                "execution_epoch": "child-epoch",
                "request_digest": digest(call["request"]),
                "admission_digest": digest(call["deployment_admission"]),
                "seal_digest": "d" * 64,
            }
        ],
    }


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
def test_begin_preserves_original_exclusive_allowed_and_stopped_refusal(
    monkeypatch, legacy, allowed
):
    async def run():
        client = Client(monkeypatch, legacy=legacy)
        proof = identity(client.host.state)
        if not allowed:
            module().begin_activity(client.host.state, proof)
            module().end_activity(client.host.state, proof)
        expected = {name: proof[name] for name in ("activity_id", "attempt", "invocation_id")} | {
            "allowed": allowed
        }
        assert await execute(client, proof=proof) == expected
        assert len(client.host.state.deployment_calls) == 1
        if legacy:
            assert client.updates == [
                (
                    client.info.run_id,
                    "deployment_call_started",
                    proof,
                    {"id": "original-fixed-lifecycle-id"},
                )
            ]
            assert len(client.queries) == 2 and client.descriptions == [client.info.run_id]
            assert not client.signals
        else:
            assert await execute(client, proof=proof) == expected
            assert len(client.signals) == 2
            assert len({value["observation_id"] for value in client.signals}) == 2
            assert all(value["proof"] == proof for value in client.signals)
            assert not client.updates
        assert all(epoch == client.info.run_id for _, epoch in client.handles)

    asyncio.run(run())


@pytest.mark.parametrize("legacy", [False, True])
def test_complete_original_seal_and_children_are_returned_detached(monkeypatch, legacy):
    async def run():
        client = Client(monkeypatch, legacy=legacy)
        payload = seal_payload(client)
        before = copy.deepcopy(payload)
        certificate = await execute(client, "deployment_seal", payload)
        assert set(certificate) == module().CERTIFICATE_FIELDS
        assert certificate == client.host.state.deployment_seal
        assert certificate["children"] == payload["children"]
        assert (
            certificate["execution_epoch"]
            == certificate["original_execution_epoch"]
            == client.info.run_id
        )
        assert certificate["proof_digest"] == digest(
            {key: value for key, value in certificate.items() if key != "proof_digest"}
        )
        certificate["children"][0]["run_id"] = "caller mutation"
        assert client.host.state.deployment_seal["children"] == payload["children"]
        assert payload == before
        assert bool(client.updates) is legacy and bool(client.signals) is (not legacy)

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["generic-error", "operation", "digest"])
def test_unknown_probe_is_never_positive_legacy_identification(monkeypatch, fault):
    async def run():
        client = Client(monkeypatch)

        def transform(index, value):
            if fault == "generic-error":
                return {"error": "validation_error"}
            view = value["deployment_lifecycle_observation"]
            view["operation" if fault == "operation" else "proof_digest"] = (
                "deployment_call_ended" if fault == "operation" else "f" * 64
            )
            return value

        client.transform = transform
        with pytest.raises(RalfError):
            await execute(client)
        assert not client.signals and not client.updates and not client.host.state.deployment_calls

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["first-epoch", "namespace", "workflow-type"])
def test_legacy_fallback_requires_genuine_original_sdk_identity(monkeypatch, fault):
    async def run():
        client = Client(monkeypatch, legacy=True)

        def transform(value):
            if fault == "first-epoch":
                value.raw_info.first_run_id = "before-reset"
            elif fault == "namespace":
                value.namespace = "foreign"
            else:
                value.workflow_type = "unrelated"

        client.describe_transform = transform
        with pytest.raises(RalfError):
            await execute(client)
        assert not client.signals and not client.updates and not client.host.state.deployment_calls

    asyncio.run(run())


@pytest.mark.parametrize("field,value", [("allowed", 1), ("attempt", True)])
def test_begin_ack_requires_exact_original_types(monkeypatch, field, value):
    async def run():
        client = Client(monkeypatch)

        def transform(index, response):
            result = response["deployment_lifecycle_observation"]["result"]
            if result is not None:
                result["receipt"][field] = value
            return response

        client.transform = transform
        with pytest.raises(RalfError):
            await execute(client)
        assert len(client.host.state.deployment_calls) == 1
        assert len(client.signals) == 1 and not client.updates

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["digest", "epoch", "namespace", "children"])
def test_seal_rejects_bad_certificate_even_when_other_fields_are_genuine(monkeypatch, fault):
    async def run():
        client = Client(monkeypatch)
        payload = seal_payload(client)

        def transform(index, response):
            result = response["deployment_lifecycle_observation"]["result"]
            if result is not None:
                certificate = result["receipt"]
                if fault == "digest":
                    certificate["proof_digest"] = "f" * 64
                else:
                    if fault == "epoch":
                        certificate["execution_epoch"] = "replacement"
                    elif fault == "namespace":
                        certificate["namespace"]["name"] = "foreign"
                    else:
                        certificate["children"][0]["run_id"] = "foreign-child"
                    certificate["proof_digest"] = digest(
                        {key: value for key, value in certificate.items() if key != "proof_digest"}
                    )
            return response

        client.transform = transform
        with pytest.raises(RalfError):
            await execute(client, "deployment_seal", payload)
        assert client.host.state.deployment_seal is not None
        assert len(client.signals) == 1 and not client.updates

    asyncio.run(run())


@pytest.mark.parametrize("port", ["client", "query", "signal"])
def test_port_replacement_during_probe_cannot_deliver_lifecycle_request(monkeypatch, port):
    async def run():
        client = Client(monkeypatch)

        def transform(index, value):
            if index == 1:
                if port == "client":
                    client.get_workflow_handle = lambda *args, **kwargs: None
                else:
                    setattr(client.current_handle, port, lambda *args, **kwargs: None)
            return value

        client.transform = transform
        with pytest.raises(RalfError):
            await execute(client)
        assert not client.signals and not client.updates and not client.host.state.deployment_calls

    asyncio.run(run())


def test_namespace_change_after_accepted_begin_preserves_unknown_obligation(monkeypatch):
    async def run():
        client = Client(monkeypatch)
        client.namespace_after_signal = "foreign"
        with pytest.raises(RalfError):
            await execute(client)
        assert len(client.signals) == len(client.host.state.deployment_calls) == 1
        assert not next(iter(client.host.state.deployment_calls.values()))["stopped"]
        assert not client.updates

    asyncio.run(run())


def test_lost_signal_response_does_not_retry_with_update_or_clear_original_begin(monkeypatch):
    async def run():
        client = Client(monkeypatch)
        failure = TimeoutError("delivery outcome unknown")
        client.signal_error = failure
        with pytest.raises(TimeoutError) as rejected:
            await execute(client)
        assert rejected.value is failure
        assert len(client.signals) == len(client.host.state.deployment_calls) == 1
        assert not client.updates

    asyncio.run(run())


def test_caller_cancellation_only_ends_observation_not_original_actual_call(monkeypatch):
    async def run():
        client = Client(monkeypatch)
        client.block_after_signal = True
        task = asyncio.create_task(execute(client))
        await client.delivered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(client.signals) == len(client.host.state.deployment_calls) == 1
        assert not next(iter(client.host.state.deployment_calls.values()))["stopped"]
        assert not client.updates

    asyncio.run(run())


def test_end_operation_cannot_enter_lifecycle_handler_allowlist(monkeypatch):
    async def run():
        client = Client(monkeypatch)
        with pytest.raises(RalfError):
            await execute(client, "deployment_call_ended")
        assert not client.signals and not client.updates and not client.host.state.deployment_calls

    asyncio.run(run())
