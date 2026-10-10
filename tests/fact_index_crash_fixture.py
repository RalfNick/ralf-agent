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
    SQLiteMemory,
    SQLiteVectorIndex,
)

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


source, metadata = SQLiteMemory(root / "facts.sqlite"), SQLiteMemory(root / "catalog.sqlite")
index = Index(root / "vectors.sqlite", dimensions=2)
try:
    if source.inspect_fact(Scope(), "facts", "0") is None:
        for n in range(4):
            source.put_fact(
                Scope(), "facts", str(n), "needle" if n == 3 else "background", expected_version=0
            )
    indexed = IndexedMemoryStore(source, Embedding(), index, Catalog(metadata), batch_size=2)

    async def run():
        state = await indexed.rebuild(Scope(), "facts")
        assert state["status"] == "ready" and state["scanned"] == state["indexed"] == 4
        page = await indexed.recall(Scope(), "facts", RecallQuery(text="needle", max_items=1))
        assert page.items[0]["key"] == "3" and page.items[0]["version"] == 1
        (root / "result.json").write_text(json.dumps(state))

    asyncio.run(run())
finally:
    source.close()
    index.close()
    metadata.close()
