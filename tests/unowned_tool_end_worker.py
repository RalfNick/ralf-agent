"""Isolated trusted Worker for real thread-timeout/end-evidence acceptance."""

import asyncio
import importlib.util
import json
import os
import signal
import sys
import time
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from temporalio.client import Client

import ralf_agent as r
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime


async def public_read_run(engine, client, directory):
    """Seed and verify exactly this old-public Worker using its matching SDK."""
    from ralf_agent.temporal import replay_temporal_history

    try:
        receipt = await engine.submit(
            r.AgentSpec("reader", "Read", tools=("slow", "fast"), max_decisions=2),
            "task",
            command_id="original",
            budget=32,
        )
        (directory / "public-submitted.json").write_text(json.dumps(asdict(receipt)))
        async with asyncio.timeout(25):
            while True:
                diagnostic = await engine.diagnostics(receipt.run_id)
                if diagnostic.snapshot.state == "succeeded" and diagnostic.workflow["quiescent"]:
                    break
                await asyncio.sleep(0.02)
            while True:
                registry = await engine.deployment_diagnostics()
                if registry["counts"]["held_root_runs"] == 0:
                    break
                await asyncio.sleep(0.02)
        closure = await engine._view(receipt.run_id, "deployment_closure")
        assert closure["seal"] is not None
        for label, target in (("run", receipt.run_id), ("registry", engine.command_registry_id)):
            history = await client.get_workflow_handle(target).fetch_history()
            (directory / f"public-original-{label}-history.json").write_text(history.to_json())
            await replay_temporal_history(history, namespace=client.namespace)
        (directory / "public-original-evidence.json").write_text(
            json.dumps(
                {
                    "run_id": receipt.run_id,
                    "registry_id": engine.command_registry_id,
                    "state": diagnostic.snapshot.state,
                    "quiescent": diagnostic.workflow["quiescent"],
                    "actions": diagnostic.snapshot.actions,
                    "tool_executions": diagnostic.workflow["tool_executions"],
                    "closure": closure,
                    "registry": registry,
                    "matching_old_worker_replayed_run_and_registry": True,
                    "package_file": r.__file__,
                }
            )
        )
    except BaseException as exc:
        (directory / "public-task-error.json").write_text(json.dumps({"type": type(exc).__name__}))
        raise


class Provider:
    identity = {"kind": "unowned-tool-end-probe", "version": "1"}

    async def complete(self, messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return r.ModelResponse(tool_calls=(r.ToolCall("slow", {}), r.ToolCall("fast", {})))
        return r.ModelResponse(output="done")


def runtime(directory, queue=None):
    owned = os.environ.get("RALF_TEST_END_OWNER") == "1"
    public = os.environ.get("RALF_TEST_END_PUBLIC") == "1"
    options = {"tool_execution": r.ToolExecutionOwner(version="end-compat-1")} if owned else {}
    if public:
        from ralf_agent.governance import DeploymentAdmissionPolicy

        assert owned and queue
        options["admission_policy"] = DeploymentAdmissionPolicy(queue)

    def record_call(name):
        if owned:
            with (directory / "tool-calls.jsonl").open("a") as stream:
                stream.write(json.dumps({"tool": name}) + "\n")

    def slow(arguments, context):
        record_call("slow")
        (directory / "slow-started").touch()
        try:
            while not (directory / "release-slow").exists():
                time.sleep(0.01)
            return "original slow return"
        finally:
            (directory / "slow-ended").touch()

    async def fast(arguments, context):
        record_call("fast")
        (directory / "fast-returned").touch()
        return "fast return"

    tools = r.ToolRegistry()
    for name, handler in (("slow", slow), ("fast", fast)):
        tools.register(r.ToolSpec(name, name, {"type": "object"}, cost=0), handler)
    return TemporalRuntime(
        providers={"default": Provider()},
        tools=tools,
        **options,
    )


async def main():
    queue, path, generation = sys.argv[1:]
    directory = Path(path)
    client = await Client.connect(
        os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
        namespace=os.environ["RALF_TEST_TEMPORAL_NAMESPACE"],
    )
    execution = runtime(directory, queue)
    owned = os.environ.get("RALF_TEST_END_OWNER") == "1"
    public = os.environ.get("RALF_TEST_END_PUBLIC") == "1"
    assert ("tool_execution_protocol" in execution.manifest) is owned
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    worker = build_temporal_worker(
        client, task_queue=queue, runtime=execution, graceful_shutdown_timeout=timedelta(seconds=1)
    )
    async with worker:
        ready = {"release": execution.orchestration_release, "package_file": r.__file__}
        public_engine = public_task = None
        if owned:
            ready["end_transport_available"] = (
                importlib.util.find_spec("ralf_agent.temporal_execution_end_transport") is not None
            )
        if public:
            from ralf_agent.temporal import TemporalEngine
            from ralf_agent.temporal_deployment_admission import root_run_id

            scope = r.Scope("execution-end-legacy", queue)
            public_engine = TemporalEngine(
                client,
                task_queue=queue,
                release=execution.orchestration_release,
                scope=scope,
                activity_timeout=30,
            )
            ready.update(
                run_id=root_run_id(queue, asdict(scope), "original"),
                registry_id=public_engine.command_registry_id,
            )
            ready["lifecycle_transport_available"] = (
                importlib.util.find_spec("ralf_agent.temporal_deployment_lifecycle_transport")
                is not None
            )
            public_task = asyncio.create_task(public_read_run(public_engine, client, directory))
        (directory / f"ready-{generation}.json").write_text(json.dumps(ready))
        await stop.wait()
        if public:
            errors = []
            try:
                await public_task
            except BaseException as exc:
                errors.append(exc)
            try:
                assert await execution.wait_context_executions(wait_timeout=5)
                await execution.close_context_execution(wait_timeout=5)
                await execution.tool_execution.aclose(wait_timeout=5)
            except BaseException as exc:
                errors.append(exc)
            from ralf_agent.temporal_deployment_release import check_owner

            try:
                assert await check_owner(execution).wait(wait_timeout=5)
                await execution.close_deployment_execution(wait_timeout=5)
            except BaseException as exc:
                errors.append(exc)
            try:
                await public_engine.aclose()
            except BaseException as exc:
                errors.append(exc)
            if errors:
                raise BaseExceptionGroup("Old public read Run and owned close", errors)
        elif owned:
            assert await execution.wait_context_executions(wait_timeout=5)
            await execution.close_context_execution(wait_timeout=5)
            await execution.tool_execution.aclose(wait_timeout=5)
    closed = {
        "worker_shutdown": worker.is_shutdown and not worker.is_running,
        "package_file": r.__file__,
    }
    if owned:
        closed.update(tool_owner_drained=True, tool_owner_closed=True)
    if public:
        closed["public_owner_closed"] = True
    (directory / f"closed-{generation}.json").write_text(json.dumps(closed))


if __name__ == "__main__":
    asyncio.run(main())
