"""Process-owned Service worker; crash only during a safe context read."""

import asyncio
import os
from pathlib import Path

from ralf_agent.temporal import build_temporal_worker
from tests.temporal_knowledge_worker import runtime


async def run():
    from temporalio.client import Client

    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, store = runtime(
        Path(os.environ["RALF_SESSION_ROOT"]),
        queue,
        os.environ["RALF_SESSION_KIND"],
        os.environ["RALF_SESSION_MANAGED"] == "1",
        enable_sessions=True,
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            print("TEMPORAL_SESSION_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        store.close()
