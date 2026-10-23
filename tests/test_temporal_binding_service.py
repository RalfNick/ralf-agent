import asyncio
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from relf_agent import Scope
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_binding_worker import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize(
    "kind", ["plain-cache", "managed-cache", "artifact-plain", "artifact-managed"]
)
def test_member_context_and_artifact_evidence_survive_actual_worker_restart(tmp_path, kind):
    async def run():
        from temporalio.client import Client

        import relf_agent

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "binding-" + uuid.uuid4().hex
        execution, definition, stores = runtime(tmp_path, queue, kind)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.manifest,
            scope=Scope("binding-isolation", queue),
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
                "RALF_BINDING_ROOT": str(tmp_path),
                "RALF_BINDING_KIND": kind,
                "RALF_BINDING_MODE": mode,
            }
            with log.open("w") as output:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_binding_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            for _ in range(400):
                if "TEMPORAL_BINDING_READY" in log.read_text():
                    return process
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
            pytest.fail(log.read_text())

        try:
            first = await start("crash")
            handle = await engine.submit(definition, "task", command_id="s", budget=32)
            for _ in range(500):
                if (tmp_path / "next-context-ready").exists():
                    break
                assert (await engine.status(handle.run_id)).state != "failed"
                await asyncio.sleep(0.05)
            assert (tmp_path / "next-context-ready").exists()
            before = await engine.context_artifacts(handle.run_id)
            if kind.startswith("artifact"):
                assert before and all(
                    r["intent"]["policy"] == execution.context.identity for r in before
                )
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            await start("resume")
            done = await engine.drive(handle.run_id)
            assert done.state == "succeeded", done
            if kind == "plain-cache":
                with sqlite3.connect(tmp_path / "calls.sqlite") as db:
                    assert [r[0] for r in db.execute("SELECT label FROM calls ORDER BY rowid")] == [
                        "A",
                        "B",
                    ]
            elif kind == "managed-cache":
                stages = await engine.context_stages(handle.run_id)
                assert {s["key"].split(":")[0] for s in stages} == {"0", "1"}
            else:
                after = await engine.context_artifacts(handle.run_id)
                original_ids = {r["intent"]["reference"]["artifact_id"] for r in before}
                assert [
                    r for r in after if r["intent"]["reference"]["artifact_id"] in original_ids
                ] == before
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            for store in stores:
                store.close()
            await engine.aclose()

    asyncio.run(run())
