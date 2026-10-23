"""Dataset identities come from actual stores, never display/backend aliases."""

import asyncio
import uuid
from dataclasses import asdict

from relf_agent import AgentSpec, PostgresMemory, Scope
from relf_agent.errors import MemoryBackendError
from relf_agent.temporal_bindings import normalize_request
from relf_agent.temporal_session_state import TemporalSessionState
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request

from .test_postgres_adapter import BoundaryConnection
from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service
from .test_temporal_persistent_session_data import accepted, runtime


def test_postgres_identity_initialization_transport_failure_is_sanitized():
    import pytest

    async def run():
        source = PostgresMemory(BoundaryConnection(), backend_id="boundary")
        assert source.session_dataset_id is None
        with pytest.raises(MemoryBackendError) as caught:
            await source.initialize_session_identity()
        assert "secret" not in str(caught.value)

    asyncio.run(run())


def test_real_redis_identity_survives_client_replacement_and_alias(redis_service):
    async def run():
        prefix = "dataset-" + uuid.uuid4().hex
        async with memory_at(redis_service, prefix) as (first, _):
            assert first.session_dataset_id is None
            await first.initialize_session_identity()
            key = TemporalSessionState(accepted(runtime(first))).key
            async with memory_at(redis_service, prefix) as (second, _):
                second._backend_id = "other-display-alias"
                await second.initialize_session_identity()
                assert first.session_dataset_id == second.session_dataset_id
                assert TemporalSessionState(accepted(runtime(second))).key == key
            async with memory_at(redis_service, prefix + "-other") as (other, _):
                await other.initialize_session_identity()
                assert TemporalSessionState(accepted(runtime(other))).key != key

    asyncio.run(run())


def test_real_redis_replaced_dataset_is_refused_before_context_read(redis_service):
    async def run():
        async with memory_at(redis_service, "replace-" + uuid.uuid4().hex) as (backend, client):
            await backend.initialize_session_identity()
            execution = runtime(backend)
            state = TemporalRunState(
                "run",
                asdict(Scope()),
                "first",
                normalize_request(submission_request(AgentSpec("a", "Answer"), "task")),
                execution.manifest,
            )
            await client.set(backend._prefix + ":session-resource-v1", uuid.uuid4().hex)
            _, request = state.next_operation()
            response = await execution.prepare_context(request)
            assert not response["ok"] and response["code"] == "definition_mismatch"
            await execution.close_session_execution()

    asyncio.run(run())


def test_real_postgres_identity_survives_connection_and_search_path(postgres_dsn):
    import psycopg
    from psycopg import sql

    async def run():
        schema = "session_identity_" + uuid.uuid4().hex
        async with await psycopg.AsyncConnection.connect(postgres_dsn, autocommit=True) as conn:
            try:
                await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                await conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                first = PostgresMemory(conn, backend_id="first-alias")
                await first.initialize()
                await first.initialize_session_identity()
                key = TemporalSessionState(accepted(runtime(first))).key
                await conn.execute("SET search_path TO public")
                await first.initialize_session_identity()
                assert TemporalSessionState(accepted(runtime(first))).key == key
                async with await psycopg.AsyncConnection.connect(
                    postgres_dsn, autocommit=True
                ) as other_conn:
                    await other_conn.execute(
                        sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
                    )
                    second = PostgresMemory(other_conn, backend_id="second-alias")
                    await second.initialize()
                    await second.initialize_session_identity()
                    assert second.session_dataset_id == first.session_dataset_id
                    assert TemporalSessionState(accepted(runtime(second))).key == key
            finally:
                await conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

    asyncio.run(run())
