"""Actual root/private Sessions with bound RAG and automatic rule/model memory."""

import asyncio
import os
import uuid

import pytest

from ralf_agent import (
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
    Runtime,
    Scope,
    SQLiteMemory,
)
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_topology import CompositeSessionTopology
from tests.temporal_memory_worker import definition
from tests.temporal_memory_worker import runtime as memory_runtime

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["parallel", "dynamic-dag", "nested"])
def test_actual_tree_bound_memory_and_rag_finish_before_root_save(
    tmp_path, kind, context_reads=False
):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "tree-memory-" + uuid.uuid4().hex
        scope = Scope("temporal-memory", queue)
        base, facts = memory_runtime(tmp_path, queue)
        sessions = SQLiteMemory(tmp_path / "sessions.sqlite")
        knowledge = InMemoryKnowledgeStore()
        knowledge.put(
            scope,
            "runbooks",
            Document("manual", "task first-result second-result runbook evidence"),
            expected_version=0,
        )
        execution = TemporalRuntime(
            providers=base.providers,
            tools=base.tools,
            binding_catalog=base.binding_catalog,
            stage_policy=base.stage_policy,
            knowledge=KnowledgeContext(LexicalRetriever(knowledge), namespace="runbooks"),
            session_store=sessions,
            enable_sessions=True,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
            **({"context_reads": True} if context_reads else {}),
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=3,
            drive_timeout=25,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(definition(kind), "chat", command_id="open")
                for index in (0, 1):
                    turn = await entry.submit("task", command_id=f"turn-{index}", budget=32)
                    done = await engine.drive(turn.turn.run.run_id)
                    assert done.state == "succeeded", done
                    for _ in range(200):
                        if not (await entry.status()).busy:
                            break
                        await asyncio.sleep(0.05)
                    assert not (await entry.status()).busy
                    pending, members = [turn.turn.run.run_id], 0
                    while pending:
                        run_id = pending.pop()
                        proof = await engine.diagnostics(run_id)
                        pending.extend(
                            value["run_id"] for value in proof.workflow.get("children", [])
                        )
                        stages = await engine.memory_stages(run_id)
                        if stages:
                            if context_reads:
                                reads = await engine.context_read_stages(run_id)
                                assert reads and all(
                                    read["status"] == "completed" for read in reads
                                )
                            members += len(stages)
                            assert all(value["status"] == "completed" for value in stages)
                            contexts = [
                                value.get("response", {})
                                for value in proof.snapshot.actions
                                if value["kind"] == "context"
                            ]
                            raw = await engine._view(run_id, "diagnostics")
                            contexts.extend(
                                value.get("prepared", {}) for value in raw.get("context_stages", [])
                            )
                            assert any(
                                value.get("knowledge_references") or value.get("references")
                                for value in contexts
                            ), (
                                contexts,
                                [(a["kind"], a.get("phase")) for a in proof.snapshot.actions],
                            )
                            assert (await engine.session_stages(run_id))[0]["status"] == "completed"
                        assert proof.budget["reserved"] == proof.budget["unknown"] == 0
                        await replay_temporal_history(
                            await client.get_workflow_handle(run_id).fetch_history()
                        )
                    assert members == 2
                    assert sessions.read(scope, entry.ref.key.storage_key)[0] == index + 1
                for namespace in ("one", "two"):
                    from ralf_agent.recall import RecallQuery

                    record = facts.recall(scope, namespace, RecallQuery())
                    assert record.items, namespace
        finally:
            if context_reads:
                await execution.close_context_execution()
            await execution.close_session_execution()
            await host.aclose()
            await engine.aclose()
            facts.store.close()
            sessions.store.close()

    asyncio.run(asyncio.wait_for(run(), timeout=120))
