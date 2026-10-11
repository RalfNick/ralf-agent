"""Actual Redis/PostgreSQL root/private resources and accepted namespace selectors."""

import asyncio
import os
import uuid

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    ManagedContextPipeline,
    Runtime,
    Scope,
    SessionBindingResource,
    ToolRegistry,
)
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_topology import CompositeSessionTopology

from .test_postgres_adapter import postgres_dsn as postgres_dsn
from .test_postgres_adapter import stores
from .test_redis_memory_adapter import memory_at
from .test_redis_memory_adapter import redis_service as redis_service
from .test_temporal_session_tree_service import Provider, definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


async def scenario(root, private, scope, kind, managed, rooted=True):
    from temporalio.client import Client

    for backend in (root, private):
        await backend.initialize_session_identity()
    provider = Provider()
    catalog = BindingCatalog(scope=scope)
    catalog.register(
        "session",
        "member",
        "1",
        SessionBindingResource(
            private, namespaces=("private-a", "private-b"), default_namespace="private-a"
        ),
    )
    path = "graph/nodes/writer" if kind == "graph" else "team/members/writer"
    selected = BoundDefinition(
        definition(kind),
        {
            path: AgentBindingDescriptor(
                session=BindingSelection.ref("member", "1", selector={"namespace": "private-b"})
            )
        },
    )
    execution = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        enable_sessions=True,
        session_writes=True,
        session_store=SessionBindingResource(root, namespaces=("root",), default_namespace="root")
        if rooted
        else None,
        context_builder=ManagedContextPipeline() if managed else None,
        session_topology=CompositeSessionTopology(),
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    queue = "tree-remote-" + uuid.uuid4().hex
    engine = TemporalEngine(
        client,
        task_queue=queue,
        release=execution.orchestration_release,
        scope=scope,
        activity_timeout=3,
        drive_timeout=20,
    )
    host = Runtime.from_temporal(engine)
    addresses = []
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            entry = await host.open_session(selected, "chat", command_id="open")
            for index in (0, 1):
                turn = await entry.submit("task", command_id=f"turn-{index}", budget=32)
                for _ in range(100):
                    done = await engine.drive(turn.turn.run.run_id)
                    if done.state == "succeeded":
                        break
                    assert done.state in {"running", "waiting_reconciliation"}, done
                    await asyncio.sleep(0.05)
                assert done.state == "succeeded", done
                for _ in range(200):
                    if not (await entry.status()).busy:
                        break
                    await asyncio.sleep(0.05)
                assert not (await entry.status()).busy
                proof = await engine.diagnostics(turn.turn.run.run_id)
                assert proof.budget["spent"] == (3 if rooted else 2)
                assert proof.budget["reserved"] == proof.budget["unknown"] == 0
                if rooted:
                    assert (await root.read(scope, entry.ref.key.storage_key))[0] == index + 1
                else:
                    assert (await root.read(scope, entry.ref.key.storage_key))[0] == 0
                child_id = proof.workflow["children"][0]["run_id"]
                stages = await engine.session_stages(child_id)
                address = stages[0]["intent"]["address"]
                assert address.startswith('ralf-session-v1:["private-b","ralf-temporal-member-v1:')
                addresses.append(address)
                assert (await private.read(scope, address))[0] == index + 1
                if root is not private:
                    assert (await root.read(scope, address))[0] == 0
                for run_id in (child_id, turn.turn.run.run_id):
                    await replay_temporal_history(
                        await client.get_workflow_handle(run_id).fetch_history()
                    )
            assert addresses[0] == addresses[1]
            assert len(provider.calls) == 2
    finally:
        await execution.close_session_execution()
        await host.aclose()
        await engine.aclose()


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("rooted", [False, True])
def test_actual_redis_tree_independent_namespaces(redis_service, managed, rooted):
    async def run():
        async with memory_at(redis_service, "tree-" + uuid.uuid4().hex) as (backend, _):
            await scenario(
                backend, backend, Scope("tree-redis", uuid.uuid4().hex), "graph", managed, rooted
            )

    asyncio.run(asyncio.wait_for(run(), timeout=90))


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("rooted", [False, True])
def test_actual_postgres_tree_independent_namespaces(postgres_dsn, managed, rooted):
    async def run():
        async with stores(postgres_dsn) as (backend, _, scope):
            await scenario(backend, backend, scope, "team", managed, rooted)

    asyncio.run(asyncio.wait_for(run(), timeout=90))


@pytest.mark.parametrize("managed", [False, True])
def test_actual_redis_root_postgres_private_are_independent(redis_service, postgres_dsn, managed):
    async def run():
        async with stores(postgres_dsn) as (pg, _, scope):
            async with memory_at(redis_service, "mixed-tree-" + uuid.uuid4().hex) as (redis, _):
                await scenario(redis, pg, scope, "graph", managed)

    asyncio.run(asyncio.wait_for(run(), timeout=90))


async def lost_root_ack_scenario(backend, scope):
    append = backend.append
    writes = []

    async def committed_then_lost(*args, **kwargs):
        value = await append(*args, **kwargs)
        writes.append((args[1], kwargs["message_id"]))
        if "ralf-temporal-member-v1:" not in args[1] and len(writes) == 2:
            raise OSError("lost root acknowledgement after actual database commit")
        return value

    backend.append = committed_then_lost
    try:
        await scenario(backend, backend, scope, "graph", True)
        assert len(writes) == len(set(writes)) == 4
    finally:
        backend.append = append


def test_actual_redis_original_root_recovers_committed_lost_ack(redis_service):
    async def run():
        async with memory_at(redis_service, "root-ack-" + uuid.uuid4().hex) as (backend, _):
            await lost_root_ack_scenario(backend, Scope("root-ack", uuid.uuid4().hex))

    asyncio.run(asyncio.wait_for(run(), timeout=90))


def test_actual_postgres_original_root_recovers_committed_lost_ack(postgres_dsn):
    async def run():
        async with stores(postgres_dsn) as (backend, _, scope):
            await lost_root_ack_scenario(backend, scope)

    asyncio.run(asyncio.wait_for(run(), timeout=90))
