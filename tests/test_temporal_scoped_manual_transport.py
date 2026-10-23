"""Async manual observations retain original Registry proof and bounded pending work."""

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from relf_agent.errors import RalfError
from relf_agent.temporal_workflow import TemporalCommandRegistryWorkflow, workflow
from relf_agent.types import digest
from tests.test_temporal_scoped_manual_recovery_state import (
    manual_request,
    original_state,
    verified,
)


def fixture(monkeypatch, *, hold=False, failure=False):
    state, _ = original_state()
    node = object.__new__(TemporalCommandRegistryWorkflow)
    node.commands = state
    node._deployment_registry_initialization_error = node._deployment_registry_epoch = None
    info = NS(
        workflow_id="ralf-temporal-commands-" + digest(state.scope),
        namespace="default",
        run_id="registry-epoch",
        first_execution_run_id="registry-epoch",
        original_execution_run_id="registry-epoch",
        task_queue="original-queue",
    )
    request = manual_request()
    envelope = {
        "version": 1,
        "scope": state.scope,
        "namespace": "default",
        "execution_epoch": info.run_id,
        "observation_id": "original",
        "request": request,
    }
    gate, calls = asyncio.Event(), []
    monkeypatch.setattr(workflow, "info", lambda: info)

    async def execute(name, value, **options):
        from relf_agent.temporal_parent_state import CONTROL_ACTIVITY

        assert name == CONTROL_ACTIVITY and value["mode"] == "scoped_manual"
        assert options["task_queue"] == info.task_queue
        assert options["start_to_close_timeout"].total_seconds() == 30
        assert options["schedule_to_close_timeout"].total_seconds() == 65
        assert options["retry_policy"].maximum_attempts == 1
        calls.append(copy.deepcopy(value))
        if hold:
            await gate.wait()
        if failure:
            return {"ok": False, "code": "definition_mismatch"}
        # The Activity receives the pre-await prepared submission. Other
        # confirmations may commit while it waits; do not reread that state.
        return {"ok": True, "result": verified({"submission": value["submission"]}, request)}

    monkeypatch.setattr(workflow, "execute_activity", execute)
    return node, info, envelope, gate, calls


def test_pure_probe_and_signal_reuse_original_full_verifier_once(monkeypatch):
    from relf_agent.temporal_scoped_manual_transport import accept, observe

    async def run():
        host, info, envelope, _, calls = fixture(monkeypatch)
        before = copy.deepcopy(vars(host.commands))
        assert observe(host, envelope, info)["result"] is None
        assert vars(host.commands) == before
        await accept(host, envelope, info)
        first = observe(host, envelope, info)["result"]
        assert (
            first["ok"]
            and first["receipt"]["control_binding"]["target_execution_epoch"] == "original-epoch"
        )
        await accept(host, envelope, info)
        await accept(host, {**envelope, "observation_id": "repeat"}, info)
        assert len(calls) == 1 and len(host.commands.identities) == 2
        assert observe(host, {**envelope, "observation_id": "repeat"}, info)["result"] == first

    asyncio.run(run())


def test_original_registry_signal_and_query_use_the_same_observation(monkeypatch):
    from relf_agent.temporal_scoped_manual_recovery import configuration

    async def run():
        host, info, envelope, _, calls = fixture(monkeypatch)
        request = {
            "kind": "scoped_manual_configuration",
            "scope": host.commands.scope,
            "manual_observation": envelope,
        }
        assert host.view(request)["manual_observation"]["result"] is None
        assert not calls and len(host.commands.identities) == 1
        await host.reserve_scoped_manual(envelope)
        assert host.view(request)["manual_observation"]["result"]["ok"]
        assert host.view(
            {k: v for k, v in request.items() if k != "manual_observation"}
        ) == configuration(host.commands, info)
        assert len(calls) == 1

    asyncio.run(run())


