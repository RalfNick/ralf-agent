import asyncio
import importlib

import pytest

from ralf_agent.errors import DefinitionMismatch, MemoryBackendError, ValidationError
from ralf_agent.types import Scope, digest


def api():
    return importlib.import_module("ralf_agent.vector")


@pytest.fixture(params=["memory", "sqlite"])
def index(request, tmp_path):
    module = api()
    backend = (
        module.InMemoryVectorIndex(dimensions=2)
        if request.param == "memory"
        else module.SQLiteVectorIndex(tmp_path / "vectors.db", dimensions=2)
    )
    yield backend
    backend.close()


def test_cosine_ranking_is_real_geometry_and_scope_isolated(index):
    module = api()
    entries = [
        module.VectorEntry("parallel", "a", 1, "a", [1, 0]),
        module.VectorEntry("diagonal", "b", 1, "b", [1, 1]),
        module.VectorEntry("orthogonal", "c", 1, "c", [0, 1]),
    ]
    index.upsert(Scope(), "n", entries)
    index.upsert(
        Scope("foreign", "owner"), "n", [module.VectorEntry("foreign", "f", 1, "f", [1, 0])]
    )
    hits = index.search(Scope(), "n", [1, 0], limit=3)
    assert [hit.chunk_id for hit in hits] == ["parallel", "diagonal", "orthogonal"]
    assert [hit.score for hit in hits] == pytest.approx([1.0, 0.7071067811865475, 0.0])
    assert not hasattr(hits[0], "text")
    assert index.search(Scope(), "other", [1, 0], limit=3) == []
    index.delete_document(Scope(), "n", "a")
    assert [hit.chunk_id for hit in index.search(Scope(), "n", [1, 0], limit=3)] == [
        "diagonal",
        "orthogonal",
    ]


@pytest.mark.parametrize("vector", [[0, 0], [1], [True, 1], [float("nan"), 1], [float("inf"), 1]])
def test_vector_validation_rejects_bad_values_before_writing(index, vector):
    module = api()
    with pytest.raises(ValidationError):
        index.upsert(Scope(), "n", [module.VectorEntry("bad", "a", 1, "x", vector)])
    assert index.search(Scope(), "n", [1, 0], limit=5) == []
    with pytest.raises(ValidationError):
        index.search(Scope(), "n", vector, limit=5)


def test_vector_entry_input_is_detached_and_upsert_replaces_same_identity(index):
    module = api()
    vector = [1, 0]
    entry = module.VectorEntry("a", "doc", 1, "x", vector)
    vector[0] = 0
    index.upsert(Scope(), "n", [entry])
    assert index.search(Scope(), "n", [1, 0], limit=1)[0].score == pytest.approx(1.0)
    index.upsert(Scope(), "n", [module.VectorEntry("a", "doc", 2, "y", [0, 1])])
    hits = index.search(Scope(), "n", [1, 0], limit=5)
    assert len(hits) == 1 and hits[0].version == 2
    assert hits[0].score == pytest.approx(0.0)


class ExplicitEmbedding:
    identity = {"kind": "test-precomputed", "version": "1"}
    dimensions = 2

    async def embed(self, texts):
        table = {"apple": [1.0, 0.0], "banana": [0.0, 1.0], "query": [1.0, 0.0]}
        return [table[text] for text in texts]


def test_vector_retriever_accepts_native_async_callable_embedding(index):
    module = api()
    retrieval = importlib.import_module("ralf_agent.retrieval")

    class Embed:
        async def __call__(self, texts):
            return await ExplicitEmbedding().embed(texts)

    class CallableEmbedding:
        identity = {"kind": "callable-embedding", "version": "1"}
        dimensions = 2
        embed = Embed()

    async def run():
        with retrieval.InMemoryKnowledgeStore() as store:
            store.put(Scope(), "n", retrieval.Document("a", "apple"), expected_version=0)
            store.put(Scope(), "n", retrieval.Document("b", "banana"), expected_version=0)
            retriever = module.VectorRetriever(store, index, CallableEmbedding())
            await retriever.index_document(Scope(), "n", "a")
            await retriever.index_document(Scope(), "n", "b")
            result = await retriever.retrieve(
                Scope(), "n", retrieval.RetrievalQuery("query", limit=1)
            )
            assert [item.document_id for item in result.items] == ["a"]
            assert result.items[0].score == pytest.approx(1.0)
            await retriever.validate(Scope(), "n", result.items)

    asyncio.run(run())


