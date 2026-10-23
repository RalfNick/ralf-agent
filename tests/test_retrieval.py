import asyncio
import importlib
import time

import pytest

from relf_agent.errors import ValidationError
from relf_agent.storage import SQLiteStore
from relf_agent.types import Scope, canonical


@pytest.mark.parametrize("configuration", [{"limit": 10**100}, {"max_chars": 1}])
def test_query_rejects_unrepresentable_limits_before_backend_access(configuration):
    from relf_agent.retrieval import RetrievalQuery

    with pytest.raises(ValidationError):
        RetrievalQuery("cache", **configuration)


def api():
    return importlib.import_module("relf_agent.retrieval")


@pytest.fixture(params=["memory", "sqlite"])
def knowledge(request, tmp_path):
    module = api()
    store = (
        module.InMemoryKnowledgeStore(chunk_size=8, overlap=2)
        if request.param == "memory"
        else module.SQLiteKnowledgeStore(tmp_path / "knowledge.db", chunk_size=8, overlap=2)
    )
    yield store
    store.close()


def test_document_metadata_is_finite_and_detached():
    module = api()
    metadata = {"nested": {"tag": "original"}}
    document = module.Document("runbook", "restart safely", metadata=metadata)
    metadata["nested"]["tag"] = "changed"
    document.metadata["nested"]["tag"] = "changed again"
    assert document.metadata == {"nested": {"tag": "original"}}
    with pytest.raises(ValidationError):
        module.Document("bad", "x", metadata={"number": float("nan")})


def test_chunks_preserve_overlap_scope_and_source_provenance(knowledge):
    module = api()
    scope = Scope("ops", "alice")
    assert (
        knowledge.put(
            scope,
            "books",
            module.Document("a", "abcdefghijklmnop", "runbook:a", {"kind": "ops"}),
            expected_version=0,
        )
        == 1
    )
    chunks = knowledge.chunks(scope, "books", "a")
    assert [chunk.text for chunk in chunks] == ["abcdefgh", "ghijklmn", "mnop"]
    assert len({chunk.chunk_id for chunk in chunks}) == 3
    assert all(chunk.scope == scope and chunk.namespace == "books" for chunk in chunks)
    assert all(chunk.source_uri == "runbook:a" and chunk.version == 1 for chunk in chunks)
    assert chunks[0].metadata == {"kind": "ops"}
    chunks[0].metadata["kind"] = "changed"
    assert knowledge.get_chunk(scope, "books", chunks[0].chunk_id).metadata == {"kind": "ops"}
    assert knowledge.get(scope, "other", "a") is None
    assert knowledge.chunks(Scope("ops", "bob"), "books", "a") == []


def test_updates_and_soft_delete_keep_cas_versions_and_invalidate_old_chunks(knowledge):
    module = api()
    scope = Scope()
    knowledge.put(scope, "n", module.Document("a", "old content"), expected_version=0)
    old_chunk = knowledge.chunks(scope, "n", "a")[0]
    with pytest.raises(module.KnowledgeVersionConflict):
        knowledge.put(scope, "n", module.Document("a", "bad update"), expected_version=0)
    assert knowledge.put(scope, "n", module.Document("a", "new content"), expected_version=1) == 2
    assert knowledge.get_chunk(scope, "n", old_chunk.chunk_id) is None
    assert knowledge.get(scope, "n", "a").text == "new content"
    assert knowledge.delete(scope, "n", "a", expected_version=2) == 3
    assert knowledge.get(scope, "n", "a") is None
    assert knowledge.chunks(scope, "n", "a") == []
    with pytest.raises(module.KnowledgeVersionConflict):
        knowledge.put(scope, "n", module.Document("a", "resurrect"), expected_version=0)
    assert (
        knowledge.put(scope, "n", module.Document("a", "explicit restore"), expected_version=3) == 4
    )


def test_missing_document_delete_creates_versioned_tombstone(knowledge):
    module = api()
    assert knowledge.delete(Scope(), "n", "missing", expected_version=0) == 1
    with pytest.raises(module.KnowledgeVersionConflict):
        knowledge.put(Scope(), "n", module.Document("missing", "late"), expected_version=0)


@pytest.mark.parametrize("expires_at", [True, "tomorrow", float("nan"), float("inf")])
def test_invalid_ttl_never_consumes_document_version(knowledge, expires_at):
    module = api()
    with pytest.raises(ValidationError):
        knowledge.put(
            Scope(), "n", module.Document("a", "x"), expected_version=0, expires_at=expires_at
        )
    assert knowledge.put(Scope(), "n", module.Document("a", "x"), expected_version=0) == 1


