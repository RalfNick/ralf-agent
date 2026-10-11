"""Actual SDK History for original root and stable private member Sessions."""

import asyncio
import os
import uuid

import pytest

from ralf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    ManagedContextPipeline,
    ModelResponse,
    Runtime,
    Scope,
    SessionBindingResource,
    SQLiteMemory,
    TeamSpec,
    ToolRegistry,
)
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_topology import CompositeSessionTopology

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class Provider:
    identity = {"kind": "session-tree-service", "version": "1"}

    def __init__(self):
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(messages)
        return ModelResponse(output="answer")


def definition(kind):
    agent = AgentSpec("writer", "Answer")
    graph = GraphWorkflowSpec("g", [GraphNode("writer", agent=agent)])
    if kind == "graph":
        return graph
    if kind == "team":
        return TeamSpec("t", {"writer": agent})
    if kind == "dynamic":
        return DynamicWorkflowSpec("d", {"writer": agent}, planner="dag-rule", plan_mode="dag")
    return TeamSpec("nested", {"graph": graph})


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic", "nested"])
@pytest.mark.parametrize("managed", [False, True])
def test_actual_root_and_member_sessions_two_turns_and_replay(tmp_path, kind, managed):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "session-tree-" + uuid.uuid4().hex
        backend, provider = SQLiteMemory(tmp_path / "data.sqlite"), Provider()
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=SessionBindingResource(
                backend, namespaces=("chat",), default_namespace="chat"
            ),
            context_builder=ManagedContextPipeline() if managed else None,
            enable_sessions=True,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("session-tree", queue),
            activity_timeout=3,
            drive_timeout=20,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(definition(kind), "chat", command_id="open")
                members = []
                for index in (0, 1):
                    turn = await entry.submit("task", command_id=f"turn-{index}", budget=32)
                    done = await engine.drive(turn.turn.run.run_id)
                    assert done.state == "succeeded", done
                    for _ in range(200):
                        if not (await entry.status()).busy:
                            break
                        await asyncio.sleep(0.05)
                    assert not (await entry.status()).busy
                    proof = await engine.diagnostics(turn.turn.run.run_id)
                    assert proof.budget["spent"] == 3
                    assert proof.budget["reserved"] == proof.budget["unknown"] == 0
                    assert backend.read(engine.scope, entry.ref.key.storage_key)[0] == index + 1
                    pending = [turn.turn.run.run_id]
                    private = []
                    while pending:
                        run_id = pending.pop()
                        child = await engine.diagnostics(run_id)
                        for stage in await engine.session_stages(run_id):
                            private.append(stage["intent"]["address"])
                        pending.extend(c["run_id"] for c in child.workflow.get("children", []))
                        await replay_temporal_history(
                            await client.get_workflow_handle(run_id).fetch_history()
                        )
                    members.append(private)
                assert len(provider.calls) == 2
                assert members[0] == members[1]
        finally:
            await execution.close_session_execution(wait_timeout=3)
            await host.aclose()
            await engine.aclose()
            backend.store.close()

    asyncio.run(run())


