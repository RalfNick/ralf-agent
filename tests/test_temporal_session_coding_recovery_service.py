"""Fixed S2 recovery gates on original Session/Run Histories and PG evidence."""

import asyncio
import copy
import json
import os
from dataclasses import asdict

import pytest

from ralf_agent import Runtime
from ralf_agent.errors import SessionBusy
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_session_state import workflow_id
from ralf_agent.types import digest
from tests.test_temporal_deployment_coding_service import coding_system, definition
from tests.test_temporal_deployment_dispatch_service import _eventually

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires externally owned actual Temporal and PostgreSQL",
)


async def open_session(system, kind="agent"):
    facade = Runtime.from_temporal(system.engine)
    spec, value, calls = definition(kind)
    session = await facade.open_session(spec, "recovery", command_id="open")
    coordinator = workflow_id(session.ref.key)
    system.targets.add(coordinator)
    return facade, session, value, calls, coordinator


async def submit(system, session, value, command):
    expected = root_run_id(
        system.policy.deployment_id,
        asdict(system.scope),
        "ralf-session-run:" + digest([session.ref.key.to_dict(), command]),
    )
    system.targets.add(expected)
    run = await session.submit(value, command_id=command, budget=64)
    assert run.ref.run_id == expected
    return run


def test_actual_session_coding_approval_cold_handoff_lost_retirement_and_cancel(
    tmp_path, monkeypatch
):
    async def scenario():
        async with coding_system(
            tmp_path, monkeypatch, kind="recursive", deployment_sessions=True
        ) as system:
            first = await system.start_process()
            facade, session, value, calls, coordinator = await open_session(system, "recursive")
            try:
                original = await submit(system, session, value, "first")
                before = await _eventually(
                    lambda: system.engine.status(original.ref.run_id),
                    lambda state: state.state == "waiting_approval",
                    seconds=80,
                )
                pending = copy.deepcopy(before.pending[0])
                identities = {
                    target: (await system.client.get_workflow_handle(target).describe()).run_id
                    for target in {coordinator, original.ref.run_id, pending["run_id"]}
                }
                assert (await session.status()).busy
                await system.count(1)
                assert not system.lines("native-submissions.jsonl")
                # Existing graceful handoff drains original end ACKs, without
                # canceling business or transferring execution authority.
                first.terminate()
                assert await asyncio.to_thread(first.wait, timeout=80) == 0
                assert (
                    "DEPLOYMENT_CODING_WORKER_HANDOFF_COMPLETE"
                    in (tmp_path / "worker-0.log").read_text()
                )
                await system.start_process()
                repeated = await submit(system, session, value, "first")
                assert repeated.receipt == original.receipt and repeated.turn == original.turn
                assert (await system.engine.status(original.ref.run_id)).pending[0] == pending
                for target, epoch in identities.items():
                    assert (
                        await system.client.get_workflow_handle(target).describe()
                    ).run_id == epoch
                (tmp_path / "lose-release-reply").touch()
                assert (
                    await system.approve(original.ref.run_id, all_steps=True)
                ).state == "succeeded"
                await _eventually(session.status, lambda state: not state.busy, seconds=80)
                await system.count(0)
                assert (tmp_path / "lost-release-reply.json").exists()
                assert len(system.lines("native-commits.jsonl")) == calls
                await system.evidence(original.ref.run_id)
                next_run = await submit(system, session, value, "second")
                assert next_run.turn.turn_seq == 2
                await _eventually(
                    lambda: system.engine.status(next_run.ref.run_id),
                    lambda state: state.state == "waiting_approval",
                    seconds=80,
                )
                await system.engine.cancel(next_run.ref.run_id, command_id="cancel-second-turn")
                await _eventually(session.status, lambda state: not state.busy, seconds=80)
                await system.count(0)
                await system.evidence(next_run.ref.run_id)
                assert (await system.engine.status(next_run.ref.run_id)).state == "cancelled"
                assert len(system.lines("native-commits.jsonl")) == calls
                assert len(system.lines("native-submissions.jsonl")) == calls * 2
                assert (await system.client.get_workflow_handle(coordinator).describe()).run_id == (
                    identities[coordinator]
                )
            finally:
                await facade.aclose()

    asyncio.run(asyncio.wait_for(scenario(), 600))


@pytest.mark.parametrize("boundary", ["effect", "native-stop", "deployment-end"])
def test_actual_session_coding_original_ack_retains_turn_until_retirement(
    tmp_path, monkeypatch, boundary
):
    async def scenario():
        async with coding_system(tmp_path, monkeypatch, deployment_sessions=True) as system:
            async with system.worker():
                facade, session, value, calls, _ = await open_session(system)
                try:
                    if boundary == "effect":
                        await system.effect_ack_gate(True)
                    else:
                        prefix = "hold-" if boundary == "native-stop" else "block-"
                        (tmp_path / (prefix + boundary)).touch()
                    run = await submit(system, session, value, "first")
                    leaf, action_id = await system.approve(run.ref.run_id)
                    await _eventually(
                        lambda: asyncio.sleep(0, result=system.lines("native-commits.jsonl")),
                        lambda records: len(records) == calls,
                        seconds=80,
                    )
                    if boundary == "effect":
                        await _eventually(
                            lambda: system.engine.events(leaf),
                            lambda events: any(
                                e.kind == "effect_journal_ack_deferred" for e in events
                            ),
                            seconds=80,
                        )
                    else:
                        marker = tmp_path / (prefix + boundary + ".attempted")
                        await _eventually(
                            lambda: asyncio.sleep(0, result=marker.exists()), bool, seconds=80
                        )
                    await system.count(1)
                    assert (await session.status()).busy
                    assert (await system.view(leaf, "deployment_closure"))["seal"] is None
                    with pytest.raises(SessionBusy):
                        await session.submit(value, command_id="blocked-next", budget=64)
                    assert len(await session.turns()) == 1
                    before = copy.deepcopy(system.lines("native-submissions.jsonl"))
                    assert len(before) == calls * 2
                    if boundary == "effect":
                        await system.effect_ack_gate(False)
                    else:
                        (tmp_path / (prefix + boundary)).unlink()
                    # The completed invocation retries its end ACK itself. Once
                    # admitted, retirement may seal the leaf before a new drive;
                    # observe that recovery without racing a sealed mutation.
                    if boundary != "deployment-end":
                        await system.engine.drive(leaf, wait_seconds=0)
                    details = await _eventually(
                        lambda: system.view(leaf),
                        lambda d: any(
                            a["id"] == action_id and a["status"] in {"completed", "outcome_unknown"}
                            for a in d["snapshot"]["actions"]
                        ),
                        seconds=80,
                    )
                    action = next(a for a in details["snapshot"]["actions"] if a["id"] == action_id)
                    if action["status"] == "outcome_unknown":
                        assert type(action["delegated_execution"].get("result_candidate")) is dict
                        await system.engine.reconcile(
                            leaf, action_id, query=True, command_id="recover-original-candidate"
                        )
                    await _eventually(session.status, lambda state: not state.busy, seconds=80)
                    await system.count(0)
                    await system.evidence(run.ref.run_id)
                    assert system.lines("native-submissions.jsonl") == before
                    assert len(system.lines("native-commits.jsonl")) == calls
                    (tmp_path / "session-ack-result.json").write_text(
                        json.dumps({"boundary": boundary, "turns": 1, "held_root_runs": 0})
                    )
                finally:
                    await facade.aclose()

    asyncio.run(asyncio.wait_for(scenario(), 300))
