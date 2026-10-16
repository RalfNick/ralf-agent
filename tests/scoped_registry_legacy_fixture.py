"""Run only the original immutable basic SDK Registry, with explicit owned stop."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

import ralf_agent
from ralf_agent.temporal import _workflow_runner
from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow


async def main():
    queue, directory = sys.argv[1], Path(sys.argv[2])
    client = await Client.connect(
        os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
        namespace=os.environ["RALF_TEST_TEMPORAL_NAMESPACE"],
    )
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    worker = Worker(
        client,
        task_queue=queue,
        workflows=[TemporalCommandRegistryWorkflow],
        workflow_runner=_workflow_runner(),
    )
    async with worker:
        (directory / "ready.json").write_text(json.dumps({"package_file": ralf_agent.__file__}))
        await stop.wait()
    (directory / "closed.json").write_text(
        json.dumps(
            {
                "worker_shutdown": worker.is_shutdown and not worker.is_running,
                "package_file": ralf_agent.__file__,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
