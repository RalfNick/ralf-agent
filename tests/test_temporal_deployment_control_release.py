"""Registry-owned SDK verification of original descendant command identity."""

import asyncio
from types import SimpleNamespace

import pytest

from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME
from ralf_agent.types import digest


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


def environment(monkeypatch, publication=2, registry_version=2, *, nested=False):
    from temporalio.client import WorkflowExecutionStatus

    from tests.test_temporal_deployment_coding_release import environment as original
    from tests.test_temporal_deployment_execution import child_setup, sealed

    runtime, client, _, root, _, _ = original(monkeypatch, publication, registry_version)
    child, _, _ = child_setup(
        runtime,
        client,
        {"run_id": root["run_id"]},
        child_id="original-intermediate" if nested else "original-leaf",
        kind="graph" if nested else "agent",
    )
    targets = [child]
    if nested:
        leaf, _, _ = child_setup(runtime, client, child, child_id="original-leaf")
        client.proofs[leaf["run_id"]]["execution_epoch"] = "leaf-epoch"
        client.proofs[leaf["run_id"]]["original_execution_epoch"] = "leaf-epoch"
        client.descriptions[leaf["run_id"]].run_id = "leaf-epoch"
        targets.append(leaf)
        child = leaf
    for target in targets:
        proof = client.proofs[target["run_id"]]
        proof["admission_receipt"] = sealed(
            {
                "version": 1,
                "run_id": proof["run_id"],
                "execution_epoch": proof["execution_epoch"],
                "root": root["admission_receipt"]["root"],
                "metadata_digest": digest(proof["admission"]),
            }
        )
        parent_id = proof["admission"]["lineage"][-1]["parent_run_id"]
        client.proofs[parent_id]["children"][0]["deployment_execution_epoch"] = proof[
            "execution_epoch"
        ]
    for identity, proof in tuple(client.proofs.items()):
        client.proofs[identity] = sealed(proof)
        client.descriptions[identity].raw_info = SimpleNamespace(
            first_run_id=proof["execution_epoch"]
        )
        client.descriptions[identity].task_queue = "original-queue"
    registry = client.descriptions[client.registry.registry_id]
    registry.workflow_type, registry.status = COMMAND_REGISTRY_NAME, WorkflowExecutionStatus.RUNNING
    target = client.proofs[child["run_id"]]
    value = {
        "mode": "control",
        "scope": root["scope"],
        "root": root["admission_receipt"]["root"],
        "target": target["run_id"],
        "target_execution_epoch": target["execution_epoch"],
        "manifest": runtime.manifest,
        "registry_execution_epoch": "registry-epoch",
    }
    info = SimpleNamespace(
        workflow_id=client.registry.registry_id,
        workflow_run_id="registry-epoch",
        workflow_namespace=client.namespace,
    )
    binding = {
        "version": 1,
        "scope": root["scope"],
        "namespace": root["namespace"],
        "target": target["run_id"],
        "target_execution_epoch": target["execution_epoch"],
        "root_run_id": root["run_id"],
        "root_execution_epoch": root["execution_epoch"],
    }
    client.updates.clear()
    return runtime, client, value, info, binding


@pytest.mark.parametrize("publication,registry_version", [(2, 2), (2, 3), (3, 3)])
@pytest.mark.parametrize("nested", [False, True])
def test_control_verifier_reads_complete_original_ancestry_without_mutation(
    monkeypatch, publication, registry_version, nested
):
    from ralf_agent import temporal_deployment_release as release

    async def run():
        runtime, client, value, info, binding = environment(
            monkeypatch, publication, registry_version, nested=nested
        )
        assert await release.execute(runtime, client, value, info) == binding
        assert not client.updates and not client.retirements
        assert len(client.registry.roots) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        "registry-first",
        "registry-status",
        "registry-info",
        "target-first",
        "ancestor-first",
        "root-first",
        "scope",
        "namespace",
        "parent",
        "missing-pin",
        "wrong-pin",
        "call-id",
        "receipt-root",
        "root-epoch",
        "manifest",
        "raw-attestation",
        "old-registry",
    ],
)
def test_control_verifier_refuses_unverified_identity_without_any_history_mutation(
    monkeypatch, fault
):
    from temporalio.client import WorkflowExecutionStatus

    from ralf_agent import temporal_deployment_release as release
    from tests.test_temporal_deployment_execution import sealed

    async def run():
        runtime, client, value, info, _ = environment(
            monkeypatch, 3, 2 if fault == "old-registry" else 3, nested=True
        )
        target = client.proofs[value["target"]]
        parent_id = target["admission"]["lineage"][-1]["parent_run_id"]
        parent = client.proofs[parent_id]
        if fault == "registry-first":
            client.descriptions[
                client.registry.registry_id
            ].raw_info.first_run_id = "old-registry-epoch"
        elif fault == "registry-status":
            client.descriptions[
                client.registry.registry_id
            ].status = WorkflowExecutionStatus.TERMINATED
        elif fault == "registry-info":
            info.workflow_run_id = "foreign-registry-epoch"
        elif fault == "target-first":
            client.descriptions[value["target"]].raw_info.first_run_id = "pre-reset-target"
        elif fault == "ancestor-first":
            client.descriptions[parent_id].raw_info.first_run_id = "pre-reset-parent"
        elif fault == "root-first":
            client.descriptions[value["root"]["run_id"]].raw_info.first_run_id = "pre-reset-root"
        elif fault == "scope":
            value["scope"] = {**value["scope"], "principal": "foreign"}
        elif fault == "namespace":
            client.namespace_uuid = "22222222-2222-2222-2222-222222222222"
        elif fault == "parent":
            client.descriptions[value["target"]].parent_run_id = "foreign-parent-epoch"
        elif fault in {"missing-pin", "wrong-pin"}:
            parent["children"][0]["deployment_execution_epoch"] = (
                None if fault == "missing-pin" else "foreign-child-epoch"
            )
        elif fault == "call-id":
            parent["children"][0]["id"] = "foreign-intent"
        elif fault == "receipt-root":
            target["admission_receipt"]["root"]["execution_epoch"] = "foreign-root-epoch"
            target["admission_receipt"] = sealed(target["admission_receipt"])
        elif fault == "root-epoch":
            value["root"]["execution_epoch"] = "foreign-root-epoch"
        elif fault == "manifest":
            value["manifest"] = {**value["manifest"], "foreign": True}
        elif fault == "raw-attestation":
            value["control_binding"] = {"forged": True}
        client.proofs[parent_id], client.proofs[value["target"]] = sealed(parent), sealed(target)
        with pytest.raises(DefinitionMismatch):
            await release.execute(runtime, client, value, info)
        assert not client.updates and not client.retirements

    asyncio.run(run())


def test_fixed_release_registration_wraps_control_result_and_sanitized_refusal(monkeypatch):
    from temporalio import activity

    from ralf_agent import temporal_deployment_release as release

    async def run():
        runtime, client, value, info, binding = environment(monkeypatch)
        monkeypatch.setattr(activity, "info", lambda: info)
        registered = release.registered_activity(runtime, client)
        assert await registered(value) == {"ok": True, "result": binding}
        assert release.is_registered_activity(runtime, client, registered)
        value["root"]["execution_epoch"] = "foreign"
        assert await registered(value) == {"ok": False, "code": "definition_mismatch"}
        assert not client.updates

    asyncio.run(run())
