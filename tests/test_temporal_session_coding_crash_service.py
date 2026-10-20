"""A killed original CONTROL keeps its Session Turn and root obligation held."""

import asyncio
import copy
import json
import os
from dataclasses import asdict

import pytest

from ralf_agent import Runtime
from ralf_agent.errors import CloseIncomplete, SessionBusy
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_session_state import workflow_id
from ralf_agent.types import digest
from tests.test_temporal_deployment_coding_service import coding_system, definition
from tests.test_temporal_deployment_dispatch_service import _eventually

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires externally owned actual Temporal and PostgreSQL",
)


def test_actual_session_coding_control_hard_kill_retains_original_turn_and_unknown_call(
    tmp_path, monkeypatch
):
    async def scenario():
        with pytest.raises(CloseIncomplete) as unresolved:
            async with coding_system(
                tmp_path, monkeypatch, kind="recursive", deployment_sessions=True
            ) as system:
                # Existing gate is within the real CONTROL observe body, after its
                # original deployment call grant; it is never a caller stop proof.
                gate = tmp_path / "block-control-observe"
                gate.touch()
                first = await system.start_process()
                facade = Runtime.from_temporal(system.engine)
                spec, value, _ = definition("recursive")
                try:
                    session = await facade.open_session(spec, "hard-kill", command_id="open")
                    session_ref = session.ref
                    coordinator_id = workflow_id(session_ref.key)
                    system.targets.add(coordinator_id)
                    coordinator = system.client.get_workflow_handle(coordinator_id)
                    coordinator_epoch = (await coordinator.describe()).run_id
                    command = "original-turn"
                    expected = root_run_id(
                        system.policy.deployment_id,
                        asdict(system.scope),
                        "ralf-session-run:" + digest([session_ref.key.to_dict(), command]),
                    )
                    system.targets.add(expected)
                    original = await session.submit(value, command_id=command, budget=64)
                    assert original.ref.run_id == expected and original.turn.turn_seq == 1
                    descriptor = await system.client.get_workflow_handle(expected).describe()
                    root_epoch = descriptor.run_id
                    assert descriptor.raw_info.first_run_id == root_epoch
                    assert (descriptor.parent_id, descriptor.parent_run_id) == (
                        coordinator_id,
                        coordinator_epoch,
                    )
                    selector = {
                        "scope": asdict(system.scope),
                        "namespace": system.data["namespace"],
                        "coordinator_execution_epoch": coordinator_epoch,
                        "session_command_id": command,
                        "turn_id": original.turn.turn_id,
                    }
                    intent = await coordinator.query(
                        "view", {"kind": "deployment_session_intent", **selector}
                    )
                    start_query = {
                        "kind": "deployment_session_start",
                        **selector,
                        "intent_digest": intent["intent_digest"],
                    }
                    start = await coordinator.query("view", start_query)
                    assert start["phase"] == "started" and start["execution_epoch"] == root_epoch
                    marker = tmp_path / "held-control-observe.json"
                    await _eventually(
                        lambda: asyncio.sleep(0, result=marker.exists()), bool, seconds=80
                    )
                    held = json.loads(marker.read_text())
                    assert held["pid"] == first.pid
                    before = await system.view(
                        held["workflow_id"], "deployment_closure", epoch=held["execution_epoch"]
                    )
                    matching = [
                        record
                        for record in before["calls"].values()
                        if record["identity"]["activity_id"] == held["activity_id"]
                    ]
                    assert len(matching) == 1
                    call = copy.deepcopy(matching[0])
                    assert call["identity"]["activity_name"] == "ralf.temporal.control.v1"
                    assert call["allowed"] and not call["stopped"] and call["end_proof"] is None
                    assert call["fence_proof"] is None
                    assert system.lines("native-submissions.jsonl") == []
                    assert (await session.status()).busy
                    await system.count(1)

                    await system.kill(first)
                    gate.unlink()
                    await system.start_process()
                    duplicate = await session.submit(value, command_id=command, budget=64)
                    assert duplicate.ref == original.ref and duplicate.turn == original.turn
                    assert duplicate.receipt == original.receipt and session.ref == session_ref
                    assert (await coordinator.describe()).run_id == coordinator_epoch
                    assert (
                        await system.client.get_workflow_handle(expected).describe()
                    ).run_id == (root_epoch)
                    assert await coordinator.query("view", start_query) == start
                    assert (
                        await coordinator.query(
                            "view", {"kind": "deployment_session_intent", **selector}
                        )
                        == intent
                    )
                    after = await system.view(
                        held["workflow_id"], "deployment_closure", epoch=held["execution_epoch"]
                    )
                    assert [
                        record
                        for record in after["calls"].values()
                        if record["identity"]["activity_id"] == held["activity_id"]
                    ] == [call]
                    assert "actual_call_not_stopped" in after["reasons"] and after["seal"] is None
                    assert (await session.status()).busy
                    with pytest.raises(SessionBusy):
                        await session.submit(value, command_id="blocked-next", budget=64)
                    assert len(await session.turns()) == 1
                    await system.count(1)
                    assert system.lines("native-submissions.jsonl") == []
                    assert system.lines("native-commits.jsonl") == []
                    closure = await system.evidence(expected, sealed=False)
                    assert closure["deployment"]["admission"]["lineage"] == []
                    origin = closure["deployment"]["admission"]["session_origin"]
                    assert origin["coordinator_id"] == coordinator_id
                    assert origin["coordinator_execution_epoch"] == coordinator_epoch
                    assert origin["turn_id"] == original.turn.turn_id
                    assert origin["intent_digest"] == intent["intent_digest"]
                    await system.expect_retention(expected)
                    path = tmp_path / "session-control-death-retained.json"
                    path.write_text(
                        json.dumps(
                            {
                                "session_ref": session_ref.to_dict(),
                                "turn": original.turn.to_dict(),
                                "coordinator_epoch": coordinator_epoch,
                                "run_id": expected,
                                "run_epoch": root_epoch,
                                "intent": intent,
                                "start": start,
                                "original_control": call,
                                "killed_worker_pid": first.pid,
                                "held_root_runs": 1,
                                "native_submissions": 0,
                                "native_commits": 0,
                            },
                            sort_keys=True,
                        )
                    )
                    path.chmod(0o600)
                finally:
                    await facade.aclose()
        system.assert_retained()
        # The killed original handler has no end/fence proof. Successful close
        # would incorrectly discard its original outstanding obligation.
        assert "deployment_coding" in unresolved.value.report
        report = json.loads((tmp_path / "cleanup.json").read_text())
        assert report["close_error"] == "CloseIncomplete"
        assert not report["assembly_close_succeeded"] and report["workers_exited"]
        assert not report["evidence_errors"] and not report["unexpected_retention"]
        assert report["deletion_evidence"]["retained_roots"] == system.expected_retention
        assert (tmp_path / "session-control-death-retained.json").exists()

    asyncio.run(asyncio.wait_for(scenario(), 300))
