"""Namespace scoping preserves the candidate window of ranked Facts recall."""

import asyncio
from dataclasses import replace

import pytest

from ralf_agent import (
    FactsBindingResource,
    InMemoryMemory,
    RecallPage,
    RecallQuery,
    Scope,
    SemanticMemoryStore,
)
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from ralf_agent.types import canonical

from .semantic_fixture import Embedding, facts


@pytest.mark.parametrize("max_items,keys", [(1, ["b"]), (2, ["b", "c"])])
def test_scoped_semantic_recall_preserves_candidate_window_and_ranked_results(max_items, keys):
    async def run():
        source = facts()
        memory = SemanticMemoryStore(source, Embedding(), min_score=0.5)
        view = FactsBindingResource(
            memory, namespaces=("assistant",), default_namespace="assistant"
        ).select({}, Scope())
        query = RecallQuery(text="vehicle", max_items=max_items, scan_limit=3)
        page = await view.recall(Scope(), "logical-agent", query)
        assert [item["key"] for item in page.items] == keys
        assert page.scanned == 3 and page.next_cursor is None
        assert page.used_chars == len(canonical(page.items)) <= query.max_chars
        assert all(item["_facts_binding"]["namespace"] == "assistant" for item in page.items)
        await view.validate_facts(Scope(), "logical-agent", page.items)
        with pytest.raises(AuthorizationDenied):
            await view.recall(Scope("foreign", "owner"), "logical-agent", query)
        source.put_fact(Scope(), "assistant", "b", "withdrawn", expected_version=1)
        with pytest.raises(ValidationError):
            await view.validate_facts(Scope(), "logical-agent", page.items)

    asyncio.run(run())


def test_scoped_semantic_recall_accounts_for_provenance_without_exceeding_char_budget():
    async def run():
        memory = SemanticMemoryStore(facts(), Embedding(), min_score=0.5)
        view = FactsBindingResource(
            memory, namespaces=("assistant",), default_namespace="assistant"
        ).select({}, Scope())
        page = await view.recall(
            Scope(), "logical", RecallQuery(text="vehicle", max_items=2, max_chars=190)
        )
        assert page.items == [] and page.used_chars == 2
        assert page.scanned == page.skipped == 3 and page.next_cursor is None

    asyncio.run(run())


class RankedWindow(InMemoryMemory):
    """A structural third-party window backend, independent of SemanticMemoryStore."""

    recall_mode = "window"

    async def recall(self, scope, namespace, query):
        source = super().recall(scope, namespace, replace(query, max_items=query.scan_limit))
        items = list(reversed(source.items))[: query.max_items]
        return RecallPage(
            items,
            None,
            len(canonical(items)),
            source.scanned,
            source.scanned - len(items),
            source.snapshot_id,
        )


def test_scoped_recall_supports_structural_window_backends_and_refuses_mode_drift():
    async def run():
        memory = RankedWindow(backend_id="ranked-facts")
        for key in ("a", "b"):
            memory.put_fact(Scope(), "selected", key, key, expected_version=0)
        resource = FactsBindingResource(
            memory, namespaces=("selected",), default_namespace="selected"
        )
        view = resource.select({}, Scope())
        page = await view.recall(Scope(), "logical", RecallQuery(max_items=1, scan_limit=2))
        assert [item["key"] for item in page.items] == ["b"] and page.scanned == 2
        original_identity = resource.identity
        memory.recall_mode = "cursor"
        assert resource.identity != original_identity
        with pytest.raises(DefinitionMismatch):
            await view.recall(Scope(), "logical", RecallQuery())

    asyncio.run(run())


def test_scoped_window_refuses_source_pagination():
    class InvalidWindow(RankedWindow):
        async def recall(self, scope, namespace, query):
            page = await super().recall(scope, namespace, query)
            return replace(page, next_cursor="unexpected-cursor")

    async def run():
        memory = InvalidWindow(backend_id="invalid-window")
        memory.put_fact(Scope(), "selected", "a", "value", expected_version=0)
        view = FactsBindingResource(
            memory, namespaces=("selected",), default_namespace="selected"
        ).select({}, Scope())
        with pytest.raises(ValidationError):
            await view.recall(Scope(), "logical", RecallQuery())

    asyncio.run(run())


