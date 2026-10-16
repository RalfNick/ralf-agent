"""Isolated trusted Worker for real thread-timeout/end-evidence acceptance."""

import asyncio
import importlib.util
import json
import os
import signal
import sys
import time
from datetime import timedelta
from pathlib import Path

from temporalio.client import Client

import ralf_agent as r
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime


class Provider:
    identity = {"kind": "unowned-tool-end-probe", "version": "1"}

    async def complete(self, messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return r.ModelResponse(tool_calls=(r.ToolCall("slow", {}), r.ToolCall("fast", {})))
        return r.ModelResponse(output="done")


def runtime(directory):
    owned = os.environ.get("RALF_TEST_END_OWNER") == "1"

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
        **({"tool_execution": r.ToolExecutionOwner(version="end-compat-1")} if owned else {}),
    )


async def main():
    queue, path, generation = sys.argv[1:]
    directory = Path(path)
    client = await Client.connect(
        os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
        namespace=os.environ["RALF_TEST_TEMPORAL_NAMESPACE"],
    )
    execution = runtime(directory)
    owned = os.environ.get("RALF_TEST_END_OWNER") == "1"
    assert ("tool_execution_protocol" in execution.manifest) is owned
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    worker = build_temporal_worker(
        client, task_queue=queue, runtime=execution, graceful_shutdown_timeout=timedelta(seconds=1)
    )
    async with worker:
        ready = {"release": execution.orchestration_release, "package_file": r.__file__}
        if owned:
            ready["end_transport_available"] = (
                importlib.util.find_spec("ralf_agent.temporal_execution_end_transport") is not None
            )
        (directory / f"ready-{generation}.json").write_text(json.dumps(ready))
        await stop.wait()
        if owned:
            assert await execution.wait_context_executions(wait_timeout=5)
            await execution.close_context_execution(wait_timeout=5)
            await execution.tool_execution.aclose(wait_timeout=5)
    closed = {
        "worker_shutdown": worker.is_shutdown and not worker.is_running,
        "package_file": r.__file__,
    }
    if owned:
        closed.update(tool_owner_drained=True, tool_owner_closed=True)
    (directory / f"closed-{generation}.json").write_text(json.dumps(closed))


if __name__ == "__main__":
    asyncio.run(main())
