"""Existing Coding compositions as original Session children on Temporal/PG.

The finite native peer tests protocol and lifecycle, not model task quality.
The original fixture retains recovery data whenever deletion is unproven.
"""

import asyncio
import json
import os
from dataclasses import asdict

import pytest

from ralf_agent import Runtime
from ralf_agent.errors import SessionBusy
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_session_state import workflow_id
from ralf_agent.types import digest
from tests.test_temporal_deployment_coding_service import TOPOLOGIES, coding_system, definition
from tests.test_temporal_deployment_dispatch_service import _eventually

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires externally owned actual Temporal and PostgreSQL",
)


@pytest.mark.parametrize("kind,syntax", TOPOLOGIES)
def test_actual_coding_session_original_turns_approval_tree_and_retirement(
    tmp_path, monkeypatch, kind, syntax
):
    async def scenario():
        async with (
            coding_system(
                tmp_path,
                monkeypatch,
                kind=kind,
                syntax=syntax,
                deployment_sessions=True,
            ) as system,
            system.worker(),
        ):
            facade = Runtime.from_temporal(system.engine)
            spec, value, calls = definition(kind)
            session = await facade.open_session(spec, "coding", command_id="session-open")
            coordinator_id = workflow_id(session.ref.key)
            system.targets.add(coordinator_id)
            coordinator = system.client.get_workflow_handle(coordinator_id)
            descriptor = await coordinator.describe()
            coordinator_epoch = descriptor.run_id
            assert descriptor.raw_info.first_run_id == coordinator_epoch
            evidence = []
            try:
                for seq in (1, 2):
                    command = f"session-turn-{seq}"
                    run_command = "ralf-session-run:" + digest([session.ref.key.to_dict(), command])
                    expected = root_run_id(
                        system.policy.deployment_id, asdict(system.scope), run_command
                    )
                    system.targets.add(expected)
                    run = await session.submit(value, command_id=command, budget=64)
                    assert run.ref.run_id == expected and run.turn.turn_seq == seq
                    await _eventually(
                        lambda expected=expected: system.engine.status(expected),
                        lambda state: state.state == "waiting_approval",
                        seconds=80,
                    )
                    await system.count(1)
                    assert (await session.status()).busy
                    assert len(system.lines("native-commits.jsonl")) == calls * (seq - 1)
                    with pytest.raises(SessionBusy):
                        await session.submit(value, command_id=f"busy-{seq}", budget=64)
                    assert len(await session.turns()) == seq
                    duplicate = await session.submit(value, command_id=command, budget=64)
                    assert duplicate.receipt == run.receipt and duplicate.turn == run.turn
                    assert (await system.approve(expected, all_steps=True)).state == "succeeded"
                    await _eventually(session.status, lambda state: not state.busy, seconds=80)
                    await system.count(0)
                    assert len(system.lines("native-submissions.jsonl")) == calls * seq * 2
                    assert len(system.lines("native-commits.jsonl")) == calls * seq

                    selector = {
                        "scope": asdict(system.scope),
                        "namespace": system.data["namespace"],
                        "coordinator_execution_epoch": coordinator_epoch,
                        "session_command_id": command,
                        "turn_id": run.turn.turn_id,
                    }
                    intent = await coordinator.query(
                        "view", {"kind": "deployment_session_intent", **selector}
                    )
                    start = await coordinator.query(
                        "view",
                        {
                            "kind": "deployment_session_start",
                            **selector,
                            "intent_digest": intent["intent_digest"],
                        },
                    )
                    assert start["phase"] == "started"
                    actual = await system.client.get_workflow_handle(expected).describe()
                    assert actual.run_id == start["execution_epoch"] == actual.raw_info.first_run_id
                    assert (actual.parent_id, actual.parent_run_id) == (
                        coordinator_id,
                        coordinator_epoch,
                    )
                    closure = await system.evidence(expected)
                    admission = closure["deployment"]["admission"]
                    assert admission["version"] == 2 and admission["lineage"] == []
                    origin = admission["session_origin"]
                    assert origin["coordinator_id"] == coordinator_id
                    assert origin["coordinator_execution_epoch"] == coordinator_epoch
                    assert origin["intent_digest"] == intent["intent_digest"]
                    assert origin["turn_id"] == run.turn.turn_id
                    if seq == 2:
                        history = intent["submission"]["request"]["session_history"]
                        assert [message["role"] for message in history] == ["user", "assistant"]
                    native_count = len(system.lines("native-commits.jsonl"))
                    repeated = await session.submit(value, command_id=command, budget=64)
                    assert repeated.receipt == run.receipt and repeated.turn == run.turn
                    assert len(system.lines("native-commits.jsonl")) == native_count
                    evidence.append(
                        {
                            "turn_id": run.turn.turn_id,
                            "turn_seq": seq,
                            "run_id": expected,
                            "run_epoch": actual.run_id,
                            "intent_digest": intent["intent_digest"],
                            "seal": closure["seal"],
                            "held_root_runs": 0,
                        }
                    )
                assert len(await session.turns()) == 2
                assert (await coordinator.describe()).run_id == coordinator_epoch
                (tmp_path / "session-coding-result.json").write_text(
                    json.dumps(
                        {
                            "kind": kind,
                            "syntax": syntax,
                            "model_quality": None,
                            "session_ref": session.ref.to_dict(),
                            "coordinator_epoch": coordinator_epoch,
                            "turns": evidence,
                            "business_commits": len(system.lines("native-commits.jsonl")),
                        },
                        sort_keys=True,
                    )
                )
            finally:
                await facade.aclose()

    asyncio.run(asyncio.wait_for(scenario(), timeout=360))
