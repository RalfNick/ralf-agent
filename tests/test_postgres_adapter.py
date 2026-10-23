"""Boundary validation plus real PostgreSQL storage contracts.

Set RALF_TEST_POSTGRES_DSN to enable the integration cases. No SQL simulator is
used: skipped tests are not evidence of database behavior.
"""

import asyncio
import importlib
import importlib.util
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from relf_agent.errors import IdempotencyConflict, MemoryBackendError, ValidationError
from relf_agent.recall import RecallQuery
from relf_agent.retrieval import (
    Document,
    KnowledgeContext,
    KnowledgeVersionConflict,
    LexicalRetriever,
    RetrievalQuery,
)
from relf_agent.types import Scope


def adapter(name="PostgresMemory"):
    module = "relf_agent.postgres"
    assert importlib.util.find_spec(module) is not None, "Missing PostgreSQL adapter"
    return getattr(importlib.import_module(module), name)


@pytest.mark.parametrize("name", ["PostgresMemory", "PostgresKnowledgeStore"])
@pytest.mark.parametrize("identity", [None, "", "  ", 123, False])
def test_backend_identity_is_explicit_nonempty_text(name, identity):
    with pytest.raises(ValidationError):
        adapter(name)(connection=object(), backend_id=identity)


class BoundaryConnection:
    """No SQL behavior; only constructor, transport failure and ownership checks."""

    autocommit = True

    def __init__(self):
        self.closed = False

    def cursor(self, **kwargs):
        raise RuntimeError("password=secret SQL SELECT private_data")

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("name", ["PostgresMemory", "PostgresKnowledgeStore"])
def test_borrowed_close_preserves_connection_and_owned_close_is_idempotent(name):
    async def scenario():
        borrowed = BoundaryConnection()
        store = adapter(name)(borrowed, backend_id="pg-boundary")
        await store.aclose()
        assert not borrowed.closed
        owned = BoundaryConnection()
        store = adapter(name)(owned, backend_id="pg-owned", owns_connection=True)
        await store.aclose()
        await store.aclose()
        assert owned.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("name", ["PostgresMemory", "PostgresKnowledgeStore"])
def test_transport_exception_has_safe_typed_public_message(name):
    async def scenario():
        store = adapter(name)(BoundaryConnection(), backend_id="pg-error")
        with pytest.raises(MemoryBackendError) as captured:
            await store.initialize()
        assert "secret" not in str(captured.value)
        assert "SELECT" not in str(captured.value)

    asyncio.run(scenario())


def test_borrowed_connection_must_be_autocommit_before_adapter_use():
    connection = BoundaryConnection()
    connection.autocommit = False
    with pytest.raises(ValidationError):
        adapter()(connection, backend_id="pg-invalid")


def test_synchronous_connection_is_rejected_before_io():
    class SynchronousConnection(BoundaryConnection):
        def close(self):
            self.closed = True

    with pytest.raises(ValidationError):
        adapter()(SynchronousConnection(), backend_id="pg-sync")


@pytest.mark.parametrize("chunk_size,overlap", [(0, 0), (4, 4), (4, -1), (True, 0)])
def test_knowledge_chunk_configuration_is_validated(chunk_size, overlap):
    with pytest.raises(ValidationError):
        adapter("PostgresKnowledgeStore")(
            BoundaryConnection(), backend_id="pg-invalid", chunk_size=chunk_size, overlap=overlap
        )


