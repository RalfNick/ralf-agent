"""Scoped data views on real storage/retrieval ports and adversarial async boundaries."""

import asyncio
import importlib
from dataclasses import FrozenInstanceError, replace

import pytest

from relf_agent import BindingCatalog, BindingSelection, InMemoryMemory, Scope, SQLiteMemory
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.recall import RecallPage, RecallQuery
from relf_agent.retrieval import (
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
)
from relf_agent.types import canonical


def resources():
    try:
        return importlib.import_module("relf_agent.binding_data")
    except ModuleNotFoundError:
        pytest.fail("H1d scoped data resource module is missing")


@pytest.fixture(params=["memory", "sqlite"])
def facts(request, tmp_path):
    backend = (
        InMemoryMemory(backend_id="facts")
        if request.param == "memory"
        else SQLiteMemory(tmp_path / "facts.sqlite")
    )
    for namespace in ("red", "blue"):
        for key in ("a", "b", "c"):
            backend.put_fact(Scope(), namespace, key, namespace + key, expected_version=0)
    yield backend
    backend.close()


def fact_views(backend):
    resource = resources().FactsBindingResource(
        backend, namespaces=("red", "blue"), default_namespace="red"
    )
    return resource, resource.select({}, Scope()), resource.select({"namespace": "blue"}, Scope())


def test_facts_namespace_provenance_and_foreign_reference_refusal(facts):
    async def run():
        resource, red, blue = fact_views(facts)
        records = await red.facts(Scope(), "agent-logical-name")
        assert [r["value"] for r in records] == ["reda", "redb", "redc"]
        assert records[0]["_facts_binding"]["namespace"] == "red"
        assert [r["value"] for r in await blue.facts(Scope(), "agent-logical-name")] == [
            "bluea",
            "blueb",
            "bluec",
        ]
        assert await red.validate_facts(Scope(), "agent-logical-name", records) is None
        with pytest.raises(AuthorizationDenied):
            await blue.validate_facts(Scope(), "agent-logical-name", records)
        records[0]["value"] = "fabricated"
        with pytest.raises(ValidationError):
            await red.validate_facts(Scope(), "agent-logical-name", records)
        assert facts.facts(Scope(), "red")[0]["value"] == "reda"
        with pytest.raises(FrozenInstanceError):
            red.namespace = "blue"
        with pytest.raises(AuthorizationDenied):
            resource.select({"namespace": "private"}, Scope())
        with pytest.raises(AuthorizationDenied):
            await red.facts(Scope(principal="other"), "agent")

    asyncio.run(run())


def test_facts_pagination_bounds_cursor_binding_and_stale_reference(facts):
    async def run():
        _, red, blue = fact_views(facts)
        query = RecallQuery(max_items=1, max_chars=1000, scan_limit=3)
        page = await red.recall(Scope(), "logical", query)
        assert len(page.items) == 1 and page.next_cursor and page.used_chars <= query.max_chars
        next_page = await red.recall(
            Scope(), "different-logical", replace(query, cursor=page.next_cursor)
        )
        assert next_page.items[0]["key"] != page.items[0]["key"]
        with pytest.raises(ValidationError):
            await blue.recall(Scope(), "logical", replace(query, cursor=page.next_cursor))
        small = await red.recall(
            Scope(), "logical", RecallQuery(max_items=3, max_chars=100, scan_limit=3)
        )
        assert small.used_chars <= 100
        facts.put_fact(Scope(), "red", page.items[0]["key"], "revised", expected_version=1)
        with pytest.raises(ValidationError):
            await red.validate_facts(Scope(), "logical", page.items)

    asyncio.run(run())


def test_legacy_facts_port_remains_available_through_explicit_recall_bridge():
    class Legacy:
        backend_id = "legacy"

        def facts(self, scope, namespace):
            return [{"key": "k", "value": namespace, "version": 1, "expires_at": None}]

    async def run():
        resource = resources().FactsBindingResource(
            Legacy(), namespaces=("red",), default_namespace="red"
        )
        view = resource.select({}, Scope())
        page = await view.recall(Scope(), "logical", RecallQuery())
        assert page.items[0]["value"] == "red" and page.backend_bounded is False
        assert await view.validate_facts(Scope(), "logical", page.items) is None

    asyncio.run(run())


@pytest.mark.parametrize("role", ["facts", "knowledge"])
def test_catalog_allowlist_selection_and_selected_view_reregistration_refusal(role):
    api = resources()
    backend = (
        InMemoryMemory(backend_id="memory")
        if role == "facts"
        else KnowledgeContext(LexicalRetriever(InMemoryKnowledgeStore()))
    )
    wrapper = api.FactsBindingResource if role == "facts" else api.KnowledgeBindingResource
    resource = wrapper(backend, namespaces=("red", "blue"), default_namespace="red")
    catalog = BindingCatalog(scope=Scope())
    catalog.register(role, "shared", "1", resource)
    view, record = catalog.resolve(
        role, BindingSelection.ref("shared", "1", selector={"namespace": "blue"}), Scope()
    )
    assert record["resource"]["namespace"] == "blue"
    with pytest.raises(ValidationError):
        catalog.register(role, "view", "1", view)
    with pytest.raises(ValidationError):
        wrapper(view)
    with pytest.raises(AuthorizationDenied):
        catalog.resolve(
            role, BindingSelection.ref("shared", "1", selector={"namespace": "private"}), Scope()
        )
    with pytest.raises(ValidationError):
        catalog.resolve(
            role,
            BindingSelection.ref("shared", "1", selector={"namespace": "red", "query": "x"}),
            Scope(),
        )


