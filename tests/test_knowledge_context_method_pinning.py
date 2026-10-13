import asyncio
import copy
from dataclasses import asdict

import pytest

from ralf_agent import (
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
    Scope,
)
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.types import canonical


@pytest.mark.parametrize("operation", ["retrieve", "validate"])
@pytest.mark.parametrize("during_await", [False, True])
def test_knowledge_context_rejects_method_replacement_without_identity_change(
    operation, during_await
):
    async def run():
        store = InMemoryKnowledgeStore(backend_id="pin-source")
        store.put(Scope(), "manuals", Document("guide", "connection pool"), expected_version=0)
        entered, release = asyncio.Event(), asyncio.Event()

        class Retriever:
            identity = {"kind": "external-method-pin", "version": "1"}

            async def retrieve(self, *args):
                result = await LexicalRetriever(store).retrieve(*args)
                if operation == "retrieve" and during_await:
                    entered.set()
                    await release.wait()
                return result

            async def validate(self, *args):
                await LexicalRetriever(store).validate(*args)
                if operation == "validate" and during_await:
                    entered.set()
                    await release.wait()

        retriever = Retriever()
        context = KnowledgeContext(retriever, namespace="manuals")
        original_identity = context.identity
        references = await context.references(Scope(), "pool") if operation == "validate" else None

        async def replacement(*args):
            return None

        async def operate():
            if operation == "retrieve":
                return await context.references(Scope(), "pool")
            return await context.validate(Scope(), references)

        if during_await:
            task = asyncio.create_task(operate())
            await entered.wait()
            setattr(retriever, operation, replacement)
            release.set()
            with pytest.raises(DefinitionMismatch):
                await task
        else:
            setattr(retriever, operation, replacement)
            with pytest.raises(DefinitionMismatch):
                await operate()
        assert context.identity == original_identity

    asyncio.run(run())


def test_knowledge_context_rejects_in_place_callable_body_change():
    class Read:
        def __call__(self, *args):
            return RetrievalResult((), "external", 0)

    class Retriever:
        identity = {"kind": "callable-body", "version": "1"}
        retrieve = Read()

        def validate(self, *args):
            return None

    context = KnowledgeContext(Retriever())
    original = Read.__call__.__code__

    def replacement(self, *args):
        return None

    try:
        Read.__call__.__code__ = replacement.__code__
        with pytest.raises(DefinitionMismatch):
            asyncio.run(context.references(Scope(), "pool"))
    finally:
        Read.__call__.__code__ = original


def test_knowledge_context_keeps_sync_callable_ports_and_identity_bytes():
    class CallableRetriever:
        identity = {"kind": "callable-source", "version": "1"}

        def __init__(self):
            from ralf_agent import RetrievalResult

            self.retrieve = lambda *args: RetrievalResult((), "external", 0)
            self.validate = lambda *args: None

    context = KnowledgeContext(CallableRetriever(), namespace="manuals", limit=2, max_chars=900)
    assert context.identity == {
        "kind": "knowledge-context",
        "version": "1",
        "retriever": {"kind": "callable-source", "version": "1"},
        "namespace": "manuals",
        "limit": 2,
        "max_chars": 900,
    }

    async def run():
        assert await context.references(Scope(), "pool") == []
        assert await context.validate(Scope(), []) is None

    asyncio.run(run())


def test_knowledge_context_rejects_query_budget_change_before_disclosing_large_source():
    class Retriever:
        identity = {"kind": "query-budget-context", "version": "1"}

        async def retrieve(self, scope, namespace, query):
            object.__setattr__(query, "max_chars", 20000)
            item = RetrievedChunk(
                "guide",
                "chunk",
                1,
                "x" * 2000,
                "fixture://guide",
                {},
                None,
                scope,
                namespace,
                1,
            )
            return RetrievalResult((item,), "external", len(canonical([asdict(item)])))

        async def validate(self, *args):
            return None

    context = KnowledgeContext(Retriever(), limit=1, max_chars=400)
    with pytest.raises(DefinitionMismatch):
        asyncio.run(context.references(Scope(), "query"))
    assert context.max_chars == 400


@pytest.mark.parametrize("field", ["text", "limit", "max_chars"])
@pytest.mark.parametrize("after_await", [False, True])
def test_knowledge_context_rejects_changed_original_query_parameters(field, after_await):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Retriever:
            identity = {"kind": "query-parameter-context", "version": "1"}

            async def retrieve(self, scope, namespace, query):
                if after_await:
                    entered.set()
                    await release.wait()
                value = {"text": "different query", "limit": 99, "max_chars": 100000}[field]
                object.__setattr__(query, field, value)
                return RetrievalResult((), "external", 0)

            async def validate(self, *args):
                return None

        context = KnowledgeContext(Retriever())
        task = asyncio.create_task(context.references(Scope(), "original query"))
        if after_await:
            await asyncio.wait_for(entered.wait(), timeout=2)
            release.set()
        with pytest.raises(DefinitionMismatch):
            await task

    asyncio.run(run())


def test_retrieval_query_original_fields_keep_public_wire_and_copy_compatibility():
    query = RetrievalQuery("original", 2, 999)
    expected = {"text": "original", "limit": 2, "max_chars": 999}
    assert asdict(query) == expected
    assert repr(query) == "RetrievalQuery(text='original', limit=2, max_chars=999)"
    assert asdict(copy.copy(query)) == asdict(copy.deepcopy(query)) == expected
    assert RetrievalQuery(**expected) == query


@pytest.mark.parametrize(("field", "value"), [("limit", True), ("max_chars", 8000.0)])
def test_knowledge_query_pin_does_not_confuse_equal_numeric_types(field, value):
    class Retriever:
        identity = {"kind": "query-numeric-type", "version": "1"}

        async def retrieve(self, scope, namespace, query):
            object.__setattr__(query, field, value)
            return RetrievalResult((), "external", 0)

        async def validate(self, *args):
            return None

    with pytest.raises(DefinitionMismatch):
        asyncio.run(KnowledgeContext(Retriever(), limit=1).references(Scope(), "query"))
