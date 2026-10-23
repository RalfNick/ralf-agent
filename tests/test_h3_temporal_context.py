"""Pure Activity/History protocol integration, without a Temporal service."""

import asyncio
from dataclasses import asdict

from relf_agent import (
    Document,
    InMemoryArtifactStore,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
    RelevantDataContext,
    Scope,
)
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request
from tests.test_composite_data_context import Provider, agent, registry
from tests.test_temporal_managed_context import finish


def test_selected_knowledge_context_uses_original_temporal_managed_stages():
    async def run():
        knowledge = InMemoryKnowledgeStore()
        knowledge.put(
            Scope(), "docs", Document("guide", "task preferred language zh-CN"), expected_version=0
        )
        provider = Provider()
        writes = []
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=registry(writes),
            knowledge=KnowledgeContext(LexicalRetriever(knowledge), namespace="docs"),
            context_builder=RelevantDataContext(
                InMemoryArtifactStore(backend_id="artifacts"),
                mode="model",
                summary_max_chars=256,
                tool_result_chars=1024,
                preview_chars=64,
            ),
        )
        state = TemporalRunState(
            "run", asdict(Scope()), "s", submission_request(agent(), "task"), runtime.manifest
        )
        await finish(runtime, state)
        assert len(writes) == 4 and provider.summaries >= 1
        assert state.budget["spent"] == 5 + provider.summaries
        assert "zh-CN" in str(provider.requests)
        assert runtime.manifest["kernel"] == "temporal-2"

    asyncio.run(run())