def test_inflight_duplicate_is_claimed_before_await_and_query_never_confirms_delivery(monkeypatch):
    from relf_agent.temporal_scoped_manual_transport import accept, observe

    async def run():
        host, info, envelope, gate, calls = fixture(monkeypatch, hold=True)
        task = asyncio.create_task(accept(host, envelope, info))
        await asyncio.sleep(0)
        await accept(host, envelope, info)
        assert len(calls) == 1 and len(host.commands.identities) == 1
        assert observe(host, envelope, info)["result"] is None
        gate.set()
        await task
        assert observe(host, envelope, info)["result"]["ok"]
        assert len(host.commands.identities) == 2

    asyncio.run(run())


def test_pending_bound_never_evicts_inflight_or_business_identity(monkeypatch):
    from relf_agent.temporal_scoped_manual_transport import accept, observe

    async def run():
        host, info, e, gate, calls = fixture(monkeypatch, hold=True)
        tasks = [
            asyncio.create_task(accept(host, {**e, "observation_id": str(i)}, info))
            for i in range(64)
        ]
        try:
            await asyncio.sleep(0)
            await accept(host, {**e, "observation_id": "overflow"}, info)
            assert len(calls) == 64 and len(host._manual_observations) == 64
            assert observe(host, {**e, "observation_id": "overflow"}, info)["result"] is None
            assert len(host.commands.identities) == 1
        finally:
            gate.set()
            await asyncio.gather(*tasks)
        assert all(value["result"]["ok"] for value in host._manual_observations.values())
        await accept(host, {**e, "observation_id": "overflow"}, info)
        assert observe(host, {**e, "observation_id": "overflow"}, info)["result"]["ok"]
        assert len(host._manual_observations) == 64 and len(host.commands.identities) == 2
        assert len(calls) == 64

    asyncio.run(run())


def test_rejected_original_proof_is_recorded_without_a_business_slot(monkeypatch):
    from relf_agent.temporal_scoped_manual_transport import accept, observe

    async def run():
        host, info, envelope, _, calls = fixture(monkeypatch, failure=True)
        await accept(host, envelope, info)
        assert observe(host, envelope, info)["result"] == {
            "ok": False,
            "error": "definition_mismatch",
        }
        assert len(calls) == 1 and len(host.commands.identities) == 1
        assert not host.commands.scoped_manual_slots

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    ["scope", "namespace", "epoch", "reset", "request", "digest", "query", "version", "nonce"],
)
def test_invalid_signal_never_reaches_original_proof(monkeypatch, fault):
    from relf_agent.temporal_scoped_manual_transport import accept, observe

    async def run():
        host, info, e, _, calls = fixture(monkeypatch)
        e = copy.deepcopy(e)
        if fault == "scope":
            e["scope"] = {"workspace": "other"}
        elif fault == "namespace":
            e["namespace"] = "other"
        elif fault == "epoch":
            e["execution_epoch"] = "other"
        elif fault == "reset":
            info.first_execution_run_id = "before"
        elif fault == "request":
            e["request"]["recovery"]["registry_execution_epoch"] = "other"
        elif fault == "digest":
            e["request"]["payload_digest"] = "a" * 64
        elif fault == "query":
            e["request"]["recovery"]["payload"]["query"] = True
        elif fault == "version":
            e["version"] = True
        else:
            e["observation_id"] = "x" * 129
        before = copy.deepcopy(vars(host.commands))
        await accept(host, e, info)
        assert not calls and vars(host.commands) == before
        assert not getattr(host, "_manual_observations", {})
        with pytest.raises(RalfError):
            observe(host, e, info)

    asyncio.run(run())


def test_observation_collision_never_replaces_original_request_or_receipt(monkeypatch):
    from relf_agent.temporal_scoped_manual_transport import accept, observe

    async def run():
        host, info, e, _, calls = fixture(monkeypatch)
        await accept(host, e, info)
        other = copy.deepcopy(e)
        other["request"]["command_id"] = "different"
        await accept(host, other, info)
        assert len(calls) == 1 and len(host.commands.identities) == 2
        with pytest.raises(RalfError):
            observe(host, other, info)
        assert observe(host, e, info)["result"]["ok"]

    asyncio.run(run())
