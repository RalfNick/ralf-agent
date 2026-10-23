import asyncio
import time
import uuid
from contextlib import asynccontextmanager

import pytest

from relf_agent import Document, Scope
from relf_agent.chunking import ParagraphChunker
from relf_agent.errors import BudgetExceeded, IdempotencyConflict, MemoryBackendError
from relf_agent.ingestion import IngestionCoordinator
from relf_agent.ingestion_types import SourceDocument
from relf_agent.postgres import PostgresKnowledgeStore
from relf_agent.retrieval import KnowledgeVersionConflict, RetrievalQuery

from .test_postgres_adapter import postgres_dsn as _postgres_dsn

postgres_dsn = _postgres_dsn


@asynccontextmanager
async def store(dsn, kind=PostgresKnowledgeStore):
    s = await kind.connect(dsn, backend_id="ingestion-pg", chunk_size=8, overlap=2)
    scope = Scope("ingestion-pg-" + uuid.uuid4().hex, "owner'")
    try:
        await s.initialize()
        yield s, scope
    finally:
        for table in (
            "ralf_knowledge_terms",
            "ralf_knowledge_chunks",
            "ralf_knowledge_documents",
            "ralf_knowledge_ingestions",
        ):
            await s.connection.execute(
                f"DELETE FROM {table} WHERE workspace=%s", (scope.workspace,)
            )
        await s.aclose()


def test_actual_postgres_replay_cas_scope_defaults_and_expiry(postgres_dsn):
    async def run():
        async with store(postgres_dsn) as (s, scope):
            source = SourceDocument("guide", b"abcdefghijklmnop", source_uri="user://guide")
            coordinator = IngestionCoordinator(s)
            original = await coordinator.ingest(
                scope, "docs", source, command_id="first", expected_version=0
            )
            assert [c.text for c in await s.chunks(scope, "docs", "guide")] == [
                "abcdefgh",
                "ghijklmn",
                "mnop",
            ]
            with pytest.raises(IdempotencyConflict):
                await coordinator.ingest(
                    scope,
                    "docs",
                    SourceDocument("guide", b"other"),
                    command_id="first",
                    expected_version=0,
                )
            with pytest.raises(KnowledgeVersionConflict):
                await coordinator.ingest(
                    scope, "docs", source, command_id="second", expected_version=0
                )
            assert await s.ingestion_receipt(scope, "docs", "second") is None
            assert (
                await s.ingestion_receipt(Scope(scope.workspace, "other"), "docs", "first") is None
            )
            assert await s.ingestion_receipt(scope, "other", "first") is None
            await s.put(scope, "docs", Document("guide", "updated"), expected_version=1)
            await s.delete(scope, "docs", "guide", expected_version=2)
            assert (
                await IngestionCoordinator(s, chunker=ParagraphChunker(size=5)).ingest(
                    scope, "docs", source, command_id="first", expected_version=0
                )
                == original
            )
            expired = await coordinator.ingest(
                scope,
                "docs",
                source,
                command_id="expired",
                expected_version=3,
                expires_at=time.time() - 1,
            )
            assert expired.document_version == 4 and await s.get(scope, "docs", "guide") is None
            assert await s.ingestion_receipt(scope, "docs", "expired") == expired

    asyncio.run(run())


def test_actual_postgres_failure_after_chunks_rolls_back_entire_ingestion(postgres_dsn):
    class Store(PostgresKnowledgeStore):
        fail = True

        async def _execute(self, sql, *args, **kwargs):
            if self.fail and sql.startswith("INSERT INTO ralf_knowledge_ingestions"):
                raise MemoryBackendError("Synthetic receipt failure")
            return await super()._execute(sql, *args, **kwargs)

    async def run():
        async with store(postgres_dsn, Store) as (s, scope):
            source = SourceDocument("guide", b"pool timeout")
            with pytest.raises(MemoryBackendError):
                await IngestionCoordinator(s).ingest(
                    scope, "docs", source, command_id="first", expected_version=0
                )
            assert await s.get(scope, "docs", "guide") is None
            assert await s.chunks(scope, "docs", "guide") == []
            assert (await s.lexical(scope, "docs", RetrievalQuery("pool"))).items == ()
            assert await s.ingestion_receipt(scope, "docs", "first") is None
            s.fail = False
            assert (
                await IngestionCoordinator(s).ingest(
                    scope, "docs", source, command_id="first", expected_version=0
                )
            ).document_version == 1

    asyncio.run(run())