def test_invalid_values_are_rejected_before_database_io():
    async def scenario():
        memory = adapter()(BoundaryConnection(), backend_id="pg-values")
        knowledge = adapter("PostgresKnowledgeStore")(
            BoundaryConnection(), backend_id="pg-knowledge-values"
        )
        scope = Scope("pg-test", "owner")
        for scope_input, session in [(None, "s"), (scope, " ")]:
            with pytest.raises(ValidationError):
                await memory.read(scope_input, session)
        for version in [True, -1, 2**63]:
            with pytest.raises(ValidationError):
                await memory.append(scope, "s", {}, expected_revision=version, message_id="m")
        with pytest.raises(ValidationError):
            await memory.append(scope, "s", [], expected_revision=0, message_id="m")
        with pytest.raises(ValidationError):
            await memory.put_fact(scope, "ns", "k", 1, expected_version=0, expires_at=float("nan"))
        with pytest.raises(ValidationError):
            await memory.put_fact(scope, "", "k", 1, expected_version=0)
        with pytest.raises(ValidationError):
            await knowledge.put(scope, "ns", object(), expected_version=0)
        with pytest.raises(ValidationError):
            await knowledge.lexical(scope, "ns", object())

    asyncio.run(scenario())


@pytest.fixture
def postgres_dsn():
    dsn = os.environ.get("RALF_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Set RALF_TEST_POSTGRES_DSN for real PostgreSQL integration")
    pytest.importorskip("psycopg")
    return dsn


@asynccontextmanager
async def stores(dsn):
    psycopg = importlib.import_module("psycopg")
    connection = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    memory = adapter()(connection, backend_id="postgres-integration-memory")
    knowledge = adapter("PostgresKnowledgeStore")(
        connection, backend_id="postgres-integration-knowledge", chunk_size=100, overlap=10
    )
    scope = Scope("pg-test-" + uuid.uuid4().hex, "owner'")
    try:
        await memory.initialize()
        await knowledge.initialize()
        yield memory, knowledge, scope
    finally:
        if not connection.closed:
            for table in (
                "ralf_knowledge_terms",
                "ralf_knowledge_chunks",
                "ralf_knowledge_documents",
                "ralf_memory_messages",
                "ralf_memory_sessions",
                "ralf_memory_facts",
                "ralf_memory_fact_generations",
                "ralf_memory_fact_scan_epochs",
            ):
                await connection.execute(
                    f"DELETE FROM {table} WHERE workspace=%s", (scope.workspace,)
                )
        await connection.close()


def test_postgres_session_cas_idempotency_scopes_and_high_water_pages(postgres_dsn):
    async def scenario():
        async with stores(postgres_dsn) as (memory, _, scope):
            session = "s'; DROP TABLE ralf_memory_sessions;--"
            assert await memory.read(scope, session) == (0, [])
            for revision in range(8):
                assert (
                    await memory.append(
                        scope,
                        session,
                        {"number": revision + 1},
                        expected_revision=revision,
                        message_id=f"m{revision + 1}",
                    )
                    == revision + 1
                )
            assert (
                await memory.append(
                    scope, session, {"number": 1}, expected_revision=999, message_id="m1"
                )
                == 1
            )
            with pytest.raises(IdempotencyConflict):
                await memory.append(
                    scope, session, {"number": 99}, expected_revision=8, message_id="m1"
                )
            with pytest.raises(ValidationError):
                await memory.append(
                    scope, session, {"number": 9}, expected_revision=0, message_id="m9"
                )
            assert await memory.read(Scope(scope.workspace, "other"), session) == (0, [])
            query = RecallQuery(max_items=2, max_chars=200, scan_limit=3)
            first = await memory.read_page(scope, session, query)
            assert first.items == [{"number": 7}, {"number": 8}]
            assert first.backend_bounded and first.scanned == 2 and first.next_cursor
            await memory.append(scope, session, {"number": 9}, expected_revision=8, message_id="m9")
            second = await memory.read_page(
                scope, session, replace(query, cursor=first.next_cursor)
            )
            assert second.items == [{"number": 5}, {"number": 6}]
            assert second.snapshot_id == first.snapshot_id
            with pytest.raises(ValidationError):
                await memory.read_page(
                    scope, "other-session", replace(query, cursor=first.next_cursor)
                )
            small = await memory.read_page(
                scope, session, RecallQuery(max_items=1, max_chars=2, scan_limit=2)
            )
            assert small.items == [] and small.scanned == 2 and small.skipped == 2
            await memory.initialize()
            assert (await memory.read(scope, session))[0] == 9

    asyncio.run(scenario())