def test_scoped_semantic_approval_survives_authority_restart_with_original_references(tmp_path):
    from ralf_agent import (
        AgentBindingDescriptor,
        AgentDefinition,
        AgentSpec,
        BindingCatalog,
        BindingSelection,
        LocalEngine,
        MemoryRecallPolicy,
        ModelResponse,
        SQLiteMemory,
        SQLiteStore,
        TaskRecallPlanner,
        ToolRegistry,
        ToolSpec,
    )

    from .helpers import ScriptedProvider, tool_response

    class CountingEmbedding(Embedding):
        calls = 0

        async def embed(self, texts):
            self.calls += 1
            return await super().embed(texts)

    async def run():
        backend = SQLiteMemory(tmp_path / "facts.sqlite")
        writes = []
        embedding = CountingEmbedding()
        for key, value in (
            ("a", "maritime transport"),
            ("b", "automobile servicing"),
            ("c", "car policy"),
        ):
            backend.put_fact(Scope(), "selected", key, value, expected_version=0)
        catalog = BindingCatalog(scope=Scope())
        catalog.register(
            "facts",
            "semantic",
            "1",
            FactsBindingResource(
                SemanticMemoryStore(backend, embedding, min_score=0.5),
                namespaces=("selected",),
                default_namespace="selected",
            ),
        )
        definition = AgentDefinition(
            AgentSpec("worker", "Use recalled facts", ("change",)),
            AgentBindingDescriptor(facts=BindingSelection.ref("semantic", "1")),
        )
        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "change",
                "Change",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            lambda arguments, context: writes.append(context.effect_key),
        )
        policy = MemoryRecallPolicy(facts=RecallQuery(max_items=1, scan_limit=3))

        def authority(responses):
            return LocalEngine(
                SQLiteStore(tmp_path / "runs.sqlite"),
                tools=tools,
                binding_catalog=catalog,
                providers={"default": ScriptedProvider(responses)},
                recall_planner=TaskRecallPlanner(policy),
            )

        try:
            with authority([tool_response()]) as first:
                handle = first.submit(definition, "vehicle", command_id="original")
                paused = await first.drive(handle.run_id)
                assert paused.state == "waiting_approval" and writes == []
                references = first.store.run(handle.run_id)["actions"][0]["memory_references"]
                assert [item["key"] for item in references] == ["b"]
                assert embedding.calls == 1
            with authority([ModelResponse(output="done")]) as recovered:
                duplicate = recovered.submit(definition, "vehicle", command_id="original")
                assert duplicate == handle
                assert (await recovered.drive(handle.run_id)).state == "waiting_approval"
                assert embedding.calls == 1 and writes == []
                target = paused.pending[0]
                recovered.approve(
                    handle.run_id, target["action_id"], target["digest"], command_id="approve"
                )
                assert (await recovered.drive(handle.run_id)).state == "succeeded"
                assert len(writes) == 1
                assert (
                    recovered.store.run(handle.run_id)["actions"][0]["memory_references"]
                    == references
                )
        finally:
            backend.close()

    asyncio.run(run())


def test_temporal_scoped_semantic_context_survives_state_restore_without_reembedding():
    import copy
    from dataclasses import asdict

    from ralf_agent import (
        AgentBindingDescriptor,
        AgentDefinition,
        AgentSpec,
        BindingCatalog,
        BindingSelection,
        MemoryRecallPolicy,
        ModelResponse,
        TaskRecallPlanner,
        ToolRegistry,
    )
    from ralf_agent.temporal_activities import TemporalRuntime
    from ralf_agent.temporal_bindings import normalize_request
    from ralf_agent.temporal_state import TemporalRunState
    from ralf_agent.types import submission_request
    from tests.test_temporal_binding_isolation import advance

    class CountingEmbedding(Embedding):
        calls = 0

        async def embed(self, texts):
            self.calls += 1
            return await super().embed(texts)

    class Reader:
        identity = {"kind": "scoped-semantic-temporal-reader", "version": "1"}

        async def complete(self, messages, tools):
            assert "automobile servicing" in str(messages) and "car policy" in str(messages)
            assert "maritime transport" not in str(messages)
            return ModelResponse(output="done")

    async def run():
        embedding = CountingEmbedding()
        catalog = BindingCatalog(scope=Scope())
        catalog.register(
            "facts",
            "semantic",
            "1",
            FactsBindingResource(
                SemanticMemoryStore(facts(), embedding, min_score=0.5),
                namespaces=("assistant",),
                default_namespace="assistant",
            ),
        )
        runtime = TemporalRuntime(
            providers={"default": Reader()},
            tools=ToolRegistry(),
            binding_catalog=catalog,
            recall_planner=TaskRecallPlanner(
                MemoryRecallPolicy(facts=RecallQuery(max_items=2, scan_limit=3))
            ),
        )
        definition = AgentDefinition(
            AgentSpec("logical", "Use facts"),
            AgentBindingDescriptor(
                facts=BindingSelection.ref("semantic", "1"),
            ),
        )
        state = TemporalRunState(
            "original",
            asdict(Scope()),
            "session",
            normalize_request(
                submission_request(definition, "vehicle"),
            ),
            runtime.manifest,
        )
        for _ in range(12):
            if state.context_snapshot is not None:
                break
            await advance(runtime, state)
        assert state.context_snapshot is not None
        assert [item["key"] for item in state.context_snapshot["facts"]] == ["b", "c"]
        restored = copy.deepcopy(state)
        await advance(runtime, restored)
        assert restored.state == "succeeded" and restored.result == "done"
        assert embedding.calls == 1 and restored.context_snapshot == state.context_snapshot

    asyncio.run(run())
