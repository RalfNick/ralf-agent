"""Actual Temporal Service + PostgreSQL + separate worker process acceptance.

Set RALF_TEST_TEMPORAL_ADDRESS and RALF_TEST_POSTGRES_DSN to run. Setting
RALF_TEMPORAL_PROBE_REPEATS=20 repeats each contract scenario against real
services; no Temporal test server/time skipping is used.
"""

import asyncio
import importlib.util
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict
from relf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from relf_agent.types import AgentSpec, Scope, WorkflowSpec

fixture_spec = importlib.util.spec_from_file_location(
    "temporal_worker_fixture", Path(__file__).with_name("temporal_worker_fixture.py")
)
fixture = importlib.util.module_from_spec(fixture_spec)
sys.modules["temporal_worker_fixture"] = fixture
fixture_spec.loader.exec_module(fixture)

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires actual Temporal Service and PostgreSQL",
)
REPEATS = int(os.getenv("RALF_TEMPORAL_PROBE_REPEATS", "1"))


class Workers:
    def __init__(self, queue, log_dir):
        self.queue, self.log_dir, self.processes = queue, log_dir, []

    async def start(self, count=2, *, provider_version="1"):
        for _ in range(count):
            index = len(self.processes)
            log = self.log_dir / f"worker-{index}.log"
            output = log.open("w")
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                "RALF_TEST_POSTGRES_DSN": os.environ["RALF_TEST_POSTGRES_DSN"],
                "RALF_TEST_TEMPORAL_QUEUE": self.queue,
                "RALF_TEST_TEMPORAL_PROVIDER_VERSION": provider_version,
                "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
            }
            code = f"import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); import temporal_worker_fixture as f; f.main()"
            process = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "-u", "-c", code],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            output.close()
            self.processes.append((process, log))
            deadline = asyncio.get_running_loop().time() + 20
            while "TEMPORAL_WORKER_READY" not in log.read_text():
                if process.poll() is not None or asyncio.get_running_loop().time() > deadline:
                    raise AssertionError(f"Worker failed to start: {log.read_text()}")
                await asyncio.sleep(0.05)

    async def kill(self):
        for process, _ in self.processes:
            if process.poll() is None:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)


@asynccontextmanager
async def system(tmp_path, *, activity_timeout=3, worker_version="1"):
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    runtime = await fixture.runtime()
    queue = "ralf-test-" + uuid.uuid4().hex
    workers = Workers(queue, tmp_path)
    await workers.start(provider_version=worker_version)
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=runtime.manifest,
        scope=Scope("temporal-tests", queue),
        activity_timeout=activity_timeout,
        drive_timeout=25,
    )
    try:
        yield engine, runtime, workers
    finally:
        await workers.kill()
        await runtime.journal.aclose()


async def wait_status(engine, run_id, states, *, wait_seconds=20):
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        state = await engine.status(run_id)
        if state.state in states:
            return state
        assert asyncio.get_running_loop().time() < deadline, state
        await asyncio.sleep(0.05)


async def wait_effect(runtime, label):
    deadline = asyncio.get_running_loop().time() + 20
    while True:
        cursor = await runtime.journal.connection.execute(
            "SELECT effect_key,writes FROM ralf_temporal_probe_effects WHERE label=%s", (label,)
        )
        row = await cursor.fetchone()
        if row:
            return row
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.05)


