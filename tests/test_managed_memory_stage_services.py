import asyncio
import os
import uuid

import pytest

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    ManagedMemoryPolicy,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
)
from ralf_agent.errors import MemoryBackendError
from tests.helpers import ScriptedProvider
from tests.test_redis_memory_adapter import redis_service as redis_service


class LostAcknowledgement:
    def __init__(self, memory):
        self.memory, self.writes = memory, 0

    @property
    def backend_id(self):
        return self.memory.backend_id

    async def put_fact(self, *args, **kwargs):
        self.writes += 1
        await self.memory.put_fact(*args, **kwargs)
        raise MemoryBackendError("simulated lost CAS acknowledgement")

    async def recall(self, *args, **kwargs):
        return await self.memory.recall(*args, **kwargs)

    async def validate_facts(self, *args, **kwargs):
        return await self.memory.validate_facts(*args, **kwargs)


async def exercise(memory, path):
    target = LostAcknowledgement(memory)
    stage = ManagedMemoryPolicy(target, namespace="observations-" + uuid.uuid4().hex)
    provider = ScriptedProvider([ModelResponse(output="observed")])

    def engine():
        return LocalEngine(
            SQLiteStore(path),
            providers={"default": provider},
            tools=ToolRegistry(),
            stage_policy=stage,
        )

    with engine() as local:
        h = local.submit(AgentSpec("a", "Answer"), "q", command_id="s", budget=2)
        assert (await local.drive(h.run_id)).state == "succeeded"
        assert local.memory_stages(h.run_id)[0]["status"] == "outcome_unknown"
        assert local.diagnostics(h.run_id).budget["held"] == 1
    with engine() as local:
        assert (await local.drive(h.run_id)).state == "succeeded"
        assert local.memory_stages(h.run_id)[0]["status"] == "completed"
        assert local.diagnostics(h.run_id).budget["spent"] == 2
        assert local.diagnostics(h.run_id).budget["held"] == 0
        assert target.writes == provider.calls == 1
        key = local.memory_stages(h.run_id)[0]["facts"][0]["key"]
        observed = await memory.inspect_fact(local.scope, stage.namespace, key)
        assert observed["key"] == key and observed["version"] == 1
        assert observed["value"]["value"] == "observed"
        assert await memory.inspect_fact(local.scope, stage.namespace, "missing") is None


def test_actual_redis_managed_stage_lost_ack_restart(tmp_path, redis_service):
    async def run():
        from ralf_agent.redis_memory import RedisMemory

        memory = await RedisMemory.connect(redis_service, backend_id="managed-stage-redis")
        try:
            await exercise(memory, tmp_path / "run.sqlite")
        finally:
            await memory.aclose()

    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("RALF_TEST_POSTGRES_DSN"), reason="requires actual PostgreSQL")
def test_actual_postgres_managed_stage_lost_ack_restart(tmp_path):
    async def run():
        from ralf_agent.postgres import PostgresMemory

        memory = await PostgresMemory.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], backend_id="managed-stage-pg"
        )
        try:
            await exercise(memory, tmp_path / "run.sqlite")
        finally:
            await memory.aclose()

    asyncio.run(run())
