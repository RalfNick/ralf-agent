"""Actual original Temporal Worker/History with selected persistent Artifact targets."""

import asyncio
import json
import os
import uuid

import pytest

import ralf_agent as r
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime

from .test_artifact_binding_execution import Reader, definition

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("backend_kind", ["sqlite", "file"])
@pytest.mark.parametrize("kind", ["agent", "sequence", "graph", "team", "dynamic", "nested"])
def test_actual_artifact_member_targets_approval_restart_replay(tmp_path, kind, backend_kind):
    queue = "artifact-bindings-" + uuid.uuid4().hex
    scope = r.Scope("artifact-tests", queue)
    observed, puts = [], []

    async def run():
        from temporalio.client import Client

        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        handle = None
        for _stage in range(3):
            base_cls = r.SQLiteArtifactStore if backend_kind == "sqlite" else r.FileArtifactStore

            class Recorded(base_cls):
                def put(self, *args, **kwargs):
                    receipt = super().put(*args, **kwargs)
                    puts.append(receipt.artifact_id)
                    # Lose the return only after the physical content is committed.
                    raise RuntimeError("test receipt lost after original durable write")

            stores = {
                name: Recorded(tmp_path / (name + ".artifacts"), backend_id=name)
                for name in ("alpha", "beta")
            }
            original = r.InMemoryArtifactStore(backend_id="original")
            catalog = r.BindingCatalog(scope=scope)
            for name, store in stores.items():
                catalog.register(
                    "artifacts",
                    name,
                    "1",
                    r.ArtifactBindingResource(
                        store, version="1", namespaces=[name], default_namespace=name
                    ),
                )
            tools = r.ToolRegistry()

            def lookup(args, ctx):
                observed.append(ctx.run_id)
                return "EVIDENCE" * 1600

            tools.register(
                r.ToolSpec(
                    "lookup",
                    "Read",
                    {"type": "object"},
                    effect="read_only",
                    requires_approval=True,
                    cost=0,
                ),
                lookup,
            )
            execution = TemporalRuntime(
                providers={"default": Reader()},
                tools=tools,
                context_builder=r.ManagedDataContext(
                    original, scope=scope, tool_result_chars=1024, preview_chars=64
                ),
                binding_catalog=catalog,
                context_reads=True,
            )
            engine = TemporalEngine(
                client,
                task_queue=queue,
                release=execution.orchestration_release,
                scope=scope,
                activity_timeout=5,
                drive_timeout=30,
            )
            try:
                async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                    current = await engine.submit(
                        definition(kind), "read", command_id="s", budget=64
                    )
                    if handle is None:
                        handle = current
                        done = await engine.drive(handle.run_id, wait_seconds=20)
                        assert done.state == "waiting_approval" and not observed, done
                    else:
                        assert current == handle
                        for _ in range(8):
                            done = await engine.drive(handle.run_id, wait_seconds=20)
                            if done.state != "waiting_approval":
                                break
                            for item in done.pending:
                                target = item.get("run_id", handle.run_id)
                                receipt = await engine.approve(
                                    target,
                                    item["action_id"],
                                    item["digest"],
                                    command_id="approve-" + item["action_id"],
                                )
                                assert (
                                    await engine.approve(
                                        target,
                                        item["action_id"],
                                        item["digest"],
                                        command_id="approve-" + item["action_id"],
                                    )
                                    == receipt
                                )
                        assert done.state == "succeeded", done
                        runs = [handle.run_id]
                        verified = []
                        for identifier in runs:
                            diagnostics = await engine.diagnostics(identifier)
                            workflow = diagnostics.workflow or {}
                            runs.extend(child["run_id"] for child in workflow.get("children", []))
                            verified.extend(await engine.context_artifacts(identifier))
                            await replay_temporal_history(
                                await client.get_workflow_handle(identifier).fetch_history()
                            )
                        expected = ["alpha"] if kind == "agent" else ["alpha", "beta"]
                        assert (
                            sorted(item["intent"]["reference"]["backend_id"] for item in verified)
                            == expected
                        )
                        for item in verified:
                            raw = item["intent"]["reference"]
                            assert (
                                item["status"] == "verified"
                                and raw["namespace"] == raw["backend_id"]
                            )
                            assert (
                                json.loads(
                                    stores[raw["backend_id"]].get(
                                        scope, r.ArtifactReference.from_dict(raw)
                                    )
                                )
                                == "EVIDENCE" * 1600
                            )
            finally:
                await execution.close_context_execution()
                await engine.aclose()
                for store in stores.values():
                    store.close()
                original.close()
        assert len(observed) == len(puts) == (1 if kind == "agent" else 2)

    asyncio.run(asyncio.wait_for(run(), timeout=180))
