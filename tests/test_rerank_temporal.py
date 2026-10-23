"""Existing Activity/History RAG port; no new Temporal protocol or service."""

import asyncio
from dataclasses import asdict

import httpx

from relf_agent import (
    AgentSpec,
    Document,
    HTTPReranker,
    HybridRetriever,
    KnowledgeContext,
    ModelResponse,
    Scope,
    ToolRegistry,
)
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request
from tests.test_hybrid_retrieval import Branch, docs


def test_http_reranker_uses_registered_temporal_knowledge_authority():
    async def run():
        store = docs()
        store.put(Scope(), "docs", Document("b", "car safety manual"), expected_version=1)
        seen = []

        class Model:
            identity = {"kind": "rerank-history-model", "version": "1"}

            async def complete(self, messages, tools):
                assert "car safety manual" in str(messages)
                return ModelResponse(output="done")

        def service(request):
            seen.append(request)
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 1}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            ranker = HTTPReranker("fixture", base_url="http://rank.test/v2", client=client)
            hybrid = HybridRetriever(store, {"a": Branch(store, ["b"])}, reranker=ranker)
            runtime = TemporalRuntime(
                providers={"default": Model()},
                tools=ToolRegistry(),
                knowledge=KnowledgeContext(hybrid, namespace="docs"),
            )
            state = TemporalRunState(
                "run",
                asdict(Scope()),
                "s",
                submission_request(AgentSpec("answer", "Use evidence"), "car"),
                runtime.manifest,
            )
            action, request = state.next_operation()
            assert action["kind"] == "context"
            prepared = await runtime.prepare_context(request)
            state.accept_context(action["id"], prepared)
            action, request = state.next_operation()
            assert action["kind"] == "model"
            state.accept_model(action["id"], await runtime.complete_model(request))
            assert state.state == "succeeded", state.snapshot()
            assert len(seen) == 1
            await ranker.aclose()

    asyncio.run(run())
