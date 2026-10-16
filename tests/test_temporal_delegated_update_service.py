"""Real SDK Update identity evidence for the original mechanical transport helper."""

import asyncio
import json
import os
from dataclasses import asdict

import pytest

from ralf_agent.temporal_coding_composition_control import _command
from tests.test_temporal_deployment_dispatch_service import _case
from tests.test_temporal_deployment_public_service import public_system

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def command_updates(history):
    return [
        event.workflow_execution_update_accepted_event_attributes.accepted_request.meta.update_id
        for event in history.events
        if event.HasField("workflow_execution_update_accepted_event_attributes")
        and event.workflow_execution_update_accepted_event_attributes.accepted_request.input.name
        == "command"
    ]


def test_actual_mechanical_helper_uses_fresh_updates_and_one_logical_command(tmp_path):
    async def run():
        async with public_system(tmp_path, approval=True) as system, system.worker():
            spec, _, _, value = _case("graph-sequential")
            original = await system.submit(spec, value)
            await system.status(original.run_id, {"waiting_approval"})
            parent = (await system.closure(original.run_id))["deployment"]
            call = parent["children"][0]
            child_id, epoch = call["run_id"], call["deployment_execution_epoch"]
            handle = system.client.get_workflow_handle(child_id, run_id=epoch)
            description = await handle.describe()
            assert description.parent_id == original.run_id
            assert description.parent_run_id == parent["execution_epoch"]
            scope = asdict(system.scope)
            proof = await handle.query("view", {"scope": scope, "kind": "deployment_admission"})
            assert proof["request"] == call["request"]
            assert proof["admission"] == call["deployment_admission"]
            before = command_updates(await handle.fetch_history())
            receipts = []
            for _ in range(3):
                # Test only the existing internal transport helper against a
                # genuine ordinary public child. This is not native Coding
                # or caller-authorization acceptance for the outer Activity.
                receipts.append(
                    await _command(system.client, proof, "drive", owner_id=original.run_id)
                )
            assert receipts[0] == receipts[1] == receipts[2]
            after = command_updates(await handle.fetch_history())
            fresh = after[len(before) :]
            assert len(fresh) == len(set(fresh)) == 3
            events = await system.engine.events(child_id)
            recorded = [e for e in events if e.kind == "command_recorded"]
            assert len(recorded) == 1 and recorded[0].data["kind"] == "drive"
            assert (await system.engine.status(child_id)).state == "waiting_approval"
            assert system.probe.reads == []

            # Characterize the dependency assumption that originally hid
            # repeated wakes: the same SDK Update ID returns one acceptance.
            cached_request = {
                "command_id": "cached-update-probe",
                "payload": {"scope": scope, "kind": "drive"},
            }
            cached = await handle.execute_update("command", cached_request, id="cached-sdk-update")
            assert (
                await handle.execute_update("command", cached_request, id="cached-sdk-update")
                == cached
            )
            assert len(command_updates(await handle.fetch_history())) == len(after) + 1
            await system.engine.cancel(original.run_id, command_id="cancel-original")
            await system.count(0)
            assert system.probe.reads == []
            assert await system.evidence(original.run_id) == 2
            (tmp_path / "update-result.json").write_text(
                json.dumps(
                    {
                        "fresh_sdk_updates": len(fresh),
                        "logical_helper_commands": len(recorded),
                        "repeated_fixed_sdk_id_acceptances": 1,
                        "tool_calls": 0,
                        "native_coding_tested": False,
                        "outer_activity_authorization_tested": False,
                        "real_public_child_epoch": epoch,
                    },
                    indent=2,
                )
            )

    asyncio.run(asyncio.wait_for(run(), 90))
