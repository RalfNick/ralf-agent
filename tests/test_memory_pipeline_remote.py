import asyncio
import os
import uuid

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    MemoryAdmissionPolicy,
    MemoryPipeline,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
)
from tests.test_redis_memory_adapter import redis_service as redis_service


class Provider:
    identity = {"kind": "remote-memory-source-fixture", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output={"project": "RALF"})


async def exercise(memory, path):
    with LocalEngine(
        SQLiteStore(path), providers={"default": Provider()}, tools=ToolRegistry()
    ) as engine:
        policy = MemoryAdmissionPolicy({"project": ("result", "project")})
        pipeline = MemoryPipeline(
            engine, memory=memory, policy=policy, namespace="memory-" + uuid.uuid4().hex
        )
        result = await pipeline.run(AgentSpec("a", "Observe"), "project", command_id="first")
        assert result["memory"]["status"] == "completed"
        receipt = await pipeline.consolidate(result["task"]["run_id"], command_id="first:memory")
        assert receipt["facts"][0]["duplicate"] is True
        facts = await memory.facts(engine.scope, pipeline.namespace)
        assert len(facts) == 1 and facts[0]["version"] == 1
        assert facts[0]["value"]["value"] == "RALF"


def test_real_redis_automatic_memory_cas_duplicate(tmp_path, redis_service):
    async def run():
        from relf_agent.redis_memory import RedisMemory

        memory = await RedisMemory.connect(redis_service, backend_id="memory-pipeline-redis")
        try:
            if hasattr(memory, "initialize"):
                await memory.initialize()
            await exercise(memory, tmp_path / "run.sqlite")
        finally:
            await memory.aclose()

    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("RALF_TEST_POSTGRES_DSN"), reason="requires actual PostgreSQL")
def test_real_postgres_automatic_memory_cas_duplicate(tmp_path):
    async def run():
        from relf_agent.postgres import PostgresMemory

        memory = await PostgresMemory.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], backend_id="memory-pipeline-pg"
        )
        try:
            if hasattr(memory, "initialize"):
                await memory.initialize()
            await exercise(memory, tmp_path / "run.sqlite")
        finally:
            await memory.aclose()

    asyncio.run(run())
