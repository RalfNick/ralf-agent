"""Actual Worker exit/wait and original History recovery, without read replay."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from relf_agent import Runtime
from relf_agent.temporal import TemporalEngine, replay_temporal_history

from .temporal_context_read_worker import runtime
from .test_temporal_context_read_composition import definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("window", ["held-end", "model-prepared"])
@pytest.mark.parametrize("managed", [False, True])
def test_actual_worker_exit_preserves_read_snapshot_and_original_end_gate(
    tmp_path, window, managed
):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "read-crash-" + uuid.uuid4().hex
        execution, backend, scope = runtime(tmp_path, queue, managed)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=2,
            drive_timeout=10,
        )
        host = Runtime.from_temporal(engine)
        processes = []

        async def start(mode):
            log_path = tmp_path / f"worker-{len(processes)}.log"
            environment = {
                key: os.environ[key]
                for key in ("PATH", "RALF_TEST_TEMPORAL_ADDRESS")
                if key in os.environ
            }
            environment.update(
                PYTHONPATH=str(Path(__file__).parents[1] / "src"),
                RALF_READ_ROOT=str(tmp_path),
                RALF_READ_WINDOW=mode,
                RALF_READ_MANAGED=str(int(managed)),
                RALF_TEST_TEMPORAL_QUEUE=queue,
            )
            with log_path.open("w") as log:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_context_read_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            async with asyncio.timeout(15):
                while "READ_WORKER_READY" not in log_path.read_text():  # noqa: ASYNC110 -- process readiness
                    assert process.poll() is None, log_path.read_text()
                    await asyncio.sleep(0.05)
            return process

        try:
            first = await start(window)
            session = await host.open_session(definition("graph"), "chat", command_id="open")
            turn = await session.submit("question", command_id="first", budget=32)
            marker = tmp_path / "window-ready"
            async with asyncio.timeout(20):
                while not marker.exists():  # noqa: ASYNC110 -- actual process fault window
                    await asyncio.sleep(0.05)
            if window == "held-end":
                async with asyncio.timeout(8):
                    while True:
                        parent = await engine.diagnostics(turn.turn.run.run_id)
                        reader_id = parent.workflow["children"][0]["run_id"]
                        stages = await engine.context_read_stages(reader_id)
                        if stages and stages[0]["response_observed"]:
                            break
                        await asyncio.sleep(0.05)
                assert stages[0]["execution_end_proof"] is None
                assert (await session.status()).busy
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            assert first.returncode is not None
            await start("none")
            if window == "held-end":
                stages = await engine.context_read_stages(reader_id)
                assert stages[0]["execution_end_proof"] is None
                assert (await session.status()).busy
                # Trusted supervisor proof only after this actual process exited.
                # Restarting a Worker alone cannot certify the original handler.
                original = json.loads(marker.read_text())
                await client.get_workflow_handle(
                    reader_id, run_id=original["execution_epoch"]
                ).execute_update(
                    "context_execution_ended",
                    original,
                    id="supervised-read-end:" + original["action_id"],
                )
            async with asyncio.timeout(25):
                while True:
                    done = await engine.drive(turn.turn.run.run_id, wait_seconds=0.5)
                    if done.state == "succeeded" and not (await session.status()).busy:
                        break
                    assert done.state in {"running", "queued", "succeeded"}, done
                    await asyncio.sleep(0.05)
            parent = await engine.diagnostics(turn.turn.run.run_id)
            reader_id = parent.workflow["children"][0]["run_id"]
            stages = await engine.context_read_stages(reader_id)
            assert all(stage["status"] == "completed" for stage in stages)
            assert backend.read(scope, session.ref.key.storage_key)[0] == 1
            with sqlite3.connect(tmp_path / "audit.sqlite") as audit:
                counts = dict(
                    audit.execute("SELECT kind,COUNT(*) FROM audit GROUP BY kind").fetchall()
                )
            assert counts == {"read": 2, "model": 1, "append": 2}
            for run_id in (reader_id, turn.turn.run.run_id):
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)
            await execution.close_context_execution()
            await execution.context_execution.aclose()
            await execution.close_session_execution()
            await host.aclose()
            await engine.aclose()
            backend.store.close()

    asyncio.run(asyncio.wait_for(run(), 120))
