"""Real Redis Facts and configured PostgreSQL Knowledge resource views."""

import asyncio

import pytest

from ralf_agent import Scope
from ralf_agent.errors import AuthorizationDenied
from ralf_agent.recall import RecallQuery
from ralf_agent.retrieval import Document, KnowledgeContext, LexicalRetriever

from .test_data_binding_resources import resources
from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_postgres_adapter import stores
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service


def test_real_redis_facts_namespace_recall_and_foreign_validation(redis_service):
    async def run():
        async with memory_at(redis_service, "data-bindings") as (backend, client):
            for namespace in ("red", "blue"):
                await backend.put_fact(Scope(), namespace, "same", namespace, expected_version=0)
            resource = resources().FactsBindingResource(
                backend, namespaces=("red", "blue"), default_namespace="red"
            )
            red = resource.select({}, Scope())
            blue = resource.select({"namespace": "blue"}, Scope())
            page = await red.recall(Scope(), "logical", RecallQuery())
            assert page.items[0]["value"] == "red"
            assert (await blue.facts(Scope(), "logical"))[0]["value"] == "blue"
            assert await red.validate_facts(Scope(), "logical", page.items) is None
            with pytest.raises(AuthorizationDenied):
                await blue.validate_facts(Scope(), "logical", page.items)

    asyncio.run(run())


def test_real_postgres_knowledge_namespace_sources(postgres_dsn):
    async def run():
        async with stores(postgres_dsn) as (memory, docs):
            for namespace in ("red", "blue"):
                await docs.put(
                    Scope(), namespace, Document("same", "pool " + namespace), expected_version=0
                )
            resource = resources().KnowledgeBindingResource(
                KnowledgeContext(LexicalRetriever(docs)),
                namespaces=("red", "blue"),
                default_namespace="red",
            )
            red = resource.select({}, Scope())
            blue = resource.select({"namespace": "blue"}, Scope())
            references = await red.references(Scope(), "pool")
            assert references[0]["value"]["text"] == "pool red"
            assert (await blue.references(Scope(), "pool"))[0]["value"]["text"] == "pool blue"
            assert await red.validate(Scope(), references) is None

    asyncio.run(run())
