"""SIGKILL/restart of separate actual Workers with the original Session History."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Runtime
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_session_tree_worker import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize(
    "window",
    ["root-read-adopted", "member-committed", "root-prepared", "root-committed", "root-received"],
)
@pytest.mark.parametrize("managed", [False, True])
def test_independent_workers_resume_original_tree_without_duplicate_io(tmp_path, window, managed):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "tree-crash-" + uuid.uuid4().hex
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

        async def start(window_name):
            log_path = tmp_path / f"worker-{len(processes)}.log"
            env = {
                key: os.environ[key]
                for key in ("PATH", "RALF_TEST_TEMPORAL_ADDRESS")
                if key in os.environ
            }
            env.update(
                PYTHONPATH=str(Path(__file__).parents[1] / "src"),
                RALF_TREE_ROOT=str(tmp_path),
                RALF_TREE_WINDOW=window_name,
                RALF_TREE_MANAGED="1" if managed else "0",
                RALF_TEST_TEMPORAL_QUEUE=queue,
            )
            with log_path.open("w") as log:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_session_tree_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            for _ in range(300):
                if "TREE_WORKER_READY" in log_path.read_text():
                    return process
                assert process.poll() is None, log_path.read_text()
                await asyncio.sleep(0.05)
            raise AssertionError(log_path.read_text())

        try:
            first_worker = await start(window)
            definition = GraphWorkflowSpec(
                "g", [GraphNode("writer", agent=AgentSpec("writer", "Answer"))]
            )
            entry = await host.open_session(definition, "chat", command_id="open")
            turn = await entry.submit("task", command_id="first", budget=32)
            marker = tmp_path / "window-ready"
            for _ in range(400):
                if marker.exists():
                    break
                await asyncio.sleep(0.05)
            assert marker.exists(), [p.poll() for p in processes]
            first_worker.kill()
            await asyncio.to_thread(first_worker.wait, timeout=5)
            await start("none")
            if window in {"root-committed", "member-committed"}:
                # Only kill+wait of this actual process proves all its handlers ended.
                assert first_worker.returncode is not None
                committed = json.loads(marker.read_text())
                target = None
                for _ in range(100):
                    pending = [turn.turn.run.run_id]
                    while pending:
                        run_id = pending.pop()
                        proof = await engine.diagnostics(run_id)
                        stages = await engine.session_stages(run_id)
                        stage = next(
                            (
                                value
                                for value in stages
                                if value["intent"]["address"] == committed["address"]
                                and value.get("write_action")
                            ),
                            None,
                        )
                        if stage is not None:
                            action = next(
                                value
                                for value in proof.snapshot.actions
                                if value["id"] == stage["write_action"]
                            )
                            if action.get("dispatch_grant", {}).get("allowed"):
                                target = (run_id, proof.release_digest, action)
                                break
                        pending.extend(
                            value["run_id"] for value in proof.workflow.get("children", [])
                        )
                    if target is not None:
                        break
                    await asyncio.sleep(0.05)
                assert target is not None
                run_id, release_digest, action = target
                await client.get_workflow_handle(run_id).execute_update(
                    "session_execution_ended",
                    {
                        "scope": {"workspace": scope.workspace, "principal": scope.principal},
                        "action_id": action["id"],
                        "release_digest": release_digest,
                        "request_digest": action["request_digest"],
                    },
                    id="worker-stop-proof:" + action["id"],
                )
            for _ in range(100):
                done = await engine.drive(turn.turn.run.run_id, wait_seconds=1)
                if done.state == "succeeded" and not (await entry.status()).busy:
                    break
                assert done.state not in {"failed", "cancelled"}, done
                await asyncio.sleep(0.05)
            assert done.state == "succeeded", done
            assert not (await entry.status()).busy
            proof = await engine.diagnostics(turn.turn.run.run_id)
            assert proof.budget["spent"] == 3
            assert proof.budget["reserved"] == proof.budget["unknown"] == 0
            with sqlite3.connect(tmp_path / "audit.sqlite") as db:
                rows = [
                    (kind, json.loads(value))
                    for kind, value in db.execute("SELECT kind,value FROM audit")
                ]
            assert len([v for k, v in rows if k == "model"]) == 1
            writes = [v for k, v in rows if k == "append"]
            assert len(writes) == len({v["message_id"] for v in writes}) == 2
            assert len({v["address"] for v in writes}) == 2
            assert len([v for k, v in rows if k == "read"]) == 2
            assert backend.read(scope, entry.ref.key.storage_key)[0] == 1
            pending = [turn.turn.run.run_id]
            while pending:
                run_id = pending.pop()
                flow = await engine.diagnostics(run_id)
                pending.extend(c["run_id"] for c in flow.workflow.get("children", []))
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            await execution.close_session_execution()
            await host.aclose()
            await engine.aclose()
            backend.store.close()

    asyncio.run(asyncio.wait_for(run(), timeout=120))
