import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ralf_agent import AgentLimitProposal, Runtime, Scope
from ralf_agent.temporal import TemporalEngine, replay_temporal_history
from tests.temporal_limits_worker import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class CustomLimits:
    identity = {"kind": "custom-service-limits", "version": "1"}

    def propose(self, spec):
        return AgentLimitProposal(max_tool_actions=0 if spec.name == "limited" else 1)


@pytest.mark.parametrize("kind", ["native", "sequence", "graph", "team", "dynamic", "nested"])
@pytest.mark.parametrize("managed", [False, True])
def test_accepted_limits_survive_worker_kill_without_policy_reexecution(tmp_path, kind, managed):
    async def run():
        from temporalio.client import Client

        import ralf_agent

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "limits-" + uuid.uuid4().hex
        execution, definition = runtime(tmp_path, queue, kind, managed)
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("temporal-limits", queue),
            activity_timeout=2,
        )
        host = Runtime.from_temporal(engine)
        processes = []

        async def start(mode):
            log = tmp_path / f"worker-{mode}.log"
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(
                    [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
                ),
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                "RALF_TEST_TEMPORAL_QUEUE": queue,
                "RALF_LIMITS_ROOT": str(tmp_path),
                "RALF_LIMITS_KIND": kind,
                "RALF_LIMITS_MANAGED": str(int(managed)),
                "RALF_LIMITS_MODE": mode,
            }
            with log.open("w") as out:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.temporal_limits_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=env,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            for _ in range(400):
                if "TEMPORAL_LIMITS_READY" in log.read_text():
                    return process
                assert process.poll() is None, log.read_text()
                await asyncio.sleep(0.05)
            pytest.fail(log.read_text())

        try:
            worker = await start("crash")
            original = await host.submit(
                definition, "task", command_id="submit-" + queue, budget=24
            )
            for _ in range(400):
                if (tmp_path / "context-ready").exists():
                    break
                assert worker.poll() is None, (tmp_path / "worker-crash.log").read_text()
                await asyncio.sleep(0.05)
            assert (tmp_path / "context-ready").exists(), await original.diagnostics()
            node_id = (tmp_path / "context-ready").read_text()
            before = await client.get_workflow_handle(node_id).query(
                "view", {"kind": "diagnostics", "scope": as_scope(engine.scope)}
            )
            assert before["limits_stages"][-1]["caps"]["max_tool_actions"] == 0
            worker.kill()
            await asyncio.to_thread(worker.wait, timeout=5)
            await host.aclose()
            host = Runtime.from_temporal(engine)
            await start("recover")
            attached = await host.aattach(original.ref)
            result = await attached.wait(wait_timeout=40, terminal_only=True)
            assert result.snapshot.state == "succeeded", await attached.diagnostics()
            rows = [
                json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()
            ]
            count = 1 if kind == "native" else 2
            assert len([r for r in rows if r["kind"] == "limits"]) == count
            assert len([r for r in rows if r["kind"] == "model"]) == count
            for run_id in {original.ref.run_id, node_id}:
                await replay_temporal_history(
                    await client.get_workflow_handle(run_id).fetch_history()
                )
        finally:
            await host.aclose()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=5)
            await engine.aclose()

    asyncio.run(run())


def as_scope(scope):
    from dataclasses import asdict

    return asdict(scope)


@pytest.mark.parametrize("mode", ["host-inherit", "host-disabled", "custom"])
@pytest.mark.parametrize("managed", [False, True])
def test_host_only_binding_and_custom_policy_reject_business_tool_dispatch(mode, managed):
    from ralf_agent import (
        AgentBindingDescriptor,
        AgentDefinition,
        AgentSpec,
        BindingCatalog,
        BindingSelection,
        FixedAgentLimits,
        ManagedContextPipeline,
        ModelResponse,
        ToolCall,
        ToolRegistry,
        ToolSpec,
    )
    from ralf_agent.temporal import build_temporal_worker
    from ralf_agent.temporal_activities import TemporalRuntime

    async def run():
        from temporalio.client import Client

        calls = []

        class Provider:
            identity = {"kind": "limits-service-batch", "version": "1"}

            async def complete(self, messages, tools):
                calls.append("model")
                return ModelResponse(tool_calls=[ToolCall("lookup", {}, "read")])

        async def handler(arguments, context):
            calls.append("tool")
            return "unsafe"

        queue = "limit-bound-" + uuid.uuid4().hex
        scope = Scope("temporal-limits", queue)
        catalog = None
        if mode == "custom":
            catalog = BindingCatalog(scope=scope)
            catalog.register("limits", "selected", "1", CustomLimits())
        choice = (
            BindingSelection.ref("selected", "1")
            if mode == "custom"
            else BindingSelection.disabled()
            if mode == "host-disabled"
            else BindingSelection.inherit()
        )
        definition = AgentDefinition(
            AgentSpec("limited", "answer", ("lookup",)), AgentBindingDescriptor(limits=choice)
        )
        tools = ToolRegistry()
        tools.register(ToolSpec("lookup", "read", {"type": "object"}), handler)
        execution = TemporalRuntime(
            providers={"default": Provider()},
            tools=tools,
            limits=FixedAgentLimits(max_tool_actions=1 if mode == "custom" else 0),
            binding_catalog=catalog,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        engine = TemporalEngine(client, task_queue=queue, release=execution.manifest, scope=scope)
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                agent_run = await host.submit(definition, "task", command_id="submit-" + queue)
                result = await agent_run.wait(wait_timeout=20, terminal_only=True)
                assert result.snapshot.state == "failed"
                assert result.snapshot.error["code"] == "agent_limit_exceeded"
                assert calls == ["model"]
                await replay_temporal_history(
                    await client.get_workflow_handle(agent_run.ref.run_id).fetch_history()
                )
        finally:
            await host.aclose()
            await engine.aclose()

    asyncio.run(run())
