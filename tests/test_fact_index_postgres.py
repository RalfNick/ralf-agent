"""Actual PostgreSQL full-corpus scan/index contracts; no SQL simulation."""

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
from tests.test_postgres_adapter import postgres_dsn as postgres_dsn
from tests.test_postgres_adapter import stores


def test_postgres_scan_covers_expired_unicode_and_fixed_snapshot(postgres_dsn):
    async def run():
        async with stores(postgres_dsn) as (source, _, scope):
            await source.put_fact(
                scope,
                "facts",
                "one",
                {"text": "中文🙂", "number": 9007199254740997},
                expected_version=0,
            )
            await source.put_fact(
                scope, "facts", "expired", "needle", expected_version=0, expires_at=0
            )
            snapshot = await source.fact_snapshot(scope, "facts")
            first = await source.scan_facts(scope, "facts", FactScanQuery(limit=1))
            assert (
                first.snapshot_id == snapshot
                and first.items[0]["value"]["number"] == 9007199254740997
            )
            second = await source.scan_facts(
                scope, "facts", FactScanQuery(limit=1, cursor=first.next_cursor)
            )
            assert second.items[0]["key"] == "expired" and second.next_cursor is None
            assert [v["key"] for v in await source.facts(scope, "facts")] == ["one"]
            with pytest.raises(ValidationError):
                await source.scan_facts(
                    Scope(scope.workspace, "other"),
                    "facts",
                    FactScanQuery(limit=1, cursor=first.next_cursor),
                )
            await source.put_fact(scope, "facts", "one", "changed", expected_version=1)
            with pytest.raises(ValidationError):
                await source.scan_facts(
                    scope, "facts", FactScanQuery(limit=1, cursor=first.next_cursor)
                )

    asyncio.run(run())


def test_postgres_scan_bounds_actual_key_and_payload_before_decode(postgres_dsn, monkeypatch):
    import psycopg.rows

    sizes = []
    original = psycopg.rows.tuple_row

    def rows(cursor):
        make = original(cursor)

        def record(values):
            if cursor.description and cursor.description[0].name == "position":
                sizes.append((len(values[1]), len(values[2])))
            return make(values)

        return record

    async def run():
        async with stores(postgres_dsn) as (source, _, scope):
            await source.put_fact(scope, "facts", "k" * 100, "v" * 100000, expected_version=0)
            monkeypatch.setattr(psycopg.rows, "tuple_row", rows)
            with pytest.raises(BudgetExceeded):
                await source.scan_facts(scope, "facts", FactScanQuery(max_bytes=2))
            assert sizes == [(3, 3)]

    asyncio.run(run())


def test_postgres_byte_continuation_preserves_all_records(postgres_dsn):
    from relf_agent.types import canonical

    async def run():
        async with stores(postgres_dsn) as (source, _, scope):
            for key in ["one", "two"]:
                await source.put_fact(scope, "facts", key, "中文🙂", expected_version=0)
            original = await source.scan_facts(scope, "facts", FactScanQuery(limit=1))
            allowance = len(canonical(original.items).encode("utf-8"))
            first = await source.scan_facts(
                scope, "facts", FactScanQuery(limit=2, max_bytes=allowance)
            )
            assert first.items == original.items and first.next_cursor
            second = await source.scan_facts(
                scope,
                "facts",
                FactScanQuery(limit=2, max_bytes=allowance, cursor=first.next_cursor),
            )
            assert [i["key"] for i in first.items + second.items] == ["one", "two"]
            assert second.next_cursor is None

    asyncio.run(run())


