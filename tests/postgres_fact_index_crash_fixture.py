"""Real derived-index crashes; SDK binding checks remain enabled."""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

from ralf_agent import (
    FactIndexCatalog,
    IndexedMemoryStore,
    RecallQuery,
    Scope,
    SQLiteVectorIndex,
)
from ralf_agent.postgres import PostgresMemory

root, window, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
root.mkdir(exist_ok=True)
counts = root / "counts.sqlite"
with sqlite3.connect(counts) as db:
    db.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")


def record(kind):
    with sqlite3.connect(counts) as db:
        db.execute("INSERT INTO calls VALUES (?)", (kind,))


def crash():
    print("fact-index-crash-window", flush=True)
    os._exit(79)


class Embedding:
    dimensions = 2
    identity = {"kind": "fact-index-crash-embedding", "version": "1"}

    async def embed(self, texts):
        record("query" if texts == ["needle"] else "batch")
        return [[1.0, 0.0] if "needle" in text else [0.0, 1.0] for text in texts]


class Catalog(FactIndexCatalog):
    async def save(self, scope, index_id, key, value, *, expected_version):
        result = await super().save(scope, index_id, key, value, expected_version=expected_version)
        if mode == "crash":
            if (
                window == "embedding-response-saved"
                and key == "build"
                and value["phase"] == "embedded"
            ):
                crash()
            if (
                window == "page-checkpoint-saved"
                and key == "build"
                and value["phase"] == "scan"
                and value["scanned"] == 2
            ):
                crash()
            if window == "active-committed" and key == "active":
                crash()
        return result


class Index(SQLiteVectorIndex):
    def upsert(self, *args, **kwargs):
        result = super().upsert(*args, **kwargs)
        record("upsert")
        if mode == "crash" and window == "vectors-committed":
            crash()
        return result


async def run():
    source = await PostgresMemory.connect(
        os.environ["RALF_TEST_POSTGRES_DSN"], backend_id="postgres-index-crash"
    )
    scope = Scope("pg-index-crash:" + str(root), "owner")
    index = Index(root / "vectors.sqlite", dimensions=2)
    try:
        await source.initialize()
        if await source.inspect_fact(scope, "facts", "0") is None:
            for n in range(4):
                await source.put_fact(
                    scope, "facts", str(n), "needle" if n == 3 else "background", expected_version=0
                )
        indexed = IndexedMemoryStore(source, Embedding(), index, Catalog(source), batch_size=2)
        state = await indexed.rebuild(scope, "facts")
        assert state["status"] == "ready" and state["scanned"] == state["indexed"] == 4
        page = await indexed.recall(scope, "facts", RecallQuery(text="needle", max_items=1))
        assert page.items[0]["key"] == "3" and page.items[0]["version"] == 1
        (root / "result.json").write_text(json.dumps(state))
    finally:
        index.close()
        await source.aclose()


asyncio.run(run())
