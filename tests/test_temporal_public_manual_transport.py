"""Public strong manual observations keep original SDK proof and Action slots."""

import asyncio
import copy
from importlib import import_module
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("temporalio")

from relf_agent.errors import RalfError
from relf_agent.temporal_workflow import TemporalCommandRegistryWorkflow, workflow
from tests.test_temporal_manual_recovery import manual_request, verified
from tests.test_temporal_recovery_capacity import full_registry


def api():
    return import_module("relf_agent.temporal_public_manual_transport")


def fixture(monkeypatch, *, version=2, hold=False, failure=False):
    state, original = full_registry(version)
    request = manual_request(original)
    node = object.__new__(TemporalCommandRegistryWorkflow)
    node.commands = state
    node._deployment_registry_initialization_error = None
    node._deployment_registry_epoch = "registry-epoch"
    info = NS(
        workflow_id=state.deployment.registry_id,
        namespace=request["namespace"]["name"],
        run_id="registry-epoch",
        first_execution_run_id="registry-epoch",
        original_execution_run_id="registry-epoch",
    )
    envelope = dict(
        version=1,
        scope=request["scope"],
        namespace=request["namespace"],
        registry_id=info.workflow_id,
        execution_epoch=info.run_id,
        observation_id="original",
        request=request,
    )
    gate, calls = asyncio.Event(), []
    prepared = state.prepare_deployment_control(request)
    monkeypatch.setattr(workflow, "info", lambda: info)

    async def execute(name, value, **options):
        from relf_agent.temporal_deployment_release import RELEASE_ACTIVITY

        assert name == RELEASE_ACTIVITY and value["mode"] == "manual_control"
        assert value["registry_execution_epoch"] == info.run_id
        assert value["payload"] == request["recovery"]["payload"]
        assert options["retry_policy"].maximum_attempts == 1
        calls.append(copy.deepcopy(value))
        if hold:
            await gate.wait()
        return (
            {"ok": False, "code": "definition_mismatch"}
            if failure
            else {"ok": True, "result": verified(prepared)}
        )

    monkeypatch.setattr(workflow, "execute_activity", execute)
    return node, info, envelope, gate, calls


@pytest.mark.parametrize("version", [2, 3, 4])
def test_observation_is_pure_and_full_handler_commits_only_one_original_slot(monkeypatch, version):
    async def run():
        node, info, envelope, _, calls = fixture(monkeypatch, version=version)
        before = copy.deepcopy(vars(node.commands.deployment))
        assert api().observe(node, envelope, info)["result"] is None
        assert vars(node.commands.deployment) == before
        await api().accept(node, envelope, info)
        result = api().observe(node, envelope, info)["result"]
        assert result["ok"] and result["receipt"]["control_binding"]["version"] == 2
        await api().accept(node, envelope, info)
        repeat = {**envelope, "observation_id": "repeat"}
        await api().accept(node, repeat, info)
        assert api().observe(node, repeat, info)["result"] == result
        assert len(calls) == 1 and len(node.commands.deployment.manual_recoveries) == 1
        assert (
            len(node.commands.deployment.commands) == 2 and len(node.commands.deployment.roots) == 1
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "namespace",
        "epoch",
        "reset",
        "registry",
        "policy",
        "payload",
        "descendant",
        "normal",
        "private",
    ],
)
def test_invalid_or_other_control_cannot_claim_manual_slot(monkeypatch, fault):
    async def run():
        node, info, envelope, _, calls = fixture(monkeypatch)
        if fault == "scope":
            envelope["scope"] = {"workspace": "other", "principal": "p"}
        elif fault == "namespace":
            envelope["namespace"] = {
                **envelope["namespace"],
                "id": "22222222-2222-2222-2222-222222222222",
            }
        elif fault == "epoch":
            envelope["execution_epoch"] = "replacement"
        elif fault == "reset":
            info.original_execution_run_id = "reset"
        elif fault == "registry":
            envelope["registry_id"] = "other"
        elif fault == "policy":
            envelope["request"]["admission_policy"]["max_active_root_runs"] = 2
        elif fault == "payload":
            envelope["request"]["recovery"]["payload"]["result"] = "changed"
        elif fault == "descendant":
            envelope["request"]["descendant"] = {}
        elif fault == "normal":
            del envelope["request"]["recovery"]
        else:
            node.commands.admission_protocol = 1
        await api().accept(node, envelope, info)
        assert not calls and len(node.commands.deployment.commands) == 1
        with pytest.raises(RalfError):
            api().observe(node, envelope, info)

    asyncio.run(run())


def test_failed_original_verifier_keeps_slot_and_root_unmodified(monkeypatch):
    async def run():
        node, info, envelope, _, calls = fixture(monkeypatch, failure=True)
        await api().accept(node, envelope, info)
        assert api().observe(node, envelope, info)["result"] == {
            "ok": False,
            "error": "definition_mismatch",
        }
        assert len(calls) == 1 and not node.commands.deployment.manual_recoveries
        assert len(node.commands.deployment.commands) == len(node.commands.deployment.roots) == 1

    asyncio.run(run())


def test_pending_verifiers_are_bounded_and_not_evicted(monkeypatch):
    async def run():
        node, info, envelope, gate, calls = fixture(monkeypatch, hold=True)
        tasks = [
            asyncio.create_task(api().accept(node, {**envelope, "observation_id": str(i)}, info))
            for i in range(64)
        ]
        try:
            await asyncio.sleep(0)
            assert len(calls) == 64 and len(node.commands.deployment.commands) == 1
            await api().accept(node, envelope, info)
            assert api().observe(node, envelope, info)["result"] is None
            assert len(calls) == 64
        finally:
            gate.set()
            await asyncio.gather(*tasks)
        await api().accept(node, envelope, info)
        assert api().observe(node, envelope, info)["result"]["ok"] is True
        assert len(node.commands.deployment.manual_recoveries) == 1

    asyncio.run(run())