def test_postgres_fact_expiry_preserves_cas_and_invalidates_references(postgres_dsn):
    async def scenario():
        async with stores(postgres_dsn) as (memory, _, scope):
            assert (
                await memory.put_fact(
                    scope,
                    "facts",
                    "expired",
                    {"secret": 1},
                    expected_version=0,
                    expires_at=time.time() - 1,
                )
                == 1
            )
            assert await memory.facts(scope, "facts") == []
            with pytest.raises(ValidationError):
                await memory.put_fact(scope, "facts", "expired", {}, expected_version=0)
            assert (
                await memory.put_fact(scope, "facts", "expired", {"fresh": 2}, expected_version=1)
                == 2
            )
            for key in ("b", "c", "d"):
                await memory.put_fact(scope, "facts", key, key, expected_version=0)
            query = RecallQuery(max_items=1, max_chars=1000, scan_limit=2)
            first = await memory.recall(scope, "facts", query)
            assert first.items[0]["key"] == "expired" and first.next_cursor
            await memory.validate_facts(scope, "facts", first.items)
            assert await memory.facts(Scope(scope.workspace, "other"), "facts") == []
            with pytest.raises(ValidationError):
                await memory.validate_facts(Scope(scope.workspace, "other"), "facts", first.items)
            await memory.put_fact(scope, "facts", "expired", 3, expected_version=2)
            with pytest.raises(ValidationError):
                await memory.validate_facts(scope, "facts", first.items)
            with pytest.raises(ValidationError):
                await memory.recall(scope, "facts", replace(query, cursor=first.next_cursor))
            await memory.put_fact(
                scope, "facts", "ttl", 1, expected_version=0, expires_at=time.time() + 0.04
            )
            references = [
                item for item in await memory.facts(scope, "facts") if item["key"] == "ttl"
            ]
            assert len(references) == 1
            await asyncio.sleep(0.05)
            with pytest.raises(ValidationError):
                await memory.validate_facts(scope, "facts", references)
            assert all(item["key"] != "ttl" for item in await memory.facts(scope, "facts"))

    asyncio.run(scenario())


def test_postgres_first_writers_race_on_independent_connections(postgres_dsn):
    async def scenario():
        async with stores(postgres_dsn) as (memory, knowledge, scope):
            other_memory = await adapter().connect(postgres_dsn, backend_id="pg-racer")
            other_knowledge = adapter("PostgresKnowledgeStore")(
                other_memory.connection, backend_id="pg-knowledge-racer"
            )
            try:
                calls = [
                    memory.append(
                        scope, "race", {"writer": 1}, expected_revision=0, message_id="a"
                    ),
                    other_memory.append(
                        scope, "race", {"writer": 2}, expected_revision=0, message_id="b"
                    ),
                ]
                outcomes = await asyncio.gather(*calls, return_exceptions=True)
                assert sum(result == 1 for result in outcomes) == 1
                assert sum(isinstance(result, ValidationError) for result in outcomes) == 1
                outcomes = await asyncio.gather(
                    memory.put_fact(scope, "race", "key", 1, expected_version=0),
                    other_memory.put_fact(scope, "race", "key", 2, expected_version=0),
                    return_exceptions=True,
                )
                assert sum(result == 1 for result in outcomes) == 1
                assert sum(isinstance(result, ValidationError) for result in outcomes) == 1
                outcomes = await asyncio.gather(
                    knowledge.put(scope, "race", Document("doc", "first"), expected_version=0),
                    other_knowledge.put(
                        scope, "race", Document("doc", "second"), expected_version=0
                    ),
                    return_exceptions=True,
                )
                assert sum(result == 1 for result in outcomes) == 1
                assert sum(isinstance(result, KnowledgeVersionConflict) for result in outcomes) == 1
            finally:
                await other_memory.aclose()
                assert other_memory.connection.closed

    asyncio.run(scenario())


