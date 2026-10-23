"""Actual remote async data ports and original read-end Histories."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import pytest

from relf_agent import PostgresMemory, Scope

from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service
from .test_temporal_session_tree_remote import scenario

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@asynccontextmanager
async def isolated_postgres(dsn):
    import psycopg
    from psycopg import sql

    schema = "read_owner_" + uuid.uuid4().hex
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as connection:
        await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            await connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
            )
            backend = PostgresMemory(connection, backend_id="read-owner:" + schema)
            await backend.initialize()
            try:
                yield backend
            finally:
                await backend.aclose()
        finally:
            await connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@pytest.mark.parametrize("managed", [False, True])
def test_actual_redis_read_owner_root_private_two_turns(redis_service, managed):
    async def run():
        async with memory_at(redis_service, "read-owner-" + uuid.uuid4().hex) as (backend, _):
            await scenario(
                backend,
                backend,
                Scope("read-owner-redis", uuid.uuid4().hex),
                "graph",
                managed,
                context_reads=True,
            )

    asyncio.run(asyncio.wait_for(run(), 120))


@pytest.mark.parametrize("managed", [False, True])
def test_actual_postgres_read_owner_independent_root_private_two_turns(postgres_dsn, managed):
    async def run():
        async with isolated_postgres(postgres_dsn) as root:
            async with isolated_postgres(postgres_dsn) as private:
                scope = Scope("read-owner-pg", uuid.uuid4().hex)
                await scenario(root, private, scope, "team", managed, context_reads=True)

    asyncio.run(asyncio.wait_for(run(), 120))
