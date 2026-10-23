"""Separate actual Worker built only through declared Temporal assembly."""

import asyncio
import json
import os
import sqlite3
from pathlib import Path

from relf_agent import (
    ComponentRegistry,
    ModelResponse,
    Scope,
    TemporalProfileCatalog,
    TemporalRuntimeBuilder,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)


class Provider:
    identity = {"kind": "profile-service-offline", "version": "1"}

    def __init__(self, root, mode="plain"):
        self.root = Path(root)
        self.mode = mode

    async def complete(self, messages, tools):
        with sqlite3.connect(self.root / "audit.sqlite") as connection:
            connection.execute("INSERT INTO calls VALUES ('model')")
        if self.mode == "approval" and not any(m.get("role") == "tool" for m in messages):
            return ModelResponse(tool_calls=[ToolCall("query", {}, call_id="query")])
        return ModelResponse(output="answer")

    async def aclose(self):
        with sqlite3.connect(self.root / "audit.sqlite") as connection:
            connection.execute("INSERT INTO calls VALUES ('resource-close')")


async def assembly(root, queue):
    root = Path(root)
    with sqlite3.connect(root / "audit.sqlite") as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")
    registry = ComponentRegistry()

    def factory(config, context):
        assert context.store is None
        return context.own_async(Provider(root, config.get("mode", "plain")))

    registry.register("provider", "service-offline", factory)

    def tools_factory(config, context):
        tools = ToolRegistry()

        def query(arguments, invocation):
            with sqlite3.connect(root / "audit.sqlite") as connection:
                connection.execute("INSERT INTO calls VALUES ('query')")
            return "observed"

        tools.register(
            ToolSpec(
                "query",
                "Read evidence",
                {"type": "object"},
                effect="read_only",
                requires_approval=True,
            ),
            query,
        )
        return tools

    registry.register("tools", "service-read", tools_factory)
    catalog = TemporalProfileCatalog.from_file(root / "profile.json")
    return await TemporalRuntimeBuilder(registry, base_dir=root).abuild(
        catalog.default_profile, scope=Scope("profile-service", queue)
    )


async def run():
    from temporalio.client import Client

    root = Path(os.environ["RALF_PROFILE_ROOT"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    assembled = await assembly(root, queue)
    try:
        (root / ("release-" + os.environ["RALF_PROFILE_WORKER_ID"] + ".json")).write_text(
            json.dumps(assembled.release, sort_keys=True)
        )
        await assembled.start_worker(client, task_queue=queue)
        print("PROFILE_WORKER_READY", flush=True)
        while not (root / ("stop-" + os.environ["RALF_PROFILE_WORKER_ID"])).exists():  # noqa: ASYNC110 -- cross-process stop file
            await asyncio.sleep(0.05)
    finally:
        await assembled.aclose(wait_timeout=20)
        print("PROFILE_WORKER_CLOSED", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