def test_expired_document_hides_authoritative_chunks_and_lexical_hits(knowledge):
    module = api()
    scope = Scope()
    knowledge.put(
        scope,
        "n",
        module.Document("a", "checkout"),
        expected_version=0,
        expires_at=time.time() - 1,
    )
    assert knowledge.get(scope, "n", "a") is None
    assert knowledge.chunks(scope, "n", "a") == []
    assert knowledge.lexical(scope, "n", module.RetrievalQuery("checkout")).items == ()
    assert knowledge.put(scope, "n", module.Document("a", "live"), expected_version=1) == 2


def test_lexical_search_filters_scope_namespace_and_returns_honest_mode(tmp_path):
    module = api()
    for factory in (module.InMemoryKnowledgeStore, module.SQLiteKnowledgeStore):
        store = (
            factory() if factory is module.InMemoryKnowledgeStore else factory(tmp_path / "lex.db")
        )
        with store:
            scope = Scope("ops", "alice")
            store.put(
                scope, "books", module.Document("rank-1", "checkout incident"), expected_version=0
            )
            store.put(scope, "books", module.Document("rank-2", "checkout"), expected_version=0)
            store.put(
                scope, "other", module.Document("foreign", "checkout incident"), expected_version=0
            )
            store.put(
                Scope("ops", "bob"),
                "books",
                module.Document("private", "checkout incident"),
                expected_version=0,
            )
            result = store.lexical(scope, "books", module.RetrievalQuery("checkout incident"))
            assert [item.document_id for item in result.items] == ["rank-1", "rank-2"]
            assert [item.score for item in result.items] == [2.0, 1.0]
            assert result.mode == "lexical"


def test_chinese_bigrams_retrieve_literal_matching_text(knowledge):
    module = api()
    knowledge.put(Scope(), "n", module.Document("a", "支付故障处理"), expected_version=0)
    result = knowledge.lexical(Scope(), "n", module.RetrievalQuery("故障处理"))
    assert [item.document_id for item in result.items] == ["a"]
    assert result.items[0].score == 3.0


def test_lexical_character_budget_skips_oversized_hit_without_truncating(tmp_path):
    module = api()
    with module.SQLiteKnowledgeStore(tmp_path / "budget.db", chunk_size=4000, overlap=0) as store:
        store.put(
            Scope(), "n", module.Document("large", "checkout " + "x" * 2000), expected_version=0
        )
        store.put(Scope(), "n", module.Document("small", "checkout"), expected_version=0)
        result = store.lexical(Scope(), "n", module.RetrievalQuery("checkout", max_chars=600))
        assert [item.document_id for item in result.items] == ["small"]
        assert result.items[0].text == "checkout"
        assert 0 < result.used_chars <= 600


def test_sqlite_authority_survives_reopen_and_borrowed_store_is_not_closed(tmp_path):
    module = api()
    path = tmp_path / "persist.db"
    with module.SQLiteKnowledgeStore(path) as store:
        store.put(Scope(), "n", module.Document("a", "checkout"), expected_version=0)
    execution = SQLiteStore(path)
    borrowed = module.SQLiteKnowledgeStore(execution)
    assert borrowed.get(Scope(), "n", "a").version == 1
    borrowed.close()
    assert execution.conn.execute("SELECT 1").fetchone()[0] == 1
    execution.close()


def test_knowledge_context_revalidates_persisted_refs_without_retrieving(knowledge):
    module = api()
    scope = Scope("ops", "alice")
    knowledge.put(scope, "books", module.Document("a", "checkout", "runbook:a"), expected_version=0)
    context = module.KnowledgeContext(module.LexicalRetriever(knowledge), namespace="books")
    refs = asyncio.run(context.references(scope, "checkout"))
    assert refs[0]["value"] == {
        "text": "checkout",
        "document_id": "a",
        "source_uri": "runbook:a",
        "metadata": {},
    }
    assert refs[0]["_knowledge"]["scope"] == {"workspace": "ops", "principal": "alice"}
    assert refs[0]["version"] == 1
    canonical(refs)
    asyncio.run(context.validate(scope, refs))
    knowledge.put(scope, "books", module.Document("a", "new checkout"), expected_version=1)
    with pytest.raises(ValidationError, match="Knowledge source is unavailable"):
        asyncio.run(context.validate(scope, refs))


