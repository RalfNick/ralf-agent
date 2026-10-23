"""Original Coding receipts and stops retain their full History reducers."""

import asyncio
import copy
from importlib import import_module
from types import SimpleNamespace as NS

import pytest

from relf_agent.errors import RalfError
from relf_agent.temporal_workflow import TemporalRunWorkflow, workflow
from tests.test_temporal_coding_state import (
    OWNER,
    admission,
    grant,
    native_stop,
    owner_dead_payload,
    ready,
)

OPERATIONS = ("coding_receipt", "admit_coding_stop", "coding_owner_stopped")


def api():
    return import_module("relf_agent.temporal_coding_recovery_transport")


def fixture(monkeypatch, operation="coding_receipt"):
    state, action, request = ready()
    grant(state, request)
    proof = {**admission(request), "kind": "owner", "evidence": copy.deepcopy(OWNER)}
    if operation == "admit_coding_stop":
        proof = {**admission(request), "invocation_id": "c" * 32}
    elif operation == "coding_owner_stopped":
        state.admit_coding_stop({**admission(request), "invocation_id": "c" * 32})
        native_stop(state, request)
        proof = owner_dead_payload(request)
    node = object.__new__(TemporalRunWorkflow)
    node.state, node.wake_revision = state, 0
    info = NS(
        workflow_id=state.run_id,
        namespace="default",
        run_id=state.epoch,
        first_execution_run_id=state.epoch,
        original_execution_run_id=state.epoch,
    )
    monkeypatch.setattr(workflow, "info", lambda: info)
    envelope = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "namespace": "default",
        "execution_epoch": state.epoch,
        "observation_id": "original",
        "operation": operation,
        "proof": proof,
    }
    return node, info, envelope


@pytest.mark.parametrize("operation", OPERATIONS)
def test_whole_original_reducer_and_wake_preserve_idempotent_receipt(monkeypatch, operation):
    async def run():
        node, info, e = fixture(monkeypatch, operation)
        before = copy.deepcopy(vars(node.state))
        assert api().observe(node, e, info)["result"] is None
        assert vars(node.state) == before
        await api().accept(node, e, info)
        result = api().observe(node, e, info)["result"]
        assert result["ok"] is True and node.wake_revision == 1
        await api().accept(node, e, info)
        assert node.wake_revision == 1
        repeated = {**e, "observation_id": "again"}
        await api().accept(node, repeated, info)
        assert api().observe(node, repeated, info)["result"] == result
        assert node.wake_revision == 2
        assert (
            node.state.actions[-1]["delegated_execution"]["grants"]
            == before["actions"][-1]["delegated_execution"]["grants"]
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["scope", "namespace", "epoch", "reset", "action", "request", "grant", "collision"]
)
def test_foreign_or_new_grant_cannot_mutate_original_history(monkeypatch, fault):
    async def run():
        node, info, e = fixture(monkeypatch)
        before = copy.deepcopy(vars(node.state))
        if fault == "scope":
            e["scope"] = {"workspace": "other", "principal": "other"}
        elif fault == "namespace":
            e["namespace"] = "other"
        elif fault == "epoch":
            e["execution_epoch"] = "other"
        elif fault == "reset":
            info.original_execution_run_id = "other"
        elif fault == "action":
            e["proof"]["action_id"] = "other"
        elif fault == "request":
            e["proof"]["request_digest"] = "f" * 64
        elif fault == "grant":
            e["operation"] = "admit_coding_phase"
        else:
            await api().accept(node, e, info)
            before = copy.deepcopy(vars(node.state))
            e = copy.deepcopy(e)
            e["proof"]["evidence"]["pid"] = 12346
        try:
            await api().accept(node, e, info)
            assert api().observe(node, e, info)["result"]["ok"] is False
        except RalfError:
            pass
        assert vars(node.state) == before

    asyncio.run(run())


def test_workflow_probe_signal_and_bounded_cache(monkeypatch):
    async def run():
        node, _, e = fixture(monkeypatch)
        query = {"kind": "status", "scope": node.state.scope, "coding_recovery_observation": e}
        assert node.view(query)["coding_recovery_observation"]["result"] is None
        await node.coding_recovery(e)
        assert node.view(query)["coding_recovery_observation"]["result"]["ok"]
        for i in range(70):
            await node.coding_recovery({**e, "observation_id": str(i)})
        assert len(node._coding_recovery_observations) == 64

    asyncio.run(run())


def test_pending_original_handlers_are_not_evicted_or_duplicated(monkeypatch):
    async def run():
        node, info, e = fixture(monkeypatch)
        original = node.coding_receipt
        gate = asyncio.Event()
        entered = []

        async def held(proof):
            entered.append(proof)
            await gate.wait()
            return await original(proof)

        node.coding_receipt = held
        tasks = [
            asyncio.create_task(api().accept(node, {**e, "observation_id": str(i)}, info))
            for i in range(64)
        ]
        try:
            await asyncio.sleep(0)
            await api().accept(node, {**e, "observation_id": "overflow"}, info)
            await api().accept(node, {**e, "observation_id": "0"}, info)
            assert len(node._coding_recovery_observations) == len(entered) == 64
            assert api().observe(node, {**e, "observation_id": "0"}, info)["result"] is None
        finally:
            gate.set()
            await asyncio.gather(*tasks)

    asyncio.run(run())
