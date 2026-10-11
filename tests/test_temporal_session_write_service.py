import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent import Runtime, SessionRef
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from ralf_agent.temporal_session_state import workflow_id

from .temporal_session_write_worker import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "sequence"])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("window", ["prepared", "committed", "received"])
def test_persistent_turn_save_survives_worker_kill(tmp_path, kind, managed, window):
    async def run():
        from temporalio.client import Client

        import ralf_agent

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "session-save-" + uuid.uuid4().hex
        execution, definition, store, scope = runtime(tmp_path, queue, kind, managed)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=2,
            drive_timeout=30,
        )
        host = Runtime.from_temporal(engine)
        processes = []

        async def start(mode):
            log = tmp_path / ("worker-" + mode + ".log")
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(
                    [
                        str(Path(ralf_agent.__file__).parents[1]),
                        str(Path(__file__).parents[1]),
                    ]
                ),
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                "RALF_TEST_TEMPORAL_QUEUE": queue,
                "RALF_SESSION_WRITE_ROOT": str(tmp_path),
                "RALF_SESSION_WRITE_KIND": kind,
                "RALF_SESSION_WRITE_MANAGED": str(int(managed)),
                "RALF_SESSION_WRITE_WINDOW": mode,
            }
            with log.open("w") as output:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_session_write_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            for _ in range(400):
                if "SESSION_WRITE_WORKER_READY" in log.read_text():
                    return process
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
            pytest.fail(log.read_text())

        try:
            first = await start(window)
            entry = await host.open_session(definition, "chat", command_id="open")
            turn = await entry.submit("question", command_id="first", budget=32)
            for _ in range(400):
                if (tmp_path / "window-ready").exists():
                    break
                assert first.poll() is None, (tmp_path / ("worker-" + window + ".log")).read_text()
                await asyncio.sleep(0.05)
            assert (tmp_path / "window-ready").exists()
            # OS kill plus wait proves this actual Worker and every handler in it exited.
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            assert first.returncode is not None
            await start("resume")
            if window == "committed":
                for _ in range(200):
                    snapshot = await engine.status(turn.turn.run.run_id)
                    writes = [a for a in snapshot.actions if a.get("phase") == "session-write"]
                    if writes and writes[-1].get("dispatch_grant", {}).get("allowed"):
                        break
                    await asyncio.sleep(0.05)
                action = writes[-1]
                original = {
                    "scope": {"workspace": scope.workspace, "principal": scope.principal},
                    "action_id": action["id"],
                    "release_digest": (
                        await engine.diagnostics(turn.turn.run.run_id)
                    ).release_digest,
                    "request_digest": action["request_digest"],
                }
                await client.get_workflow_handle(turn.turn.run.run_id).execute_update(
                    "session_execution_ended",
                    original,
                    id="worker-stop-proof:" + action["id"],
                )
            done = await engine.drive(turn.turn.run.run_id)
            assert done.state == "succeeded", done
            for _ in range(200):
                if not (await entry.status()).busy:
                    break
                await asyncio.sleep(0.05)
            assert not (await entry.status()).busy
            attached = await host.aattach_session(SessionRef.from_dict(entry.ref.to_dict()))
            second = await attached.submit("follow up", command_id="second", budget=32)
            assert (await second.wait(wait_timeout=30)).snapshot.state == "succeeded"
            with sqlite3.connect(tmp_path / "audit.sqlite") as db:
                rows = [(k, json.loads(v)) for k, v in db.execute("SELECT kind,value FROM audit")]
            appends = [v for k, v in rows if k == "append"]
            models = [v for k, v in rows if k == "model"]
            count = 2 if kind == "native" else 4
            assert len(appends) == len(models) == count
            assert len({v["message_id"] for v in appends}) == count
            assert {v["address"] for v in appends} == {entry.ref.key.storage_key}
            assert [len(v["records"]) for v in models] == list(range(count))
            for run_id in [
                turn.turn.run.run_id,
                second.turn.run.run_id,
                workflow_id(entry.ref.key),
            ]:
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            await execution.close_session_execution()
            store.close()
            await host.aclose()
            await engine.aclose()

    asyncio.run(run())


def test_cancelled_turn_retains_busy_until_actual_sync_handler_ends():
    async def run():
        import threading

        from temporalio.client import Client

        from ralf_agent import (
            AgentSpec,
            InMemoryMemory,
            ModelResponse,
            Scope,
            ThreadedMemoryAdapter,
            ToolRegistry,
        )
        from ralf_agent.errors import CloseIncomplete, SessionBusy
        from ralf_agent.temporal import build_temporal_worker
        from ralf_agent.temporal_activities import TemporalRuntime

        committed, finish = threading.Event(), threading.Event()

        class Delayed(InMemoryMemory):
            def append(self, *args, **kwargs):
                result = super().append(*args, **kwargs)
                committed.set()
                assert finish.wait(20), "test must release actual handler"
                return result

        class Provider:
            identity = {"kind": "cancel-session-save", "version": "1"}

            async def complete(self, messages, tools):
                return ModelResponse(output="answer")

        backend = Delayed()
        execution = TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            session_store=ThreadedMemoryAdapter(backend),
            enable_sessions=True,
            session_writes=True,
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "session-cancel-" + uuid.uuid4().hex
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.manifest,
            scope=Scope("session-cancel", queue),
            activity_timeout=1,
            drive_timeout=10,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(AgentSpec("a", "Answer"), "chat", command_id="open")
                turn = await entry.submit("task", command_id="first")
                for _ in range(200):
                    if committed.is_set():
                        break
                    await asyncio.sleep(0.05)
                assert committed.is_set()
                await engine.cancel(turn.turn.run.run_id, command_id="cancel")
                assert (await engine.status(turn.turn.run.run_id)).state == "cancelled"
                assert (await entry.status()).busy
                with pytest.raises(SessionBusy):
                    await entry.submit("next", command_id="busy")
                assert not await execution.wait_session_executions(wait_timeout=0.05)
                with pytest.raises(CloseIncomplete):
                    await execution.close_session_execution(wait_timeout=0.05)
                finish.set()
                for _ in range(200):
                    await engine.drive(turn.turn.run.run_id)
                    if not (await entry.status()).busy:
                        break
                    await asyncio.sleep(0.05)
                assert not (await entry.status()).busy
                done = await engine.diagnostics(turn.turn.run.run_id)
                assert done.snapshot.state == "cancelled"
                assert done.budget["reserved"] == done.budget["unknown"] == 0
                assert backend.read(engine.scope, entry.ref.key.storage_key)[0] == 1
                assert await execution.wait_session_executions(wait_timeout=3)
                await replay_temporal_history(
                    await client.get_workflow_handle(turn.turn.run.run_id).fetch_history()
                )
        finally:
            finish.set()
            await execution.close_session_execution(wait_timeout=3)
            await host.aclose()
            await engine.aclose()

    asyncio.run(run())
