import asyncio
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent import Scope
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_managed_context_worker import runtime
from tests.test_composite_data_context import agent, definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize(
    "kind", ["native", "parallel", "team", "dynamic-dag", "nested", "cancel-read"]
)
def test_actual_history_restores_summary_before_adoption_after_worker_kill(tmp_path, kind):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "h3-context-" + uuid.uuid4().hex
        execution, artifacts = runtime(tmp_path, queue)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("h3-temporal", queue),
            activity_timeout=3,
            drive_timeout=30,
        )
        processes = []

        async def start(mode):
            log = tmp_path / f"worker-{mode}.log"
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(
                    [str(Path(__file__).parents[1] / "src"), str(Path(__file__).parents[1])]
                ),
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                "RALF_TEST_TEMPORAL_QUEUE": queue,
                "RALF_H3_ROOT": str(tmp_path),
                "RALF_H3_MODE": mode,
            }
            with log.open("w") as output:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_managed_context_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            for _ in range(400):
                if "H3_TEMPORAL_READY" in log.read_text():
                    return process
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
            pytest.fail(log.read_text())

        try:
            first = await start("cancel-read" if kind == "cancel-read" else "crash")
            h = await engine.submit(
                agent() if kind in {"native", "cancel-read"} else definition(kind),
                "task",
                command_id="s",
                budget=32,
            )
            if kind == "cancel-read":
                marker = tmp_path / "model-artifact-read-ready"
                for _ in range(500):
                    if marker.exists():
                        break
                    assert first.poll() is None, (tmp_path / "worker-cancel-read.log").read_text()
                    await asyncio.sleep(0.05)
                assert marker.exists()
                await engine.cancel(h.run_id, command_id="cancel")
                assert (await engine.status(h.run_id)).state == "cancelled"
                (tmp_path / "release-model-read").write_text("ready")
                for _ in range(500):
                    info = await engine.diagnostics(h.run_id)
                    if info.workflow["quiescent"]:
                        break
                    await asyncio.sleep(0.05)
                assert info.workflow["quiescent"]
                assert info.budget["reserved"] == info.budget["unknown"] == 0
                with sqlite3.connect(tmp_path / "business.sqlite") as db:
                    counts = dict(db.execute("SELECT kind, COUNT(*) FROM calls GROUP BY kind"))
                assert counts == {"business": 1, "tool": 1}
                await replay_temporal_history(
                    await client.get_workflow_handle(h.run_id).fetch_history()
                )
                return
            for _ in range(500):
                if (tmp_path / "summary-finalize-ready").exists():
                    break
                status = await engine.status(h.run_id)
                assert status.state != "failed", (
                    status.error,
                    (tmp_path / "worker-crash.log").read_text(),
                )
                await asyncio.sleep(0.05)
            assert (tmp_path / "summary-finalize-ready").exists()
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            await start("resume")
            done = await engine.drive(h.run_id)
            assert done.state == "succeeded", done
            diagnostics = await engine.diagnostics(h.run_id)
            assert diagnostics.budget["reserved"] == diagnostics.budget["unknown"] == 0
            runs = [h.run_id]
            for run_id in runs:
                info = await client.get_workflow_handle(run_id).query(
                    "view",
                    {
                        "scope": {"workspace": "h3-temporal", "principal": queue},
                        "kind": "diagnostics",
                    },
                )
                if "children" in info["workflow"]:
                    runs.extend(child["run_id"] for child in info["workflow"]["children"])
                else:
                    for stage in info["context_stages"]:
                        operations = [
                            a
                            for a in info["snapshot"]["actions"]
                            if a.get("stage_key") == stage["key"] and a.get("phase") == "summary"
                        ]
                        assert len(operations) <= 1
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
            with sqlite3.connect(tmp_path / "business.sqlite") as db:
                tools = db.execute("SELECT COUNT(*) FROM calls WHERE kind='tool'").fetchone()[0]
                summaries = db.execute(
                    "SELECT COUNT(*) FROM calls WHERE kind='summary'"
                ).fetchone()[0]
            expected = 1 if kind == "native" else 2
            assert tools == expected * 4 and summaries == expected * 2
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)
            artifacts.close()
            await engine.aclose()

    asyncio.run(run())
