import asyncio
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent import Runtime, Scope, SessionRef
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from ralf_agent.temporal_session_state import workflow_id
from tests.temporal_knowledge_worker import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "sequence", "graph", "team", "dynamic", "nested"])
@pytest.mark.parametrize("managed", [False, True])
def test_original_turn_and_conversation_survive_actual_worker_kill(tmp_path, kind, managed):
    async def run():
        from temporalio.client import Client

        import ralf_agent

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "session-recovery-" + uuid.uuid4().hex
        execution, definition, store = runtime(tmp_path, queue, kind, managed, enable_sessions=True)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("temporal-knowledge", queue),
            activity_timeout=2,
        )
        host = Runtime.from_temporal(engine)
        processes = []

        async def start(mode):
            log = tmp_path / f"worker-{mode}.log"
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(
                    [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
                ),
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                "RALF_TEST_TEMPORAL_QUEUE": queue,
                "RALF_SESSION_ROOT": str(tmp_path),
                "RALF_SESSION_KIND": kind,
                "RALF_SESSION_MANAGED": str(int(managed)),
                "RALF_SESSION_MODE": mode,
            }
            with log.open("w") as out:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_session_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=env,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            for _ in range(400):
                if "TEMPORAL_SESSION_READY" in log.read_text():
                    return process
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
            pytest.fail(log.read_text())

        async def idle(entry):
            for _ in range(400):
                if not (await entry.status()).busy:
                    return
                await asyncio.sleep(0.05)
            pytest.fail(str(await entry.status()))

        try:
            worker = await start("crash")
            entry = await host.open_session(definition, "chat", command_id="open")
            first = await entry.submit("pool", command_id="first", budget=24)
            assert (await first.wait(wait_timeout=30)).snapshot.state == "succeeded"
            await idle(entry)
            second = await entry.submit("pool", command_id="second", budget=24)
            for _ in range(400):
                if (tmp_path / "read-ready").exists():
                    break
                assert worker.poll() is None, (tmp_path / "worker-crash.log").read_text()
                await asyncio.sleep(0.05)
            assert (tmp_path / "read-ready").exists(), await second.diagnostics()
            assert (await entry.status()).busy
            worker.kill()
            await asyncio.to_thread(worker.wait, timeout=5)
            await host.aclose()  # Detach never cancels the original Turn.
            await start("resume")
            host = Runtime.from_temporal(engine)
            attached = await host.aattach_session(SessionRef.from_dict(entry.ref.to_dict()))
            replay = await attached.submit("pool", command_id="second", budget=24)
            assert replay.turn == second.turn and replay.ref == second.ref
            assert (await replay.wait(wait_timeout=30)).snapshot.state == "succeeded"
            await idle(attached)
            assert [t.turn_seq for t in await attached.turns()] == [1, 2]
            assert (await host.aattach(second.ref)).ref == second.ref
            with sqlite3.connect(store.path) as db:
                rows = list(db.execute("SELECT kind,value FROM audit ORDER BY rowid"))
            one = [("retrieve", "A"), ("model", '["pool A evidence"]')]
            if kind != "native":
                one += [("retrieve", "B"), ("model", '["pool B evidence"]')]
            assert rows == one * 2
            for run_id in (workflow_id(entry.ref.key), first.ref.run_id, second.ref.run_id):
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
        finally:
            await host.aclose()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            store.close()
            await engine.aclose()

    asyncio.run(run())