def test_cancelled_parent_retains_actual_root_handler_until_late_receipt(tmp_path):
    async def run():
        import threading

        from temporalio.client import Client

        from ralf_agent import InMemoryMemory, ThreadedMemoryAdapter
        from ralf_agent.errors import CloseIncomplete, SessionBusy

        committed, finish = threading.Event(), threading.Event()

        class DelayedRoot(InMemoryMemory):
            def append(self, scope, address, message, *, expected_revision, message_id):
                revision = super().append(
                    scope,
                    address,
                    message,
                    expected_revision=expected_revision,
                    message_id=message_id,
                )
                if "ralf-temporal-member-v1:" not in address:
                    committed.set()
                    assert finish.wait(30), "test must release actual root handler"
                return revision

        backend, provider = DelayedRoot(), Provider()
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=ThreadedMemoryAdapter(backend),
            enable_sessions=True,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "tree-cancel-" + uuid.uuid4().hex
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("tree-cancel", queue),
            activity_timeout=1,
            drive_timeout=10,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(definition("graph"), "chat", command_id="open")
                turn = await entry.submit("task", command_id="first", budget=32)
                for _ in range(200):
                    if committed.is_set():
                        break
                    await asyncio.sleep(0.05)
                assert committed.is_set()
                await engine.cancel(turn.turn.run.run_id, command_id="cancel")
                assert (await engine.status(turn.turn.run.run_id)).state == "cancelled"
                assert (await entry.status()).busy
                with pytest.raises(SessionBusy):
                    await entry.submit("next", command_id="busy")
                assert not await execution.wait_session_executions(wait_timeout=0.05)
                with pytest.raises(CloseIncomplete):
                    await execution.close_session_execution(wait_timeout=0.05)
                finish.set()
                for _ in range(200):
                    await engine.drive(turn.turn.run.run_id)
                    if not (await entry.status()).busy:
                        break
                    await asyncio.sleep(0.05)
                assert not (await entry.status()).busy
                proof = await engine.diagnostics(turn.turn.run.run_id)
                assert proof.snapshot.state == "cancelled"
                assert proof.budget["reserved"] == proof.budget["unknown"] == 0
                assert backend.read(engine.scope, entry.ref.key.storage_key)[0] == 1
                assert len(provider.calls) == 1
                await replay_temporal_history(
                    await client.get_workflow_handle(turn.turn.run.run_id).fetch_history()
                )
        finally:
            finish.set()
            await execution.close_session_execution(wait_timeout=3)
            await host.aclose()
            await engine.aclose()

    asyncio.run(asyncio.wait_for(run(), timeout=90))


@pytest.mark.parametrize("kind", ["parallel", "sequence", "flat", "model-dag"])
def test_additional_original_tree_execution_shapes(tmp_path, kind):
    async def run():
        from temporalio.client import Client

        from ralf_agent import DAGNode, DAGProposal, ValueRef, WorkflowSpec

        class PlanningProvider(Provider):
            identity = {"kind": "tree-shapes-service", "version": "1"}

            async def complete(self, messages, tools):
                self.calls.append(messages)
                if "Return a JSON DAG" in messages[0]["content"]:
                    return ModelResponse(
                        output={
                            "status": "plan",
                            **DAGProposal(
                                [DAGNode("step-0", "writer")], output=ValueRef("step-0")
                            ).to_dict(),
                        }
                    )
                return ModelResponse(output="answer")

        agent = AgentSpec("writer", "Answer")
        if kind == "parallel":
            spec = GraphWorkflowSpec(
                "parallel",
                [GraphNode("left", agent=agent), GraphNode("right", agent=agent)],
                max_concurrency=2,
            )
        elif kind == "sequence":
            spec = TeamSpec("sequence-member", {"writer": WorkflowSpec("seq", [agent, agent])})
        else:
            spec = DynamicWorkflowSpec(
                "planned",
                {"writer": agent},
                planner="dag-model" if kind == "model-dag" else "rule",
                plan_mode="dag" if kind == "model-dag" else "flat",
            )
        provider, backend = PlanningProvider(), SQLiteMemory(tmp_path / "data.sqlite")
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=backend,
            enable_sessions=True,
            session_writes=True,
            context_builder=ManagedContextPipeline(),
            session_topology=CompositeSessionTopology(),
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "tree-shapes-" + uuid.uuid4().hex
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("tree-shapes", queue),
            activity_timeout=3,
            drive_timeout=15,
        )
        host = Runtime.from_temporal(engine)
        saved = []
        expected_calls = 1 if kind == "flat" else 2
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(spec, "chat", command_id="open")
                for index in (0, 1):
                    turn = await entry.submit("task", command_id=f"turn-{index}", budget=32)
                    done = await engine.drive(turn.turn.run.run_id)
                    assert done.state == "succeeded", done
                    for _ in range(200):
                        if not (await entry.status()).busy:
                            break
                        await asyncio.sleep(0.05)
                    assert not (await entry.status()).busy
                    proof = await engine.diagnostics(turn.turn.run.run_id)
                    assert proof.budget["spent"] == expected_calls * 2 + 1
                    pending, addresses = [turn.turn.run.run_id], []
                    while pending:
                        run_id = pending.pop()
                        for stage in await engine.session_stages(run_id):
                            address = stage["intent"]["address"]
                            addresses.append(address)
                            assert backend.read(engine.scope, address)[0] == index + 1
                        proof = await engine.diagnostics(run_id)
                        pending.extend(
                            value["run_id"] for value in proof.workflow.get("children", [])
                        )
                        await replay_temporal_history(
                            await client.get_workflow_handle(run_id).fetch_history()
                        )
                    assert len(set(addresses)) == expected_calls + 1
                    saved.append(sorted(addresses))
                assert saved[0] == saved[1]
                assert len(provider.calls) == expected_calls * 2
        finally:
            await execution.close_session_execution()
            await host.aclose()
            await engine.aclose()
            backend.store.close()

    asyncio.run(asyncio.wait_for(run(), timeout=90))