@pytest.mark.parametrize(
    "options",
    [
        ([], "red"),
        ([None], None),
        ([""], ""),
        (["red", "red"], "red"),
        (["red"], "blue"),
        (["x" * 129], "x" * 129),
    ],
)
def test_invalid_data_namespace_allowlists_fail_before_port_calls(options):
    with pytest.raises(ValidationError):
        resources().FactsBindingResource(
            InMemoryMemory(), namespaces=options[0], default_namespace=options[1]
        )


def test_knowledge_shared_retriever_scoped_sources_and_stale_versions():
    async def run():
        store = InMemoryKnowledgeStore(backend_id="docs")
        for namespace in ("red", "blue"):
            store.put(
                Scope(),
                namespace,
                Document("guide", "pool " + namespace, source_uri="fixture://" + namespace),
                expected_version=0,
            )
        context = KnowledgeContext(LexicalRetriever(store), namespace="host-original")
        resource = resources().KnowledgeBindingResource(
            context, namespaces=("red", "blue"), default_namespace="red"
        )
        red = resource.select({}, Scope())
        blue = resource.select({"namespace": "blue"}, Scope())
        references = await red.references(Scope(), "pool")
        assert (
            references[0]["value"]["text"] == "pool red"
            and references[0]["_knowledge"]["namespace"] == "red"
        )
        assert (await blue.references(Scope(), "pool"))[0]["value"]["text"] == "pool blue"
        assert context.namespace == "host-original"
        assert await red.validate(Scope(), references) is None
        with pytest.raises(ValidationError):
            await blue.validate(Scope(), references)
        with pytest.raises(AuthorizationDenied):
            await red.references(Scope(principal="other"), "pool")
        store.put(Scope(), "red", Document("guide", "pool changed"), expected_version=1)
        with pytest.raises(ValidationError):
            await red.validate(Scope(), references)

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["facts", "recall", "validate_facts"])
def test_facts_backend_drift_after_await_is_refused(operation):
    class Drift(InMemoryMemory):
        async def facts(self, *args):
            result = super().facts(*args)
            await asyncio.sleep(0)
            self.backend_id = "changed"
            return result

        async def recall(self, *args):
            result = super().recall(*args)
            await asyncio.sleep(0)
            self.backend_id = "changed"
            return result

        async def validate_facts(self, *args):
            result = super().validate_facts(*args)
            await asyncio.sleep(0)
            self.backend_id = "changed"
            return result

    async def run():
        backend = Drift(backend_id="original")
        backend.put_fact(Scope(), "red", "k", "v", expected_version=0)
        _, view, _ = fact_views(backend)
        raw = InMemoryMemory.facts(backend, Scope(), "red")
        if operation == "validate_facts":
            seed = InMemoryMemory(backend_id="original")
            seed.put_fact(Scope(), "red", "k", "v", expected_version=0)
            _, source, _ = fact_views(seed)
            raw = await source.facts(Scope(), "logical")
        extra = (
            (RecallQuery(),)
            if operation == "recall"
            else (raw,)
            if operation == "validate_facts"
            else ()
        )
        with pytest.raises(DefinitionMismatch):
            await getattr(view, operation)(Scope(), "logical", *extra)

    asyncio.run(run())


def test_knowledge_context_configuration_drift_during_io_is_refused():
    async def run():
        store = InMemoryKnowledgeStore()
        store.put(Scope(), "red", Document("guide", "pool red"), expected_version=0)

        class Drift(LexicalRetriever):
            async def retrieve(self, *args):
                result = await super().retrieve(*args)
                await asyncio.sleep(0)
                context.limit = 7
                return result

        context = KnowledgeContext(Drift(store))
        resource = resources().KnowledgeBindingResource(
            context, namespaces=("red",), default_namespace="red"
        )
        with pytest.raises(DefinitionMismatch):
            await resource.select({}, Scope()).references(Scope(), "pool")

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["query", "items", "characters", "scan"])
def test_scoped_fact_recall_refuses_invalid_queries_and_overbudget_backends(kind):
    class Invalid(InMemoryMemory):
        def recall(self, scope, namespace, query):
            items = self.facts(scope, namespace)
            if kind == "characters":
                items[0]["value"] = "x" * 1000
            return RecallPage(
                items,
                None,
                len(canonical(items)),
                100 if kind == "scan" else len(items),
                0,
                "snapshot",
            )

    backend = Invalid()
    for key in ("a", "b") if kind == "items" else ("a",):
        backend.put_fact(Scope(), "red", key, "v", expected_version=0)
    _, view, _ = fact_views(backend)
    query = None if kind == "query" else RecallQuery(max_items=1, max_chars=500, scan_limit=2)
    with pytest.raises(ValidationError):
        asyncio.run(view.recall(Scope(), "logical", query))


@pytest.mark.parametrize("operation", ["retrieve", "validate"])
def test_knowledge_view_refuses_actual_retriever_replacement_with_same_identity(operation):
    async def run():
        store = InMemoryKnowledgeStore()
        store.put(Scope(), "red", Document("guide", "pool red"), expected_version=0)

        class Swap(LexicalRetriever):
            async def retrieve(self, *args):
                result = await super().retrieve(*args)
                if operation == "retrieve":
                    context.retriever = Swap(store)
                return result

            async def validate(self, *args):
                result = await super().validate(*args)
                if operation == "validate":
                    context.retriever = Swap(store)
                return result

        context = KnowledgeContext(Swap(store))
        resource = resources().KnowledgeBindingResource(
            context, namespaces=("red",), default_namespace="red"
        )
        view = resource.select({}, Scope())
        if operation == "retrieve":
            with pytest.raises(DefinitionMismatch):
                await view.references(Scope(), "pool")
        else:
            refs = await view.references(Scope(), "pool")
            with pytest.raises(DefinitionMismatch):
                await view.validate(Scope(), refs)

    asyncio.run(run())
