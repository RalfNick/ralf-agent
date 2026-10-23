import asyncio
import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from relf_agent import AgentSpec, ManagedModelSummarizer, Scope
from relf_agent.temporal import TemporalEngine, replay_temporal_history

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_real_custom_context_two_workers_restart_history_and_model_summary(tmp_path):
    async def run():
        from temporalio.client import Client

        fixture_path = Path(__file__).with_name("temporal_context_worker.py")
        fixture_spec = importlib.util.spec_from_file_location(
            "temporal_context_worker", fixture_path
        )
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        runtime = fixture.runtime()
        queue = "context-" + uuid.uuid4().hex
        processes = []

        async def start():
            for _ in range(2):
                log = tmp_path / f"worker-{len(processes)}.log"
                with log.open("w") as output:
                    process = await asyncio.to_thread(
                        subprocess.Popen,
                        [
                            sys.executable,
                            "-u",
                            "-c",
                            "import sys; sys.path.insert(0, "
                            + repr(str(fixture_path.parent))
                            + "); import temporal_context_worker as f; asyncio = __import__('asyncio'); asyncio.run(f.run())",
                        ],
                        env={
                            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
                            "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                            "RALF_TEST_TEMPORAL_QUEUE": queue,
                        },
                        stdout=output,
                        stderr=subprocess.STDOUT,
                    )
                processes.append(process)
                deadline = asyncio.get_running_loop().time() + 20
                while "TEMPORAL_CONTEXT_READY" not in log.read_text():
                    assert (
                        process.poll() is None and asyncio.get_running_loop().time() < deadline
                    ), log.read_text()
                    await asyncio.sleep(0.05)

        async def stop():
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)

        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=runtime.manifest,
            scope=Scope("custom-context", queue),
            activity_timeout=5,
            drive_timeout=25,
        )
        try:
            await start()
            handle = await engine.submit(
                AgentSpec("custom", "Observe preference with approval", ("observe",)),
                "INC-POOL",
                command_id="first",
                budget=8,
            )
            paused = await engine.drive(handle.run_id)
            assert paused.state == "waiting_approval"
            initial_context = next(a for a in paused.actions if a["kind"] == "context")
            assert initial_context["status"] == "completed"
            assert initial_context["response"]["context_identity"]["measurement"]["estimated"]
            await stop()
            await start()
            pending = paused.pending[0]
            await engine.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            done = await engine.drive(handle.run_id)
            assert done.state == "succeeded" and done.result["language"] == "zh-CN"
            assert (
                next(a for a in done.actions if a["id"] == initial_context["id"])["response"]
                == initial_context["response"]
            )
            repeated = await engine.submit(
                AgentSpec("custom", "Observe preference with approval", ("observe",)),
                "INC-POOL",
                command_id="first",
                budget=8,
            )
            assert repeated == handle
            summary = await ManagedModelSummarizer().summarize(
                engine,
                [[{"role": "assistant", "content": "zh-CN; INC-POOL unresolved"}]],
                command_id="summary",
                max_chars=128,
            )
            assert "INC-POOL" in summary.summary.text
            for run_id in (handle.run_id, summary.run_id):
                history = await client.get_workflow_handle(run_id).fetch_history()
                await replay_temporal_history(history)
            # New context snapshots live in real History; no LocalEngine database.
            assert not list(tmp_path.glob("*.sqlite"))
        finally:
            await stop()

    asyncio.run(run())