def test_vector_retriever_hydrates_authority_and_never_revives_stale_hits(index):
    module = api()
    retrieval = importlib.import_module("ralf_agent.retrieval")
    with retrieval.InMemoryKnowledgeStore() as store:
        store.put(Scope(), "n", retrieval.Document("a", "apple"), expected_version=0)
        store.put(Scope(), "n", retrieval.Document("b", "banana"), expected_version=0)
        retriever = module.VectorRetriever(store, index, ExplicitEmbedding())
        asyncio.run(retriever.index_document(Scope(), "n", "a"))
        asyncio.run(retriever.index_document(Scope(), "n", "b"))
        result = asyncio.run(retriever.retrieve(Scope(), "n", retrieval.RetrievalQuery("query")))
        assert result.mode == "vector"
        assert [item.document_id for item in result.items] == ["a", "b"]
        assert result.items[0].text == "apple" and result.items[0].score == pytest.approx(1.0)
        store.put(Scope(), "n", retrieval.Document("a", "banana"), expected_version=1)
        store.delete(Scope(), "n", "b", expected_version=1)
        stale = asyncio.run(retriever.retrieve(Scope(), "n", retrieval.RetrievalQuery("query")))
        assert stale.items == ()
        with pytest.raises(ValidationError):
            asyncio.run(retriever.validate(Scope(), "n", result.items))


def test_embedding_model_namespaces_do_not_mix_on_shared_index(index):
    module = api()
    retrieval = importlib.import_module("ralf_agent.retrieval")
    with retrieval.InMemoryKnowledgeStore() as store:
        store.put(Scope(), "n", retrieval.Document("a", "apple"), expected_version=0)
        first = module.VectorRetriever(store, index, ExplicitEmbedding())
        asyncio.run(first.index_document(Scope(), "n", "a"))
        second_embedding = ExplicitEmbedding()
        second_embedding.identity = {"kind": "test-precomputed", "version": "2"}
        second = module.VectorRetriever(store, index, second_embedding)
        assert (
            asyncio.run(second.retrieve(Scope(), "n", retrieval.RetrievalQuery("query"))).items
            == ()
        )


def test_embedding_configuration_change_during_indexing_prevents_index_write(index):
    module = api()
    retrieval = importlib.import_module("ralf_agent.retrieval")

    class ChangingEmbedding(ExplicitEmbedding):
        async def embed(self, texts):
            self.identity = {"kind": "changed", "version": "2"}
            return await super().embed(texts)

    with retrieval.InMemoryKnowledgeStore() as store:
        store.put(Scope(), "n", retrieval.Document("a", "apple"), expected_version=0)
        retriever = module.VectorRetriever(store, index, ChangingEmbedding())
        with pytest.raises(DefinitionMismatch):
            asyncio.run(retriever.index_document(Scope(), "n", "a"))
        assert index.search(Scope(), retriever.index_namespace("n"), [1, 0], limit=5) == []


def test_source_update_during_embedding_prevents_stale_index_write(index):
    module = api()
    retrieval = importlib.import_module("ralf_agent.retrieval")
    with retrieval.InMemoryKnowledgeStore() as store:
        store.put(Scope(), "n", retrieval.Document("a", "apple"), expected_version=0)

        class UpdatingEmbedding(ExplicitEmbedding):
            async def embed(self, texts):
                store.put(Scope(), "n", retrieval.Document("a", "banana"), expected_version=1)
                return await super().embed(texts)

        retriever = module.VectorRetriever(store, index, UpdatingEmbedding())
        with pytest.raises(ValidationError, match="Knowledge source is unavailable"):
            asyncio.run(retriever.index_document(Scope(), "n", "a"))
        assert index.search(Scope(), retriever.index_namespace("n"), [1, 0], limit=5) == []


