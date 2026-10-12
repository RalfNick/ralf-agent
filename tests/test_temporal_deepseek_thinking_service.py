"""Actual Worker loss and History replay; HTTP fixture proves protocol only."""

import asyncio
import copy
import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from ralf_agent import RunRef, Runtime, Scope
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_deepseek_thinking_worker import FINAL_MESSAGE, NATIVE_MESSAGE, runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "graph"])
@pytest.mark.parametrize("window", ["approval", "receipt"])
def test_deepseek_native_receipt_and_final_reasoning_survive_worker_loss_and_history_replay(
    tmp_path, kind, window
):
    asyncio.run(recover(tmp_path, kind, window))


async def recover(root, kind, window):
    from temporalio.client import Client

    import ralf_agent

    address = os.environ["RALF_TEST_TEMPORAL_ADDRESS"]
    client = await Client.connect(address)
    queue = "deepseek-thinking-" + uuid.uuid4().hex
    execution, definition, provider_client = runtime(root, kind)
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("temporal-deepseek-thinking", queue),
        activity_timeout=3,
    )
    host = Runtime.from_temporal(engine)
    processes = []

    def lifecycle(row):
        with (root / "deepseek-worker-lifecycle.jsonl").open("a") as output:
            output.write(json.dumps({"queue": queue, "kind": kind, "window": window, **row}) + "\n")

    async def start(label):
        log = root / f"deepseek-worker-{label}.log"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(
                [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
            ),
            "RALF_TEST_TEMPORAL_ADDRESS": address,
            "RALF_TEST_TEMPORAL_QUEUE": queue,
            "RALF_DEEPSEEK_WORKER_ROOT": str(root),
            "RALF_DEEPSEEK_WORKER_KIND": kind,
            "RALF_DEEPSEEK_WORKER_MODE": label,
            "RALF_DEEPSEEK_WORKER_WINDOW": window,
        }
        with log.open("w") as output:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "from tests.temporal_deepseek_thinking_worker import run; import asyncio; asyncio.run(run())",
                ],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        processes.append(process)
        lifecycle({"phase": "worker-started", "mode": label, "pid": process.pid})
        for _ in range(400):
            if "TEMPORAL_DEEPSEEK_READY" in log.read_text():
                return process
            assert process.poll() is None, log.read_text()
            await asyncio.sleep(0.05)
        pytest.fail(log.read_text())

    def audit():
        return [
            json.loads(line) for line in (root / "deepseek-audit.jsonl").read_text().splitlines()
        ]

    async def diagnostics(run_id):
        return await client.get_workflow_handle(run_id).query(
            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
        )

    try:
        original_worker = await start("original")
        original = await host.submit(
            definition, "Three units", command_id="submit-" + queue, budget=16
        )
        item = None
        for _ in range(600):
            if window == "receipt":
                ready = root / "receipt-ready"
                if ready.exists():
                    node_id = ready.read_text()
                    break
            else:
                pending = await original.pending()
                if pending:
                    item = pending[0]
                    node_id = item["ref"]["run_id"]
                    break
            assert (await original.status()).state not in {"failed", "succeeded"}, (
                await original.diagnostics()
            )
            await asyncio.sleep(0.05)
        else:
            pytest.fail(str(await original.diagnostics()))
        before = await diagnostics(node_id)
        lifecycle(
            {"phase": "checkpoint", "root_run_id": original.ref.run_id, "node_run_id": node_id}
        )
        assert before["snapshot"]["state"] == (
            "waiting_approval" if window == "approval" else "running"
        )
        actions = before["snapshot"]["actions"]
        model = next(action for action in actions if action["kind"] == "model")
        raw = model["received_response"]
        assert raw["continuation"]["protocol"] == "deepseek-thinking-v1"
        assert raw["continuation"]["data"] == {"message": NATIVE_MESSAGE}
        assert raw["tool_calls"] == [
            {"name": "calculate", "arguments": {"quantity": 3}, "call_id": "native-quantity"}
        ]
        if window == "approval":
            tool = next(action for action in actions if action["kind"] == "tool")
            assert tool["arguments"] == {"quantity": 3, "price": 2}
            assert model["response"]["continuation_proposal"]["tool_calls"][0]["arguments"] == {
                "quantity": 3
            }
        else:
            assert model["status"] == "received"
            assert model["model_receipt"]["received_response"] == raw
            assert not any(action["kind"] == "tool" for action in actions)
            assert any(
                action["kind"] == "model_adoption" and action["status"] == "executing"
                for action in actions
            )
            assert before["budget"]["spent"] == 1 and before["budget"]["unknown"] == 0
        pinned_model = copy.deepcopy(model)
        assert [row["phase"] for row in audit() if row["kind"] == "model"] == ["initial"]
        assert not any(row["kind"] == "tool" for row in audit())
        original_worker.kill()
        await asyncio.to_thread(original_worker.wait, timeout=5)
        lifecycle({"phase": "worker-killed", "mode": "original", "pid": original_worker.pid})
        await host.aclose()
        host = Runtime.from_temporal(engine)
        await start("recover")
        attached = await host.aattach(original.ref)
        if item is None:
            for _ in range(600):
                pending = await attached.pending()
                if pending:
                    item = pending[0]
                    break
                assert (await attached.status()).state not in {"failed", "succeeded"}, (
                    await attached.diagnostics()
                )
                await asyncio.sleep(0.05)
            else:
                pytest.fail(str(await attached.diagnostics()))
        owner = await host.aattach(RunRef.from_dict(item["ref"]))
        receipt = await owner.approve(item["action_id"], item["digest"], command_id="approved-once")
        assert (
            await owner.approve(item["action_id"], item["digest"], command_id="approved-once")
            == receipt
        )
        for _ in range(600):
            result = await attached.wait(wait_timeout=0.1, terminal_only=True)
            if result.snapshot.state in {"succeeded", "failed"}:
                break
        assert result.snapshot.state == "succeeded", await attached.diagnostics()
        after = await diagnostics(node_id)
        assert after["snapshot"]["result"] == {"amount": 6}
        recorded = next(
            action for action in after["snapshot"]["actions"] if action["id"] == pinned_model["id"]
        )
        if window == "approval":
            assert recorded == pinned_model
        else:
            assert recorded["status"] == "completed"
            for field in ("received_response", "model_receipt", "dispatch_request", "attempts"):
                assert recorded[field] == pinned_model[field]
        finals = [
            action
            for action in after["snapshot"]["actions"]
            if action["kind"] == "model" and action["received_response"]["tool_calls"] == []
        ]
        assert len(finals) == 1
        assert finals[0]["received_response"]["output"] == FINAL_MESSAGE["content"]
        final_continuation = finals[0]["received_response"]["continuation"]
        assert final_continuation["data"] == {"message": FINAL_MESSAGE}
        assert final_continuation["owner_digest"] == raw["continuation"]["owner_digest"]
        assert [row["phase"] for row in audit() if row["kind"] == "model"] == ["initial", "final"]
        assert [row for row in audit() if row["kind"] == "tool"] == [
            {"kind": "tool", "quantity": 3, "price": 2}
        ]
        for run_id in {original.ref.run_id, node_id}:
            await replay_temporal_history(await client.get_workflow_handle(run_id).fetch_history())
        lifecycle({"phase": "replayed", "root_run_id": original.ref.run_id, "node_run_id": node_id})
    finally:
        await host.aclose()
        for process in processes:
            if process.poll() is None:
                process.kill()
            await asyncio.to_thread(process.wait, timeout=5)
            lifecycle(
                {"phase": "worker-reaped", "pid": process.pid, "returncode": process.returncode}
            )
        await execution.close_context_execution(wait_timeout=2)
        await provider_client.aclose()
        await engine.aclose()
