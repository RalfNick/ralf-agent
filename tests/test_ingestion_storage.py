import asyncio
import importlib
import importlib.util
import threading

import pytest

from ralf_agent import Document, InMemoryKnowledgeStore, Scope, SQLiteKnowledgeStore
from ralf_agent.errors import IdempotencyConflict, MemoryBackendError, ValidationError
from ralf_agent.retrieval import KnowledgeVersionConflict


def api():
    assert importlib.util.find_spec("ralf_agent.ingestion"), "Missing atomic ingestion coordinator"
    return importlib.import_module("ralf_agent.ingestion"), importlib.import_module(
        "ralf_agent.ingestion_types"
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    s = (
        InMemoryKnowledgeStore()
        if request.param == "memory"
        else SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite")
    )
    yield s
    s.close()


def ingest(store, source=None, command="first", version=0, **opts):
    api_, dto = api()
    return asyncio.run(
        api_.IngestionCoordinator(store, **opts).ingest(
            Scope(),
            "docs",
            source or dto.SourceDocument("a", b"pool diagnosis"),
            command_id=command,
            expected_version=version,
        )
    )


def test_atomic_ingestion_replays_original_after_source_update_delete_and_pipeline_move(store):
    _, dto = api()
    source = dto.SourceDocument("a", b"pool diagnosis")
    original = ingest(store, source)
    assert original.document_version == 1 and original.status == "knowledge_committed"
    store.put(Scope(), "docs", Document("a", "new content"), expected_version=1)
    store.delete(Scope(), "docs", "a", expected_version=2)
    from ralf_agent.chunking import ParagraphChunker

    assert ingest(store, source, chunker=ParagraphChunker(size=6)) == original
    assert store.get(Scope(), "docs", "a") is None
    assert store.ingestion_receipt(Scope(), "other", "first") is None
    assert store.ingestion_receipt(Scope("other", "owner"), "docs", "first") is None


def test_changed_command_content_conflicts_and_cas_failure_does_not_save_receipt(store):
    _, dto = api()
    ingest(store)
    with pytest.raises(IdempotencyConflict):
        ingest(store, dto.SourceDocument("a", b"changed"))
    with pytest.raises(KnowledgeVersionConflict):
        ingest(store, command="second")
    assert store.ingestion_receipt(Scope(), "docs", "second") is None
    assert store.get(Scope(), "docs", "a").version == 1


def test_custom_chunker_is_used_atomically_and_locations_are_detached(store):
    _, dto = api()

    class Splitter:
        identity = {"kind": "custom-splitter", "version": "1"}

        def split(self, parsed):
            return (
                dto.ChunkSpan(0, 4, {"part": "first"}),
                dto.ChunkSpan(4, len(parsed.document.text), {"part": "second"}),
            )

    receipt = ingest(store, chunker=Splitter())
    chunks = store.chunks(Scope(), "docs", "a")
    assert [c.text for c in chunks] == ["pool", " diagnosis"]
    assert chunks[0].metadata == {"_chunk": {"part": "first"}}
    receipt.locations[0]["start"] = 100
    assert store.ingestion_receipt(Scope(), "docs", "first").locations[0]["start"] == 0


@pytest.mark.parametrize("kind", ["contextmanager", "generator", "bad-offset", "wrong-identity"])
def test_invalid_custom_completion_does_not_consume_version(store, kind):
    core, dto = api()
    from contextlib import contextmanager

    from ralf_agent.document_parsing import TextDocumentParser

    class Parser(TextDocumentParser):
        identity = {"kind": "custom-parser", "version": "1"}

        def parse(self, source):
            if kind == "contextmanager":
                return contextmanager(lambda: iter(()))()
            if kind == "generator":
                return iter(())
            if kind == "wrong-identity":
                return dto.ParsedDocument(Document("other", "text"), source.sha256)
            return super().parse(source)

    class BadChunker:
        identity = {"kind": "bad-span", "version": "1"}

        def split(self, parsed):
            return (dto.ChunkSpan(0, 999999),)

    options = {"parser": Parser()} if kind != "bad-offset" else {"chunker": BadChunker()}
    with pytest.raises(ValidationError):
        ingest(store, **options)
    assert (
        store.get(Scope(), "docs", "a") is None
        and store.ingestion_receipt(Scope(), "docs", "first") is None
    )


def test_new_ingestion_refuses_legacy_store_before_parser_runs():
    core, dto = api()

    class Legacy:
        backend_id = "legacy"

        def put(self, *args, **kw):
            raise AssertionError("No fallback write")

    with pytest.raises(ValidationError):
        core.IngestionCoordinator(Legacy())


def test_receipt_survives_sqlite_reopen(tmp_path):
    core, dto = api()
    path = tmp_path / "store.sqlite"
    source = dto.SourceDocument("a", b"diagnosis")
    with SQLiteKnowledgeStore(path) as s:
        original = ingest(s, source)
    with SQLiteKnowledgeStore(path) as s:
        assert ingest(s, source) == original


def test_sqlite_failure_after_chunk_write_rolls_back_document_and_receipt(tmp_path):
    core, dto = api()
    with SQLiteKnowledgeStore(tmp_path / "store.sqlite") as s:
        s.store.conn.execute(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON knowledge_ingestions BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        with pytest.raises(MemoryBackendError):
            ingest(s)
        assert s.get(Scope(), "docs", "a") is None
        assert s.chunks(Scope(), "docs", "a") == []
        assert s.ingestion_receipt(Scope(), "docs", "first") is None
        s.store.conn.execute("DROP TRIGGER fail_receipt")
        assert ingest(s).document_version == 1


def test_sqlite_ingestion_rejects_ambient_transaction_before_false_commit_receipt(tmp_path):
    core, dto = api()
    with SQLiteKnowledgeStore(tmp_path / "store.sqlite") as s:
        with s.store.transaction():
            with pytest.raises(ValidationError):
                ingest(s)
        assert s.get(Scope(), "docs", "a") is None


def test_memory_concurrent_identical_command_commits_one_version():
    core, dto = api()
    s = InMemoryKnowledgeStore()
    barrier = threading.Barrier(2)
    results = []

    def run():
        barrier.wait()
        results.append(ingest(s))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert (
        len(results) == 2 and results[0] == results[1] and s.get(Scope(), "docs", "a").version == 1
    )


def test_missing_component_method_is_typed_preflight_error():
    core, _ = api()
    with pytest.raises(ValidationError):
        core.IngestionCoordinator(InMemoryKnowledgeStore(), parser=object())


def test_mutated_chunk_span_is_revalidated_before_write(store):
    core, dto = api()

    class Corrupt:
        identity = {"kind": "corrupt-span", "version": "1"}

        def split(self, parsed):
            span = dto.ChunkSpan(0, len(parsed.document.text))
            object.__setattr__(span, "start", False)
            return (span,)

    with pytest.raises(ValidationError):
        ingest(store, chunker=Corrupt())
    assert store.get(Scope(), "docs", "a") is None


def test_cancelled_wait_after_actual_commit_replays_without_second_write():
    core, dto = api()

    async def run():
        committed = asyncio.Event()

        class Store(InMemoryKnowledgeStore):
            async def ingest(self, *args, **kwargs):
                receipt = super().ingest(*args, **kwargs)
                committed.set()
                await asyncio.Event().wait()
                return receipt

        store = Store()
        coordinator = core.IngestionCoordinator(store)
        source = dto.SourceDocument("a", b"hello")
        task = asyncio.create_task(
            coordinator.ingest(Scope(), "docs", source, command_id="first", expected_version=0)
        )
        await asyncio.wait_for(committed.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        receipt = await coordinator.ingest(
            Scope(), "docs", source, command_id="first", expected_version=0
        )
        assert receipt.document_version == 1 and store.get(Scope(), "docs", "a").version == 1

    asyncio.run(run())


def test_backend_drift_after_await_is_not_confirmed_as_success():
    core, dto = api()

    async def run():
        from ralf_agent.errors import DefinitionMismatch

        class Store(InMemoryKnowledgeStore):
            async def ingest(self, *args, **kwargs):
                receipt = super().ingest(*args, **kwargs)
                await asyncio.sleep(0)
                self.backend_id = "changed"
                return receipt

        store = Store()
        coordinator = core.IngestionCoordinator(store)
        with pytest.raises(DefinitionMismatch):
            await coordinator.ingest(
                Scope(),
                "docs",
                dto.SourceDocument("a", b"hello"),
                command_id="first",
                expected_version=0,
            )
        assert store.get(Scope(), "docs", "a").version == 1

    asyncio.run(run())


def test_default_coordinator_uses_existing_store_chunk_configuration():
    core, dto = api()
    store = InMemoryKnowledgeStore(chunk_size=8, overlap=2)
    ingest(store, dto.SourceDocument("a", b"abcdefghijklmnop"))
    assert [c.text for c in store.chunks(Scope(), "docs", "a")] == ["abcdefgh", "ghijklmn", "mnop"]


def test_store_refuses_executable_prepared_subclass_before_transaction(store):
    _, dto = api()
    from ralf_agent.chunking import CharacterChunker
    from ralf_agent.document_parsing import TextDocumentParser

    class Executable(dto.PreparedIngestion):
        def chunks(self, record):
            raise AssertionError("Plugin code must not run within storage transaction")

    source = dto.SourceDocument("a", b"hello")
    parsed = TextDocumentParser().parse(source)
    prepared = Executable(
        source, parsed, CharacterChunker().split(parsed), {"version": "1"}, expected_version=0
    )
    with pytest.raises(ValidationError):
        store.ingest(Scope(), "docs", prepared, command_id="first")
    assert store.get(Scope(), "docs", "a") is None


def test_parser_method_disappearing_after_parse_is_typed_registration_error(store):
    from ralf_agent.document_parsing import TextDocumentParser
    from ralf_agent.errors import DefinitionMismatch

    class Drift(TextDocumentParser):
        def parse(self, source):
            result = super().parse(source)
            self.parse = None
            return result

    with pytest.raises(DefinitionMismatch):
        ingest(store, parser=Drift())
    assert store.get(Scope(), "docs", "a") is None