def test_sqlite_vector_configuration_and_data_survive_reopen(tmp_path):
    module = api()
    path = tmp_path / "vectors.db"
    with module.SQLiteVectorIndex(path, dimensions=2) as index:
        index.upsert(Scope(), "n", [module.VectorEntry("a", "doc", 1, digest("x"), [1, 0])])
    with module.SQLiteVectorIndex(path, dimensions=2) as index:
        assert index.search(Scope(), "n", [1, 0], limit=1)[0].document_id == "doc"
    with pytest.raises(ValidationError):
        module.SQLiteVectorIndex(path, dimensions=3)


def test_indexing_rejects_foreign_document_record_even_if_chunks_look_valid(index):
    module = api()
    retrieval = importlib.import_module("ralf_agent.retrieval")
    with retrieval.InMemoryKnowledgeStore() as store:
        store.put(Scope(), "n", retrieval.Document("a", "apple"), expected_version=0)

        class WrongRecordAuthority:
            backend_id = "wrong-record"

            def get(self, scope, namespace, document_id):
                record = store.get(scope, namespace, document_id)
                return retrieval.DocumentRecord(
                    record.document_id,
                    record.text,
                    record.source_uri,
                    record.metadata,
                    version=record.version,
                    expires_at=record.expires_at,
                    scope=Scope("foreign", "someone"),
                    namespace=namespace,
                )

            def chunks(self, *args):
                return store.chunks(*args)

            def get_chunk(self, *args):
                return store.get_chunk(*args)

        retriever = module.VectorRetriever(WrongRecordAuthority(), index, ExplicitEmbedding())
        with pytest.raises(ValidationError, match="Knowledge source is unavailable"):
            asyncio.run(retriever.index_document(Scope(), "n", "a"))


def test_partial_remote_index_failure_is_repaired_by_explicit_reindex():
    module = api()
    retrieval = importlib.import_module("ralf_agent.retrieval")

    class PartialIndex(module.InMemoryVectorIndex):
        fail = True

        def upsert(self, scope, namespace, entries):
            if self.fail:
                self.fail = False
                super().upsert(scope, namespace, entries[:1])
                raise RuntimeError("partial remote write")
            return super().upsert(scope, namespace, entries)

    class ExplicitTwoChunkEmbedding(ExplicitEmbedding):
        async def embed(self, texts):
            return [[1.0, 0.0] if text in ("apple ", "query") else [0.0, 1.0] for text in texts]

    with retrieval.InMemoryKnowledgeStore(chunk_size=6, overlap=0) as store:
        store.put(Scope(), "n", retrieval.Document("a", "apple banana"), expected_version=0)
        index = PartialIndex(dimensions=2)
        retriever = module.VectorRetriever(store, index, ExplicitTwoChunkEmbedding())
        with pytest.raises(MemoryBackendError, match="backend operation failed"):
            asyncio.run(retriever.index_document(Scope(), "n", "a"))
        query = retrieval.RetrievalQuery("query")
        assert len(asyncio.run(retriever.retrieve(Scope(), "n", query)).items) == 1
        asyncio.run(retriever.index_document(Scope(), "n", "a"))
        assert len(asyncio.run(retriever.retrieve(Scope(), "n", query)).items) == 2


def test_sqlite_vector_search_rejects_replaced_index_file(tmp_path):
    module = api()
    path, replacement = tmp_path / "vectors.db", tmp_path / "replacement.db"
    with module.SQLiteVectorIndex(path, dimensions=2) as original:
        original.upsert(Scope(), "n", [module.VectorEntry("a", "a", 1, "a", [1, 0])])
        with module.SQLiteVectorIndex(replacement, dimensions=2) as other:
            other.upsert(Scope(), "n", [module.VectorEntry("b", "b", 1, "b", [0, 1])])
        replacement.replace(path)
        with pytest.raises(ValidationError):
            original.search(Scope(), "n", [1, 0], limit=5)