def test_postgres_complete_corpus_index_survives_connection_and_vector_reopen(
    postgres_dsn, tmp_path
):
    from relf_agent.postgres import PostgresMemory

    async def run():
        async with stores(postgres_dsn) as (source, _, scope):
            for n in range(270):
                await source.put_fact(
                    scope,
                    "facts",
                    str(n),
                    "needle" if n == 269 else "background",
                    expected_version=0,
                )
            vectors = SQLiteVectorIndex(tmp_path / "vectors.sqlite", dimensions=2)
            try:
                indexed = IndexedMemoryStore(source, Embedding(), vectors, FactIndexCatalog(source))
                build = await indexed.rebuild(scope, "facts")
                assert build["status"] == "ready" and build["indexed"] == 270
            finally:
                vectors.close()
            restored_source = await PostgresMemory.connect(
                postgres_dsn, backend_id=source.backend_id
            )
            vectors = SQLiteVectorIndex(tmp_path / "vectors.sqlite", dimensions=2)
            try:
                await restored_source.initialize()
                embedding = Embedding()
                restored = IndexedMemoryStore(
                    restored_source, embedding, vectors, FactIndexCatalog(restored_source)
                )
                assert (await restored.rebuild(scope, "facts"))["build_id"] == build["build_id"]
                assert embedding.batches == []
                page = await restored.recall(
                    scope, "facts", RecallQuery(text="needle", max_items=1)
                )
                assert [i["key"] for i in page.items] == ["269"]
            finally:
                vectors.close()
                await restored_source.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "window",
    [
        "embedding-response-saved",
        "vectors-committed",
        "page-checkpoint-saved",
        "active-committed",
    ],
)
def test_postgres_real_process_recovers_original_accepted_index(postgres_dsn, tmp_path, window):
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path

    import relf_agent

    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(relf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
        ),
        "RALF_TEST_POSTGRES_DSN": postgres_dsn,
    }
    for mode, expected in [("crash", 79), ("resume", 0)]:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.postgres_fact_index_crash_fixture",
                str(tmp_path),
                window,
                mode,
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == expected, result.stderr
    with sqlite3.connect(tmp_path / "counts.sqlite") as connection:
        counts = dict(connection.execute("SELECT kind,COUNT(*) FROM calls GROUP BY kind"))
    assert counts["batch"] == 2 and counts["query"] == 1
    assert counts["upsert"] == (3 if window == "vectors-committed" else 2)
    with sqlite3.connect(tmp_path / "vectors.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM vector_entries").fetchone()[0] == 4


def test_postgres_configured_index_and_agent_recover_with_owned_clients(
    postgres_dsn, tmp_path, monkeypatch
):
    import uuid

    from relf_agent import AgentSpec, RuntimeBuilder, RuntimeProfile

    monkeypatch.setenv("RALF_TEST_FACT_SOURCE_DSN", postgres_dsn)
    profile = RuntimeProfile(
        "pg-index",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "memory_store": {
                "adapter": "indexed-recall-async",
                "config": {
                    "backend": {
                        "adapter": "postgres",
                        "config": {
                            "dsn_env": "RALF_TEST_FACT_SOURCE_DSN",
                            "backend_id": "pg-index-source",
                            "initialize": True,
                        },
                    },
                    "catalog": {
                        "adapter": "memory-cas",
                        "config": {
                            "backend": {
                                "adapter": "postgres",
                                "config": {
                                    "dsn_env": "RALF_TEST_FACT_SOURCE_DSN",
                                    "backend_id": "pg-index-catalog",
                                    "initialize": True,
                                },
                            }
                        },
                    },
                },
            },
            "recall_planner": {"adapter": "task-text"},
        },
    )
    scope = Scope("pg-config:" + uuid.uuid4().hex, "owner")

    async def run():
        builder = RuntimeBuilder(base_dir=tmp_path)
        runtime = await builder.abuild(profile, tmp_path / "runs.sqlite", scope=scope)
        source = runtime.memory.backend
        metadata = runtime.memory.catalog.backend
        try:
            await runtime.memory.put_fact(
                scope, "answer", "preference", "needle", expected_version=0
            )
            index = await runtime.memory.rebuild(scope, "answer")
            handle = runtime.submit(AgentSpec("answer", "Answer"), "needle", command_id="same")
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
            action = next(
                a for a in runtime.store.run(handle.run_id)["actions"] if a["kind"] == "model"
            )
            assert [i["key"] for i in action["memory_references"]] == ["preference"]
            manifest = runtime.diagnostics(handle.run_id).manifest
        finally:
            await runtime.aclose()
        assert source.connection.closed and metadata.connection.closed
        runtime = await builder.abuild(profile, tmp_path / "runs.sqlite", scope=scope)
        try:
            assert (await runtime.memory.rebuild(scope, "answer"))["build_id"] == index["build_id"]
            assert (
                runtime.submit(AgentSpec("answer", "Answer"), "needle", command_id="same") == handle
            )
            assert runtime.diagnostics(handle.run_id).manifest == manifest
        finally:
            await runtime.aclose()

    asyncio.run(run())
