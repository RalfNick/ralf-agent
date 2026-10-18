"""Original Registry retirement keeps its full verifier and original epoch."""

import asyncio
import copy
from importlib import import_module
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("temporalio")

from ralf_agent.errors import RalfError
from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow, workflow
from ralf_agent.types import digest
from tests.test_temporal_deployment_public_registry import setup


def api():
    return import_module("ralf_agent.temporal_deployment_retirement_transport")


def fixture(monkeypatch, *, hold=False, failure=False):
    state, reserve = setup()
    root = state.reserve(reserve)["root_admission"]
    binding = {
        k: root[k]
        for k in (
            "scope",
            "command_id",
            "run_id",
            "request_digest",
            "manifest_digest",
            "proof_digest",
        )
    } | {
        "admission_policy": reserve["admission_policy"],
        "namespace": reserve["namespace"],
        "execution_epoch": "original-run",
    }
    state.bind_deployment_root(binding)
    certificate = {
        k: binding[k]
        for k in (
            "scope",
            "command_id",
            "run_id",
            "request_digest",
            "manifest_digest",
            "namespace",
            "execution_epoch",
        )
    }
    certificate.update(
        version=1,
        original_execution_epoch="original-run",
        terminal_state="cancelled",
        children=[],
        admission_digest="a" * 64,
        receipt_digest="b" * 64,
        closure_digest="c" * 64,
    )
    certificate["proof_digest"] = digest(certificate)
    request = {**binding, "certificate": certificate}
    node = object.__new__(TemporalCommandRegistryWorkflow)
    node.commands = state
    node._deployment_registry_initialization_error = None
    node._deployment_registry_epoch = "registry-epoch"
    info = NS(
        workflow_id=state.deployment.registry_id,
        namespace=reserve["namespace"]["name"],
        run_id="registry-epoch",
        first_execution_run_id="registry-epoch",
        original_execution_run_id="registry-epoch",
    )
    envelope = dict(
        version=1,
        scope=reserve["scope"],
        namespace=reserve["namespace"],
        registry_id=info.workflow_id,
        execution_epoch=info.run_id,
        observation_id="original",
        request=request,
    )
    gate, calls = asyncio.Event(), []
    monkeypatch.setattr(workflow, "info", lambda: info)

    async def execute(name, value, **options):
        from ralf_agent.temporal_deployment_release import RELEASE_ACTIVITY

        assert name == RELEASE_ACTIVITY and value["mode"] == "verify"
        assert value["registry_execution_epoch"] == info.run_id
        calls.append(copy.deepcopy(value))
        if hold:
            await gate.wait()
        if failure:
            return {"ok": False, "code": "definition_mismatch"}
        return {"ok": True, "result": {"root": value["root"], "certificate": value["certificate"]}}

    monkeypatch.setattr(workflow, "execute_activity", execute)
    return node, info, envelope, gate, calls


def test_probe_is_pure_and_original_async_handler_alone_commits_retirement(monkeypatch):
    async def run():
        node, info, envelope, _, calls = fixture(monkeypatch)
        before = copy.deepcopy(vars(node.commands.deployment))
        assert api().observe(node, envelope, info)["result"] is None
        assert vars(node.commands.deployment) == before
        await api().accept(node, envelope, info)
        result = api().observe(node, envelope, info)["result"]
        assert result["ok"] and result["receipt"]["released"] is True
        assert not node.commands.deployment.roots and len(calls) == 1
        await api().accept(node, envelope, info)
        other = {**envelope, "observation_id": "repeat"}
        await api().accept(node, other, info)
        assert api().observe(node, other, info)["result"] == result
        assert len(calls) == 1 and len(node.commands.deployment.retirements) == 1

    asyncio.run(run())


def test_pending_proof_keeps_root_and_deduplicates_delivery(monkeypatch):
    async def run():
        node, info, envelope, gate, calls = fixture(monkeypatch, hold=True)
        task = asyncio.create_task(api().accept(node, envelope, info))
        try:
            await asyncio.sleep(0)
            assert len(calls) == 1 and node.commands.deployment.roots
            assert api().observe(node, envelope, info)["result"] is None
            await api().accept(node, envelope, info)
            assert len(calls) == 1
        finally:
            gate.set()
            await task
        assert not node.commands.deployment.roots

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    ["scope", "namespace", "epoch", "reset", "registry", "policy", "certificate", "private"],
)
def test_wrong_identity_or_proof_cannot_retire_original_root(monkeypatch, fault):
    async def run():
        node, info, envelope, _, calls = fixture(monkeypatch)
        if fault == "scope":
            envelope["scope"] = {"workspace": "other", "principal": "other"}
        elif fault == "namespace":
            envelope["namespace"] = {
                **envelope["namespace"],
                "id": "22222222-2222-2222-2222-222222222222",
            }
        elif fault == "epoch":
            envelope["execution_epoch"] = "replacement"
        elif fault == "reset":
            info.first_execution_run_id = "before-reset"
        elif fault == "registry":
            envelope["registry_id"] = "other"
        elif fault == "policy":
            envelope["request"]["admission_policy"]["max_active_root_runs"] = 2
        elif fault == "certificate":
            envelope["request"]["certificate"]["terminal_state"] = "succeeded"
        else:
            node.commands.admission_protocol = 1
        await api().accept(node, envelope, info)
        assert not calls and node.commands.deployment.roots
        with pytest.raises(RalfError):
            api().observe(node, envelope, info)

    asyncio.run(run())


def test_verifier_refusal_retains_quota_and_is_observed(monkeypatch):
    async def run():
        node, info, envelope, _, calls = fixture(monkeypatch, failure=True)
        await api().accept(node, envelope, info)
        assert api().observe(node, envelope, info)["result"] == {
            "ok": False,
            "error": "definition_mismatch",
        }
        assert len(calls) == 1 and node.commands.deployment.roots

    asyncio.run(run())


def test_pending_capacity_never_evicts_original_verification(monkeypatch):
    async def run():
        node, info, envelope, gate, calls = fixture(monkeypatch, hold=True)
        tasks = [
            asyncio.create_task(api().accept(node, {**envelope, "observation_id": str(i)}, info))
            for i in range(64)
        ]
        try:
            await asyncio.sleep(0)
            assert len(calls) == 64 and node.commands.deployment.roots
            overflow = {**envelope, "observation_id": "overflow"}
            await api().accept(node, overflow, info)
            assert len(calls) == 64 and api().observe(node, overflow, info)["result"] is None
        finally:
            gate.set()
            await asyncio.gather(*tasks)
        await api().accept(node, overflow, info)
        assert api().observe(node, overflow, info)["result"]["receipt"]["released"] is True
        assert len(node._retirement_observations) == 64

    asyncio.run(run())
