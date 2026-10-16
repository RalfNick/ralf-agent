"""Isolated trusted Worker for real thread-timeout/end-evidence acceptance."""

import asyncio
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
    def slow(arguments, context):
        (directory / "slow-started").touch()
        try:
            while not (directory / "release-slow").exists():
                time.sleep(0.01)
            return "original slow return"
        finally:
            (directory / "slow-ended").touch()

    async def fast(arguments, context):
        (directory / "fast-returned").touch()
        return "fast return"

    tools = r.ToolRegistry()
    for name, handler in (("slow", slow), ("fast", fast)):
        tools.register(r.ToolSpec(name, name, {"type": "object"}, cost=0), handler)
    return TemporalRuntime(providers={"default": Provider()}, tools=tools)


async def main():
    queue, path, generation = sys.argv[1:]
    directory = Path(path)
    client = await Client.connect(
        os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
        namespace=os.environ["RALF_TEST_TEMPORAL_NAMESPACE"],
    )
    execution = runtime(directory)
    assert "tool_execution_protocol" not in execution.manifest
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    worker = build_temporal_worker(
        client, task_queue=queue, runtime=execution, graceful_shutdown_timeout=timedelta(seconds=1)
    )
    async with worker:
        (directory / f"ready-{generation}.json").write_text(
            json.dumps({"release": execution.orchestration_release, "package_file": r.__file__})
        )
        await stop.wait()
    (directory / f"closed-{generation}.json").write_text(
        json.dumps(
            {
                "worker_shutdown": worker.is_shutdown and not worker.is_running,
                "package_file": r.__file__,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
