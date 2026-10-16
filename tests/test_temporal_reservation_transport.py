"""Original reservation evidence survives Update exhaustion and observer loss."""

import asyncio
import copy

import pytest

pytest.importorskip("temporalio")

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_deployment_submissions import _update
from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow
from tests.test_temporal_recovery_capacity import control, full_registry


def registry(version=2):
    value = object.__new__(TemporalCommandRegistryWorkflow)
    value.commands, original = full_registry(version)
    value._deployment_registry_epoch = None
    value._deployment_registry_initialization_error = None
    return value, control(original, "cancel", "stop-original")


def observe(request, identity="first"):
    return {
        "kind": "deployment_reserve_receipt",
        "scope": request["scope"],
        "observation_id": identity,
        "request": copy.deepcopy(request),
    }


@pytest.mark.parametrize("version", [2, 3, 4])
def test_original_reservation_requires_processing_and_keeps_one_business_record(version):
    owner, request = registry(version)
    envelope = observe(request)
    before = copy.deepcopy(vars(owner.commands.deployment))
    pending = owner.view(envelope)
    assert pending.get("version") == 1 and pending["result"] is None
    assert vars(owner.commands.deployment) == before
    owner.reserve_command(envelope)
    receipt = owner.view(envelope)["result"]["receipt"]
    assert receipt["command_id"] == "stop-original"
    assert receipt["record_state"] == "durably_recorded"
    for index in range(80):
        retry = observe(request, f"retry-{index}")
        owner.reserve_command(retry)
        assert owner.view(retry)["result"]["receipt"] == receipt
    assert len(owner.commands.deployment.commands) == 2
    # Evicting transport observations must not evict business identities.
    assert len(owner._reserve_observations) == 64
    assert owner.view(envelope)["result"] is None
    owner.reserve_command(envelope)
    assert owner.view(envelope)["result"]["receipt"] == receipt
    assert len(owner.commands.deployment.commands) == 2


@pytest.mark.parametrize("mutation", ["scope", "namespace", "descendant", "epoch"])
def test_invalid_signal_never_records_or_poison_original_authority(mutation):
    owner, request = registry()
    envelope = observe(request)
    if mutation == "scope":
        envelope["scope"] = {**request["scope"], "principal": "other"}
    elif mutation == "namespace":
        envelope["request"]["namespace"]["id"] = "22222222-2222-2222-2222-222222222222"
    elif mutation == "descendant":
        envelope["request"]["descendant"] = {"root_command_id": "one", "execution_epoch": "x"}
    else:
        owner._deployment_registry_initialization_error = "definition_mismatch"
    before = copy.deepcopy(vars(owner.commands.deployment))
    owner.reserve_command(envelope)
    assert owner.view(envelope).get("error") in {"authorization_denied", "definition_mismatch"}
    assert vars(owner.commands.deployment) == before
    assert not getattr(owner, "_reserve_observations", {})


class Handle:
    def __init__(self, owner):
        self.owner = owner
        self.sent = asyncio.Event()
        self.process = asyncio.Event()
        self.envelope = None

    async def query(self, name, value):
        assert name == "view"
        if self.envelope is not None:
            await self.process.wait()
            self.owner.reserve_command(self.envelope)
            self.envelope = None
        return self.owner.view(value)

    async def signal(self, name, value):
        assert name == "reserve_command"
        self.envelope = copy.deepcopy(value)
        self.sent.set()

    async def execute_update(self, *args, **options):
        raise AssertionError("Distinct SDK Update allowance is already exhausted")


def test_sdk_signal_ack_never_becomes_acceptance_without_original_result():
    async def run():
        owner, request = registry()
        handle = Handle(owner)
        task = asyncio.create_task(_update(handle, "reserve", request))
        sent = asyncio.create_task(handle.sent.wait())
        done, _ = await asyncio.wait({task, sent}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert handle.sent.is_set() and not task.done()
        assert len(owner.commands.deployment.commands) == 1
        handle.process.set()
        receipt = await task
        assert receipt["record_state"] == "durably_recorded"
        assert len(owner.commands.deployment.commands) == 2
        await sent

    asyncio.run(run())


def test_observer_cancellation_preserves_original_command_and_retry_identity():
    async def run():
        owner, request = registry()
        handle = Handle(owner)
        task = asyncio.create_task(_update(handle, "reserve", request))
        sent = asyncio.create_task(handle.sent.wait())
        done, _ = await asyncio.wait({task, sent}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        owner.reserve_command(handle.envelope)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(owner.commands.deployment.commands) == 2
        handle.envelope = None
        handle.process.set()
        receipt = await _update(handle, "reserve", request)
        assert receipt["command_id"] == "stop-original"
        assert len(owner.commands.deployment.commands) == 2
        await sent

    asyncio.run(run())


def test_unsupported_old_worker_is_rejected_before_signal():
    class Old(Handle):
        async def query(self, name, value):
            return {"error": "validation_error"}

    async def run():
        owner, request = registry()
        handle = Old(owner)
        with pytest.raises(DefinitionMismatch):
            await _update(handle, "reserve", request)
        assert not handle.sent.is_set()

    asyncio.run(run())


def test_observation_id_cannot_replace_original_request_or_leak_other_result():
    owner, request = registry()
    envelope = observe(request)
    owner.reserve_command(envelope)
    original = owner.view(envelope)
    changed = copy.deepcopy(envelope)
    changed["request"]["command_id"] = "other-business-command"
    assert owner.view(changed) == {"error": "idempotency_conflict"}
    owner.reserve_command(changed)
    assert owner.view(envelope) == original
    assert len(owner.commands.deployment.commands) == 2


def test_refused_observation_does_not_permanently_reject_later_original_retry():
    from ralf_agent.temporal_state import TemporalCommandRegistryState
    from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY, setup

    owner, _ = registry()
    owner.commands = TemporalCommandRegistryState(
        admission_policy=POLICY.identity, namespace=NAMESPACE, admission_protocol=2, capacity=1
    )
    _, original = setup()
    root = owner.commands.reserve(original)["root_admission"]
    request = control(original, "cancel", "stop-original")
    refused = observe(request)
    owner.reserve_command(refused)
    assert owner.view(refused)["result"] == {"ok": False, "error": "validation_error"}
    # The original SDK epoch becomes known; this is not a new business request.
    owner.commands.bind_deployment_root(
        {
            **{
                k: root[k]
                for k in (
                    "scope",
                    "namespace",
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "admission_policy": POLICY.identity,
            "execution_epoch": "original-root-epoch",
        }
    )
    retry = observe(request, "retry-after-binding")
    owner.reserve_command(retry)
    assert owner.view(retry)["result"]["receipt"]["command_id"] == "stop-original"
    assert owner.view(refused)["result"]["ok"] is False
    assert len(owner.commands.deployment.commands) == 2
