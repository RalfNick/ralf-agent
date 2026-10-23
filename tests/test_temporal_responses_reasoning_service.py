"""Actual process loss and History replay; HTTP fixtures prove protocol only."""

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
from relf_agent.temporal_session_state import workflow_id
from tests.temporal_responses_reasoning_worker import FINAL_OUTPUT, NATIVE_OUTPUT, runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "graph"])
@pytest.mark.parametrize("window", ["approval", "receipt"])
def test_responses_original_receipt_survives_worker_loss_duplicate_approval_and_history_replay(
    tmp_path, kind, window
):
    asyncio.run(asyncio.wait_for(recover(tmp_path, kind, window), 120))


def test_final_session_receipt_recovers_without_dispatch_and_turn_two_echoes_original_items(
    tmp_path,
):
    asyncio.run(asyncio.wait_for(recover(tmp_path, "native", "final-session"), 120))


async def recover(root, kind, window):
    from temporalio.client import Client

    import relf_agent

    address, session = os.environ["RALF_TEST_TEMPORAL_ADDRESS"], window == "final-session"
    client = await Client.connect(address)
    queue = "responses-reasoning-" + uuid.uuid4().hex
    execution, definition, provider_client, backend = runtime(root, kind, session=session)
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("temporal-responses-reasoning", queue),
        activity_timeout=3,
    )
    host, processes, entry = Runtime.from_temporal(engine), [], None

    def lifecycle(row):
        with (root / "responses-worker-lifecycle.jsonl").open("a") as output:
            output.write(
                json.dumps(
                    {"address": address, "queue": queue, "kind": kind, "window": window, **row}
                )
                + "\n"
            )

    async def start(mode):
        log = root / ("responses-worker-" + mode + ".log")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(
                [str(Path(relf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
            ),
            "RALF_TEST_TEMPORAL_ADDRESS": address,
            "RALF_TEST_TEMPORAL_QUEUE": queue,
            "RALF_RESPONSES_WORKER_ROOT": str(root),
            "RALF_RESPONSES_WORKER_KIND": kind,
            "RALF_RESPONSES_WORKER_MODE": mode,
            "RALF_RESPONSES_WORKER_WINDOW": window,
        }
        with log.open("w") as output:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "from tests.temporal_responses_reasoning_worker import run; import asyncio; asyncio.run(run())",
                ],
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        processes.append(process)
        lifecycle({"phase": "worker-started", "mode": mode, "pid": process.pid})
        async with asyncio.timeout(25):
            while "TEMPORAL_RESPONSES_REASONING_READY" not in log.read_text():  # noqa: ASYNC110 -- actual process readiness
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
        return process

    def audit():
        return [
            json.loads(line) for line in (root / "responses-audit.jsonl").read_text().splitlines()
        ]

    async def diagnostics(run_id):
        return await client.get_workflow_handle(run_id).query(
            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
        )

    try:
        original_worker = await start("original")
        if session:
            entry = await host.open_session(definition, "reasoning", command_id="open")
            original = await entry.submit("turn-one", command_id="turn-one", budget=16)
        else:
            original = await host.submit(
                definition, "Three units", command_id="submit-" + queue, budget=16
            )
        item = None
        async with asyncio.timeout(30):
            while True:
                if window != "approval":
                    ready = root / "receipt-ready"
                    if ready.exists():
                        node_id = ready.read_text()
                        break
                else:
                    pending = await original.pending()
                    if pending:
                        item, node_id = pending[0], pending[0]["ref"]["run_id"]
                        break
                assert (await original.status()).state not in {"failed", "succeeded"}, (
                    await original.diagnostics()
                )
                assert original_worker.poll() is None, (
                    root / "responses-worker-original.log"
                ).read_text()
                await asyncio.sleep(0.05)
        before = await diagnostics(node_id)
        lifecycle(
            {"phase": "checkpoint", "root_run_id": original.ref.run_id, "node_run_id": node_id}
        )
        assert before["snapshot"]["state"] == (
            "waiting_approval" if window == "approval" else "running"
        )
        actions = before["snapshot"]["actions"]
        models = [action for action in actions if action["kind"] == "model"]
        model = models[-1] if session else models[0]
        raw = model["received_response"]
        assert raw["continuation"]["protocol"] == "openai-responses-reasoning-v1"
        assert raw["continuation"]["data"] == {"output": FINAL_OUTPUT if session else NATIVE_OUTPUT}
        if session:
            assert raw["output"] == ' { "amount" : 6 } ' and raw["tool_calls"] == []
            assert len(models) == 2
            assert (
                len(
                    [
                        action
                        for action in actions
                        if action["kind"] == "tool" and action["status"] == "completed"
                    ]
                )
                == 1
            )
        else:
            assert raw["output"] is None
            assert raw["tool_calls"] == [
                {
                    "name": "calculate",
                    "arguments": {"quantity": 3},
                    "call_id": "native-call-temporal-fixture-task-tool-1",
                }
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
            if not session:
                assert not any(action["kind"] == "tool" for action in actions)
            assert any(
                action["kind"] == "model_adoption" and action["status"] == "executing"
                for action in actions
            )
            assert (
                before["budget"]["spent"] == (2 if session else 1)
                and before["budget"]["unknown"] == 0
            )
        pinned_model = copy.deepcopy(model)
        assert [row["phase"] for row in audit() if row["kind"] == "model"] == (
            ["initial", "final"] if session else ["initial"]
        )
        assert len([row for row in audit() if row["kind"] == "tool"]) == int(session)
        original_worker.kill()
        await asyncio.to_thread(original_worker.wait, timeout=5)
        assert original_worker.returncode is not None
        lifecycle(
            {
                "phase": "worker-killed",
                "mode": "original",
                "pid": original_worker.pid,
                "returncode": original_worker.returncode,
            }
        )
        await host.aclose()
        host = Runtime.from_temporal(engine)
        recovered_worker = await start("recover")
        assert recovered_worker.pid != original_worker.pid
        attached = await host.aattach(original.ref)
        if session:
            entry = await host.aattach_session(entry.ref)
        else:
            if item is None:
                async with asyncio.timeout(30):
                    while not (pending := await attached.pending()):  # noqa: ASYNC110 -- original approval admission
                        assert (await attached.status()).state not in {"failed", "succeeded"}, (
                            await attached.diagnostics()
                        )
                        await asyncio.sleep(0.05)
                item = pending[0]
            owner = await host.aattach(RunRef.from_dict(item["ref"]))
            receipt = await owner.approve(
                item["action_id"], item["digest"], command_id="approved-once"
            )
            assert (
                await owner.approve(item["action_id"], item["digest"], command_id="approved-once")
                == receipt
            )
        result = await attached.wait(wait_timeout=40, terminal_only=True)
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
        assert finals[0]["received_response"]["output"] == ' { "amount" : 6 } '
        final_continuation = finals[0]["received_response"]["continuation"]
        assert final_continuation["data"] == {"output": FINAL_OUTPUT}
        assert final_continuation["owner_digest"] == raw["continuation"]["owner_digest"]
        assert [row["phase"] for row in audit() if row["kind"] == "model"] == ["initial", "final"]
        assert [row for row in audit() if row["kind"] == "tool"] == [
            {"kind": "tool", "quantity": 3, "price": 2}
        ]
        run_ids = {original.ref.run_id, node_id}
        if session:
            async with asyncio.timeout(15):
                while (await entry.status()).busy:  # noqa: ASYNC110 -- original Session publication
                    await asyncio.sleep(0.05)
            assert len(after["native_history_episodes"]) == 1
            second = await entry.submit("turn-two", command_id="turn-two", budget=16)
            assert (
                await second.wait(wait_timeout=30, terminal_only=True)
            ).snapshot.state == "succeeded", await second.diagnostics()
            rows = [row for row in audit() if row["kind"] == "model"]
            actual = [
                item
                for item in rows[2]["body"]["input"]
                if not (
                    item.get("role") == "user" and item["content"].startswith("Reference memory;")
                )
            ]
            assert actual[:2] == rows[0]["body"]["input"][:2]
            assert actual[2:5] == NATIVE_OUTPUT
            assert actual[5] == {
                "type": "function_call_output",
                "call_id": "native-call-temporal-fixture-task-tool-1",
                "output": '{"amount":6}',
            }
            assert actual[6:9] == FINAL_OUTPUT
            assert actual[9] == {"role": "user", "content": "turn-two"}
            assert len(rows) == 4 and len([row for row in audit() if row["kind"] == "tool"]) == 2
            assert (await diagnostics(node_id))["snapshot"]["actions"] == after["snapshot"][
                "actions"
            ]
            run_ids.update((second.ref.run_id, workflow_id(entry.ref.key)))
        original_audit = copy.deepcopy(audit())
        for run_id in run_ids:
            await replay_temporal_history(await client.get_workflow_handle(run_id).fetch_history())
            lifecycle({"phase": "history-replayed", "run_id": run_id})
        assert audit() == original_audit
        recovered_worker.terminate()
        await asyncio.to_thread(recovered_worker.wait, timeout=10)
        assert recovered_worker.returncode == 0, (root / "responses-worker-recover.log").read_text()
        assert (root / "worker-closed-recover").read_text() == "closed"
        lifecycle(
            {
                "phase": "worker-stopped",
                "mode": "recover",
                "pid": recovered_worker.pid,
                "returncode": recovered_worker.returncode,
            }
        )
    finally:
        await host.aclose()
        for process in processes:
            if process.poll() is None:
                process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            lifecycle(
                {"phase": "worker-reaped", "pid": process.pid, "returncode": process.returncode}
            )
        await execution.close_context_execution(wait_timeout=5)
        await execution.close_session_execution(wait_timeout=5)
        await provider_client.aclose()
        if backend is not None:
            backend.store.close()
        await engine.aclose()
