import asyncio
import time
from dataclasses import replace

import pytest

from relf_agent import Document, InMemoryKnowledgeStore, LexicalRetriever, RetrievalQuery, Scope
from relf_agent.errors import DefinitionMismatch, ProviderError, ValidationError


def source():
    store = InMemoryKnowledgeStore()
    for key, text in (("a", "automobile"), ("b", "car")):
        store.put(Scope(), "docs", Document(key, text), expected_version=0)
    return store, LexicalRetriever(store)


def test_query_expansion_retrieves_synonym_and_keeps_original_output_bounds():
    from relf_agent import AliasQueryTransform, QueryTransformRetriever

    async def run():
        store, base = source()
        retriever = QueryTransformRetriever(base, AliasQueryTransform({"car": "automobile"}))
        result = await retriever.retrieve(Scope(), "docs", RetrievalQuery("car", 2, 8000))
        assert [c.document_id for c in result.items] == ["b", "a"]
        assert [c.text for c in result.items] == ["car", "automobile"]
        await retriever.validate(Scope(), "docs", result.items)
        small = await retriever.retrieve(Scope(), "docs", RetrievalQuery("car", 1, 8000))
        assert len(small.items) == 1 and small.items[0].document_id == "b"
        store.put(Scope(), "docs", Document("a", "changed"), expected_version=1)
        with pytest.raises(ValidationError):
            await retriever.validate(Scope(), "docs", result.items)

    asyncio.run(run())


@pytest.mark.parametrize(
    "value", ["car", (), ("car", "car"), ("",), (True,), tuple(map(str, range(5))), ("\ud800",)]
)
def test_invalid_transform_outputs_never_reach_source(value):
    from relf_agent import QueryTransformRetriever

    class Transform:
        identity = {"kind": "fixture", "version": "1"}

        def transform(self, text):
            return value

    async def run():
        _, base = source()

        async def forbidden(*args):
            raise AssertionError("Invalid proposal was dispatched")

        base.retrieve = forbidden
        retriever = QueryTransformRetriever(base, Transform())
        with pytest.raises(ValidationError):
            await retriever.retrieve(Scope(), "docs", RetrievalQuery("car"))

    asyncio.run(run())


def test_sync_transform_returning_coroutine_is_rejected():
    from relf_agent import QueryTransformRetriever

    class Transform:
        identity = {"kind": "fixture", "version": "1"}

        def transform(self, text):
            async def pending():
                raise AssertionError("Lazy synchronous transform executed")

            return pending()

    async def run():
        _, base = source()
        with pytest.raises(ValidationError):
            await QueryTransformRetriever(base, Transform()).retrieve(
                Scope(), "docs", RetrievalQuery("car")
            )

    asyncio.run(run())


@pytest.mark.parametrize("change", ["source", "method", "transform"])
def test_async_transform_drift_rejects_before_source_dispatch(change):
    from relf_agent import QueryTransformRetriever

    async def run():
        _, base = source()
        wrapper = None

        class Transform:
            identity = {"kind": "fixture", "version": "1"}

            async def transform(self, text):
                if change == "source":
                    wrapper.retriever = source()[1]
                elif change == "method":
                    base.retrieve = lambda *a: None
                else:
                    self.transform = lambda text: (text,)
                await asyncio.sleep(0)
                return (text,)

        wrapper = QueryTransformRetriever(base, Transform())
        with pytest.raises(DefinitionMismatch):
            await wrapper.retrieve(Scope(), "docs", RetrievalQuery("car"))

    asyncio.run(run())


def test_previous_candidates_are_validated_again_after_later_query_await():
    from relf_agent import AliasQueryTransform, QueryTransformRetriever

    async def run():
        store, base = source()
        original = base.retrieve

        async def updating(scope, namespace, query):
            if query.text == "automobile":
                store.put(scope, namespace, Document("b", "changed"), expected_version=1)
            return await original(scope, namespace, query)

        base.retrieve = updating
        wrapper = QueryTransformRetriever(base, AliasQueryTransform({"car": "automobile"}))
        with pytest.raises(ValidationError):
            await wrapper.retrieve(Scope(), "docs", RetrievalQuery("car"))

    asyncio.run(run())


def test_malformed_child_result_and_failure_do_not_degrade():
    from relf_agent import QueryTransformRetriever

    async def run():
        _, base = source()
        original = base.retrieve

        async def invalid(scope, namespace, query):
            result = await original(scope, namespace, query)
            return replace(result, used_chars=0)

        base.retrieve = invalid
        with pytest.raises(ValidationError):
            await QueryTransformRetriever(base).retrieve(Scope(), "docs", RetrievalQuery("car"))

        async def fail(*args):
            raise ProviderError("fixture unavailable")

        base.retrieve = fail
        with pytest.raises(ProviderError):
            await QueryTransformRetriever(base).retrieve(Scope(), "docs", RetrievalQuery("car"))

    asyncio.run(run())


