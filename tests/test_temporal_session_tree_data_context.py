"""Actual managed summary/offload adoption keeps original root/private snapshots."""

import asyncio
import os
import uuid

import pytest

from ralf_agent import Runtime, Scope, SQLiteMemory, TeamSpec
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_topology import CompositeSessionTopology
from tests.temporal_managed_context_worker import runtime as data_runtime
from tests.test_composite_data_context import agent

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("artifact_backend", ["sqlite", "file"])
def test_actual_tree_summary_and_offload_preserve_sources_across_turns(tmp_path, artifact_backend):
    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        queue = "tree-data-" + uuid.uuid4().hex
        base, artifacts = data_runtime(tmp_path, queue, artifact_backend=artifact_backend)

        class ObservedMemory(SQLiteMemory):
            def __init__(self, path):
                super().__init__(path)
                self.reads = []

            def read_page(self, scope, address, query):
                self.reads.append(address)
                return super().read_page(scope, address, query)

        backend = ObservedMemory(tmp_path / "sessions.sqlite")
        execution = TemporalRuntime(
            providers=base.providers,
            tools=base.tools,
            context_builder=base.context,
            session_store=backend,
            enable_sessions=True,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=Scope("h3-temporal", queue),
            activity_timeout=3,
            drive_timeout=25,
        )
        host = Runtime.from_temporal(engine)
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                entry = await host.open_session(
                    TeamSpec("team", {"writer": agent()}, child_budget=16),
                    "chat",
                    command_id="open",
                )
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
                    child_id = proof.workflow["children"][0]["run_id"]
                    raw = await engine._view(child_id, "diagnostics")
                    contexts = raw["context_stages"]
                    assert any(stage.get("summary_response") for stage in contexts)
                    assert any(stage.get("prepared", {}).get("offloads") for stage in contexts)
                    assert all(stage["status"] == "completed" for stage in contexts)
                    saves = await engine.session_stages(child_id)
                    assert saves[0]["status"] == "completed"
                    assert backend.read(engine.scope, saves[0]["intent"]["address"])[0] == index + 1
                    assert backend.read(engine.scope, entry.ref.key.storage_key)[0] == index + 1
                    assert raw["budget"]["reserved"] == raw["budget"]["unknown"] == 0
                    for run_id in (turn.turn.run.run_id, child_id):
                        await replay_temporal_history(
                            await client.get_workflow_handle(run_id).fetch_history()
                        )
                assert execution.providers["default"].summaries >= 2
            # Exactly one original root and one original private snapshot per Turn,
            # independent of subsequent model/summary/offload context rebuilds.
            assert len(backend.reads) == 4
        finally:
            await execution.close_session_execution()
            await host.aclose()
            await engine.aclose()
            backend.store.close()
            artifacts.close()

    asyncio.run(asyncio.wait_for(run(), timeout=120))