def test_actual_postgres_independent_connections_serialize_command_admission(postgres_dsn):
    async def run():
        async with store(postgres_dsn) as (s, scope):
            other = await PostgresKnowledgeStore.connect(postgres_dsn, backend_id=s.backend_id)
            try:
                source = SourceDocument("guide", b"pool timeout")
                calls = [
                    IngestionCoordinator(k).ingest(
                        scope, "docs", source, command_id="first", expected_version=0
                    )
                    for k in (s, other)
                ]
                receipts = await asyncio.gather(*calls)
                assert (
                    receipts[0] == receipts[1]
                    and (await s.get(scope, "docs", "guide")).version == 1
                )
                calls = [
                    IngestionCoordinator(k).ingest(
                        scope,
                        "docs",
                        SourceDocument(name, name.encode()),
                        command_id="conflict",
                        expected_version=0,
                    )
                    for k, name in ((s, "a"), (other, "b"))
                ]
                outcomes = await asyncio.gather(*calls, return_exceptions=True)
                assert sum(isinstance(x, IdempotencyConflict) for x in outcomes) == 1
                records = [await s.get(scope, "docs", n) for n in ("a", "b")]
                assert sum(record is not None for record in records) == 1
            finally:
                await other.aclose()

    asyncio.run(run())


def test_actual_postgres_receipt_capacity_rejects_new_write_but_preserves_replay(
    postgres_dsn, monkeypatch
):
    monkeypatch.setattr("relf_agent.postgres_ingestion.INGESTION_CAPACITY", 2)

    async def run():
        async with store(postgres_dsn) as (s, scope):
            c = IngestionCoordinator(s)
            first = await c.ingest(
                scope, "docs", SourceDocument("a", b"a"), command_id="a", expected_version=0
            )
            await c.ingest(
                scope, "docs", SourceDocument("b", b"b"), command_id="b", expected_version=0
            )
            with pytest.raises(BudgetExceeded):
                await c.ingest(
                    scope, "docs", SourceDocument("c", b"c"), command_id="c", expected_version=0
                )
            assert await s.get(scope, "docs", "c") is None
            assert (
                await c.ingest(
                    scope, "docs", SourceDocument("a", b"a"), command_id="a", expected_version=0
                )
                == first
            )

    asyncio.run(run())


def test_actual_ingestion_pg_qdrant_requires_explicit_index_and_hydrates_current_source(
    postgres_dsn,
):
    import os

    import httpx

    from relf_agent import (
        CharacterChunker,
        HashEmbeddingProvider,
        QdrantVectorIndex,
        VectorRetriever,
    )

    url = os.environ.get("RALF_TEST_QDRANT_URL")
    if not url:
        pytest.skip("Set RALF_TEST_QDRANT_URL for real PostgreSQL/Qdrant ingestion composition")

    async def run():
        collection = "ingestion_" + uuid.uuid4().hex
        index = QdrantVectorIndex(
            url=url, backend_id="ingestion-qdrant", collection=collection, dimensions=128
        )
        try:
            await index.initialize()
            async with store(postgres_dsn) as (s, scope):
                c = IngestionCoordinator(s, chunker=CharacterChunker(size=100, overlap=0))
                source = SourceDocument(
                    "guide", b"pool timeout diagnosis", source_uri="user://guide"
                )
                receipt = await c.ingest(
                    scope, "docs", source, command_id="first", expected_version=0
                )
                retriever = VectorRetriever(s, index, HashEmbeddingProvider())
                assert receipt.status == "knowledge_committed"
                assert (
                    await retriever.retrieve(scope, "docs", RetrievalQuery("pool timeout"))
                ).items == ()
                await retriever.index_document(scope, "docs", "guide")
                hits = (
                    await retriever.retrieve(scope, "docs", RetrievalQuery("pool timeout"))
                ).items
                assert len(hits) == 1 and hits[0].chunk_id == receipt.chunk_ids[0]
                assert hits[0].text == "pool timeout diagnosis"
                assert (
                    await retriever.retrieve(
                        Scope(scope.workspace, "other"), "docs", RetrievalQuery("pool timeout")
                    )
                ).items == ()
                await c.ingest(
                    scope,
                    "docs",
                    SourceDocument("guide", b"revised source", source_uri="user://guide"),
                    command_id="update",
                    expected_version=1,
                )
                assert (
                    await retriever.retrieve(scope, "docs", RetrievalQuery("pool timeout"))
                ).items == ()
                assert (
                    await c.ingest(scope, "docs", source, command_id="first", expected_version=0)
                    == receipt
                )
        finally:
            await index.aclose()
            async with httpx.AsyncClient() as cleanup:
                result = await cleanup.delete(
                    f"{url.rstrip('/')}/collections/{collection}", timeout=10
                )
                assert result.status_code == 200

    asyncio.run(run())
