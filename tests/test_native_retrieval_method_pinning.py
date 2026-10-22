import asyncio

import pytest

from ralf_agent import (
    Document,
    HashEmbeddingProvider,
    HybridRetriever,
    InMemoryKnowledgeStore,
    InMemoryVectorIndex,
    KnowledgeContext,
    LexicalRetriever,
    LocalEngine,
    ModelResponse,
    RetrievalQuery,
    Scope,
    SQLiteStore,
    ToolRegistry,
    VectorRetriever,
)
from ralf_agent.errors import DefinitionMismatch, ValidationError


def setup_retriever(kind, store):
    if kind == "lexical":
        return LexicalRetriever(store)
    if kind == "hybrid":
        return HybridRetriever(store, {"lexical": LexicalRetriever(store)})
    return VectorRetriever(
        store, InMemoryVectorIndex(dimensions=8), HashEmbeddingProvider(dimensions=8)
    )


@pytest.mark.parametrize("kind", ["lexical", "vector", "hybrid"])
@pytest.mark.parametrize("during_await", [False, True])
def test_native_source_method_replacement_cannot_accept_stale_reference(kind, during_await):
    async def run():
        scope = Scope()
        store = InMemoryKnowledgeStore(backend_id="original-source")
        store.put(scope, "manuals", Document("guide", "pool OLD_SOURCE"), expected_version=0)
        original = store.get_chunk
        entered, release = asyncio.Event(), asyncio.Event()
        hold = False

        async def suspended_read(*args):
            value = original(*args)
            if hold:
                entered.set()
                await release.wait()
            return value

        store.get_chunk = suspended_read
        retriever = setup_retriever(kind, store)
        if kind == "vector":
            await retriever.index_document(scope, "manuals", "guide")
        context = KnowledgeContext(retriever, namespace="manuals")
        identity = context.identity
        references = await context.references(scope, "pool")
        assert references
        old_chunk = original(scope, "manuals", references[0]["_knowledge"]["chunk_id"])
        if during_await:
            hold = True
            task = asyncio.create_task(context.validate(scope, references))
            await entered.wait()
        store.put(scope, "manuals", Document("guide", "pool NEW_SOURCE"), expected_version=1)
        if not during_await:
            with pytest.raises(ValidationError):
                await context.validate(scope, references)
        store.get_chunk = lambda *args: old_chunk
        release.set()
        with pytest.raises(DefinitionMismatch):
            if during_await:
                await task
            else:
                await context.validate(scope, references)
        assert context.identity == identity
        assert store.get(scope, "manuals", "guide").version == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    ("component", "method"),
    [
        ("store", "get"),
        ("store", "chunks"),
        ("index", "upsert"),
        ("index", "delete_document"),
        ("index", "search"),
        ("embedding", "embed"),
    ],
)
def test_vector_registered_port_drift_refuses_before_dispatch(component, method):
    async def run():
        store = InMemoryKnowledgeStore()
        retriever = setup_retriever("vector", store)

        def unexpected(*args, **kwargs):
            raise AssertionError("Replaced port must not execute")

        setattr(getattr(retriever, component), method, unexpected)
        with pytest.raises(DefinitionMismatch):
            await retriever.retrieve(Scope(), "manuals", RetrievalQuery("pool"))

    asyncio.run(run())


def test_engine_refuses_changed_source_port_before_disclosing_old_evidence(tmp_path):
    from ralf_agent import AgentSpec

    async def run():
        source = InMemoryKnowledgeStore()
        source.put(Scope(), "manuals", Document("guide", "pool OLD_SOURCE"), expected_version=0)
        old_chunk = source.chunks(Scope(), "manuals", "guide")[0]
        entered, release = asyncio.Event(), asyncio.Event()

        class PausedContext(KnowledgeContext):
            async def references(self, scope, text):
                references = await super().references(scope, text)
                entered.set()
                await release.wait()
                return references

        class Provider:
            identity = {"kind": "no-stale-disclosure", "version": "1"}
            calls = 0

            async def complete(self, messages, tools):
                self.calls += 1
                return ModelResponse(output="done")

        provider = Provider()
        context = PausedContext(LexicalRetriever(source), namespace="manuals")
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": provider},
            tools=ToolRegistry(),
            knowledge=context,
        ) as engine:
            handle = engine.submit(AgentSpec("a", "Use current sources"), "pool", command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await entered.wait()
            source.put(Scope(), "manuals", Document("guide", "pool NEW_SOURCE"), expected_version=1)
            source.get_chunk = lambda *args: old_chunk
            release.set()
            snapshot = await task
            assert snapshot.state == "failed"
            assert provider.calls == 0

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["lexical", "vector", "hybrid"])
def test_each_source_read_refuses_drift_before_dispatching_the_next_chunk(kind):
    async def run():
        store = InMemoryKnowledgeStore()
        for document in ("one", "two"):
            store.put(Scope(), "manuals", Document(document, "pool guide"), expected_version=0)
        original = store.get_chunk
        entered, release = asyncio.Event(), asyncio.Event()
        replacement_calls = []

        async def read(*args):
            result = original(*args)
            entered.set()
            await release.wait()
            return result

        def replaced(*args):
            replacement_calls.append(args)
            return original(*args)

        store.get_chunk = read
        retriever = setup_retriever(kind, store)
        chunks = tuple(store.chunks(Scope(), "manuals", name)[0] for name in ("one", "two"))
        task = asyncio.create_task(retriever.validate(Scope(), "manuals", chunks))
        await entered.wait()
        store.get_chunk = replaced
        release.set()
        with pytest.raises(DefinitionMismatch):
            await task
        assert replacement_calls == []

    asyncio.run(run())


def test_index_validation_refuses_drift_before_the_final_document_read():
    async def run():
        store = InMemoryKnowledgeStore()
        store.put(Scope(), "manuals", Document("guide", "pool guide"), expected_version=0)
        original_chunk, original_get = store.get_chunk, store.get
        entered, release = asyncio.Event(), asyncio.Event()
        replacement_calls = []

        async def read(*args):
            result = original_chunk(*args)
            entered.set()
            await release.wait()
            return result

        def replaced(*args):
            replacement_calls.append(args)
            return original_get(*args)

        store.get_chunk = read
        retriever = setup_retriever("vector", store)
        task = asyncio.create_task(retriever.index_document(Scope(), "manuals", "guide"))
        await entered.wait()
        store.get = replaced
        release.set()
        with pytest.raises(DefinitionMismatch):
            await task
        assert replacement_calls == []

    asyncio.run(run())
