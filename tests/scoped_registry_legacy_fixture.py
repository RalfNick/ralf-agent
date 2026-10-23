"""Run the original immutable SDK Registry/Parent, with explicit owned stop."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from temporalio.client import Client

import relf_agent
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime


class Provider:
    identity = {"kind": "legacy-scoped-drive", "version": "1"}

    async def complete(self, messages, tools):
        return relf_agent.ModelResponse(output="original answer")


async def main():
    queue, directory = sys.argv[1], Path(sys.argv[2])
    client = await Client.connect(
        os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
        namespace=os.environ["RALF_TEST_TEMPORAL_NAMESPACE"],
    )
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=relf_agent.ToolRegistry())
    worker = build_temporal_worker(client, task_queue=queue, runtime=runtime)
    async with worker:
        (directory / "ready.json").write_text(
            json.dumps(
                {"package_file": relf_agent.__file__, "release": runtime.orchestration_release}
            )
        )
        await stop.wait()
    (directory / "closed.json").write_text(
        json.dumps(
            {
                "worker_shutdown": worker.is_shutdown and not worker.is_running,
                "package_file": relf_agent.__file__,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