def test_context_rejects_tampered_or_foreign_reference(knowledge):
    module = api()
    scope = Scope()
    knowledge.put(scope, "n", module.Document("a", "checkout"), expected_version=0)
    context = module.KnowledgeContext(module.LexicalRetriever(knowledge), namespace="n")
    refs = asyncio.run(context.references(scope, "checkout"))
    refs[0]["value"]["text"] = "injected"
    with pytest.raises(ValidationError):
        asyncio.run(context.validate(scope, refs))
    refs = asyncio.run(context.references(scope, "checkout"))
    with pytest.raises(ValidationError):
        asyncio.run(context.validate(Scope("other", "local-owner"), refs))


def test_async_authority_port_is_supported_without_threading(knowledge):
    module = api()

    class AsyncAuthority:
        backend_id = "async:knowledge"

        async def lexical(self, scope, namespace, query):
            await asyncio.sleep(0)
            return knowledge.lexical(scope, namespace, query)

        async def get_chunk(self, scope, namespace, chunk_id):
            await asyncio.sleep(0)
            return knowledge.get_chunk(scope, namespace, chunk_id)

    knowledge.put(Scope(), "n", module.Document("a", "checkout"), expected_version=0)
    context = module.KnowledgeContext(module.LexicalRetriever(AsyncAuthority()), namespace="n")
    refs = asyncio.run(context.references(Scope(), "checkout"))
    asyncio.run(context.validate(Scope(), refs))
    assert refs[0]["value"]["document_id"] == "a"


def test_actual_authority_change_cannot_hide_behind_replacement(knowledge):
    module = api()
    from relf_agent.errors import DefinitionMismatch

    knowledge.put(Scope(), "n", module.Document("a", "checkout"), expected_version=0)

    class ChangingAuthority:
        backend_id = "authority:v1"

        async def lexical(self, scope, namespace, query):
            self.backend_id = "authority:v2"
            retriever.store = ReplacementAuthority()
            return knowledge.lexical(scope, namespace, query)

        async def get_chunk(self, *args):
            return knowledge.get_chunk(*args)

    class ReplacementAuthority(ChangingAuthority):
        backend_id = "authority:v1"

    retriever = module.LexicalRetriever(ChangingAuthority())
    with pytest.raises(DefinitionMismatch):
        asyncio.run(retriever.retrieve(Scope(), "n", module.RetrievalQuery("checkout")))


def test_actual_retriever_change_cannot_hide_behind_facade_replacement(knowledge):
    module = api()
    from relf_agent.errors import DefinitionMismatch

    knowledge.put(Scope(), "n", module.Document("a", "checkout"), expected_version=0)

    class ChangingRetriever:
        identity = {"kind": "custom", "version": "1"}

        async def retrieve(self, scope, namespace, query):
            self.identity = {"kind": "custom", "version": "2"}
            context.retriever = ReplacementRetriever()
            return knowledge.lexical(scope, namespace, query)

        async def validate(self, scope, namespace, items):
            return None

    class ReplacementRetriever(ChangingRetriever):
        identity = {"kind": "custom", "version": "1"}

    context = module.KnowledgeContext(ChangingRetriever(), namespace="n")
    with pytest.raises(DefinitionMismatch):
        asyncio.run(context.references(Scope(), "checkout"))


def test_facade_rejects_invalid_scope_before_calling_custom_retriever():
    module = api()

    class Retriever:
        identity = {"kind": "empty", "version": "1"}
        called = False

        async def retrieve(self, scope, namespace, query):
            self.called = True
            return module.RetrievalResult((), "lexical", 0)

        async def validate(self, scope, namespace, items):
            return None

    retriever = Retriever()
    with pytest.raises(ValidationError):
        asyncio.run(module.KnowledgeContext(retriever).references({}, "query"))
    assert not retriever.called


def test_sqlite_read_rejects_replaced_authority_file(tmp_path):
    module = api()
    path, replacement = tmp_path / "authority.db", tmp_path / "replacement.db"
    with module.SQLiteKnowledgeStore(path) as original:
        original.put(Scope(), "n", module.Document("a", "old checkout"), expected_version=0)
        with module.SQLiteKnowledgeStore(replacement) as other:
            other.put(Scope(), "n", module.Document("a", "new checkout"), expected_version=0)
        replacement.replace(path)
        with pytest.raises(ValidationError):
            original.get(Scope(), "n", "a")
