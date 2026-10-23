"""Scoped knowledge, source adoption and real callback boundaries."""

import asyncio
import copy
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    Document,
    InMemoryKnowledgeStore,
    KnowledgeBindingResource,
    KnowledgeContext,
    LexicalRetriever,
    ManagedContextPipeline,
    ModelResponse,
    Scope,
    ToolRegistry,
    WorkflowSpec,
)
from relf_agent.errors import AuthorizationDenied, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_bindings import normalize_request
from relf_agent.temporal_state import TemporalRunState, validate_request
from relf_agent.types import submission_request
from tests.test_temporal_binding_isolation import advance


@pytest.mark.parametrize("scoped", [False, True])
def test_http_query_provider_pins_client_instance_instead_of_context_manager(scoped):
    from relf_agent import ModelQueryTransform, OpenAIChatProvider, QueryTransformRetriever
    from relf_agent.errors import DefinitionMismatch

    query = OpenAIChatProvider("fixture", api_key="test-only", base_url="http://query.test")
    context = KnowledgeContext(
        QueryTransformRetriever(
            LexicalRetriever(InMemoryKnowledgeStore()), ModelQueryTransform(query)
        )
    )
    catalog = BindingCatalog(scope=Scope()) if scoped else None
    if scoped:
        catalog.register("knowledge", "docs", "1", KnowledgeBindingResource(context))
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        knowledge=None if scoped else context,
        binding_catalog=catalog,
    )
    runtime.validate_release()
    query.client = object()
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_scoped_sqlite_publication_fixes_physical_database(tmp_path):
    from relf_agent import SQLiteKnowledgeStore
    from relf_agent.errors import DefinitionMismatch

    stores = [
        SQLiteKnowledgeStore(tmp_path / name, backend_id="shared") for name in ("a.db", "b.db")
    ]
    try:
        runtimes = []
        for store in stores:
            catalog = BindingCatalog(scope=Scope())
            catalog.register(
                "knowledge",
                "docs",
                "1",
                KnowledgeBindingResource(KnowledgeContext(LexicalRetriever(store))),
            )
            runtimes.append(
                TemporalRuntime(
                    providers={"default": Provider()}, tools=ToolRegistry(), binding_catalog=catalog
                )
            )
        assert runtimes[0].manifest != runtimes[1].manifest
        with pytest.raises(DefinitionMismatch):
            runtimes[1].validate_release(runtimes[0].manifest)
    finally:
        for store in stores:
            store.close()


@pytest.mark.parametrize("managed", [False, True])
def test_scoped_facts_and_knowledge_keep_independent_sources_after_restore(managed):
    from relf_agent import FactsBindingResource, InMemoryMemory

    async def run():
        original, state, _, provider, scope = setup(managed)
        facts = InMemoryMemory()
        facts.put_fact(scope, "personal", "preference", "prefers pool", expected_version=0)
        catalog = original.binding_catalog
        catalog.register(
            "facts",
            "personal",
            "1",
            FactsBindingResource(facts, namespaces=("personal",), default_namespace="personal"),
        )
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            binding_catalog=catalog,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        request = copy.deepcopy(state.request)
        request["agent_bindings"]["agent"]["facts"] = BindingSelection.ref(
            "personal", "1", selector={"namespace": "personal"}
        ).to_dict()
        state = TemporalRunState("run", asdict(scope), "s", request, runtime.manifest)
        for _ in range(12):
            if state.context_snapshot is not None:
                break
            await advance(runtime, state)
        snapshot = state.context_snapshot
        assert snapshot is not None, state.snapshot()
        assert snapshot["facts"][0]["value"] == "prefers pool"
        assert snapshot["knowledge_references"][0]["_knowledge"]["namespace"] == "blue"
        restored = copy.deepcopy(state)
        await advance(runtime, restored)
        assert restored.state == "succeeded", restored.snapshot()
        assert "prefers pool" in str(provider.messages) and "blue evidence" in str(
            provider.messages
        )
        assert len(provider.messages) == 1

    asyncio.run(run())


