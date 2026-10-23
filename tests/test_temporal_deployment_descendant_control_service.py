"""Actual public v2 descendant approval using deterministic read-only business.

Requires an externally owned Temporal Service. No Coding, native process,
PostgreSQL, Docker, or model network is involved in this regression.
"""

import asyncio
import copy
import json
import os
from dataclasses import asdict

import pytest

from relf_agent.temporal_deployment_admission import registry_id
from relf_agent.types import canonical
from tests.test_temporal_deployment_dispatch_service import _case, _eventually
from tests.test_temporal_deployment_public_service import public_system

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"),
    reason="requires externally owned actual Temporal Service",
)


def test_actual_public_v2_graph_descendant_approval_uses_original_root_and_receipt(tmp_path):
    async def scenario():
        from temporalio.api.enums.v1 import EventType

        async with public_system(tmp_path, approval=True) as system, system.worker():
            spec, expected_reads, expected_descendants, value = _case("graph-sequential")
            manifest = json.loads(canonical(system.runtime.orchestration_release))
            assert manifest["deployment_admission_protocol"]["version"] == 2
            original = await system.submit(spec, value)
            root_sdk = system.client.get_workflow_handle(original.run_id)
            root_epoch = (await root_sdk.describe()).run_id
            controls, observed = [], []

            for index in range(expected_descendants):
                waiting = await _eventually(
                    lambda: system.engine.status(original.run_id),
                    lambda status: (
                        status.state == "waiting_approval"
                        and any(
                            item.get("run_id") not in {control[0] for control in controls}
                            for item in status.pending
                        )
                    ),
                )
                pending = next(
                    item
                    for item in waiting.pending
                    if item.get("run_id") not in {control[0] for control in controls}
                )
                child_id = pending["run_id"]
                assert child_id != original.run_id
                child_sdk = system.client.get_workflow_handle(child_id)
                child_description = await child_sdk.describe()
                child_epoch = child_description.run_id
                assert child_description.parent_id == original.run_id
                assert child_description.parent_run_id == root_epoch
                history = await child_sdk.fetch_history()
                started = history.events[0].workflow_execution_started_event_attributes
                assert started.original_execution_run_id == child_epoch
                assert started.first_execution_run_id == child_epoch
                assert started.parent_workflow_execution.workflow_id == original.run_id
                assert started.parent_workflow_execution.run_id == root_epoch
                assert started.parent_workflow_namespace == system.namespace["name"]
                assert started.task_queue.name == system.queue
                proof = (await system.closure(child_id))["deployment"]
                assert proof["scope"] == asdict(system.scope)
                assert proof["namespace"] == system.namespace
                assert proof["execution_epoch"] == proof["original_execution_epoch"] == child_epoch
                assert proof["manifest"] == manifest
                root_proof = (await system.closure(original.run_id))["deployment"]
                assert proof["admission"]["root"] == root_proof["admission"]["root"]
                assert len(proof["admission"]["lineage"]) == 1
                link = proof["admission"]["lineage"][0]
                assert link["parent_run_id"] == original.run_id
                assert link["parent_execution_epoch"] == root_epoch
                assert link["child_run_id"] == child_id
                held = await system.count(1)
                assert held["counts"]["held_root_runs_for_scope"] == 1
                assert len(held["held_roots"]) == 1
                root = held["held_roots"][0]
                assert root["run_id"] == original.run_id
                assert root["state"] == "held-bound" and root["execution_epoch"] == root_epoch
                assert len(system.probe.reads) == index

                # Only the public typed API supplies the control. The production
                # Registry verifier must derive this child's root association.
                command_id = "approve-descendant-" + str(index)
                receipt = await system.engine.approve(
                    child_id, pending["action_id"], pending["digest"], command_id=command_id
                )
                assert receipt.run_id == child_id and receipt.kind == "approve"
                assert (
                    receipt.record_state == "durably_recorded" and receipt.apply_state == "applied"
                )
                assert (
                    await system.engine.approve(
                        child_id, pending["action_id"], pending["digest"], command_id=command_id
                    )
                    == receipt
                )
                assert (await child_sdk.describe()).run_id == child_epoch
                controls.append((child_id, pending, command_id, receipt, child_epoch))
                observed.append({"child_id": child_id, "child_epoch": child_epoch, "held": held})

            terminal = await system.status(original.run_id, {"succeeded", "failed"})
            assert terminal.state == "succeeded", terminal
            retired = await system.count(0)
            assert retired["held_roots"] == []
            assert {root["run_id"] for root in retired["retired_roots"]} == {original.run_id}
            assert len(system.probe.reads) == expected_reads
            assert len(system.probe.models) == expected_reads * 2
            assert {(read["run_id"], read["execution_epoch"]) for read in system.probe.reads} == {
                (child_id, epoch) for child_id, _, _, _, epoch in controls
            }
            reads = copy.deepcopy(system.probe.reads)
            for child_id, pending, command_id, receipt, epoch in controls:
                assert (
                    await system.engine.approve(
                        child_id, pending["action_id"], pending["digest"], command_id=command_id
                    )
                    == receipt
                )
                assert (
                    await system.client.get_workflow_handle(child_id).describe()
                ).run_id == epoch
            assert await system.submit(spec, value) == original
            assert system.probe.reads == reads
            assert (await root_sdk.describe()).run_id == root_epoch
            assert await system.evidence(original.run_id) == expected_descendants + 1
            after = await system.count(0)
            assert after["counts"]["command_records"] == retired["counts"]["command_records"]

            registry = system.client.get_workflow_handle(registry_id(system.policy.deployment_id))
            registry_history = await registry.fetch_history()
            submitted_targets = set()
            for event in registry_history.events:
                if event.event_type != EventType.EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_ACCEPTED:
                    continue
                request = event.workflow_execution_update_accepted_event_attributes.accepted_request
                if request.input.name == "reserve":
                    payloads = await system.client.data_converter.decode(
                        request.input.args.payloads
                    )
                    if payloads[0].get("kind") == "submit":
                        submitted_targets.add(payloads[0]["target"])
            assert submitted_targets == {original.run_id}
            (tmp_path / "descendant-control-observations.json").write_text(
                json.dumps(
                    {
                        "root_id": original.run_id,
                        "root_epoch": root_epoch,
                        "namespace": system.namespace,
                        "children": observed,
                        "retired": after,
                        "business_reads": reads,
                    },
                    sort_keys=True,
                )
            )

    asyncio.run(asyncio.wait_for(scenario(), 180))
