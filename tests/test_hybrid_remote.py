import asyncio
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from relf_agent import (
    HashEmbeddingProvider,
    IngestionCoordinator,
    RetrievalQuery,
    RuntimeBuilder,
    RuntimeProfile,
    SourceDocument,
)
from relf_agent.errors import ValidationError


@pytest.fixture
def embedding_service():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(value)
            vectors = asyncio.run(HashEmbeddingProvider(dimensions=8).embed(value["input"]))
            result = {
                "object": "list",
                "model": "fixture-embedding",
                "data": [
                    {"object": "embedding", "index": i, "embedding": v}
                    for i, v in reversed(list(enumerate(vectors)))
                ],
                "usage": {"prompt_tokens": len(vectors), "total_tokens": len(vectors)},
            }
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
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


@pytest.mark.parametrize("http_embedding", [False, True])
def test_actual_pg_qdrant_hybrid_assembly_fixed_sources_and_usage(
    tmp_path, monkeypatch, http_embedding, embedding_service
):
    dsn = os.environ.get("RALF_TEST_POSTGRES_DSN")
    url = os.environ.get("RALF_TEST_QDRANT_URL")
    if not dsn or not url:
        pytest.skip("Set actual PostgreSQL/Qdrant service settings")
    monkeypatch.setenv("RALF_HYBRID_PG", dsn)
    monkeypatch.setenv("RALF_HYBRID_QDRANT", url)
    endpoint, requests = embedding_service
    collection = "hybrid_" + uuid.uuid4().hex
    config = {
        "dsn_env": "RALF_HYBRID_PG",
        "url_env": "RALF_HYBRID_QDRANT",
        "backend_id": "hybrid-pg",
        "index_backend_id": "hybrid-qdrant",
        "collection": collection,
        "initialize": True,
        "namespace": collection,
        "embedding": {
            "type": "openai" if http_embedding else "hash",
            "config": {
                "model": "fixture-embedding",
                "base_url": endpoint,
                "anonymous": True,
                "dimensions": 8,
            }
            if http_embedding
            else {"dimensions": 8},
        },
    }
    profile = RuntimeProfile(
        "remote-hybrid",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={"knowledge": {"adapter": "postgres-qdrant-hybrid", "config": config}},
    )

    async def run():
        runtime = await RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "runs.sqlite")
        hybrid = runtime.knowledge.retriever
        store = hybrid.store
        try:
            assert not requests
            receipt = await IngestionCoordinator(store).ingest(
                runtime.scope,
                collection,
                SourceDocument("guide", b"pool timeout diagnosis", source_uri="user://guide"),
                command_id="first",
                expected_version=0,
            )
            vector = hybrid.retrievers["vector"]
            await vector.index_document(runtime.scope, collection, "guide")
            result = await hybrid.retrieve(
                runtime.scope, collection, RetrievalQuery("pool timeout")
            )
            assert len(result.items) == 1 and result.items[0].chunk_id == receipt.chunk_ids[0]
            assert result.mode == "hybrid:rrf"
            references = await runtime.knowledge.references(runtime.scope, "pool timeout")
            await runtime.knowledge.validate(runtime.scope, references)
            await store.delete(runtime.scope, collection, "guide", expected_version=1)
            assert (
                await hybrid.retrieve(runtime.scope, collection, RetrievalQuery("pool timeout"))
            ).items == ()
            with pytest.raises(ValidationError):
                await runtime.knowledge.validate(runtime.scope, references)
            assert bool(requests) == http_embedding
        finally:
            for table in [
                "ralf_knowledge_terms",
                "ralf_knowledge_chunks",
                "ralf_knowledge_documents",
                "ralf_knowledge_ingestions",
            ]:
                await store.connection.execute(
                    f"DELETE FROM {table} WHERE namespace=%s", (collection,)
                )
            await runtime.aclose()
            async with httpx.AsyncClient() as cleanup:
                response = await cleanup.delete(f"{url}/collections/{collection}", timeout=10)
                assert response.status_code == 200

    asyncio.run(run())
