"""Declared components, separate real Workers, original Turn/History authority."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent import AgentSpec, Runtime, TemporalProfile
from ralf_agent.temporal import replay_temporal_history
from ralf_agent.types import digest

from .temporal_profile_worker import assembly
from .test_temporal_context_read_composition import definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize(
    "kind", ["native", "sequence", "graph", "team", "plan", "dag", "nested", "approval"]
)
def test_profile_separate_workers_two_turns_restart_and_replay(tmp_path, kind):
    async def run():
        from temporalio.client import Client

        profile = TemporalProfile(
            "service",
            "1",
            {
                "default": {
                    "adapter": "service-offline",
                    "config": {"mode": "approval" if kind == "approval" else "plain"},
                }
            },
            {
                "session_store": {"adapter": "sqlite", "config": {"path": "session.sqlite"}},
                "context_assembler": {"adapter": "managed-summary"},
                **({"tools": {"adapter": "service-read"}} if kind == "approval" else {}),
            },
            execution={
                "enable_sessions": True,
                "session_writes": True,
                "composite_sessions": True,
                "context_reads": True,
            },
        )
        (tmp_path / "profile.json").write_text(
            json.dumps(
                {
                    "kind": "temporal-profiles",
                    "schema_version": 1,
                    "default": {"name": "service", "version": "1"},
                    "profiles": [profile.to_dict()],
                }
            )
        )
        queue = "profile-" + uuid.uuid4().hex
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        parent = await assembly(tmp_path, queue)
        engine = parent.create_engine(
            client, task_queue=queue, activity_timeout=3, drive_timeout=30
        )
        host = Runtime.from_temporal(engine)
        processes = []

        async def start():
            identity = str(len(processes))
            log_path = tmp_path / ("worker-" + identity + ".log")
            environment = {
                k: os.environ[k] for k in ("PATH", "RALF_TEST_TEMPORAL_ADDRESS") if k in os.environ
            }
            environment.update(
                PYTHONPATH=str(Path(__file__).parents[1] / "src"),
                RALF_PROFILE_ROOT=str(tmp_path),
                RALF_TEST_TEMPORAL_QUEUE=queue,
                RALF_PROFILE_WORKER_ID=identity,
            )
            with log_path.open("w") as log:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "import asyncio; from tests.temporal_profile_worker import run; asyncio.run(run())",
                    ],
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            processes.append((identity, process, log_path))
            async with asyncio.timeout(15):
                while "PROFILE_WORKER_READY" not in log_path.read_text():  # noqa: ASYNC110 -- original process readiness
                    assert process.poll() is None, log_path.read_text()
                    await asyncio.sleep(0.05)
            assert digest(
                json.loads((tmp_path / ("release-" + identity + ".json")).read_text())
            ) == digest(parent.release)

        async def stop():
            for identity, process, log_path in processes:
                if process.poll() is None:
                    (tmp_path / ("stop-" + identity)).touch()
                    assert await asyncio.to_thread(process.wait, 25) == 0, log_path.read_text()
                assert "PROFILE_WORKER_CLOSED" in log_path.read_text()

        try:
            await start()
            await start()
            selected_definition = (
                AgentSpec("approved", "Answer", tools=["query"])
                if kind == "approval"
                else definition(kind)
            )
            session = await host.open_session(selected_definition, "chat", command_id="open")
            for index in (1, 2):
                turn = await session.submit("question", command_id=f"turn-{index}", budget=64)
                done = await engine.drive(turn.turn.run.run_id)
                if kind == "approval":
                    assert done.state == "waiting_approval", done
                    target = done.pending[0]
                    if index == 1:
                        await stop()
                        await start()
                        await start()
                    first = await engine.approve(
                        done.run_id,
                        target["action_id"],
                        target["digest"],
                        command_id=f"approve-{index}",
                    )
                    assert (
                        await engine.approve(
                            done.run_id,
                            target["action_id"],
                            target["digest"],
                            command_id=f"approve-{index}",
                        )
                        == first
                    )
                    done = await engine.drive(done.run_id)
                assert done.state == "succeeded", done
                async with asyncio.timeout(15):
                    while (await session.status()).busy:  # noqa: ASYNC110 -- actual History quiescence
                        await asyncio.sleep(0.05)
                pending = [done.run_id]
                while pending:
                    run_id = pending.pop()
                    raw = await engine._view(run_id, "diagnostics")
                    assert raw["manifest"]["runtime_profile"] == profile.identity
                    pending.extend(child["run_id"] for child in raw["workflow"].get("children", []))
                    assert raw["workflow"]["quiescent"]
                    if raw["workflow"]["backend"] == "temporal":
                        assert raw["context_reads"]
                        assert all(
                            read["response_observed"] and read["execution_end_proof"]
                            for read in raw["context_reads"]
                        )
                    await replay_temporal_history(
                        await client.get_workflow_handle(run_id).fetch_history()
                    )
                if index == 1:
                    await stop()
                    await start()
                    await start()
                    async with asyncio.timeout(15):
                        while (await session.status()).busy:  # noqa: ASYNC110 -- original Coordinator replay/quiescence
                            await asyncio.sleep(0.05)
            with sqlite3.connect(tmp_path / "audit.sqlite") as connection:
                count = connection.execute(
                    "SELECT count(*) FROM calls WHERE kind='model'"
                ).fetchone()[0]
            assert count == (4 if kind in {"sequence", "approval"} else 2)
            if kind == "approval":
                with sqlite3.connect(tmp_path / "audit.sqlite") as connection:
                    assert (
                        connection.execute(
                            "SELECT count(*) FROM calls WHERE kind='query'"
                        ).fetchone()[0]
                        == 2
                    )
        finally:
            try:
                await stop()
            finally:
                await host.aclose()
                await parent.aclose(wait_timeout=20)

    asyncio.run(asyncio.wait_for(run(), 150))
