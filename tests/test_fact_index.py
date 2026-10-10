import asyncio
import importlib

import pytest

from ralf_agent import (
    InMemoryMemory,
    InMemoryVectorIndex,
    RecallQuery,
    Scope,
    SQLiteMemory,
    SQLiteVectorIndex,
)
from ralf_agent.errors import ValidationError


class Embedding:
    identity = {"kind": "fixture-exact-key", "version": "1"}
    dimensions = 2

    def __init__(self):
        self.batches = []

    async def embed(self, texts):
        self.batches.append(list(texts))
        return [[1.0, 0.0] if "needle" in text else [0.0, 1.0] for text in texts]


def test_qdrant_collection_change_rebuilds_instead_of_reusing_another_collection_receipt():
    import httpx

    from ralf_agent import FactIndexCatalog, IndexedMemoryStore
    from ralf_agent.qdrant import QdrantVectorIndex
    from tests.test_qdrant_adapter import QdrantHTTP

    async def run():
        source = InMemoryMemory()
        source.put_fact(Scope(), "facts", "target", "needle", expected_version=0)
        catalog = FactIndexCatalog(InMemoryMemory())
        first_service, second_service = QdrantHTTP(), QdrantHTTP()

        def second(request):
            request.url = request.url.copy_with(path=request.url.path.replace("/new", "/tests"))
            return second_service(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(first_service)) as a:
            async with httpx.AsyncClient(transport=httpx.MockTransport(second)) as b:
                first_vector = QdrantVectorIndex(
                    "http://qdrant.invalid",
                    collection="tests",
                    dimensions=2,
                    backend_id="same",
                    client=a,
                )
                second_vector = QdrantVectorIndex(
                    "http://qdrant.invalid",
                    collection="new",
                    dimensions=2,
                    backend_id="same",
                    client=b,
                )
                await first_vector.initialize(create=False)
                await second_vector.initialize(create=False)
                first = IndexedMemoryStore(source, Embedding(), first_vector, catalog)
                original = await first.rebuild(Scope(), "facts")
                restored = IndexedMemoryStore(source, Embedding(), second_vector, catalog)
                changed = await restored.rebuild(Scope(), "facts")
                assert changed["build_id"] != original["build_id"]
                page = await restored.recall(Scope(), "facts", RecallQuery(text="needle"))
                assert [i["key"] for i in page.items] == ["target"]

    asyncio.run(run())


def api():
    module = importlib.import_module("ralf_agent")
    assert hasattr(module, "IndexedMemoryStore"), "Missing complete-corpus derived Facts index"
    assert hasattr(module, "FactIndexCatalog"), "Missing replaceable index publication catalog"
    return module.IndexedMemoryStore, module.FactIndexCatalog


@pytest.mark.parametrize("storage", ["memory", "sqlite"])
def test_index_recalls_fact_beyond_native_candidate_window(tmp_path, storage):
    source = InMemoryMemory() if storage == "memory" else SQLiteMemory(tmp_path / "facts.sqlite")
    index = (
        InMemoryVectorIndex(dimensions=2)
        if storage == "memory"
        else SQLiteVectorIndex(tmp_path / "vectors.sqlite", dimensions=2)
    )
    metadata = (
        InMemoryMemory() if storage == "memory" else SQLiteMemory(tmp_path / "catalog.sqlite")
    )
    try:
        for n in range(330):
            source.put_fact(
                Scope(), "facts", str(n), "needle" if n == 329 else "background", expected_version=0
            )
        source.put_fact(Scope(), "facts", "expired", "needle", expected_version=0, expires_at=0)
        source.put_fact(Scope("other", "user"), "facts", "foreign", "needle", expected_version=0)
        cls, catalog_cls = api()
        embedding = Embedding()
        indexed = cls(source, embedding, index, catalog_cls(metadata), batch_size=32)

        async def run():
            result = await indexed.rebuild(Scope(), "facts", max_pages=64)
            assert result["status"] == "ready" and result["scanned"] == 331
            assert result["indexed"] == 330 and result["expired"] == 1
            page = await indexed.recall(Scope(), "facts", RecallQuery(text="needle", max_items=1))
            assert [item["key"] for item in page.items] == ["329"]
            assert page.items[0]["value"] == "needle" and page.items[0]["version"] == 1
            await indexed.validate_facts(Scope(), "facts", page.items)

        asyncio.run(run())
    finally:
        source.close()
        index.close()
        metadata.close()


def test_partial_index_never_becomes_active_then_resumes_original_generation():
    source, metadata = InMemoryMemory(), InMemoryMemory()
    for n in range(5):
        source.put_fact(
            Scope(), "facts", str(n), "needle" if n == 4 else "background", expected_version=0
        )
    cls, catalog_cls = api()
    embedding = Embedding()
    indexed = cls(
        source, embedding, InMemoryVectorIndex(dimensions=2), catalog_cls(metadata), batch_size=2
    )

    async def run():
        first = await indexed.rebuild(Scope(), "facts", max_pages=1)
        assert first["status"] == "building" and first["indexed"] == 2
        with pytest.raises(ValidationError):
            await indexed.recall(Scope(), "facts", RecallQuery(text="needle"))
        final = await indexed.rebuild(Scope(), "facts", max_pages=10)
        assert final["status"] == "ready" and final["build_id"] == first["build_id"]
        assert final["scanned"] == final["indexed"] == 5
        assert [
            item["key"]
            for item in (
                await indexed.recall(Scope(), "facts", RecallQuery(text="needle", max_items=1))
            ).items
        ] == ["4"]

    asyncio.run(run())


