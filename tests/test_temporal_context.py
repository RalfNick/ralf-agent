import asyncio
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentSpec,
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
    Scope,
)
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.tools import ToolRegistry
from ralf_agent.types import ModelResponse, submission_request


class Provider:
    identity = {"kind": "context-fixture", "version": "1"}
    calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        assert any("Reference memory" in m.get("content", "") for m in messages)
        return ModelResponse(output="document evidence")


def setup():
    store = InMemoryKnowledgeStore()
    scope = Scope()
    store.put(scope, "docs", Document("guide", "database timeout diagnosis"), expected_version=0)
    knowledge = KnowledgeContext(LexicalRetriever(store), namespace="docs")
    provider = Provider()
    runtime = TemporalRuntime(
        providers={"default": provider}, tools=ToolRegistry(), knowledge=knowledge
    )
    state = TemporalRunState(
        "run",
        asdict(scope),
        "first",
        submission_request(AgentSpec("a", "Answer"), "database timeout", budget=8),
        runtime.manifest,
    )
    return store, scope, runtime, state, provider


def test_context_is_separate_evidence_before_model_dispatch():
    async def run():
        _, _, runtime, state, provider = setup()
        action, request = state.next_operation()
        assert action["kind"] == "context" and provider.calls == 0
        evidence = await runtime.prepare_context(request)
        assert evidence["ok"] and evidence["references"]
        state.accept_context(action["id"], evidence)
        model, request = state.next_operation()
        assert model["kind"] == "model" and request["context"]["messages"] == evidence["messages"]
        assert (await runtime.complete_model(request))["ok"] and provider.calls == 1
        assert state.event_log[-1]["kind"] == "dispatch_intent_recorded"

    asyncio.run(run())


def test_changed_document_refuses_model_dispatch_using_fixed_snapshot():
    async def run():
        store, scope, runtime, state, provider = setup()
        action, request = state.next_operation()
        state.accept_context(action["id"], await runtime.prepare_context(request))
        _, request = state.next_operation()
        store.put(scope, "docs", Document("guide", "replaced"), expected_version=1)
        response = await runtime.complete_model(request)
        assert response["ok"] is False and response["dispatched"] is False and provider.calls == 0

    asyncio.run(run())


def test_context_manifest_and_components_drift_are_refused():
    from ralf_agent.errors import DefinitionMismatch

    _, _, runtime, _, _ = setup()
    expected = runtime.manifest
    runtime.knowledge.namespace = "changed"
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release(expected)


def test_same_identity_knowledge_replacement_is_refused():
    from ralf_agent.errors import DefinitionMismatch

    store, _, runtime, _, _ = setup()
    expected = runtime.manifest
    runtime.knowledge = KnowledgeContext(LexicalRetriever(store), namespace="docs")
    assert runtime.knowledge.identity == expected["knowledge_context"]
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release(expected)
