"""Real HTTP transport and deterministic synonyms; not a model-quality benchmark."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    Document,
    ModelResponse,
    RuntimeBuilder,
    recommended_profile,
)
from ralf_agent.errors import ValidationError
from ralf_agent.types import canonical


@pytest.fixture
def synonym_endpoint():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/v1/embeddings" and body["model"] == "fixture"
            requests.append(body)

            def vector(text):
                return [1, 0] if "automobile" in text or "car" in text else [0, 1]

            response = {
                "object": "list",
                "model": "fixture",
                "data": [
                    {"object": "embedding", "index": i, "embedding": vector(text)}
                    for i, text in reversed(list(enumerate(body["input"])))
                ],
                "usage": {"prompt_tokens": len(body["input"]), "total_tokens": len(body["input"])},
            }
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_semantic_combination_indexes_synonyms_routes_evidence_and_rejects_stale_sources(
    tmp_path, synonym_endpoint
):
    endpoint, requests = synonym_endpoint

    class Evidence:
        identity = {"kind": "evidence-fixture", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output=canonical(messages))

    registry = ComponentRegistry()
    registry.register("provider", "evidence", lambda c, ctx: Evidence())
    profile = recommended_profile(
        "semantic-knowledge",
        provider={"adapter": "evidence"},
        knowledge_namespace="manuals",
        embedding={
            "type": "openai",
            "config": {
                "model": "fixture",
                "dimensions": 2,
                "base_url": endpoint,
                "anonymous": True,
            },
        },
        components={
            "knowledge": {
                "adapter": "sqlite-hybrid-http",
                "config": {
                    "namespace": "manuals",
                    "embedding": {
                        "type": "openai",
                        "config": {
                            "model": "fixture",
                            "dimensions": 2,
                            "base_url": endpoint,
                            "anonymous": True,
                        },
                    },
                    "limit": 1,
                    "failure_policy": "strict",
                },
            }
        },
    )

    async def run():
        builder = RuntimeBuilder(registry, base_dir=tmp_path)
        runtime = await builder.abuild(profile, tmp_path / "runs.sqlite")
        refs, handle = None, None
        try:
            hybrid = runtime.knowledge.retriever
            assert not requests
            for doc, text in (
                ("vehicle", "automobile safety manual"),
                ("weather", "rain forecast"),
            ):
                hybrid.store.put(runtime.scope, "manuals", Document(doc, text), expected_version=0)
                await hybrid.retrievers["vector"].index_document(runtime.scope, "manuals", doc)
            refs = await runtime.knowledge.references(runtime.scope, "car")
            assert refs[0]["value"]["document_id"] == "vehicle"
            handle = runtime.submit(AgentSpec("answer", "Use evidence"), "car", command_id="s")
            done = await runtime.drive(handle.run_id)
            assert done.state == "succeeded" and "automobile safety manual" in done.result
            assert "rain forecast" not in done.result
        finally:
            await runtime.aclose()
        runtime = await builder.abuild(profile, tmp_path / "runs.sqlite")
        try:
            assert (
                runtime.submit(AgentSpec("answer", "Use evidence"), "car", command_id="s") == handle
            )
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
            await runtime.knowledge.validate(runtime.scope, refs)
            runtime.knowledge.retriever.store.put(
                runtime.scope,
                "manuals",
                Document("vehicle", "revised automobile manual"),
                expected_version=1,
            )
            with pytest.raises(ValidationError):
                await runtime.knowledge.validate(runtime.scope, refs)
        finally:
            await runtime.aclose()
        assert len(requests) >= 3

    asyncio.run(run())