def test_index_catalog_lazy_load_is_rejected_without_executing_generator():
    cls, _ = api()

    class LazyCatalog:
        identity = {"kind": "lazy-catalog-test", "version": "1"}
        executed = False

        def load(self, *args):
            def later():
                self.executed = True
                yield 0
                yield None

            return later()

        def save(self, *args, **kwargs):
            return kwargs["expected_version"] + 1

    source = InMemoryMemory()
    catalog = LazyCatalog()
    indexed = cls(source, Embedding(), InMemoryVectorIndex(dimensions=2), catalog)

    async def run():
        with pytest.raises(ValidationError):
            await indexed.rebuild(Scope(), "facts")

    asyncio.run(run())
    assert not catalog.executed


def test_total_index_record_budget_stops_before_next_embedding_and_activation():
    from ralf_agent.errors import BudgetExceeded

    cls, catalog_cls = api()
    source, embedding = InMemoryMemory(), Embedding()
    for n in range(3):
        source.put_fact(Scope(), "facts", str(n), "needle", expected_version=0)
    indexed = cls(
        source,
        embedding,
        InMemoryVectorIndex(dimensions=2),
        catalog_cls(InMemoryMemory()),
        batch_size=2,
        max_records=2,
    )

    async def run():
        with pytest.raises(BudgetExceeded):
            await indexed.rebuild(Scope(), "facts")
        with pytest.raises(ValidationError):
            await indexed.recall(Scope(), "facts", RecallQuery(text="needle"))

    asyncio.run(run())
    assert len(embedding.batches) == 1


def test_internal_adoption_hook_drift_is_rejected_before_io():
    from ralf_agent.errors import DefinitionMismatch

    cls, catalog_cls = api()
    embedding = Embedding()
    indexed = cls(
        InMemoryMemory(),
        embedding,
        InMemoryVectorIndex(dimensions=2),
        catalog_cls(InMemoryMemory()),
    )

    async def altered(*args):
        return None

    indexed._validate_raw = altered

    async def run():
        with pytest.raises(DefinitionMismatch):
            await indexed.rebuild(Scope(), "facts")

    asyncio.run(run())
    assert embedding.batches == []


def test_malformed_phase_has_typed_refusal_instead_of_unhashable_crash():
    cls, catalog_cls = api()

    class Corrupt(catalog_cls):
        async def load(self, *args):
            revision, state = await super().load(*args)
            if args[2] == "active" and state is not None:
                state["phase"] = {"bad": "phase"}
            return revision, state

    source = InMemoryMemory()
    indexed = cls(source, Embedding(), InMemoryVectorIndex(dimensions=2), Corrupt(InMemoryMemory()))

    async def run():
        await indexed.rebuild(Scope(), "facts")
        with pytest.raises(ValidationError):
            await indexed.recall(Scope(), "facts", RecallQuery(text="needle"))

    asyncio.run(run())


def test_source_mutation_invalidates_complete_index_and_prepared_fact_evidence():
    source, metadata = InMemoryMemory(), InMemoryMemory()
    source.put_fact(Scope(), "facts", "one", "needle", expected_version=0)
    cls, catalog_cls = api()
    indexed = cls(source, Embedding(), InMemoryVectorIndex(dimensions=2), catalog_cls(metadata))

    async def run():
        await indexed.rebuild(Scope(), "facts")
        original = await indexed.recall(Scope(), "facts", RecallQuery(text="needle"))
        source.put_fact(Scope(), "facts", "one", "background", expected_version=1)
        with pytest.raises(ValidationError):
            await indexed.recall(Scope(), "facts", RecallQuery(text="needle"))
        with pytest.raises(ValidationError):
            await indexed.validate_facts(Scope(), "facts", original.items)
        await indexed.rebuild(Scope(), "facts")
        updated = await indexed.recall(Scope(), "facts", RecallQuery(text="background"))
        assert updated.items[0]["version"] == 2 and updated.items[0]["value"] == "background"

    asyncio.run(run())


