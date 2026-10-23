import asyncio

import pytest

from relf_agent import (
    FactIndexCatalog,
    FactScanQuery,
    IndexedMemoryStore,
    RecallQuery,
    Scope,
    SQLiteVectorIndex,
)
from relf_agent.errors import BudgetExceeded, ValidationError
from tests.test_fact_index import Embedding
from tests.test_redis_memory_adapter import memory_at
from tests.test_redis_memory_adapter import redis_service as redis_service


def test_real_redis_native_scan_preserves_expired_large_integer_and_byte_continuation(
    redis_service,
):
    async def run():
        async with memory_at(redis_service, "fact-scanning") as (source, client):
            await source.put_fact(
                Scope(),
                "facts",
                "one",
                {"number": 9007199254740997, "text": "中文🙂"},
                expected_version=0,
            )
            await source.put_fact(
                Scope(), "facts", "expired", "needle", expected_version=0, expires_at=0
            )
            assert source.fact_scan_version == 1
            snapshot = await source.fact_snapshot(Scope(), "facts")
            first = await source.scan_facts(Scope(), "facts", FactScanQuery(limit=1))
            assert (
                first.snapshot_id == snapshot
                and first.items[0]["value"]["number"] == 9007199254740997
            )
            second = await source.scan_facts(
                Scope(), "facts", FactScanQuery(limit=1, cursor=first.next_cursor)
            )
            assert second.items[0]["key"] == "expired" and second.next_cursor is None
            assert [i["key"] for i in await source.facts(Scope(), "facts")] == ["one"]
            with pytest.raises(BudgetExceeded):
                await source.scan_facts(Scope(), "facts", FactScanQuery(max_bytes=2))
            await source.put_fact(Scope(), "facts", "one", "changed", expected_version=1)
            with pytest.raises(ValidationError):
                await source.scan_facts(
                    Scope(), "facts", FactScanQuery(limit=1, cursor=first.next_cursor)
                )

    asyncio.run(run())


def test_real_redis_complete_index_and_catalog_recover_across_client_reconnect(
    redis_service, tmp_path
):
    async def run():
        vectors = SQLiteVectorIndex(tmp_path / "vectors.sqlite", dimensions=2)
        async with memory_at(redis_service, "fact-corpus") as (source, _):
            for n in range(270):
                await source.put_fact(
                    Scope(),
                    "facts",
                    str(n),
                    "needle" if n == 269 else "background",
                    expected_version=0,
                )
            indexed = IndexedMemoryStore(source, Embedding(), vectors, FactIndexCatalog(source))
            build = await indexed.rebuild(Scope(), "facts")
            assert build["status"] == "ready" and build["indexed"] == 270
            page = await indexed.recall(Scope(), "facts", RecallQuery(text="needle", max_items=1))
            assert page.items[0]["key"] == "269"
            snapshot = await source.fact_snapshot(Scope(), "facts")
        vectors.close()
        vectors = SQLiteVectorIndex(tmp_path / "vectors.sqlite", dimensions=2)
        async with memory_at(redis_service, "fact-corpus") as (source, _):
            try:
                assert await source.fact_snapshot(Scope(), "facts") == snapshot
                embedding = Embedding()
                restored = IndexedMemoryStore(source, embedding, vectors, FactIndexCatalog(source))
                receipt = await restored.rebuild(Scope(), "facts")
                assert receipt["build_id"] == build["build_id"] and receipt["indexed"] == 270
                assert embedding.batches == []
                page = await restored.recall(
                    Scope(), "facts", RecallQuery(text="needle", max_items=1)
                )
                assert page.items[0]["key"] == "269"
            finally:
                vectors.close()

    asyncio.run(run())
