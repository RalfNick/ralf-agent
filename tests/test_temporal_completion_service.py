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
from tests.temporal_completion_worker import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "sequence", "graph", "team", "dynamic", "nested"])
@pytest.mark.parametrize("managed", [False, True])
def test_verification_is_not_repeated_after_real_worker_loss(tmp_path, kind, managed):
    asyncio.run(recover(tmp_path, kind, managed, "accept"))


@pytest.mark.parametrize("managed", [False, True])
def test_retry_feedback_and_verdict_survive_real_worker_loss(tmp_path, managed):
    asyncio.run(recover(tmp_path, "native", managed, "retry"))


async def recover(tmp_path, kind, managed, window):
    from dataclasses import asdict

    from temporalio.client import Client

    import relf_agent

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    queue = "completion-" + uuid.uuid4().hex
    execution, definition, store, memory = runtime(tmp_path, queue, kind, managed)
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=Scope("temporal-completion", queue),
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
            "RALF_COMPLETION_ROOT": str(tmp_path),
            "RALF_COMPLETION_KIND": kind,
            "RALF_COMPLETION_MANAGED": str(int(managed)),
            "RALF_COMPLETION_MODE": mode,
            "RALF_COMPLETION_WINDOW": window,
        }
        with log.open("w") as out:
            process = await asyncio.to_thread(
                subprocess.Popen,
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "from tests.temporal_completion_worker import run; import asyncio; asyncio.run(run())",
                ],
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        processes.append(process)
        for _ in range(400):
            if "TEMPORAL_COMPLETION_READY" in log.read_text():
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
        await drive_to_read(original)
        node_id = (tmp_path / "read-ready").read_text()
        before = await client.get_workflow_handle(node_id).query(
            "view", {"kind": "diagnostics", "scope": asdict(engine.scope)}
        )
        assert before["completion_stages"][-1]["verdict"]["status"] == window
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
        assert len([r for r in rows if r["kind"] == "model"]) == count * 3
        assert len([r for r in rows if r["kind"] == "tool"]) == count
        assert [r["status"] for r in rows if r["kind"] == "verify"] == ["retry", "accept"] * count
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


@pytest.mark.parametrize("mode", ["reject", "retry-limit", "disabled-schema"])
def test_actual_host_verifier_rejection_limits_and_schema_are_authoritative(mode):
    from relf_agent import (
        AgentBindingDescriptor,
        AgentDefinition,
        AgentSpec,
        BindingSelection,
        ToolRegistry,
    )
    from relf_agent.temporal import build_temporal_worker
    from relf_agent.temporal_activities import TemporalRuntime
    from tests.test_temporal_completion import Provider, Verifier

    async def run():
        from temporalio.client import Client

        queue = "completion-negative-" + uuid.uuid4().hex
        provider = Provider()
        verifier = Verifier("retry" if mode == "retry-limit" else "reject")
        execution = TemporalRuntime(
            providers={"default": provider}, tools=ToolRegistry(), verifier=verifier
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.manifest,
            scope=Scope("completion-negative", queue),
        )
        host = Runtime.from_temporal(engine)
        spec = AgentSpec(
            "a",
            "answer",
            max_decisions=2,
            output_schema={"type": "string"} if mode == "disabled-schema" else None,
        )
        definition = AgentDefinition(
            spec,
            AgentBindingDescriptor(
                verifier=BindingSelection.disabled()
                if mode == "disabled-schema"
                else BindingSelection.inherit()
            ),
        )
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                agent_run = await host.submit(
                    definition, {"target": "demo"}, command_id="submit-" + queue
                )
                result = await agent_run.wait(wait_timeout=20, terminal_only=True)
                expected = {
                    "reject": "completion_rejected",
                    "retry-limit": "decision_limit",
                    "disabled-schema": "validation_error",
                }[mode]
                assert (
                    result.snapshot.state == "failed" and result.snapshot.error["code"] == expected
                )
                assert len(provider.calls) == (2 if mode == "retry-limit" else 1)
                assert len(verifier.calls) == (
                    0 if mode == "disabled-schema" else 2 if mode == "retry-limit" else 1
                )
                stages = await engine.completion_stages(agent_run.ref.run_id)
                assert len(stages) == (
                    0 if mode == "disabled-schema" else 2 if mode == "retry-limit" else 1
                )
                assert len(provider.calls) == (2 if mode == "retry-limit" else 1)
                await replay_temporal_history(
                    await client.get_workflow_handle(agent_run.ref.run_id).fetch_history()
                )
        finally:
            await host.aclose()
            await engine.aclose()

    asyncio.run(run())


def test_actual_cancelled_verification_keeps_session_busy_until_activity_returns():
    from relf_agent import AgentSpec, ToolRegistry
    from relf_agent.temporal import build_temporal_worker
    from relf_agent.temporal_activities import TemporalRuntime
    from tests.test_temporal_completion import Provider, Verifier

    async def run():
        from temporalio.client import Client

        gate, started = asyncio.Event(), asyncio.Event()

        class Gated(TemporalRuntime):
            async def verify_completion(self, request):
                started.set()
                await gate.wait()
                return await super().verify_completion(request)

        queue = "completion-session-cancel-" + uuid.uuid4().hex
        execution = Gated(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            verifier=Verifier(),
            enable_sessions=True,
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.manifest,
            scope=Scope("completion-session", queue),
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                try:
                    session = await host.open_session(
                        AgentSpec("a", "answer"), "chat", command_id="open-" + queue
                    )
                    agent_run = await session.submit({"target": "demo"}, command_id="turn-" + queue)
                    await asyncio.wait_for(started.wait(), 10)
                    await agent_run.cancel(command_id="cancel-" + queue)
                    assert (await agent_run.status()).state == "cancelled"
                    assert (await session.status()).busy
                    gate.set()
                    for _ in range(200):
                        if not (await session.status()).busy:
                            break
                        await asyncio.sleep(0.05)
                    assert not (await session.status()).busy
                    info = await engine.diagnostics(agent_run.ref.run_id)
                    assert (
                        info.workflow["quiescent"] and not info.workflow["unknown_remote_execution"]
                    )
                    assert (await agent_run.status()).result is None
                    await replay_temporal_history(
                        await client.get_workflow_handle(agent_run.ref.run_id).fetch_history()
                    )
                finally:
                    gate.set()
        finally:
            await host.aclose()
            await engine.aclose()

    asyncio.run(run())
