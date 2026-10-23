"""Actual Worker loss at signed approval; fixture HTTP is never model-quality evidence."""

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

from relf_agent import RunRef, Runtime, Scope
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_continuation_worker import PARTS, runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "graph"])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("window", ["approval", "receipt"])
def test_signed_native_group_survives_worker_loss_and_duplicate_approval(
    tmp_path, kind, managed, window
):
    asyncio.run(recover(tmp_path, kind, managed, window))


async def recover(root, kind, managed, window):
    from temporalio.client import Client

    import relf_agent

    address = os.environ["RALF_TEST_TEMPORAL_ADDRESS"]
    client = await Client.connect(address)
    queue = "continuation-" + uuid.uuid4().hex
    execution, definition, provider_client = runtime(root, kind, managed)
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("temporal-continuation", queue),
        activity_timeout=3,
    )
    host = Runtime.from_temporal(engine)
    processes = []

    async def start(label):
        log = root / f"worker-{label}.log"
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(
                [
                    str(Path(relf_agent.__file__).parents[1]),
                    str(Path(__file__).parents[1]),
                ]
            ),
            "RALF_TEST_TEMPORAL_ADDRESS": address,
            "RALF_TEST_TEMPORAL_QUEUE": queue,
            "RALF_CONTINUATION_ROOT": str(root),
            "RALF_CONTINUATION_KIND": kind,
            "RALF_CONTINUATION_MANAGED": str(int(managed)),
            "RALF_CONTINUATION_MODE": label,
            "RALF_CONTINUATION_WINDOW": window,
        }
        with log.open("w") as output:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "from tests.temporal_continuation_worker import run; import asyncio; asyncio.run(run())",
                ],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        processes.append(process)
        for _ in range(400):
            if "TEMPORAL_CONTINUATION_READY" in log.read_text():
                return process
            assert process.poll() is None, log.read_text()
            await asyncio.sleep(0.05)
        pytest.fail(log.read_text())

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
        before = await client.get_workflow_handle(node_id).query(
            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
        )
        assert before["manifest"]["binding_protocol"] == 6
        assert before["snapshot"]["state"] == (
            "waiting_approval" if window == "approval" else "running"
        )
        actions = before["snapshot"]["actions"]
        model = next(a for a in actions if a["kind"] == "model")
        if window == "approval":
            tool = next(a for a in actions if a["kind"] == "tool")
            assert tool["arguments"] == {"quantity": 3, "price": 2}
        else:
            assert model["status"] == "received"
            assert not any(a["kind"] == "tool" for a in actions)
            assert any(
                a["kind"] == "model_adoption" and a["status"] == "executing" for a in actions
            )
            assert before["budget"]["spent"] == 1 and before["budget"]["unknown"] == 0
        raw = model["received_response"]
        assert raw["continuation"]["data"]["content"] == {"role": "model", "parts": PARTS}
        assert raw["tool_calls"] == [
            {"name": "calculate", "arguments": {"quantity": 3}, "call_id": "native-quantity"}
        ]
        if window == "approval":
            assert model["response"]["continuation_proposal"]["tool_calls"][0]["arguments"] == {
                "quantity": 3
            }
        else:
            assert model["model_receipt"]["received_response"] == raw
        pinned_model = copy.deepcopy(model)
        rows = [
            json.loads(line)
            for line in (root / "continuation-audit.jsonl").read_text().splitlines()
        ]
        assert [r["phase"] for r in rows if r["kind"] == "model"] == ["initial"]
        assert not any(r["kind"] == "tool" for r in rows)
        original_worker.kill()
        await asyncio.to_thread(original_worker.wait, timeout=5)
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
        after = await client.get_workflow_handle(node_id).query(
            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
        )
        assert after["snapshot"]["result"] == {"amount": 6}
        recorded = next(a for a in after["snapshot"]["actions"] if a["id"] == pinned_model["id"])
        if window == "approval":
            assert recorded == pinned_model
        else:
            # Receiving and adopting are distinct History phases. Adoption
            # changes status/response; the original receipt remains exact.
            assert recorded["status"] == "completed"
            for field in ("received_response", "model_receipt", "dispatch_request", "attempts"):
                assert recorded[field] == pinned_model[field]
        rows = [
            json.loads(line)
            for line in (root / "continuation-audit.jsonl").read_text().splitlines()
        ]
        assert [r["phase"] for r in rows if r["kind"] == "model"] == ["initial", "continued"]
        assert [r for r in rows if r["kind"] == "tool"] == [
            {"kind": "tool", "quantity": 3, "price": 2}
        ]
        for run_id in {original.ref.run_id, node_id}:
            await replay_temporal_history(await client.get_workflow_handle(run_id).fetch_history())
    finally:
        await host.aclose()
        for process in processes:
            if process.poll() is None:
                process.kill()
            await asyncio.to_thread(process.wait, timeout=5)
        await execution.close_context_execution(wait_timeout=2)
        await provider_client.aclose()
        await engine.aclose()
