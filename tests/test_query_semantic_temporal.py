import asyncio
from dataclasses import asdict

from ralf_agent import (
    AgentSpec,
    AliasQueryTransform,
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
    ModelResponse,
    QueryTransformRetriever,
    Scope,
    ToolRegistry,
)
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request


def test_query_transform_uses_original_temporal_context_history_snapshot():
    async def run():
        store = InMemoryKnowledgeStore()
        store.put(Scope(), "docs", Document("guide", "automobile"), expected_version=0)

        class Model:
            identity = {"kind": "query-history-reader", "version": "1"}

            async def complete(self, messages, tools):
                assert "automobile" in str(messages)
                return ModelResponse(output="done")

        class Transform(AliasQueryTransform):
            calls = 0

            def transform(self, text):
                self.calls += 1
                return super().transform(text)

        transform = Transform({"car": "automobile"})
        knowledge = KnowledgeContext(
            QueryTransformRetriever(LexicalRetriever(store), transform),
            namespace="docs",
        )
        runtime = TemporalRuntime(
            providers={"default": Model()}, tools=ToolRegistry(), knowledge=knowledge
        )
        state = TemporalRunState(
            "run",
            asdict(Scope()),
            "session",
            submission_request(AgentSpec("answer", "Use evidence"), "car"),
            runtime.manifest,
        )
        action, request = state.next_operation()
        prepared = await runtime.prepare_context(request)
        state.accept_context(action["id"], prepared)
        restored = TemporalRunState(
            "run",
            asdict(Scope()),
            "session",
            submission_request(AgentSpec("answer", "Use evidence"), "car"),
            runtime.manifest,
        )
        original, _ = restored.next_operation()
        restored.accept_context(original["id"], prepared)
        action, request = restored.next_operation()
        assert action["kind"] == "model"
        restored.accept_model(action["id"], await runtime.complete_model(request))
        assert restored.state == "succeeded"
        assert transform.calls == 1

    asyncio.run(run())
