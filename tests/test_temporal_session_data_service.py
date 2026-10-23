import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from relf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_session_data_worker import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "sequence"])
@pytest.mark.parametrize("managed", [False, True])
def test_session_reads_and_accepted_model_survive_actual_worker_kill(tmp_path, kind, managed):
    async def run():
        from temporalio.client import Client

        import relf_agent

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "session-read-" + uuid.uuid4().hex
        execution, definition, store, scope = runtime(tmp_path, queue, kind, managed)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=2,
            drive_timeout=30,
        )
        processes = []

        async def start(mode):
            log = tmp_path / f"worker-{mode}.log"
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(
                    [str(Path(relf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
                ),
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                "RALF_TEST_TEMPORAL_QUEUE": queue,
                "RALF_SESSION_READ_ROOT": str(tmp_path),
                "RALF_SESSION_READ_KIND": kind,
                "RALF_SESSION_READ_MANAGED": str(int(managed)),
                "RALF_SESSION_READ_MODE": mode,
            }
            with log.open("w") as output:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_session_data_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            for _ in range(400):
                if "SESSION_READ_WORKER_READY" in log.read_text():
                    return process
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
            pytest.fail(log.read_text())

        try:
            first = await start("crash")
            handle = await engine.submit(definition, "task", command_id="s", budget=24)
            for _ in range(400):
                if (tmp_path / "read-ready").exists():
                    break
                assert first.poll() is None, (tmp_path / "worker-crash.log").read_text()
                await asyncio.sleep(0.05)
            assert (tmp_path / "read-ready").exists(), await engine.status(handle.run_id)
            if kind == "native":
                with sqlite3.connect(store.path) as db:
                    assert (
                        db.execute("SELECT count(*) FROM audit WHERE kind='read'").fetchone()[0]
                        == 1
                    )
                    assert (
                        db.execute("SELECT count(*) FROM audit WHERE kind='model'").fetchone()[0]
                        == 0
                    )
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            # Change already accepted A data while no Worker can read it.
            from relf_agent import SessionBindingResource, SQLiteMemory
            from relf_agent.temporal_session_data import private_address

            backend = SQLiteMemory(store)
            address = (
                SessionBindingResource(backend, namespaces=("A",), default_namespace="A")
                .select({}, scope)
                .storage_key(private_address(handle.run_id, 0))
            )
            backend.append(
                scope,
                address,
                {"content": "changed after acceptance"},
                expected_revision=1,
                message_id="after",
            )
            await start("resume")
            done = await engine.drive(handle.run_id)
            assert done.state == "succeeded", done
            with sqlite3.connect(store.path) as db:
                rows = list(db.execute("SELECT kind, value FROM audit ORDER BY rowid"))
            reads = [value for kind, value in rows if kind == "read"]
            models = [json.loads(value) for kind, value in rows if kind == "model"]
            assert len(reads) == (1 if kind == "native" else 2)
            assert models == (
                [["A evidence"]] if kind == "native" else [["A evidence"], ["B evidence"]]
            )
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            store.close()
            await engine.aclose()

    asyncio.run(run())
