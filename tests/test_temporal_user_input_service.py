"""Actual original Worker loss, durable input ACK loss and History replay."""

import asyncio
import copy
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from relf_agent import RunRef, Runtime, Scope
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from relf_agent.types import digest
from tests.temporal_user_input_worker import (
    FENCE_ENTERED,
    FENCE_RELEASED,
    FENCE_REQUESTED,
    runtime,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["agent", "graph", "plan", "team", "dag", "nested"])
@pytest.mark.parametrize("window", ["question", "answer-ack-lost"])
def test_actual_input_survives_process_restart_and_lost_ack(tmp_path, kind, window):
    asyncio.run(asyncio.wait_for(recover(tmp_path, kind, window), 120))


async def recover(root, kind, window):
    from temporalio.client import Client

    import relf_agent

    address, queue = os.environ["RALF_TEST_TEMPORAL_ADDRESS"], "input-" + uuid.uuid4().hex
    client = await Client.connect(address)
    execution, definition = runtime(root, kind)
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("temporal-input", queue),
        activity_timeout=4,
    )
    host, processes = Runtime.from_temporal(engine), []

    def lifecycle(row):
        value = {"queue": queue, "kind": kind, "window": window, **row}
        with (root / "input-lifecycle.jsonl").open("a") as output:
            output.write(json.dumps(value) + "\n")
        target = os.environ.get("RALF_DEV93_TEMPORAL_LIFECYCLE_FILE")
        if target:
            with Path(target).open("a") as output:
                output.write(json.dumps(value) + "\n")

    async def start(label):
        log = root / (label + ".log")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(
                [str(Path(relf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
            ),
            "RALF_TEST_TEMPORAL_ADDRESS": address,
            "RALF_TEST_TEMPORAL_QUEUE": queue,
            "RALF_INPUT_ROOT": str(root),
            "RALF_INPUT_KIND": kind,
        }
        with log.open("w") as output:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [sys.executable, "-u", "-m", "tests.temporal_user_input_worker"],
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        processes.append(process)
        lifecycle({"phase": "worker-started", "pid": process.pid, "label": label})
        async with asyncio.timeout(20):
            while "TEMPORAL_INPUT_READY" not in log.read_text():
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
        return process

    def audit():
        path = root / "input-audit.jsonl"
        return (
            []
            if not path.exists()
            else [json.loads(line) for line in path.read_text().splitlines()]
        )

    try:
        first = await start("original")
        session = await host.open_session(definition, "chat", command_id="open")
        original = await session.submit("Choose an item", command_id="turn", budget=32)
        async with asyncio.timeout(30):
            while True:
                pending = await original.pending()
                if pending:
                    item = next(p for p in pending if p["kind"] == "input")
                    break
                assert (await original.status()).state not in {"succeeded", "failed"}, (
                    await original.diagnostics()
                )
                await asyncio.sleep(0.05)
        assert (await session.status()).busy
        owner = await host.aattach(RunRef.from_dict(item["ref"]))
        before = await owner.diagnostics()
        before_audit = copy.deepcopy(audit())
        if window == "answer-ack-lost":
            # Normal control Activities remain runnable. Hold the original
            # retryable native Context before it invokes its original handler.
            (root / FENCE_REQUESTED).write_text("hold continuation")
            original_handle = engine._handle

            class LostAck:
                def __init__(self, handle):
                    self.handle = handle

                def __getattr__(self, name):
                    return getattr(self.handle, name)

                async def execute_update(self, name, request):
                    receipt = await self.handle.execute_update(name, request)
                    if request.get("payload", {}).get("kind") == "send_input":
                        lifecycle(
                            {"phase": "answer-update-committed-ack-discarded", "receipt": receipt}
                        )
                        raise ConnectionError("Discarded completed input Update response")
                    return receipt

            engine._handle = lambda run_id: LostAck(original_handle(run_id))
            try:
                with pytest.raises(ConnectionError):
                    await engine.send_input(
                        owner.ref.run_id,
                        item["pending_id"],
                        item["target_digest"],
                        "wire",
                        command_id="answer",
                    )
            finally:
                engine._handle = original_handle
            async with asyncio.timeout(15):
                while not (root / FENCE_ENTERED).exists():  # noqa: ASYNC110 -- actual subprocess fence
                    await asyncio.sleep(0.01)
            entry = json.loads((root / FENCE_ENTERED).read_text().splitlines()[0])
            assert entry["pid"] == first.pid and entry["attempt"] == 1
            assert digest(entry["request"]) == entry["request_digest"]
            history = await client.get_workflow_handle(entry["workflow_id"]).fetch_history()
            scheduled = next(
                event.activity_task_scheduled_event_attributes
                for event in history.events
                if event.HasField("activity_task_scheduled_event_attributes")
                and event.activity_task_scheduled_event_attributes.activity_id
                == entry["activity_id"]
            )
            assert scheduled.activity_type.name == entry["activity"]
            assert json.loads(scheduled.input.payloads[0].data) == entry["request"]
            lifecycle(
                {
                    "phase": "original-context-activity-entered",
                    "pid": entry["pid"],
                    "workflow_id": entry["workflow_id"],
                    "activity_id": entry["activity_id"],
                    "attempt": entry["attempt"],
                    "scheduled_event_id": next(
                        event.event_id
                        for event in history.events
                        if event.HasField("activity_task_scheduled_event_attributes")
                        and event.activity_task_scheduled_event_attributes == scheduled
                    ),
                    "request_digest": entry["request_digest"],
                }
            )
            accepted = await owner.status()
            assert accepted.state not in {"succeeded", "failed", "cancelled"}
            assert audit() == before_audit
            lifecycle(
                {
                    "phase": "pre-continuation-fence-confirmed",
                    "run_id": owner.ref.run_id,
                    "state_revision": accepted.state_revision,
                    "activity": entry["activity"],
                    "workflow_id": entry["workflow_id"],
                    "activity_id": entry["activity_id"],
                    "request_digest": entry["request_digest"],
                    "history_event_count": len(history.events),
                    "provider_audit_phases": [row["phase"] for row in before_audit],
                }
            )
        first.kill()
        await asyncio.to_thread(first.wait, timeout=5)
        assert audit() == before_audit
        lifecycle(
            {"phase": "worker-killed-and-reaped", "pid": first.pid, "returncode": first.returncode}
        )
        if window == "answer-ack-lost":
            (root / FENCE_RELEASED).write_text("original worker stopped")
        await host.aclose()
        host = Runtime.from_temporal(engine)
        await start("recovered")
        attached = await host.aattach(original.ref)
        owner = await host.aattach(RunRef.from_dict(item["ref"]))
        if window == "question":
            assert (await owner.status()).state == "waiting_input"
            assert audit() == before_audit
            assert (await owner.diagnostics()).budget == before.budget
        receipt = await owner.send_input(
            item["pending_id"], item["target_digest"], "wire", command_id="answer"
        )
        assert (
            await owner.send_input(
                item["pending_id"], item["target_digest"], "wire", command_id="answer"
            )
            == receipt
        )
        result = await attached.wait(wait_timeout=30, terminal_only=True)
        assert result.snapshot.state == "succeeded", await attached.diagnostics()
        assert result.snapshot.result == "Selected wire"
        rows = audit()
        assert [row["phase"] for row in rows] == (
            ["worker"] if kind in {"plan", "dag"} else ["question", "continued"]
        )
        recovered_session = await host.aattach_session(session.ref)
        turns = await recovered_session.turns()
        assert len(turns) == 1 and turns[0].run == original.ref
        lifecycle(
            {
                "phase": "original-run-and-turn-continued",
                "run_id": original.ref.run_id,
                "turn_command_id": turns[0].command_id,
                "input_command_id": receipt.command_id,
                "provider_audit_phases": [row["phase"] for row in rows],
            }
        )
        flow = await attached.diagnostics()
        run_ids = {
            original.ref.run_id,
            owner.ref.run_id,
            engine.command_registry_id,
            "ralf-temporal-session-" + session.ref.key.key_id,
        }
        todo = list(flow.workflow.get("children", []))
        while todo:
            child = todo.pop()
            run_ids.add(child["run_id"])
            todo.extend((await engine.diagnostics(child["run_id"])).workflow.get("children", []))
        replay_before = copy.deepcopy(rows)
        for run_id in run_ids:
            history = await client.get_workflow_handle(run_id).fetch_history()
            (root / ("history-" + digest(run_id) + ".json")).write_text(history.to_json())
            await replay_temporal_history(history)
            lifecycle(
                {
                    "phase": "history-replayed",
                    "run_id": run_id,
                    "event_count": len(history.events),
                    "audit_phases": [r["phase"] for r in replay_before],
                }
            )
        assert audit() == replay_before
    finally:
        try:
            await host.aclose(close_timeout=2)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
                lifecycle(
                    {
                        "phase": "worker-finally-reaped",
                        "pid": process.pid,
                        "returncode": process.returncode,
                    }
                )
            await execution.close_context_execution(wait_timeout=2)
            await engine.aclose()