@pytest.mark.parametrize(
    "window",
    ["embedding-response-saved", "vectors-committed", "page-checkpoint-saved", "active-committed"],
)
def test_real_process_recovery_reuses_accepted_embeddings_and_original_publication(
    tmp_path, window
):
    import json
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path

    import ralf_agent

    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
        ),
    }
    for mode, expected in [("crash", 79), ("resume", 0)]:
        result = subprocess.run(
            [sys.executable, "-m", "tests.fact_index_crash_fixture", str(tmp_path), window, mode],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == expected, result.stderr
    with sqlite3.connect(tmp_path / "counts.sqlite") as db:
        calls = dict(db.execute("SELECT kind,COUNT(*) FROM calls GROUP BY kind"))
    assert calls["batch"] == 2 and calls["query"] == 1
    assert calls["upsert"] == (3 if window == "vectors-committed" else 2)
    with sqlite3.connect(tmp_path / "vectors.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM vector_entries").fetchone()[0] == 4
    saved = json.loads((tmp_path / "result.json").read_text())
    assert saved["status"] == "ready" and saved["indexed"] == 4


def test_source_change_during_active_commit_cannot_confirm_current_publication():
    source = InMemoryMemory()
    source.put_fact(Scope(), "facts", "one", "needle", expected_version=0)

    class Changed(InMemoryMemory):
        async def put_fact(self, *args, **kwargs):
            revision = super().put_fact(*args, **kwargs)
            if args[2] == "active":
                source.put_fact(Scope(), "facts", "one", "changed", expected_version=1)
            return revision

    cls, catalog_cls = api()
    indexed = cls(source, Embedding(), InMemoryVectorIndex(dimensions=2), catalog_cls(Changed()))

    async def run():
        with pytest.raises(ValidationError):
            await indexed.rebuild(Scope(), "facts")

    asyncio.run(run())


def test_partial_cursor_cannot_be_forged_into_complete_active_state():
    cls, catalog_cls = api()

    class Partial(catalog_cls):
        async def load(self, *args):
            revision, state = await super().load(*args)
            if args[2] == "active" and state is not None:
                state["cursor"] = "partial-records-remain"
            return revision, state

    source = InMemoryMemory()
    source.put_fact(Scope(), "facts", "one", "needle", expected_version=0)
    indexed = cls(source, Embedding(), InMemoryVectorIndex(dimensions=2), Partial(InMemoryMemory()))

    async def run():
        await indexed.rebuild(Scope(), "facts")
        with pytest.raises(ValidationError):
            await indexed.recall(Scope(), "facts", RecallQuery(text="needle"))

    asyncio.run(run())


def test_same_snapshot_clone_cannot_replace_actual_source_resource_during_embedding(tmp_path):
    from ralf_agent import SQLiteStore
    from ralf_agent.errors import DefinitionMismatch

    source, metadata = SQLiteMemory(tmp_path / "source.sqlite"), InMemoryMemory()
    replacement = SQLiteStore(tmp_path / "cloned.sqlite")
    original = source.store
    source.put_fact(Scope(), "facts", "one", "needle", expected_version=0)
    source.fact_snapshot(Scope(), "facts")
    original.conn.backup(replacement.conn)

    class Changed(Embedding):
        async def embed(self, texts):
            vectors = await super().embed(texts)
            source.store = replacement
            return vectors

    cls, catalog_cls = api()
    indexed = cls(source, Changed(), InMemoryVectorIndex(dimensions=2), catalog_cls(metadata))
    try:

        async def run():
            with pytest.raises(DefinitionMismatch):
                await indexed.rebuild(Scope(), "facts")

        asyncio.run(run())
    finally:
        source.store = original
        source.close()
        replacement.close()


def test_index_recall_cursor_preserves_byte_stop_without_repeating_first_hit():
    cls, catalog_cls = api()
    source = InMemoryMemory()
    for key in ["one", "two", "three"]:
        source.put_fact(Scope(), "facts", key, "needle", expected_version=0)
    indexed = cls(
        source, Embedding(), InMemoryVectorIndex(dimensions=2), catalog_cls(InMemoryMemory())
    )

    async def run():
        await indexed.rebuild(Scope(), "facts")
        first = await indexed.recall(
            Scope(), "facts", RecallQuery(text="needle", max_items=1, scan_limit=1)
        )
        assert len(first.items) == 1 and first.next_cursor is not None
        second = await indexed.recall(
            Scope(),
            "facts",
            RecallQuery(text="needle", max_items=1, scan_limit=1, cursor=first.next_cursor),
        )
        assert len(second.items) == 1 and second.items[0]["key"] != first.items[0]["key"]

    asyncio.run(run())


def test_host_scoped_view_can_collect_multiple_indexed_facts_and_validate_provenance():
    from ralf_agent.binding_data import FactsView

    cls, catalog_cls = api()
    source = InMemoryMemory()
    for key in ["one", "two", "three"]:
        source.put_fact(Scope(), "physical", key, "needle", expected_version=0)
    indexed = cls(
        source, Embedding(), InMemoryVectorIndex(dimensions=2), catalog_cls(InMemoryMemory())
    )
    view = FactsView(indexed, Scope(), "physical", indexed.backend_id)

    async def run():
        await indexed.rebuild(Scope(), "physical")
        page = await view.recall(
            Scope(), "logical", RecallQuery(text="needle", max_items=3, scan_limit=8)
        )
        assert {i["key"] for i in page.items} == {"one", "two", "three"}
        assert all(i["_facts_binding"]["namespace"] == "physical" for i in page.items)
        await view.validate_facts(Scope(), "logical", page.items)

    asyncio.run(run())
