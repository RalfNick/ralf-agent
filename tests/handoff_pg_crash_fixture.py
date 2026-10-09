"""Exit after accepted execution or broker publish, before shared completion."""

import asyncio
import json
import os
import sys

from ralf_agent import AgentSpec, LocalEngine, Scope, SQLiteStore, ToolRegistry
from ralf_agent.handoff import EngineCommandDispatcher, LocalCommandAdapter
from ralf_agent.postgres_handoff import PostgresInbox, PostgresOutbox
from ralf_agent.redis_streams import RedisStreamsBus
from ralf_agent.runtime_builder import EchoProvider


async def run():
    mode, database, workspace = sys.argv[1:]
    scope = Scope(workspace, "owner")
    bus = await RedisStreamsBus.connect(
        os.environ["RALF_TEST_REDIS_URL"], backend_id="crash", prefix="pg-crash"
    )
    Kind = PostgresInbox if mode == "inbox" else PostgresOutbox
    store = await Kind.connect(os.environ["RALF_TEST_POSTGRES_DSN"], backend_id="pg-crash")
    await store.initialize()
    if mode == "inbox":
        runtime = LocalEngine(
            SQLiteStore(database),
            providers={"default": EchoProvider("crash")},
            tools=ToolRegistry(),
            scope=scope,
        )
        dispatcher = EngineCommandDispatcher(
            LocalCommandAdapter(runtime), specs={"agent": AgentSpec("agent", "Answer")}
        )
        delivery = (await bus.receive(scope, "commands", "workers", "dead"))[0]
        await store.accept(scope, delivery.message)
        result = await dispatcher.dispatch(scope, delivery.message)
    else:
        from ralf_agent import MessageEnvelope

        message = MessageEnvelope(
            "original", "commands", {"kind": "submit", "spec": "agent", "input": "hello"}
        )
        await store.enqueue(scope, message)
        result = {"broker_id": await bus.publish(scope, message)}
    print(json.dumps(result), flush=True)
    os._exit(78)


if __name__ == "__main__":
    asyncio.run(run())