def test_root_read_timeout_owns_actual_thread_and_turn_until_end(tmp_path):
    async def run():
        import threading

        from temporalio.client import Client

        from ralf_agent import InMemoryMemory, ThreadedMemoryAdapter
        from ralf_agent.errors import CloseIncomplete, SessionBusy

        started, finish, stopped = threading.Event(), threading.Event(), threading.Event()

        class BlockedRoot(InMemoryMemory):
            reads = 0

            def read_page(self, scope, address, query):
                self.reads += 1
                started.set()
                try:
                    assert finish.wait(30), "test must release actual reader"
                    return super().read_page(scope, address, query)
                finally:
                    stopped.set()

        backend, provider = BlockedRoot(), Provider()
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=ThreadedMemoryAdapter(backend),
            enable_sessions=True,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "root-read-owner-" + uuid.uuid4().hex
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("root-read-owner", queue),
            activity_timeout=1,
            drive_timeout=10,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(definition("graph"), "reader", command_id="open")
                turn = await entry.submit("task", command_id="first", budget=32)
                for _ in range(200):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.05)
                assert started.is_set()
                await engine.cancel(turn.turn.run.run_id, command_id="cancel")
                for _ in range(100):
                    proof = await engine.diagnostics(turn.turn.run.run_id)
                    actions = proof.snapshot.actions
                    if any(a["status"] == "outcome_unknown" for a in actions):
                        break
                    await asyncio.sleep(0.05)
                assert not stopped.is_set()
                assert (await entry.status()).busy
                assert not proof.workflow["quiescent"]
                with pytest.raises(SessionBusy):
                    await entry.submit("next", command_id="busy")
                assert not await execution.wait_session_executions(wait_timeout=0.05)
                with pytest.raises(CloseIncomplete):
                    await execution.close_session_execution(wait_timeout=0.05)
                finish.set()
                for _ in range(200):
                    await engine.drive(turn.turn.run.run_id)
                    if not (await entry.status()).busy:
                        break
                    await asyncio.sleep(0.05)
                assert stopped.is_set() and not (await entry.status()).busy
                assert backend.reads == 1 and not provider.calls
                assert (await engine.status(turn.turn.run.run_id)).state == "cancelled"
                assert await execution.wait_session_executions(wait_timeout=3)
                await replay_temporal_history(
                    await client.get_workflow_handle(turn.turn.run.run_id).fetch_history()
                )
        finally:
            finish.set()
            await execution.close_session_execution(wait_timeout=3)
            await host.aclose()
            await engine.aclose()

    asyncio.run(asyncio.wait_for(run(), timeout=60))
