import asyncio
import os
import uuid

import pytest

from relf_agent import AgentSpec, Document, RetrievalQuery, RuntimeBuilder, RuntimeProfile

from .test_redis_memory_adapter import redis_service as _redis_service

redis_service = _redis_service


def postgres_dsn():
    value = os.environ.get("RALF_TEST_POSTGRES_DSN")
    if not value:
        pytest.skip("Requires real PostgreSQL test DSN")
    return value


def test_real_redis_profile_runs_and_closes_owned_clients(tmp_path, redis_service, monkeypatch):
    monkeypatch.setenv("RALF_REMOTE_REDIS", redis_service)
    config = {
        "url_env": "RALF_REMOTE_REDIS",
        "backend_id": "redis-assembly",
        "prefix": "assembly-" + uuid.uuid4().hex,
    }
    profile = RuntimeProfile(
        "redis",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "session_store": {"adapter": "redis", "config": config},
            "memory_store": {"adapter": "redis", "config": config},
            "recall_policy": {"adapter": "bounded-recall"},
        },
    )

    async def run():
        runtime = await RuntimeBuilder().abuild(profile, tmp_path / "redis.sqlite")
        try:
            await runtime.memory.put_fact(
                runtime.scope, "reader", "fact", "Redis reference", expected_version=0
            )
            h = runtime.submit(AgentSpec("reader", "Answer"), "question", command_id="s")
            assert (await runtime.drive(h.run_id)).state == "succeeded"
            assert (await runtime.sessions.read(runtime.scope, h.run_id))[0] == 1
            assert "Redis reference" in str(runtime.store.run(h.run_id)["actions"])
        finally:
            await runtime.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("vector", [False, True])
def test_real_postgres_knowledge_profile_and_qdrant_hydration(tmp_path, monkeypatch, vector):
    monkeypatch.setenv("RALF_REMOTE_POSTGRES", postgres_dsn())
    url = os.environ.get("RALF_TEST_QDRANT_URL")
    if vector and not url:
        pytest.skip("Requires real Qdrant service")
    if url:
        monkeypatch.setenv("RALF_REMOTE_QDRANT", url)
    identity = uuid.uuid4().hex
    config = {
        "dsn_env": "RALF_REMOTE_POSTGRES",
        "backend_id": "pg-knowledge",
        "initialize": True,
        "namespace": identity,
    }
    if vector:
        config.update(
            url_env="RALF_REMOTE_QDRANT",
            index_backend_id="qdrant-assembly",
            collection="assembly_" + identity,
            dimensions=16,
        )
    profile = RuntimeProfile(
        "postgres",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "memory_store": {
                "adapter": "postgres",
                "config": {
                    "dsn_env": "RALF_REMOTE_POSTGRES",
                    "backend_id": "pg-memory",
                    "initialize": True,
                },
            },
            "knowledge": {
                "adapter": "postgres-qdrant" if vector else "postgres-lexical",
                "config": config,
            },
        },
    )

    async def run():
        runtime = await RuntimeBuilder().abuild(
            profile, tmp_path / ("vector.sqlite" if vector else "lexical.sqlite")
        )
        authority = runtime.knowledge.retriever.store
        try:
            await authority.put(
                runtime.scope,
                identity,
                Document("policy", "Redis policy evidence"),
                expected_version=0,
            )
            if vector:
                await runtime.knowledge.retriever.index_document(runtime.scope, identity, "policy")
            h = runtime.submit(AgentSpec("reader", "Answer"), "Redis policy", command_id="s")
            assert (await runtime.drive(h.run_id)).state == "succeeded"
            assert "Redis policy evidence" in str(runtime.store.run(h.run_id)["actions"])
            assert os.environ["RALF_REMOTE_POSTGRES"] not in str(
                runtime.diagnostics(h.run_id).manifest
            )
            if vector:
                await authority.delete(runtime.scope, identity, "policy", expected_version=1)
                result = await runtime.knowledge.retriever.retrieve(
                    runtime.scope, identity, RetrievalQuery("Redis policy")
                )
                assert not result.items
        finally:
            if vector:
                client = runtime.knowledge.retriever.index._client
                await client.delete(url + "/collections/assembly_" + identity)
            await runtime.aclose()
        assert authority.connection.closed

    asyncio.run(run())