@pytest.mark.parametrize(
    "options",
    [
        {"max_candidates": True},
        {"max_candidates": 257},
        {"max_candidate_chars": 7},
        {"max_candidate_chars": 262145},
    ],
)
def test_invalid_fanout_bounds_are_rejected(options):
    from relf_agent import QueryTransformRetriever

    with pytest.raises(ValidationError):
        QueryTransformRetriever(source()[1], **options)


def test_multiquery_budget_and_duplicate_source_conflicts_cannot_expand_evidence():
    from relf_agent import QueryTransformRetriever

    class Transform:
        identity = {"kind": "fixture", "version": "1"}

        def transform(self, text):
            return ("car", "automobile")

    async def run():
        _, base = source()
        original = base.retrieve

        async def forged(scope, namespace, query):
            if query.text == "automobile":
                result = await original(
                    scope, namespace, RetrievalQuery("car", query.limit, query.max_chars)
                )
                return replace(result, items=(replace(result.items[0], text="bus"),))
            return await original(scope, namespace, query)

        base.retrieve = forged
        with pytest.raises(ValidationError):
            await QueryTransformRetriever(base, Transform()).retrieve(
                Scope(), "docs", RetrievalQuery("car", 2, 8000)
            )

    asyncio.run(run())


def test_earlier_candidate_expiry_during_later_validation_prevents_disclosure():
    from relf_agent import QueryTransformRetriever

    async def run():
        store, base = source()
        store.put(
            Scope(),
            "docs",
            Document("a", "car first"),
            expected_version=1,
            expires_at=time.time() + 0.15,
        )
        original = base.validate

        async def slow(scope, namespace, items):
            if items[0].document_id == "b":
                await asyncio.sleep(0.25)
            await original(scope, namespace, items)

        base.validate = slow
        with pytest.raises(ValidationError):
            await QueryTransformRetriever(base).retrieve(Scope(), "docs", RetrievalQuery("car"))

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        "lexical-store",
        "store-method",
        "vector-store",
        "vector-index",
        "vector-embedding",
        "hybrid-branch",
        "nested",
    ],
)
def test_same_identity_native_resources_cannot_change_during_transform(change):
    from relf_agent import (
        HashEmbeddingProvider,
        HybridRetriever,
        InMemoryVectorIndex,
        QueryTransformRetriever,
        VectorRetriever,
    )

    async def run():
        store, lexical = source()
        replacement = InMemoryKnowledgeStore(backend_id=store.backend_id)
        replacement.put(Scope(), "docs", Document("x", "car replacement"), expected_version=0)
        index = InMemoryVectorIndex(dimensions=2)
        embedding = HashEmbeddingProvider(dimensions=2)
        vector = VectorRetriever(store, index, embedding)
        base = lexical
        if change.startswith("vector"):
            base = vector
        elif change == "hybrid-branch":
            base = HybridRetriever(store, {"lexical": lexical})
        elif change == "nested":
            base = QueryTransformRetriever(lexical)

        class Transform:
            identity = {"kind": "native-resource-drift", "version": "1"}

            async def transform(self, text):
                if change in {"lexical-store", "hybrid-branch", "nested"}:
                    lexical.store = replacement
                elif change == "store-method":
                    store.get_chunk = replacement.get_chunk
                elif change == "vector-store":
                    vector.store = replacement
                elif change == "vector-index":
                    vector.index = InMemoryVectorIndex(dimensions=2, backend_id=index.backend_id)
                else:
                    vector.embedding = HashEmbeddingProvider(dimensions=2)
                await asyncio.sleep(0)
                return (text,)

        with pytest.raises(DefinitionMismatch):
            await QueryTransformRetriever(base, Transform()).retrieve(
                Scope(), "docs", RetrievalQuery("car")
            )

    asyncio.run(run())


def test_mutating_validator_cannot_validate_current_body_and_disclose_stale_body():
    from dataclasses import asdict

    from relf_agent import QueryTransformRetriever

    async def run():
        store, base = source()
        original_retrieve, original_validate = base.retrieve, base.validate

        async def changing(scope, namespace, query):
            result = await original_retrieve(scope, namespace, query)
            store.put(scope, namespace, Document("b", "car new"), expected_version=1)
            return result

        async def refresh(scope, namespace, items):
            current = (await original_retrieve(scope, namespace, RetrievalQuery("car"))).items[0]
            for key, value in asdict(current).items():
                if key != "scope":
                    object.__setattr__(items[0], key, value)
            await original_validate(scope, namespace, items)

        base.retrieve, base.validate = changing, refresh
        with pytest.raises(ValidationError):
            await QueryTransformRetriever(base).retrieve(Scope(), "docs", RetrievalQuery("car"))

    asyncio.run(run())