def spec():
    return AgentSpec("probe", "Use write, then summarize", tools=("write",))


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_real_two_workers_submit_controls_scope_and_history_replay(tmp_path, repeat):
    async def run():
        async with system(tmp_path) as (engine, runtime, workers):
            sequence = WorkflowSpec("sequence", (AgentSpec("a", "one"), AgentSpec("b", "two")))
            handle = await engine.submit(sequence, {"number": repeat}, command_id="sequence")
            done = await engine.drive(handle.run_id)
            assert done.state == "succeeded" and done.result == {"number": repeat}
            assert len(done.actions) == 2
            replay = await engine.submit(sequence, {"number": repeat}, command_id="sequence")
            assert replay == handle
            changed = TemporalEngine(
                engine.client,
                task_queue="unavailable",
                release={**engine.release, "policy": {"kind": "other"}},
                scope=engine.scope,
            )
            assert (
                await changed.submit(sequence, {"number": repeat}, command_id="sequence") == handle
            )
            with pytest.raises(IdempotencyConflict):
                await engine.submit(sequence, {"number": "changed"}, command_id="sequence")
            other = TemporalEngine(
                engine.client,
                task_queue=engine.task_queue,
                release=engine.release,
                scope=Scope("other", "other"),
            )
            with pytest.raises(AuthorizationDenied):
                await other.status(handle.run_id)
            too_late = await engine.cancel(handle.run_id, command_id="late-cancel")
            assert too_late.outcome == {"rejected": True, "reason": "too_late"}
            assert await engine.cancel(handle.run_id, command_id="late-cancel") == too_late
            other_run = await engine.submit(
                AgentSpec("other", "answer"), "second", command_id="other-submit"
            )
            with pytest.raises(IdempotencyConflict):
                await engine.cancel(other_run.run_id, command_id="late-cancel")
            with pytest.raises(IdempotencyConflict):
                await engine.submit(sequence, {"number": repeat}, command_id="late-cancel")
            with pytest.raises(IdempotencyConflict):
                await engine.cancel(handle.run_id, command_id="sequence")
            await replay_temporal_history(
                await engine.client.get_workflow_handle(engine.command_registry_id).fetch_history()
            )
            history = await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            await replay_temporal_history(history)
            events = await engine.events(handle.run_id)
            assert [event.seq for event in events] == list(range(1, len(events) + 1))
            diagnostics = await engine.diagnostics(handle.run_id)
            assert diagnostics.budget["spent"] == 2
            assert diagnostics.workflow["quiescent"]
            with pytest.raises(DefinitionMismatch):
                build_temporal_worker(
                    engine.client,
                    task_queue=engine.task_queue,
                    runtime=runtime,
                    release={**runtime.manifest, "policy": {"kind": "drift"}},
                )

    asyncio.run(run())


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_real_approval_survives_worker_restart_and_commands_dedupe(tmp_path, repeat):
    async def run():
        async with system(tmp_path) as (engine, runtime, workers):
            label = engine.task_queue + "-approval"
            handle = await engine.submit(
                spec(), {"tool": True, "arguments": {"label": label}}, command_id="submit"
            )
            pending = await wait_status(engine, handle.run_id, {"waiting_approval"})
            target = pending.pending[0]
            await workers.kill()
            await workers.start()
            receipt = await engine.approve(
                handle.run_id, target["action_id"], target["digest"], command_id="approve"
            )
            assert (
                await engine.approve(
                    handle.run_id, target["action_id"], target["digest"], command_id="approve"
                )
                == receipt
            )
            with pytest.raises(IdempotencyConflict):
                await engine.approve(
                    handle.run_id,
                    target["action_id"],
                    target["digest"],
                    command_id="approve",
                    approved=False,
                )
            done = await engine.drive(handle.run_id)
            assert done.state == "succeeded", done
            key, writes = await wait_effect(runtime, label)
            assert writes == 1
            action = next(a for a in done.actions if a["kind"] == "tool")
            assert action["effect_key"] == key and len(action["attempts"]) == 1
            assert (await engine.diagnostics(handle.run_id)).budget["spent"] == 3
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )

    asyncio.run(run())


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_real_effect_committed_receipt_lost_same_key_query_and_cross_run_guard(tmp_path, repeat):
    async def run():
        async with system(tmp_path, activity_timeout=2) as (engine, runtime, workers):
            label = engine.task_queue + "-lost"
            payload = {"tool": True, "arguments": {"label": label, "delay": 20}}
            handle = await engine.submit(spec(), payload, command_id="submit")
            pending = await wait_status(engine, handle.run_id, {"waiting_approval"})
            target = pending.pending[0]
            await engine.approve(
                handle.run_id, target["action_id"], target["digest"], command_id="approve"
            )
            key, _ = await wait_effect(runtime, label)
            await workers.kill()
            await workers.start()
            unknown = await wait_status(engine, handle.run_id, {"waiting_reconciliation"})
            action = next(a for a in unknown.actions if a["kind"] == "tool")
            assert action["effect_key"] == key and action["status"] == "outcome_unknown"
            assert (await engine.diagnostics(handle.run_id)).budget["unknown"] == 1
            second = await engine.submit(spec(), payload, command_id="second")
            second_pending = await wait_status(engine, second.run_id, {"waiting_approval"})
            second_target = second_pending.pending[0]
            await engine.approve(
                second.run_id,
                second_target["action_id"],
                second_target["digest"],
                command_id="approve-second",
            )
            blocked = await wait_status(engine, second.run_id, {"waiting_reconciliation"})
            assert blocked.error["code"] == "prior_effect_unknown"
            assert (await wait_effect(runtime, label))[1] == 1
            evidence = await engine.reconcile(
                handle.run_id, action["id"], command_id="query", query=True
            )
            assert evidence.outcome["evidence_pending"]
            done = await engine.drive(handle.run_id)
            assert done.state == "succeeded", done
            confirmed = next(a for a in done.actions if a["kind"] == "tool")
            assert confirmed["id"] == action["id"] and confirmed["effect_key"] == key
            assert len(confirmed["attempts"]) == 1
            assert (await wait_effect(runtime, label))[1] == 1
            assert (await engine.diagnostics(handle.run_id)).budget["unknown"] == 0
            await engine.cancel(second.run_id, command_id="cancel-blocked")
            cancelled = await engine.drive(second.run_id)
            assert cancelled.state == "cancelled"
            cursor = await runtime.journal.connection.execute(
                "SELECT count(*),sum(writes) FROM ralf_temporal_probe_effects WHERE label=%s",
                (label,),
            )
            assert await cursor.fetchone() == (1, 1)
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )

    asyncio.run(run())


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_real_cancel_race_keeps_terminal_and_adopts_late_receipt(tmp_path, repeat):
    async def run():
        async with system(tmp_path, activity_timeout=4) as (engine, runtime, workers):
            label = engine.task_queue + "-cancel"
            handle = await engine.submit(
                spec(),
                {"tool": True, "arguments": {"label": label, "delay": 0.8}},
                command_id="submit",
            )
            pending = await wait_status(engine, handle.run_id, {"waiting_approval"})
            target = pending.pending[0]
            await engine.approve(
                handle.run_id, target["action_id"], target["digest"], command_id="approve"
            )
            await wait_effect(runtime, label)
            receipt = await engine.cancel(handle.run_id, command_id="cancel")
            assert not receipt.outcome["remote_stop_confirmed"]
            assert await engine.cancel(handle.run_id, command_id="cancel") == receipt
            with pytest.raises(IdempotencyConflict):
                await engine.approve(
                    handle.run_id, target["action_id"], target["digest"], command_id="cancel"
                )
            assert (await engine.status(handle.run_id)).state == "cancelled"
            deadline = asyncio.get_running_loop().time() + 10
            while True:
                done = await engine.status(handle.run_id)
                action = next(a for a in done.actions if a["kind"] == "tool")
                if action["status"] == "completed":
                    break
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.05)
            assert done.state == "cancelled" and done.result is None
            assert len([a for a in done.actions if a["kind"] == "model"]) == 1
            diag = await engine.diagnostics(handle.run_id)
            assert diag.budget["spent"] == 2 and diag.workflow["quiescent"]
            assert (await wait_effect(runtime, label))[1] == 1
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )

    asyncio.run(run())


@pytest.mark.parametrize("repeat", range(REPEATS))
def test_real_worker_registration_drift_refuses_before_provider_or_tool(tmp_path, repeat):
    async def run():
        async with system(tmp_path, worker_version="2") as (engine, runtime, workers):
            handle = await engine.submit(AgentSpec("a", "answer"), "request", command_id="s")
            done = await engine.drive(handle.run_id)
            assert done.state == "failed" and done.error["code"] == "definition_mismatch"
            diagnostics = await engine.diagnostics(handle.run_id)
            assert diagnostics.budget["spent"] == 0
            assert diagnostics.budget["unknown"] == 0
            assert all(
                "TEMPORAL_PROVIDER_CALLED" not in log.read_text() for _, log in workers.processes
            )
            await replay_temporal_history(
                await engine.client.get_workflow_handle(handle.run_id).fetch_history()
            )

    asyncio.run(run())