class Provider:
    identity = {"kind": "temporal-scoped-knowledge-test", "version": "1"}

    def __init__(self):
        self.messages = []

    async def complete(self, messages, tools):
        self.messages.append(copy.deepcopy(messages))
        return ModelResponse(output="pool")


def setup(managed=False, store=None):
    scope = Scope("knowledge", "alice")
    store = store or InMemoryKnowledgeStore(backend_id="knowledge-source")
    for ns in ("red", "blue", "private"):
        store.put(scope, ns, Document("guide", "pool " + ns + " evidence"), expected_version=0)
    store.put(
        Scope("knowledge", "bob"),
        "blue",
        Document("guide", "pool foreign evidence"),
        expected_version=0,
    )
    context = KnowledgeContext(LexicalRetriever(store), namespace="unused")
    catalog = BindingCatalog(scope=scope)
    catalog.register(
        "knowledge",
        "guides",
        "1",
        KnowledgeBindingResource(context, namespaces=("red", "blue"), default_namespace="red"),
    )
    provider = Provider()
    runtime = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        context_builder=ManagedContextPipeline() if managed else None,
    )
    descriptor = AgentBindingDescriptor(
        knowledge=BindingSelection.ref("guides", "1", selector={"namespace": "blue"})
    )
    state = TemporalRunState(
        "run",
        asdict(scope),
        "s",
        normalize_request(
            submission_request(AgentDefinition(AgentSpec("a", "answer"), descriptor), "pool")
        ),
        runtime.manifest,
    )
    return runtime, state, store, provider, scope


@pytest.mark.parametrize("managed", [False, True])
def test_selected_namespace_and_scope_are_adopted_and_restored(managed):
    async def run():
        runtime, state, store, provider, scope = setup(managed)
        for _ in range(10):
            if state.context_snapshot is not None:
                break
            await advance(runtime, state)
        assert state.context_snapshot is not None, state.snapshot()
        assert [r["_knowledge"]["namespace"] for r in state.context_snapshot["references"]] == [
            "blue"
        ]
        assert state.step_manifest["knowledge_context"]["namespace"] == "blue"
        original = copy.deepcopy(state.context_snapshot)
        restored = copy.deepcopy(state)
        await advance(runtime, restored)
        assert restored.state == "succeeded", restored.snapshot()
        assert restored.context_snapshot == original and len(provider.messages) == 1
        payload = str(provider.messages)
        assert (
            "blue evidence" in payload
            and "red evidence" not in payload
            and "private evidence" not in payload
            and "foreign evidence" not in payload
        )
        store.put(scope, "blue", Document("guide", "pool changed"), expected_version=1)
        stale = copy.deepcopy(state)
        await advance(runtime, stale)
        assert stale.state == "failed" and len(provider.messages) == 1
        assert restored.result == "pool"

    asyncio.run(run())


def test_foreign_scope_ungranted_namespace_and_invalid_selector_are_refused():
    runtime, state, _, _, _ = setup()
    with pytest.raises(AuthorizationDenied):
        TemporalRunState(
            "foreign", asdict(Scope("knowledge", "bob")), "s", state.request, runtime.manifest
        )
    request = copy.deepcopy(state.request)
    request["agent_bindings"]["agent"]["knowledge"]["selector"] = {"namespace": "private"}
    with pytest.raises(AuthorizationDenied):
        validate_request(request, runtime.manifest)
    request["agent_bindings"]["agent"]["knowledge"]["selector"] = {"backend_id": "other"}
    with pytest.raises(ValidationError):
        validate_request(request, runtime.manifest)


