"""Local HTTP boundary and original source/Run authority, not semantic quality."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    Document,
    HTTPReranker,
    HybridRetriever,
    ModelResponse,
    RetrievalQuery,
    RuntimeBuilder,
    Scope,
)
from ralf_agent.errors import ProviderError, ValidationError
from ralf_agent.types import canonical
from tests.test_hybrid_retrieval import Branch, docs
from tests.test_rerank_configuration import profile


@pytest.fixture
def rerank_service():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/v2/rerank"
            requests.append(body)
            ranked = sorted(
                enumerate(body["documents"]), key=lambda pair: ("safety" not in pair[1], pair[0])
            )
            value = {
                "results": [
                    {"index": i, "relevance_score": 0.9 if "safety" in text else 0.1}
                    for i, text in ranked[: body["top_n"]]
                ],
                "meta": {"billed_units": {"search_units": 1}},
            }
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v2", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_http_rerank_combination_orders_authoritative_evidence_for_native_agent(
    tmp_path, rerank_service
):
    endpoint, requests = rerank_service

    class Echo:
        identity = {"kind": "ranked-evidence-fixture", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output=canonical(messages))

    registry = ComponentRegistry()
    registry.register("provider", "evidence", lambda c, ctx: Echo())
    base = profile(
        namespace="docs",
        limit=1,
        reranker={
            "type": "http",
            "config": {"model": "fixture", "base_url": endpoint, "anonymous": True},
        },
    )
    from ralf_agent import RuntimeProfile

    selected = RuntimeProfile(
        base.name, base.version, {"default": {"adapter": "evidence"}}, base.components
    )

    async def run():
        instance = await RuntimeBuilder(registry, base_dir=tmp_path).abuild(
            selected, tmp_path / "runs.sqlite"
        )
        try:
            assert not requests
            hybrid = instance.knowledge.retriever
            for name, text in (
                ("warranty", "car warranty information"),
                ("safety", "car safety manual"),
            ):
                hybrid.store.put(
                    instance.scope,
                    "docs",
                    Document(name, text, metadata={"secret-metadata": "never-send"}),
                    expected_version=0,
                )
                await hybrid.retrievers["vector"].index_document(instance.scope, "docs", name)
            handle = instance.submit(AgentSpec("answer", "Use evidence"), "car", command_id="s")
            result = await instance.drive(handle.run_id)
            assert result.state == "succeeded" and "car safety manual" in result.result
            assert "car warranty information" not in result.result
            assert len(requests) == 1 and "never-send" not in json.dumps(requests)
        finally:
            await instance.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("failure_policy", ["strict", "degrade"])
def test_source_changed_during_http_rerank_rejects_disclosure(failure_policy):
    async def run():
        store = docs()

        async def response(request):
            store.put(
                Scope(), "docs", Document("a", "updated private evidence"), expected_version=1
            )
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 1}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            ranker = HTTPReranker("fixture", base_url="http://rank.test/v2", client=client)
            hybrid = HybridRetriever(
                store, {"a": Branch(store, ["a"])}, reranker=ranker, failure_policy=failure_policy
            )
            with pytest.raises(ValidationError):
                await hybrid.retrieve(Scope(), "docs", RetrievalQuery("pool", limit=1))
            await ranker.aclose()

    asyncio.run(run())


def test_degrade_branch_policy_does_not_silently_skip_failed_reranker():
    async def run():
        store = docs()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"error": "private"}))
        ) as client:
            ranker = HTTPReranker("fixture", base_url="http://rank.test/v2", client=client)
            hybrid = HybridRetriever(
                store, {"a": Branch(store, ["a"])}, reranker=ranker, failure_policy="degrade"
            )
            with pytest.raises(ProviderError):
                await hybrid.retrieve(Scope(), "docs", RetrievalQuery("pool", limit=1))
            await ranker.aclose()

    asyncio.run(run())
