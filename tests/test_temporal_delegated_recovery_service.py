"""Actual original-tree controls at the production command allowance, no model API."""

import asyncio
import json
import os
from dataclasses import asdict
from datetime import timedelta

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.temporal_deployment_admission import registry_id
from ralf_agent.temporal_state import COMMAND_REGISTRY_CAPACITY
from ralf_agent.types import digest
from tests.test_temporal_deployment_dispatch_service import _case
from tests.test_temporal_deployment_public_service import public_system

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_actual_full_registry_cancel_propagates_to_original_nested_tree(tmp_path):
    _full_registry_cancel(tmp_path, transport="update")


def test_actual_signal_reservations_reach_same_production_capacity_and_tree(tmp_path):
    _full_registry_cancel(tmp_path, transport="signal")


def _full_registry_cancel(tmp_path, *, transport):
    async def run():
        async with public_system(tmp_path, hold=True) as system, system.worker():
            spec, _, _, value = _case("nested-parent-sequence")
            # This new capacity probe holds a deterministic Provider while filling
            # the real 4096-record Registry. It does not alter any S2 timeout.
            original = await system.submit(spec, value, engine=system.facade(timeout=120))
            await asyncio.wait_for(system.probe.started.wait(), 20)
            registry = system.client.get_workflow_handle(registry_id(system.policy.deployment_id))
            scope = asdict(system.scope)
            before = await system.engine.deployment_diagnostics()
            assert before["counts"]["command_records"] == 1

            async def reserve(request):
                if transport == "signal":
                    from ralf_agent.temporal_deployment_submissions import _update

                    return await _update(registry, "reserve", request)
                return await registry.execute_update(
                    "reserve", request, rpc_timeout=timedelta(seconds=15)
                )

            # Raw Updates need headroom below the Service's ten-in-flight cap.
            # Signal observers instead share a task in bounded batches below
            # the 64-entry observation cache; no rolling/unbounded fan-out.
            parallelism = 48 if transport == "signal" else 4
            for start in range(1, COMMAND_REGISTRY_CAPACITY, parallelism):
                requests = [
                    {
                        "scope": scope,
                        "command_id": f"capacity-fill:{index}",
                        "kind": "drive",
                        "target": original.run_id,
                        "payload_digest": digest({"scope": scope, "kind": "drive"}),
                        "admission_policy": system.policy.identity,
                        "namespace": system.namespace,
                    }
                    for index in range(start, min(start + parallelism, COMMAND_REGISTRY_CAPACITY))
                ]
                receipts = await asyncio.gather(*[reserve(request) for request in requests])
                assert all(r["record_state"] == "durably_recorded" for r in receipts)
                (tmp_path / "progress.json").write_text(
                    json.dumps(
                        {
                            "phase": "filling",
                            "accepted_commands": start + len(requests),
                        }
                    )
                )
            full = await system.engine.deployment_diagnostics()
            assert full["counts"]["command_records"] == COMMAND_REGISTRY_CAPACITY
            # The SDK intentionally exposes stable codes and sanitized text.
            # Verify refusal and unchanged authority facts, not server wording.
            with pytest.raises(ValidationError) as refused:
                await system.submit(spec, value, command_id="refused-fresh")
            assert refused.value.code == "validation_error"
            refused_state = await system.engine.deployment_diagnostics()
            assert refused_state["counts"]["command_records"] == COMMAND_REGISTRY_CAPACITY
            assert refused_state["counts"]["held_root_runs"] == 1
            assert (await system.engine.status(original.run_id)).state == "running"
            receipt = await system.engine.cancel(original.run_id, command_id="full-root-stop")
            assert receipt.outcome["remote_stop_confirmed"] is False
            (tmp_path / "progress.json").write_text(json.dumps({"phase": "cancellation_accepted"}))
            parent_id, original_children = original.run_id, []
            for _ in range(2):
                await system.status(parent_id, {"cancelled"})
                closure = await system.closure(parent_id)
                child = closure["deployment"]["children"][0]
                epoch = child["deployment_execution_epoch"]
                handle = system.client.get_workflow_handle(child["run_id"], run_id=epoch)
                assert (await handle.describe()).run_id == epoch
                original_children.append({"run_id": child["run_id"], "execution_epoch": epoch})
                parent_id = child["run_id"]
            await system.status(parent_id, {"cancelled"})
            assert not system.probe.release.is_set() and system.probe.reads == []
            await system.count(1)
            assert (await system.closure(original.run_id))["seal"] is None
            protected = await system.engine.deployment_diagnostics()
            assert protected["counts"]["command_records"] == COMMAND_REGISTRY_CAPACITY + 1
            system.probe.release.set()
            await system.count(0)
            assert (
                await system.engine.cancel(original.run_id, command_id="full-root-stop") == receipt
            )
            assert system.probe.reads == []
            histories = await system.evidence(original.run_id)
            assert histories == 3
            (tmp_path / "capacity-result.json").write_text(
                json.dumps(
                    {
                        "reservation_transport": transport,
                        "reservation_parallelism": parallelism,
                        "production_command_capacity": COMMAND_REGISTRY_CAPACITY,
                        "records_after_cancel": protected["counts"]["command_records"],
                        "original_children": original_children,
                        "histories_replayed": histories,
                        "held_before_provider_end": True,
                        "retired_after_actual_end": True,
                        "read_calls": 0,
                        "external_model_calls": 0,
                    },
                    indent=2,
                )
            )
            (tmp_path / "progress.json").write_text(json.dumps({"phase": "business_verified"}))

    asyncio.run(asyncio.wait_for(run(), 180))