def test_identical_steps_keep_independent_namespaces_after_restore():
    async def run():
        runtime, original, _, provider, _ = setup()
        agent = AgentSpec("same", "answer")
        definition = BoundDefinition(
            WorkflowSpec("sequence", [agent, agent]),
            {
                f"sequence/steps/{i}": AgentBindingDescriptor(
                    knowledge=BindingSelection.ref("guides", "1", selector={"namespace": ns})
                )
                for i, ns in enumerate(("red", "blue"))
            },
        )
        state = TemporalRunState(
            "run",
            original.scope,
            "s",
            normalize_request(submission_request(definition, "pool")),
            runtime.manifest,
        )
        while state.node == 0:
            await advance(runtime, state)
        state = copy.deepcopy(state)
        while state.state not in {"failed", "succeeded"}:
            await advance(runtime, state)
        assert state.state == "succeeded", state.snapshot()
        assert len(provider.messages) == 2
        assert "red evidence" in str(provider.messages[0]) and "blue evidence" not in str(
            provider.messages[0]
        )
        assert "blue evidence" in str(provider.messages[1]) and "red evidence" not in str(
            provider.messages[1]
        )

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_cancel_during_final_knowledge_validation_blocks_model(managed):
    async def run():
        runtime, state, _, provider, _ = setup(managed)
        root = runtime.binding_catalog._entries[("knowledge", "guides", "1")][0].context

        class Retriever(LexicalRetriever):
            calls = 0

            async def validate(self, *args):
                await super().validate(*args)
                self.calls += 1
                if self.calls == 3:
                    state.command("cancel", {"kind": "cancel", "scope": state.scope})
                await asyncio.sleep(0)

        root.retriever = Retriever(root.retriever.store)
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            binding_catalog=runtime.binding_catalog,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        state = TemporalRunState("run", state.scope, "s", state.request, runtime.manifest)
        for _ in range(10):
            if state.context_snapshot is not None:
                break
            await advance(runtime, state)
        await advance(runtime, state)
        assert state.state == "cancelled" and provider.messages == []

    asyncio.run(run())


@pytest.mark.parametrize("field", ["namespace", "scope", "text", "version"])
def test_context_acceptance_rejects_changed_knowledge_evidence(field):
    async def run():
        runtime, state, _, _, _ = setup()
        action, request = state.next_operation()
        response = await runtime.prepare_context(request)
        item = response["references"][0]
        if field == "namespace":
            item["_knowledge"]["namespace"] = "red"
        elif field == "scope":
            item["_knowledge"]["scope"]["principal"] = "bob"
        elif field == "text":
            item["value"]["text"] = "forged"
        else:
            item["version"] += 1
        with pytest.raises(ValidationError):
            state.accept_context(action["id"], response)

    asyncio.run(run())


@pytest.mark.parametrize("change", ["store", "get_chunk", "lexical"])
def test_native_dependency_change_during_io_is_rejected(change):
    async def run():
        runtime, state, store, provider, _ = setup()
        root = runtime.binding_catalog._entries[("knowledge", "guides", "1")][0].context
        original = store.lexical

        async def changed(*args):
            value = original(*args)
            if change == "store":
                root.retriever.store = InMemoryKnowledgeStore(backend_id=store.backend_id)
            elif change == "get_chunk":
                store.get_chunk = lambda *args: None
            else:
                store.lexical = original
            await asyncio.sleep(0)
            return value

        store.lexical = changed
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            binding_catalog=runtime.binding_catalog,
        )
        state = TemporalRunState("run", state.scope, "s", state.request, runtime.manifest)
        await advance(runtime, state)
        assert state.state == "failed" and state.error["code"] == "definition_mismatch"
        assert state.context_snapshot is None and provider.messages == []

    asyncio.run(run())


def test_scoped_knowledge_protocol_cannot_be_omitted_or_changed():
    from relf_agent.errors import DefinitionMismatch
    from relf_agent.temporal_state import validate_manifest

    runtime, _, _, _, _ = setup()
    for version in (None, 2, True):
        manifest = runtime.manifest
        if version is None:
            manifest.pop("knowledge_protocol")
        else:
            manifest["knowledge_protocol"] = version
        with pytest.raises(DefinitionMismatch):
            validate_manifest(manifest)