def test_postgres_knowledge_versions_tombstones_lexical_and_source_validation(postgres_dsn):
    async def scenario():
        async with stores(postgres_dsn) as (_, knowledge, scope):
            document = Document(
                "guide", "ALPHA beta 中文知识", "https://example.test/guide", {"tags": ["a"]}
            )
            assert await knowledge.put(scope, "docs", document, expected_version=0) == 1
            record = await knowledge.get(scope, "docs", "guide")
            assert record.text == document.text and record.version == 1
            record.metadata["tags"].append("mutated")
            assert (await knowledge.get(scope, "docs", "guide")).metadata == {"tags": ["a"]}
            chunks = await knowledge.chunks(scope, "docs", "guide")
            assert len(chunks) == 1 and chunks[0].text == document.text
            assert await knowledge.get_chunk(scope, "docs", chunks[0].chunk_id) == chunks[0]
            result = await knowledge.lexical(scope, "docs", RetrievalQuery("alpha 知识"))
            assert len(result.items) == 1 and result.items[0].score == 2.0
            assert (
                await knowledge.lexical(
                    Scope(scope.workspace, "other"), "docs", RetrievalQuery("alpha")
                )
            ).items == ()
            assert (
                await knowledge.lexical(scope, "docs", RetrievalQuery("alpha", max_chars=2))
            ).items == ()
            context = KnowledgeContext(LexicalRetriever(knowledge), namespace="docs")
            references = await context.references(scope, "alpha")
            await context.validate(scope, references)
            assert (
                await knowledge.put(scope, "docs", Document("guide", "gamma"), expected_version=1)
                == 2
            )
            assert await knowledge.get_chunk(scope, "docs", chunks[0].chunk_id) is None
            with pytest.raises(ValidationError):
                await context.validate(scope, references)
            with pytest.raises(KnowledgeVersionConflict):
                await knowledge.delete(scope, "docs", "guide", expected_version=1)
            assert await knowledge.delete(scope, "docs", "guide", expected_version=2) == 3
            assert await knowledge.get(scope, "docs", "guide") is None
            assert await knowledge.chunks(scope, "docs", "guide") == []
            with pytest.raises(KnowledgeVersionConflict):
                await knowledge.put(scope, "docs", document, expected_version=0)
            assert (
                await knowledge.put(
                    scope, "docs", document, expected_version=3, expires_at=time.time() - 1
                )
                == 4
            )
            assert await knowledge.get(scope, "docs", "guide") is None
            assert (await knowledge.lexical(scope, "docs", RetrievalQuery("alpha"))).items == ()
            assert await knowledge.put(scope, "docs", document, expected_version=4) == 5
            assert await knowledge.delete(scope, "docs", "missing", expected_version=0) == 1
            await knowledge.initialize()
            assert (await knowledge.get(scope, "docs", "guide")).version == 5

    asyncio.run(scenario())


def test_postgres_shared_connection_transactions_do_not_interleave(postgres_dsn):
    async def scenario():
        async with stores(postgres_dsn) as (memory, knowledge, scope):

            async def session_writer():
                for revision in range(15):
                    await memory.append(
                        scope,
                        "shared",
                        {"n": revision},
                        expected_revision=revision,
                        message_id=str(revision),
                    )

            async def fact_writer():
                for version in range(15):
                    await memory.put_fact(scope, "shared", "key", version, expected_version=version)

            async def document_writer():
                for version in range(15):
                    await knowledge.put(
                        scope,
                        "shared",
                        Document("doc", f"word {version}"),
                        expected_version=version,
                    )

            await asyncio.gather(session_writer(), fact_writer(), document_writer())
            assert (await memory.read(scope, "shared"))[0] == 15
            assert (await memory.facts(scope, "shared"))[0]["version"] == 15
            assert (await knowledge.get(scope, "shared", "doc")).version == 15

    asyncio.run(scenario())
