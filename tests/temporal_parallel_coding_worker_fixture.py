"""Bounded original Coding children; actual History/PG, deterministic native peer."""

import asyncio
import os
from pathlib import Path

from ralf_agent.codex_runner import CodexCodingRunner
from ralf_agent.delegated_coding import register_coding_tool
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from tests import temporal_coding_worker_fixture as leaf


async def runtime():
    original, native, journal = await leaf.runtime(request_timeout=30)
    runners = [native]
    if os.getenv("RALF_CODING_TWO_RUNNERS") == "1":
        extra = CodexCodingRunner(
            Path(os.environ["RALF_CODING_ROOT"]).with_name("native-second"),
            journal=journal,
            docker_executable=os.environ["RALF_CODING_DOCKER"],
            docker_host=os.environ["RALF_CODING_HOST"],
            request_timeout=30,
        )
        register_coding_tool(original.tools, extra, name="coding_second")
        original.binding_catalog.register("runner", "second", "1", extra)
        runners.append(extra)
    built = TemporalRuntime(
        providers=original.providers,
        tools=original.tools,
        journal=original.journal,
        binding_catalog=original.binding_catalog,
        coding_execution=True,
        coding_composition=True,
    )
    return built, runners, journal


async def main():
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    built, _, _ = await runtime()
    worker = build_temporal_worker(
        client, task_queue=os.environ["RALF_CODING_QUEUE"], runtime=built
    )
    async with worker:
        print("PARALLEL_CODING_WORKER_READY", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
