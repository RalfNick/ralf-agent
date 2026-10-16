"""Actual public Registry pressure does not strand original ordinary Tool evidence."""

import asyncio
import json
import os
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, ToolExecutionOwner
from ralf_agent.errors import IdempotencyConflict
from ralf_agent.temporal_deployment_admission import registry_id
from ralf_agent.temporal_deployment_submissions import _update
from ralf_agent.temporal_state import COMMAND_REGISTRY_CAPACITY
from ralf_agent.types import digest
from tests.test_temporal_deployment_dispatch_service import _eventually
from tests.test_temporal_deployment_public_service import (
    CommittedThreadWrite,
    SQLiteEffectEvidence,
    WriteProvider,
    public_system,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_actual_full_registry_manual_evidence_retains_physical_and_ack_obligations(tmp_path):
    async def run():
        # A new pressure probe needs a physical handler held across4096 reservations.
        # Existing45s/120s write probes and all original S2 limits remain unchanged.
        write = CommittedThreadWrite(tmp_path / "business.sqlite", hold_seconds=170)
        journal = SQLiteEffectEvidence(tmp_path / "evidence.sqlite")
        journal.block_ack = True
        options = {
            "providers": {"default": WriteProvider()},
            "tools": write.tools(),
            "journal": journal,
            "tool_execution": ToolExecutionOwner(version="manual-pressure-1"),
        }
        async with public_system(tmp_path, options=options) as system:
            system.finalizers.extend(
                [write.release.set, lambda: setattr(journal, "block_ack", False)]
            )
            async with system.worker():
                original = await system.submit(
                    AgentSpec("writer", "Write once", ("write",)),
                    {},
                    engine=system.facade(timeout=5),
                )
                assert await asyncio.to_thread(write.started.wait, 20)
                genuine, calls = write.committed()[0]
                assert calls == 1 and not write.ended.is_set()
                registry = system.client.get_workflow_handle(
                    registry_id(system.policy.deployment_id)
                )
                scope = asdict(system.scope)
                for start in range(1, COMMAND_REGISTRY_CAPACITY, 48):
                    requests = [
                        {
                            "scope": scope,
                            "command_id": f"manual-fill:{index}",
                            "kind": "drive",
                            "target": original.run_id,
                            "payload_digest": digest({"scope": scope, "kind": "drive"}),
                            "admission_policy": system.policy.identity,
                            "namespace": system.namespace,
                        }
                        for index in range(start, min(start + 48, COMMAND_REGISTRY_CAPACITY))
                    ]
                    await asyncio.gather(
                        *[_update(registry, "reserve", value) for value in requests]
                    )
                    (tmp_path / "progress.json").write_text(
                        json.dumps({"commands": start + len(requests)})
                    )
                assert (await system.engine.deployment_diagnostics())["counts"][
                    "command_records"
                ] == COMMAND_REGISTRY_CAPACITY
                await system.engine.cancel(original.run_id, command_id="full-stop")
                unknown = await _eventually(
                    lambda: system.engine.diagnostics(original.run_id),
                    lambda value: any(
                        a["kind"] == "tool" and a["status"] == "outcome_unknown"
                        for a in value.snapshot.actions
                    ),
                )
                action = next(a for a in unknown.snapshot.actions if a["kind"] == "tool")
                receipt = await system.engine.reconcile(
                    original.run_id, action["id"], genuine, command_id="manual-at-capacity"
                )
                assert receipt.apply_state == "applied"
                assert not write.ended.is_set()
                await system.count(1)
                assert (await system.closure(original.run_id))["seal"] is None
                assert (await system.engine.deployment_diagnostics())["counts"][
                    "command_records"
                ] == COMMAND_REGISTRY_CAPACITY + 2
                with pytest.raises(IdempotencyConflict):
                    await system.engine.reconcile(
                        original.run_id, action["id"], genuine, command_id="another-manual"
                    )
                write.release.set()
                assert await asyncio.to_thread(write.ended.wait, 10)
                await asyncio.wait_for(journal.ack_attempted.wait(), 15)
                await system.count(1)
                assert (await system.closure(original.run_id))["seal"] is None
                journal.block_ack = False
                await system.engine.drive(original.run_id, wait_seconds=0)
                await system.count(0)
                assert (
                    await system.engine.reconcile(
                        original.run_id, action["id"], genuine, command_id="manual-at-capacity"
                    )
                    == receipt
                )
                assert write.committed() == [(genuine, 1)]
                assert await system.evidence(original.run_id) == 1
                (tmp_path / "manual-result.json").write_text(
                    json.dumps(
                        {
                            "capacity": COMMAND_REGISTRY_CAPACITY,
                            "physical_calls": 1,
                            "held_until_actual_end_and_ack": True,
                            "duplicate_receipt_equal": True,
                            "root_history_replayed": True,
                            "external_model_calls": 0,
                        },
                        indent=2,
                    )
                )
        await journal.aclose()

    asyncio.run(asyncio.wait_for(run(), 180))
