"""Actual History/PG graph Worker; deterministic native peer, no model quality."""

import asyncio
import os

from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from tests import temporal_coding_worker_fixture as leaf


async def runtime():
    original, native, journal = await leaf.runtime(request_timeout=30)
    return (
        TemporalRuntime(
            providers=original.providers,
            tools=original.tools,
            journal=original.journal,
            binding_catalog=original.binding_catalog,
            coding_execution=True,
            coding_composition=True,
        ),
        native,
        journal,
    )


async def main():
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    if os.getenv("RALF_CODING_FAULT"):
        client = leaf.FaultClient(client, os.environ["RALF_CODING_FAULT"])
    built, _, _ = await runtime()
    worker = build_temporal_worker(
        client, task_queue=os.environ["RALF_CODING_QUEUE"], runtime=built
    )
    async with worker:
        print("CODING_GRAPH_WORKER_READY", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
