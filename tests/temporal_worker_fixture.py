"""Real Temporal subprocess worker; intentionally no mock/time-skipping server."""

import asyncio
import json
import os

from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_journal import PostgresEffectJournal
from relf_agent.tools import ToolRegistry, ToolSpec
from relf_agent.types import ModelResponse, ToolCall, canonical


class FixtureProvider:
    identity = {"kind": "real-temporal-fixture-provider", "version": "1"}

    async def complete(self, messages, tools):
        print("TEMPORAL_PROVIDER_CALLED", flush=True)
        if messages[-1]["role"] == "tool":
            return ModelResponse(
                output={"done": json.loads(messages[-1]["content"])},
                usage={"input_tokens": 1, "output_tokens": 1},
            )
        try:
            value = json.loads(messages[1]["content"])
        except ValueError:
            return ModelResponse(output=messages[1]["content"])
        if isinstance(value, dict) and value.get("tool"):
            return ModelResponse(
                tool_calls=(ToolCall("write", value["arguments"], "fixture-call"),)
            )
        return ModelResponse(output=value)


async def write(arguments, context):
    from psycopg import AsyncConnection

    conn = await AsyncConnection.connect(os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True)
    try:
        # Actual external commit uses the stable key. A crash after this commit
        # but before ActivityCompleted must not dispatch this handler again.
        await conn.execute(
            "INSERT INTO ralf_temporal_probe_effects(effect_key,label,result,writes) VALUES (%s,%s,%s,1) "
            "ON CONFLICT (effect_key) DO UPDATE SET writes=ralf_temporal_probe_effects.writes+1",
            (
                context.effect_key,
                arguments["label"],
                canonical({"label": arguments["label"], "key": context.effect_key}),
            ),
        )
        await asyncio.sleep(arguments.get("delay", 0))
        return {"label": arguments["label"], "key": context.effect_key}
    finally:
        await conn.close()


async def reconcile(arguments, context):
    from psycopg import AsyncConnection

    conn = await AsyncConnection.connect(os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True)
    try:
        cursor = await conn.execute(
            "SELECT result FROM ralf_temporal_probe_effects WHERE effect_key=%s",
            (context.effect_key,),
        )
        row = await cursor.fetchone()
        return None if row is None else json.loads(row[0])
    finally:
        await conn.close()


def tools():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "write",
            "durable probe write",
            {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "delay": {"type": "number", "minimum": 0},
                },
                "required": ["label"],
                "additionalProperties": False,
            },
            effect="queryable_write",
            requires_approval=True,
        ),
        write,
        reconciler=reconcile,
    )
    return registry


async def runtime():
    journal = await PostgresEffectJournal.connect(os.environ["RALF_TEST_POSTGRES_DSN"])
    await journal.initialize()
    await journal.connection.execute(
        "CREATE TABLE IF NOT EXISTS ralf_temporal_probe_effects (effect_key TEXT PRIMARY KEY, label TEXT NOT NULL, result TEXT NOT NULL, writes INTEGER NOT NULL)"
    )
    provider = FixtureProvider()
    provider.identity = {
        **provider.identity,
        "version": os.environ.get("RALF_TEST_TEMPORAL_PROVIDER_VERSION", "1"),
    }
    return TemporalRuntime(providers={"default": provider}, tools=tools(), journal=journal)


async def worker_main():
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    execution = await runtime()
    worker = build_temporal_worker(
        client,
        task_queue=os.environ["RALF_TEST_TEMPORAL_QUEUE"],
        runtime=execution,
        max_concurrent_activities=4,
    )
    try:
        async with worker:
            print("TEMPORAL_WORKER_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        await execution.journal.aclose()


def main():
    asyncio.run(worker_main())
