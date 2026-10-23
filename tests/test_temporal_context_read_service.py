"""Actual Temporal History read completion gates, Sessions and replay."""

import asyncio
import os
import uuid

import pytest

from relf_agent import ManagedContextPipeline, Runtime, Scope, SQLiteMemory
from relf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from relf_agent.temporal_session_topology import CompositeSessionTopology

from .test_temporal_context_read_composition import definition
from .test_temporal_persistent_session_data import runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["native", "sequence", "graph", "team", "plan", "dag", "nested"])
@pytest.mark.parametrize("managed", [False, True])
def test_actual_read_protocol_two_turns_original_compositions_and_replay(tmp_path, kind, managed):
    async def run():
        from temporalio.client import Client

        class Source(SQLiteMemory):
            def __init__(self, path):
                super().__init__(path)
                self.reads = []

            def read_page(self, scope, address, query):
                self.reads.append(address)
                return super().read_page(scope, address, query)

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "context-read-" + uuid.uuid4().hex
        source = Source(tmp_path / "session.sqlite")
        execution = runtime(
            source,
            context_reads=True,
            session_topology=CompositeSessionTopology(),
            context_builder=ManagedContextPipeline() if managed else None,
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("context-read-service", queue),
            activity_timeout=3,
            drive_timeout=25,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                session = await host.open_session(definition(kind), "chat", command_id="open")
                for index in (1, 2):
                    turn = await session.submit("question", command_id=f"turn-{index}", budget=64)
                    done = await engine.drive(turn.turn.run.run_id)
                    assert done.state == "succeeded", done
                    async with asyncio.timeout(15):
                        while (await session.status()).busy:  # noqa: ASYNC110 -- remote History observation
                            await asyncio.sleep(0.05)
                    pending, original = [done.run_id], []
                    while pending:
                        run_id = pending.pop()
                        raw = await engine._view(run_id, "diagnostics")
                        pending.extend(
                            child["run_id"] for child in raw["workflow"].get("children", [])
                        )
                        if raw["workflow"]["backend"] == "temporal":
                            reads = raw["context_reads"]
                            assert reads and all(read["status"] == "completed" for read in reads)
                            assert all(
                                read["response_observed"] and read["execution_end_proof"]
                                for read in reads
                            )
                            history = await client.get_workflow_handle(run_id).fetch_history()
                            epochs = {read["execution_epoch"] for read in reads}
                            assert len(epochs) == 1
                            original.extend(reads)
                        else:
                            history = await client.get_workflow_handle(run_id).fetch_history()
                        assert raw["budget"]["reserved"] == raw["budget"]["unknown"] == 0
                        assert raw["workflow"]["quiescent"] is True
                        await replay_temporal_history(history)
                    assert original
                    assert source.read(engine.scope, session.ref.key.storage_key)[0] == index * (
                        2 if kind == "sequence" else 1
                    )
                assert len(source.reads) == (4 if kind != "native" else 2)
                assert len(execution.providers["default"].messages) == (
                    4 if kind == "sequence" else 2
                )
                assert await execution.wait_context_executions(wait_timeout=3)
        finally:
            await execution.close_context_execution(wait_timeout=3)
            await execution.close_session_execution(wait_timeout=3)
            await host.aclose()
            await engine.aclose()
            source.store.close()

    asyncio.run(asyncio.wait_for(run(), 120))


@pytest.mark.parametrize("kind", ["native", "sequence", "team"])
@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("window", ["page", "metadata"])
def test_actual_cancel_or_timeout_keeps_reader_turn_until_original_end(kind, managed, window):
    async def run():
        import threading

        from temporalio.client import Client

        from relf_agent import InMemoryMemory, ThreadedMemoryAdapter
        from relf_agent.errors import CloseIncomplete

        started, release, stopped = (threading.Event() for _ in range(3))

        class Source(InMemoryMemory):
            def __init__(self):
                super().__init__()
                self.target_read = False
                self.pages = []

            def hold(self):
                started.set()
                try:
                    assert release.wait(15)
                finally:
                    stopped.set()

            def read_page(self, scope, address, query):
                self.pages.append(address)
                selected = kind != "team" or "ralf-temporal-member-v1:" in address
                if selected:
                    self.target_read = True
                    if window == "page":
                        self.hold()
                return super().read_page(scope, address, query)

            def inspect_session_identity(self):
                if self.target_read and window == "metadata":
                    self.hold()
                return super().inspect_session_identity()

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "held-context-read-" + uuid.uuid4().hex
        source = Source()
        execution = runtime(
            ThreadedMemoryAdapter(source),
            context_reads=True,
            session_topology=CompositeSessionTopology(),
            context_builder=ManagedContextPipeline() if managed else None,
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("held-context-read", queue),
            activity_timeout=1,
            drive_timeout=20,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                try:
                    session = await host.open_session(definition(kind), "chat", command_id="open")
                    turn = await session.submit("question", command_id="first", budget=64)
                    root_id = turn.turn.run.run_id
                    assert await asyncio.to_thread(started.wait, 5)
                    reader_id = root_id
                    if kind == "team":
                        parent = await engine.diagnostics(root_id)
                        reader_id = parent.workflow["children"][0]["run_id"]
                    # Metadata case observes the real server timeout; page case explicitly cancels.
                    if window == "page":
                        await engine.cancel(root_id, command_id="cancel")
                    async with asyncio.timeout(8):
                        while True:
                            reads = await engine.context_read_stages(reader_id)
                            state = await engine.status(reader_id)
                            if reads[0]["response_observed"] and state.state in {
                                "cancelled",
                                "failed",
                            }:
                                break
                            await asyncio.sleep(0.05)
                    assert not stopped.is_set()
                    assert (await engine.diagnostics(reader_id)).workflow["quiescent"] is False
                    assert (await session.status()).busy is True
                    assert await execution.wait_context_executions(wait_timeout=0) is False
                    with pytest.raises(CloseIncomplete):
                        await execution.close_context_execution(wait_timeout=0)
                    assert execution.providers["default"].messages == []
                    release.set()
                    assert await asyncio.to_thread(stopped.wait, 3)
                    assert await execution.wait_context_executions(wait_timeout=5)
                    async with asyncio.timeout(10):
                        while (await session.status()).busy:  # noqa: ASYNC110 -- actual History polling
                            await asyncio.sleep(0.05)
                    stages = await engine.context_read_stages(reader_id)
                    assert stages[0]["status"] == "completed" and stages[0]["execution_end_proof"]
                    assert (await engine.diagnostics(reader_id)).workflow["quiescent"] is True
                    assert len(source.pages) == (2 if kind == "team" else 1)
                    assert execution.providers["default"].messages == []
                    await replay_temporal_history(
                        await client.get_workflow_handle(reader_id).fetch_history()
                    )
                    if reader_id != root_id:
                        await replay_temporal_history(
                            await client.get_workflow_handle(root_id).fetch_history()
                        )
                finally:
                    release.set()
                    await execution.close_context_execution(wait_timeout=10)
                    await execution.close_session_execution(wait_timeout=10)
        finally:
            await host.aclose()
            await engine.aclose()

    asyncio.run(asyncio.wait_for(run(), 90))
