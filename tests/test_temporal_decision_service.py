import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from relf_agent import RecallQuery, RunRef, Runtime, Scope
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_decision_worker import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "sequence", "graph", "team", "dynamic", "nested"])
@pytest.mark.parametrize("managed", [False, True])
def test_accepted_policy_is_not_repeated_after_real_worker_loss(tmp_path, kind, managed):
    asyncio.run(recover(tmp_path, kind, managed, "final"))


@pytest.mark.parametrize("managed", [False, True])
def test_approved_tool_proposal_survive_real_worker_loss(tmp_path, managed):
    asyncio.run(recover(tmp_path, "native", managed, "approval"))


@pytest.mark.parametrize("managed", [False, True])
def test_super_delegation_survives_actual_worker_and_history(tmp_path, managed):
    asyncio.run(recover(tmp_path, "native", managed, "final", delegate=True))


async def recover(tmp_path, kind, managed, window, *, delegate=False):
    from dataclasses import asdict

    from temporalio.client import Client

    import relf_agent

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    queue = "decision-" + uuid.uuid4().hex
    execution, definition, store, memory = runtime(
        tmp_path, queue, kind, managed, delegate=delegate
    )
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("temporal-decision", queue),
        activity_timeout=2,
    )
    host = Runtime.from_temporal(engine)
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
            "RALF_DECISION_ROOT": str(tmp_path),
            "RALF_DECISION_KIND": kind,
            "RALF_DECISION_MANAGED": str(int(managed)),
            "RALF_DECISION_MODE": mode,
            "RALF_DECISION_WINDOW": window,
            "RALF_DECISION_SUPER": str(int(delegate)),
        }
        with log.open("w") as out:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "from tests.temporal_decision_worker import run; import asyncio; asyncio.run(run())",
                ],
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        processes.append(process)
        for _ in range(400):
            if "TEMPORAL_DECISION_READY" in log.read_text():
                return process
            assert process.poll() is None, log.read_text()
            await asyncio.sleep(0.05)
        pytest.fail(log.read_text())

    async def drive_to_read(agent_run):
        for _ in range(600):
            if (tmp_path / "read-ready").exists():
                return
            snapshot = await agent_run.status()
            assert snapshot.state not in {"failed", "succeeded"}, await agent_run.diagnostics()
            for item in await agent_run.pending():
                owner = await host.aattach(RunRef.from_dict(item["ref"]))
                await owner.approve(
                    item["action_id"], item["digest"], command_id="approve-" + item["action_id"]
                )
            await asyncio.sleep(0.05)
        pytest.fail(str(await agent_run.diagnostics()))

    try:
        worker = await start("crash")
        original = await host.submit(
            definition, {"target": "demo"}, command_id="submit-" + queue, budget=32
        )
        if window == "approval":
            for _ in range(600):
                pending = await original.pending()
                if pending:
                    node_id = pending[0]["ref"]["run_id"]
                    break
                assert (await original.status()).state not in {"failed", "succeeded"}, (
                    await original.diagnostics()
                )
                await asyncio.sleep(0.05)
            else:
                pytest.fail(str(await original.diagnostics()))
            (tmp_path / "read-ready").write_text(node_id)
        else:
            await drive_to_read(original)
        node_id = (tmp_path / "read-ready").read_text()
        before = await client.get_workflow_handle(node_id).query(
            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
        )
        models = [a for a in before["snapshot"]["actions"] if a["kind"] == "model"]
        assert models[-1]["response"]["decision_evidence"]["registration"]
        assert before["snapshot"]["state"] == (
            "waiting_approval" if window == "approval" else "running"
        )
        worker.kill()
        await asyncio.to_thread(worker.wait, timeout=5)
        await host.aclose()
        host = Runtime.from_temporal(engine)
        await start("recover")
        attached = await host.aattach(original.ref)
        for _ in range(600):
            for item in await attached.pending():
                owner = await host.aattach(RunRef.from_dict(item["ref"]))
                await owner.approve(
                    item["action_id"], item["digest"], command_id="approve-" + item["action_id"]
                )
            result = await attached.wait(wait_timeout=0.1, terminal_only=True)
            if result.snapshot.state in {"succeeded", "failed"}:
                break
        assert result.snapshot.state == "succeeded", await attached.diagnostics()
        rows = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
        count = 1 if kind == "native" else 2
        assert len([r for r in rows if r["kind"] == "model"]) == count * 2
        assert len([r for r in rows if r["kind"] == "tool"]) == count
        assert [r["policy"] for r in rows if r["kind"] == "model"] == (
            ["policy:A"] * 2 if count == 1 else ["policy:A"] * 2 + ["policy:B"] * 2
        )
        assert len(before["completion_stages"]) == (
            0 if window == "approval" else 2 if kind == "sequence" else 1
        )
        assert (
            len(memory.recall(engine.scope, "auto-memory", RecallQuery(max_items=16)).items)
            == count
        )
        for run_id in {original.ref.run_id, node_id}:
            await replay_temporal_history(await client.get_workflow_handle(run_id).fetch_history())
    finally:
        await host.aclose()
        for process in processes:
            if process.poll() is None:
                process.kill()
            await asyncio.to_thread(process.wait, timeout=5)
        store.close()
        await engine.aclose()
