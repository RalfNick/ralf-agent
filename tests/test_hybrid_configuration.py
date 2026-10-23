import asyncio

import pytest

from relf_agent import AgentSpec, Document, RuntimeBuilder, RuntimeProfile
from relf_agent.errors import ValidationError


def profile(adapter="sqlite-hybrid", **config):
    return RuntimeProfile(
        "hybrid",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={"knowledge": {"adapter": adapter, "config": config}},
    )


def test_default_hybrid_configuration_owned_paths_and_offline_query(tmp_path):
    builder = RuntimeBuilder(base_dir=tmp_path)
    runtime = builder.build(
        profile(namespace="docs", path="docs.sqlite", index_path="vectors.sqlite"),
        tmp_path / "runs.sqlite",
    )

    async def run():
        h = runtime.knowledge.retriever
        h.store.put(
            runtime.scope,
            "docs",
            Document("pool", "pool diagnosis", source_uri="local://pool"),
            expected_version=0,
        )
        await h.retrievers["vector"].index_document(runtime.scope, "docs", "pool")
        handle = runtime.submit(AgentSpec("answer", "Use references"), "pool", command_id="first")
        assert (await runtime.drive(handle.run_id)).state == "succeeded"
        assert h.identity["fusion"]["kind"] == "rrf" and (tmp_path / "vectors.sqlite").exists()

    try:
        asyncio.run(run())
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "config",
    [
        {"unknown": 1},
        {"embedding": {"type": "hash", "config": {"secret": 1}}},
        {"branch_limit": 100, "candidate_limit": 32},
        {"reranker": "unknown"},
        {"fusion": {"unknown": 1}},
    ],
)
def test_bad_hybrid_config_is_rejected_before_database_created(tmp_path, config):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder(base_dir=tmp_path).build(profile(**config), path)
    assert not path.exists()


def test_http_embedding_profile_async_preflight_no_paid_request(tmp_path, monkeypatch):
    monkeypatch.setenv("RALF_EMBED_TEST_KEY", "private-test-only")
    config = {
        "type": "openai",
        "config": {
            "model": "fixture",
            "dimensions": 2,
            "base_url": "http://127.0.0.1:1/v1",
            "api_key_env": "RALF_EMBED_TEST_KEY",
        },
    }
    p = profile("sqlite-hybrid-http", embedding=config, dimensions=2)
    path = tmp_path / "runs.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder(base_dir=tmp_path).build(p, path)
    assert not path.exists()

    async def run():
        runtime = await RuntimeBuilder(base_dir=tmp_path).abuild(p, path)
        embedding = runtime.knowledge.retriever.retrievers["vector"].embedding
        assert embedding.identity["model"] == "fixture" and embedding._client is None
        assert "private-test-only" not in str(runtime.knowledge.identity)
        await runtime.aclose()
        assert embedding._closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "adapter", ["sqlite-hybrid", "sqlite-hybrid-http", "postgres-qdrant-hybrid"]
)
def test_unknown_fusion_weight_branch_rejected_before_resource_creation(tmp_path, adapter):
    config = {"fusion": {"weights": {"unregistered": 2}}}
    if adapter == "sqlite-hybrid-http":
        config["embedding"] = {
            "type": "openai",
            "config": {
                "model": "fixture",
                "dimensions": 2,
                "base_url": "http://127.0.0.1:1/v1",
                "anonymous": True,
            },
        }
    if adapter == "postgres-qdrant-hybrid":
        config.update(
            {
                "dsn_env": "NEVER_OPEN_PG",
                "url_env": "NEVER_OPEN_QDRANT",
                "backend_id": "pg",
                "index_backend_id": "qdrant",
                "collection": "test",
            }
        )
    p = profile(adapter, **config)
    path = tmp_path / "must-not-exist.sqlite"

    async def run():
        runtime = None
        try:
            with pytest.raises(ValidationError, match="Fusion weights"):
                runtime = await RuntimeBuilder(base_dir=tmp_path).abuild(p, path)
        finally:
            if runtime is not None:
                await runtime.aclose()
        assert not path.exists()

    asyncio.run(run())
