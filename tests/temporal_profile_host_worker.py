"""Independent hosted versions; one qualified module identity in every process."""

import asyncio
import json
import os
import sqlite3
from contextvars import ContextVar
from pathlib import Path

from ralf_agent import (
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
    def __init__(self, root, label):
        self.root, self.label = root, label

    @property
    def identity(self):
        return {"kind": "host-service-offline", "version": "1", "label": self.label}

    async def complete(self, messages, tools):
        with sqlite3.connect(self.root / "audit.sqlite") as connection:
            connection.execute("INSERT INTO calls VALUES ('model', ?)", (self.label,))
        if not any(m.get("role") == "tool" for m in messages):
            return ModelResponse(tool_calls=[ToolCall("change", {}, call_id="change")])
        return ModelResponse(output="answer-" + self.label)

    async def aclose(self):
        with sqlite3.connect(self.root / "audit.sqlite") as connection:
            connection.execute("INSERT INTO calls VALUES ('provider-closed', ?)", (self.label,))


def change(arguments, context):
    root = Path(context_metadata_root.get())
    with sqlite3.connect(root / "audit.sqlite") as connection:
        connection.execute("INSERT INTO calls VALUES ('tool', ?)", (context.effect_key,))
        connection.execute(
            "INSERT INTO effects VALUES (?) ON CONFLICT DO NOTHING", (context.effect_key,)
        )
    return "applied"


# tools.invoke's explicit thread bridge copies the owning ContextVars.
context_metadata_root = ContextVar("host_test_root")


async def build(root, scope_id):
    root = Path(root)
    with sqlite3.connect(root / "audit.sqlite") as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT,label TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS effects (effect TEXT PRIMARY KEY)")
    registry = ComponentRegistry()

    def provider(config, context):
        assert context.store is None
        return context.own_async(Provider(root, config["label"]))

    def tools(config, context):
        result = ToolRegistry()
        result.register(
            ToolSpec(
                "change",
                "Apply change",
                {"type": "object"},
                effect="idempotent_write",
                requires_approval=True,
            ),
            change,
        )
        return result

    registry.register("provider", "host-offline", provider)
    registry.register("tools", "host-tools", tools)
    catalog = TemporalProfileCatalog.from_file(root / "catalog.json")
    return await TemporalRuntimeBuilder(registry, base_dir=root).abuild_catalog(
        catalog, scope=Scope("host-service", scope_id)
    )


async def run():
    from temporalio.client import Client

    root = Path(os.environ["RALF_HOST_ROOT"])
    identity = os.environ["RALF_HOST_WORKER_ID"]
    token = context_metadata_root.set(str(root))
    host = await build(root, os.environ["RALF_HOST_SCOPE_ID"])
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        await host.start_workers(
            client,
            queue_prefix=os.environ["RALF_HOST_QUEUE_PREFIX"],
            engine_options={"activity_timeout": 3, "drive_timeout": 30},
        )
        routes = [
            {
                "profile": p.identity,
                "queue": host.runtime(p.identity).engine.task_queue,
                "release": host.runtime(p.identity).engine.release,
            }
            for p in host.profiles
        ]
        (root / ("routes-" + identity + ".json")).write_text(json.dumps(routes))
        print("HOST_WORKER_READY", flush=True)
        while not (root / ("stop-" + identity)).exists():  # noqa: ASYNC110 -- owned process stop marker
            await asyncio.sleep(0.05)
    finally:
        await host.aclose(wait_timeout=20)
        context_metadata_root.reset(token)
        print("HOST_WORKER_CLOSED", flush=True)


if __name__ == "__main__":
    asyncio.run(run())
