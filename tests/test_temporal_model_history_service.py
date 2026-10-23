"""Actual Worker loss after final receipt/verdict, plus original History replay."""

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

from relf_agent import Runtime, Scope
from relf_agent.temporal import TemporalEngine, replay_temporal_history
from relf_agent.types import digest
from tests.temporal_model_history_worker import (
    FEEDBACK,
    FIRST_PARTS,
    FIRST_TEXT,
    SECOND_PARTS,
    SECOND_TEXT,
    runtime,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "graph"])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("window", ["receipt", "verified"])
def test_complete_final_history_survives_worker_loss_without_model_or_assistant_replay(
    tmp_path, kind, managed, window
):
    asyncio.run(asyncio.wait_for(recover(tmp_path, kind, managed, window), 120))


async def recover(root, kind, managed, window):
    from temporalio.client import Client

    import relf_agent

    address = os.environ["RALF_TEST_TEMPORAL_ADDRESS"]
    client = await Client.connect(address)
    queue = "model-history-" + uuid.uuid4().hex
    execution, definition, provider_client = runtime(root, kind, managed)
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("temporal-model-history", queue),
        activity_timeout=3,
    )
    host = Runtime.from_temporal(engine)
    processes = []

    async def start(mode):
        log = root / f"worker-{mode}.log"
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.pathsep.join(
                [str(Path(relf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
            ),
            "RALF_TEST_TEMPORAL_ADDRESS": address,
            "RALF_TEST_TEMPORAL_QUEUE": queue,
            "RALF_HISTORY_ROOT": str(root),
            "RALF_HISTORY_KIND": kind,
            "RALF_HISTORY_MANAGED": str(int(managed)),
            "RALF_HISTORY_MODE": mode,
            "RALF_HISTORY_WINDOW": window,
        }
        with log.open("w") as output:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "from tests.temporal_model_history_worker import run; import asyncio; asyncio.run(run())",
                ],
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        processes.append(process)
        async with asyncio.timeout(20):
            while "TEMPORAL_MODEL_HISTORY_READY" not in log.read_text():  # noqa: ASYNC110 -- process readiness
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
        return process

    def audit_rows():
        return [
            json.loads(line) for line in (root / "history-audit.jsonl").read_text().splitlines()
        ]

    async def inspect(run_id):
        return await client.get_workflow_handle(run_id).query(
            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
        )

    async def scheduled_requests(run_id):
        history = await client.get_workflow_handle(run_id).fetch_history()
        requests = []
        for event in history.events:
            if event.HasField("activity_task_scheduled_event_attributes"):
                attributes = event.activity_task_scheduled_event_attributes
                values = await client.data_converter.decode(attributes.input.payloads)
                assert len(values) == 1 and isinstance(values[0], dict)
                requests.append(values[0])
        return requests

    try:
        original_worker = await start("original")
        original = await host.submit(
            definition, "Question", command_id="submit-" + queue, budget=16
        )
        ready = root / "window-ready"
        async with asyncio.timeout(30):
            while not ready.exists():  # noqa: ASYNC110 -- actual persisted fault window
                assert original_worker.poll() is None, (root / "worker-original.log").read_text()
                assert (await original.status()).state not in {"failed", "succeeded"}, (
                    await original.diagnostics()
                )
                await asyncio.sleep(0.05)
        node_id = ready.read_text()
        before = await inspect(node_id)
        assert before["manifest"]["binding_protocol"] == 7
        assert before["manifest"]["model_history_protocol"] == 1
        assert before["snapshot"]["state"] == "running"
        actions = before["snapshot"]["actions"]
        first_model = next(action for action in actions if action["kind"] == "model")
        raw = first_model["received_response"]
        assert raw["output"] == FIRST_TEXT and raw["tool_calls"] == []
        assert raw["continuation"]["data"]["content"] == {"role": "model", "parts": FIRST_PARTS}
        assert first_model["model_receipt"]["received_response"] == raw
        assert before["budget"]["spent"] == 1 and before["budget"]["unknown"] == 0
        if window == "receipt":
            assert first_model["status"] == "received"
            assert not any(action["kind"] == "agent_completion" for action in actions)
        else:
            assert first_model["status"] == "completed"
            original_contexts = [
                request
                for request in await scheduled_requests(node_id)
                if request.get("phase") == ("plan" if managed else "context")
                and any(
                    message.get("content") == FEEDBACK for message in request.get("messages", [])
                )
            ]
            assert len(original_contexts) == 1
            original_context = original_contexts[0]
            context_action = next(
                action for action in actions if action["id"] == original_context["action_id"]
            )
            assert context_action["request_digest"] == digest(original_context)
            assistants = [
                message
                for message in original_context["messages"]
                if message["role"] == "assistant"
            ]
            assert assistants == [
                {
                    "role": "assistant",
                    "content": FIRST_TEXT,
                    "tool_calls": [],
                    "model_continuation": raw["continuation"],
                }
            ]
            assert original_context["messages"][-1] == {"role": "user", "content": FEEDBACK}
            assert first_model["completion_verification"]["verdict"]["status"] == "retry"
            assert first_model["completion_verification"]["request"]["output"] == {"answer": 42}
        saved_model = copy.deepcopy(first_model)
        assert [row["phase"] for row in audit_rows()] == ["initial"]
        original_worker.kill()
        await asyncio.to_thread(original_worker.wait, timeout=5)
        assert original_worker.returncode is not None
        assert [row["phase"] for row in audit_rows()] == ["initial"]
        await host.aclose()
        host = Runtime.from_temporal(engine)
        recovered_worker = await start("recover")
        attached = await host.aattach(original.ref)
        async with asyncio.timeout(35):
            while True:
                done = await attached.wait(wait_timeout=0.2, terminal_only=True)
                assert recovered_worker.poll() is None, (root / "worker-recover.log").read_text()
                if done.snapshot.state in {"succeeded", "failed"}:
                    break
        assert done.snapshot.state == "succeeded", await attached.diagnostics()
        after = await inspect(node_id)
        assert after["snapshot"]["result"] == {"answer": 43}
        models = [action for action in after["snapshot"]["actions"] if action["kind"] == "model"]
        assert len(models) == 2 and all(action["status"] == "completed" for action in models)
        for name in ("received_response", "model_receipt", "dispatch_request", "attempts"):
            assert models[0][name] == saved_model[name]
        assert [row["phase"] for row in audit_rows()] == ["initial", "continued"]
        assert after["budget"]["spent"] == 2 and after["budget"]["unknown"] == 0
        second_request = models[1]["dispatch_request"]
        assistants = [
            message for message in second_request["messages"] if message["role"] == "assistant"
        ]
        assert len(assistants) == 1
        assert assistants[0]["content"] == FIRST_TEXT
        assert assistants[0]["model_continuation"] == raw["continuation"]
        assert second_request["messages"][-1] == {"role": "user", "content": FEEDBACK}
        assert models[1]["received_response"]["output"] == SECOND_TEXT
        assert models[1]["received_response"]["continuation"]["data"]["content"] == {
            "role": "model",
            "parts": SECOND_PARTS,
        }
        events = await client.get_workflow_handle(node_id).query(
            "view", {"kind": "events", "scope": asdict(engine.scope), "after": 0, "limit": 1000}
        )
        assert [
            event["data"]["action_id"] for event in events if event["kind"] == "decision_adopted"
        ] == [model["id"] for model in models]
        for run_id in {original.ref.run_id, node_id}:
            await replay_temporal_history(await client.get_workflow_handle(run_id).fetch_history())
        recovered_worker.terminate()
        await asyncio.to_thread(recovered_worker.wait, timeout=10)
        assert recovered_worker.returncode == 0, (root / "worker-recover.log").read_text()
        assert (root / "worker-closed-recover").read_text() == "closed"
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
        await execution.close_context_execution(wait_timeout=2)
        await provider_client.aclose()
        await engine.aclose()
