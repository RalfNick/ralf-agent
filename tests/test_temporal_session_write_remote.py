"""Real remote Session CAS/receipt behavior through original Temporal History."""

import asyncio
import os
import uuid

import pytest

from ralf_agent import (
    AgentSpec,
    ManagedContextPipeline,
    ModelResponse,
    Runtime,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime

from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_postgres_adapter import stores
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


async def scenario(backend, scope, sequence, managed):
    from temporalio.client import Client

    class Provider:
        identity = {"kind": "remote-session-writes", "version": "1"}

        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            return ModelResponse(output="answer-" + str(self.calls))

    # Fault injection at the actual remote commit boundary, before Runtime fixes the port.
    append = backend.append
    writes = []

    async def lost_ack(*args, **kwargs):
        result = await append(*args, **kwargs)
        writes.append(kwargs["message_id"])
        if len(writes) == 1:
            raise RuntimeError("lost acknowledgement after actual database commit")
        return result

    backend.append = lost_ack
    await backend.initialize_session_identity()
    provider = Provider()
    execution = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        session_store=backend,
        context_builder=ManagedContextPipeline() if managed else None,
        enable_sessions=True,
        session_writes=True,
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    queue = "remote-save-" + uuid.uuid4().hex
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.manifest,
        scope=scope,
        activity_timeout=3,
        drive_timeout=30,
    )
    host = Runtime.from_temporal(engine)
    spec = AgentSpec("a", "Answer")
    definition = WorkflowSpec("sequence", [spec, spec]) if sequence else spec
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            entry = await host.open_session(definition, queue, command_id="open-" + queue)
            for index in (0, 1):
                turn = await entry.submit("task", command_id=f"turn-{index}-" + queue, budget=32)
                for _ in range(100):
                    done = await engine.drive(turn.turn.run.run_id)
                    if done.state == "succeeded":
                        break
                    assert done.state in {"running", "waiting_reconciliation"}, done
                    await asyncio.sleep(0.05)
                assert done.state == "succeeded", done
                assert (await engine.diagnostics(turn.turn.run.run_id)).budget["unknown"] == 0
                for _ in range(200):
                    if not (await entry.status()).busy:
                        break
                    await asyncio.sleep(0.05)
                assert not (await entry.status()).busy
                await replay_temporal_history(
                    await client.get_workflow_handle(turn.turn.run.run_id).fetch_history()
                )
            count = 4 if sequence else 2
            assert provider.calls == len(writes) == count
            assert len(set(writes)) == count
            revision, messages = await backend.read(scope, entry.ref.key.storage_key)
            assert revision == len(messages) == count
            assert [m["content"] for m in messages] == [
                "answer-" + str(i + 1) for i in range(count)
            ]
            assert (await backend.inspect_message(scope, entry.ref.key.storage_key, writes[0]))[
                "receipt"
            ]["revision"] == 1
        assert await execution.wait_session_executions(wait_timeout=3)
    finally:
        await execution.close_session_execution(wait_timeout=3)
        await host.aclose()
        await engine.aclose()
        backend.append = append


@pytest.mark.parametrize("sequence", [False, True])
@pytest.mark.parametrize("managed", [False, True])
def test_actual_redis_turns_lost_ack_and_exact_receipt(redis_service, sequence, managed):
    from ralf_agent import Scope

    async def run():
        async with memory_at(redis_service, "save-" + uuid.uuid4().hex) as (backend, _):
            await scenario(backend, Scope("remote-save", uuid.uuid4().hex), sequence, managed)

    asyncio.run(run())


@pytest.mark.parametrize("sequence", [False, True])
@pytest.mark.parametrize("managed", [False, True])
def test_actual_postgres_turns_lost_ack_and_exact_receipt(postgres_dsn, sequence, managed):
    async def run():
        async with stores(postgres_dsn) as (backend, _, scope):
            await scenario(backend, scope, sequence, managed)

    asyncio.run(run())
