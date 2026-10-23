"""Actual reservation transport and bounded RPC timing, not capacity acceptance."""

import asyncio
import json
import os
import time
from dataclasses import asdict

import pytest

from relf_agent.temporal_deployment_admission import registry_id
from relf_agent.temporal_deployment_submissions import _update
from relf_agent.types import digest
from tests.test_temporal_deployment_dispatch_service import _case
from tests.test_temporal_deployment_public_service import public_system

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_actual_reservation_delivery_and_result_rpc_timing(tmp_path):
    async def run():
        async with public_system(tmp_path, hold=True) as system, system.worker():
            spec, _, _, value = _case("nested-parent-sequence")
            root = await system.submit(spec, value)
            await asyncio.wait_for(system.probe.started.wait(), 20)
            original = system.client.get_workflow_handle(registry_id(system.policy.deployment_id))
            timings = []

            class Trace:
                async def query(self, name, request):
                    started = time.perf_counter()
                    result = await original.query(name, request)
                    timings.append(
                        {
                            "rpc": "query",
                            "seconds": time.perf_counter() - started,
                            "result_unknown": result.get("result") is None,
                        }
                    )
                    return result

                async def signal(self, name, request):
                    started = time.perf_counter()
                    await original.signal(name, request)
                    timings.append({"rpc": "signal", "seconds": time.perf_counter() - started})

            scope = asdict(system.scope)
            for index in range(8):
                receipt = await _update(
                    Trace(),
                    "reserve",
                    {
                        "scope": scope,
                        "command_id": f"timing:{index}",
                        "kind": "drive",
                        "target": root.run_id,
                        "payload_digest": digest({"scope": scope, "kind": "drive"}),
                        "admission_policy": system.policy.identity,
                        "namespace": system.namespace,
                    },
                )
                assert receipt["record_state"] == "durably_recorded"
            assert (await system.engine.deployment_diagnostics())["counts"]["command_records"] == 9
            await system.engine.cancel(root.run_id, command_id="stop-original")
            system.probe.release.set()
            await system.count(0)
            assert await system.evidence(root.run_id) == 3
            (tmp_path / "rpc-timing.json").write_text(json.dumps(timings, indent=2))

    asyncio.run(asyncio.wait_for(run(), 45))
