import asyncio
from dataclasses import asdict

import pytest

from relf_agent import AgentSpec, Scope, ToolRegistry
from relf_agent.errors import DefinitionMismatch
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_session_data import private_address
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request

from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_postgres_adapter import stores
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service
from .test_temporal_binding_isolation import advance
from .test_temporal_facts import Provider


async def scenario(backend, scope):
    provider = Provider()
    runtime = TemporalRuntime(
        providers={"default": provider}, tools=ToolRegistry(), session_store=backend
    )
    await backend.append(
        scope,
        private_address("run", 0),
        {"role": "assistant", "task": "earlier", "content": "remote evidence"},
        expected_revision=0,
        message_id="m",
    )
    state = TemporalRunState(
        "run",
        asdict(scope),
        "command",
        submission_request(AgentSpec("a", "Answer"), "task"),
        runtime.manifest,
    )
    await advance(runtime, state)
    assert state.context_snapshot["session_data"]["revision"] == 1
    assert state.context_snapshot["session_data"]["page"]["backend_bounded"]
    await advance(runtime, state)
    assert state.state == "succeeded" and "remote evidence" in str(provider.messages)
    original = backend._client if hasattr(backend, "_client") else backend.connection
    attribute = "_client" if hasattr(backend, "_client") else "connection"
    setattr(backend, attribute, object())
    try:
        with pytest.raises(DefinitionMismatch):
            runtime.validate_release()
    finally:
        setattr(backend, attribute, original)


def test_actual_redis_scoped_session_read_and_client_pin(redis_service):
    async def run():
        async with memory_at(redis_service, "temporal-read") as (backend, _):
            await scenario(backend, Scope())

    asyncio.run(run())


def test_actual_postgres_scoped_session_read_and_client_pin(postgres_dsn):
    async def run():
        async with stores(postgres_dsn) as (backend, _, scope):
            await scenario(backend, scope)

    asyncio.run(run())


def test_actual_postgres_session_schema_routing_is_fixed(postgres_dsn):
    import uuid

    import psycopg
    from psycopg import sql

    from relf_agent import PostgresMemory

    async def run():
        schemas = ["read_a_" + uuid.uuid4().hex, "read_b_" + uuid.uuid4().hex]
        async with await psycopg.AsyncConnection.connect(
            postgres_dsn, autocommit=True
        ) as connection:
            try:
                sources = []
                for schema, content in zip(schemas, ["original A", "other B"], strict=True):
                    await connection.execute(
                        sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
                    )
                    await connection.execute(
                        sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
                    )
                    source = PostgresMemory(connection, backend_id="same")
                    await source.initialize()
                    await source.append(
                        Scope(),
                        private_address("run", 0),
                        {"content": content},
                        expected_revision=0,
                        message_id="m",
                    )
                    sources.append(source)
                await connection.execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(schemas[0]))
                )
                provider = Provider()
                runtime = TemporalRuntime(
                    providers={"default": provider}, tools=ToolRegistry(), session_store=sources[0]
                )
                await connection.execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(schemas[1]))
                )
                state = TemporalRunState(
                    "run",
                    asdict(Scope()),
                    "c",
                    submission_request(AgentSpec("a", "Answer"), "task"),
                    runtime.manifest,
                )
                await advance(runtime, state)
                assert state.context_snapshot["session_data"]["page"]["items"] == [
                    {"content": "original A"}
                ]
                other = TemporalRuntime(
                    providers={"default": Provider()},
                    tools=ToolRegistry(),
                    session_store=sources[1],
                )
                assert (
                    runtime.manifest["session_data"]["physical"]
                    != other.manifest["session_data"]["physical"]
                )
            finally:
                for schema in schemas:
                    await connection.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                    )

    asyncio.run(run())
