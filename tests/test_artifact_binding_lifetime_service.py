"""Selected Artifact async/actual-end and independent-process History recovery."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

import relf_agent as r
from relf_agent.errors import CloseIncomplete
from relf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.types import digest

from .artifact_binding_crash_worker import runtime as process_runtime
from .test_artifact_binding_execution import Reader, definition
from .test_artifact_binding_lifetime import NativeAsyncArtifacts, components

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_actual_native_async_artifact_replacement_preserves_history_receipts(tmp_path):
    async def run():
        from temporalio.client import Client

        queue = "artifact-async-" + uuid.uuid4().hex
        scope = r.Scope("artifact-native-async", queue)
        target = NativeAsyncArtifacts()
        catalog, resource, tools, context, observed = components(scope, target)
        execution = TemporalRuntime(
            providers={"default": Reader()},
            tools=tools,
            context_builder=context,
            binding_catalog=catalog,
            context_reads=True,
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
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
                handle = await engine.submit(definition("agent"), "read", command_id="s", budget=32)
                done = await engine.drive(handle.run_id, wait_seconds=20)
                assert done.state == "succeeded", done
                record = (await engine.context_artifacts(handle.run_id))[0]
                assert record["status"] == "verified"
                reference = r.ArtifactReference.from_dict(record["intent"]["reference"])
                assert reference.backend_id == reference.namespace == "alpha"
                assert (reference.workspace, reference.principal) == (
                    scope.workspace,
                    scope.principal,
                )
                assert json.loads(await target.get(scope, reference)) == "EVIDENCE" * 1600
                assert target.puts == 1 and observed == [handle.run_id]
                assert all(loop is asyncio.get_running_loop() for loop in target.loops)
                assert not resource._threads.has_active
                assert await execution.wait_context_executions(wait_timeout=5)
                await replay_temporal_history(
                    await client.get_workflow_handle(handle.run_id).fetch_history()
                )
            receipt = await target.put(scope, "alpha", "borrowed async replacement")
            assert await target.get(scope, receipt) == "borrowed async replacement"
        finally:
            await execution.close_context_execution(wait_timeout=5)
            await engine.aclose()
            context.artifacts.close()

    asyncio.run(asyncio.wait_for(run(), 90))


def test_actual_cancel_and_close_retain_selected_sync_reader_until_original_end(tmp_path):
    async def run():
        from temporalio.client import Client

        started, release, finished = (threading.Event() for _ in range(3))

        class Held(r.SQLiteArtifactStore):
            hold_next = True

            def get(self, *args, **kwargs):
                value = super().get(*args, **kwargs)
                if self.hold_next:
                    self.hold_next = False
                    self.started.set()
                    try:
                        assert self.release.wait(20)
                    finally:
                        self.finished.set()
                return value

        queue = "artifact-held-" + uuid.uuid4().hex
        scope = r.Scope("artifact-held", queue)
        target = Held(tmp_path / "selected.sqlite", backend_id="alpha")
        target.started, target.release, target.finished = started, release, finished
        catalog, resource, tools, context, observed = components(scope, target)
        execution = TemporalRuntime(
            providers={"default": Reader()},
            tools=tools,
            context_builder=context,
            binding_catalog=catalog,
            context_reads=True,
        )
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=2,
            drive_timeout=20,
        )
        try:
            async with build_temporal_worker(client, task_queue=queue, runtime=execution):
                try:
                    handle = await engine.submit(
                        definition("agent"), "read", command_id="s", budget=32
                    )
                    assert await asyncio.to_thread(started.wait, 8)
                    await engine.cancel(handle.run_id, command_id="cancel")
                    async with asyncio.timeout(8):
                        while True:
                            reads = await engine.context_read_stages(handle.run_id)
                            held = [item for item in reads if item.get("phase") == "verify"]
                            if held and held[0]["response_observed"]:
                                break
                            await asyncio.sleep(0.05)
                    assert not finished.is_set()
                    assert held[0]["execution_end_proof"] is None
                    assert (await engine.diagnostics(handle.run_id)).workflow["quiescent"] is False
                    assert await execution.wait_context_executions(wait_timeout=0) is False
                    with pytest.raises(CloseIncomplete):
                        await execution.close_context_execution(wait_timeout=0)
                    assert execution.context_execution.active_count == 1
                    assert observed == [handle.run_id]
                    release.set()
                    assert await asyncio.to_thread(finished.wait, 5)
                    assert await execution.wait_context_executions(wait_timeout=10)
                    async with asyncio.timeout(10):
                        while not (await engine.diagnostics(handle.run_id)).workflow["quiescent"]:  # noqa: ASYNC110 -- actual History polling
                            await asyncio.sleep(0.05)
                    held = [
                        item
                        for item in await engine.context_read_stages(handle.run_id)
                        if item.get("phase") == "verify"
                    ]
                    assert held[0]["status"] == "completed" and held[0]["execution_end_proof"]
                    assert (await engine.status(handle.run_id)).state == "cancelled"
                    assert execution.context_execution.active_count == 0
                    assert not resource._threads.has_active
                    await replay_temporal_history(
                        await client.get_workflow_handle(handle.run_id).fetch_history()
                    )
                finally:
                    release.set()
                    await execution.close_context_execution(wait_timeout=10)
        finally:
            release.set()
            await resource.wait_for_calls()
            await engine.aclose()
            target.close()
            context.artifacts.close()

    asyncio.run(asyncio.wait_for(run(), 90))


@pytest.mark.parametrize("backend_kind", ["sqlite", "file"])
@pytest.mark.parametrize("window", ["intent", "receipt"])
def test_actual_independent_worker_kill_recovers_selected_intent_or_lost_receipt(
    tmp_path, backend_kind, window
):
    async def run():
        from temporalio.client import Client

        queue = "artifact-crash-" + uuid.uuid4().hex
        execution, target, original, scope = process_runtime(tmp_path, queue, backend_kind)
        client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=execution.orchestration_release,
            scope=scope,
            activity_timeout=2,
            drive_timeout=30,
        )
        processes = []
        log_root = Path(os.getenv("RALF_ARTIFACT_TEST_LOG_ROOT", str(tmp_path))) / queue
        log_root.mkdir(parents=True, exist_ok=True)

        async def start(mode):
            log_path = log_root / f"worker-{len(processes)}.log"
            environment = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.pathsep.join(
                    [str(Path(__file__).parents[1] / "src"), str(Path(__file__).parents[1])]
                ),
                "RALF_TEST_TEMPORAL_ADDRESS": os.environ["RALF_TEST_TEMPORAL_ADDRESS"],
                "RALF_TEST_TEMPORAL_QUEUE": queue,
                "RALF_ARTIFACT_ROOT": str(tmp_path),
                "RALF_ARTIFACT_BACKEND": backend_kind,
                "RALF_ARTIFACT_WINDOW": mode,
            }
            with log_path.open("w") as log:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        "from tests.artifact_binding_crash_worker import run; import asyncio; asyncio.run(run())",
                    ],
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            processes.append(process)
            async with asyncio.timeout(15):
                while "ARTIFACT_WORKER_READY" not in log_path.read_text():
                    assert process.poll() is None, log_path.read_text()
                    await asyncio.sleep(0.05)
            return process

        try:
            first = await start(window)
            handle = await engine.submit(definition("agent"), "read", command_id="s", budget=32)
            marker = tmp_path / "window-ready"
            async with asyncio.timeout(20):
                while not marker.exists():
                    assert first.poll() is None, (log_root / "worker-0.log").read_text()
                    await asyncio.sleep(0.05)
            fault = json.loads(marker.read_text())
            original_reference = fault["reference"]
            first.kill()
            await asyncio.to_thread(first.wait, timeout=5)
            assert first.returncode is not None
            await start("resume")
            done = await engine.drive(handle.run_id, wait_seconds=25)
            assert done.state == "succeeded", (done.error, done.actions)
            records = await engine.context_artifacts(handle.run_id)
            assert len(records) == 1 and records[0]["status"] == "verified"
            assert records[0]["intent"]["reference"] == original_reference
            reference = r.ArtifactReference.from_dict(original_reference)
            assert reference.backend_id == reference.namespace == "alpha"
            assert (reference.workspace, reference.principal) == (scope.workspace, scope.principal)
            assert json.loads(target.get(scope, reference)) == "EVIDENCE" * 1600
            with sqlite3.connect(tmp_path / "audit.sqlite") as audit:
                counts = dict(audit.execute("SELECT kind, COUNT(*) FROM calls GROUP BY kind"))
            assert counts == {"model": 2, "tool": 1, "put": 1}
            diagnostics = await engine.diagnostics(handle.run_id)
            if window == "receipt":
                # A restarted Worker cannot forge an original writer's stop proof.
                assert diagnostics.workflow["unknown_remote_execution"] is True
                assert diagnostics.workflow["quiescent"] is False
                writes = [action for action in done.actions if action.get("phase") == "write"]
                assert len(writes) == 1 and writes[0]["status"] == "outcome_unknown"
            else:
                request = fault["request"]
                admission = {
                    key: request[key]
                    for key in (
                        "scope",
                        "run_id",
                        "action_id",
                        "release_digest",
                        "execution_epoch",
                        "phase",
                    )
                } | {"request_digest": digest(request)}
                old_admission = await client.get_workflow_handle(handle.run_id).execute_update(
                    "admit_context_dispatch", admission, id="late-killed-reader-admission"
                )
                assert old_admission["allowed"] is False
                async with asyncio.timeout(10):
                    while not (await engine.diagnostics(handle.run_id)).workflow["quiescent"]:  # noqa: ASYNC110 -- actual History polling
                        await asyncio.sleep(0.05)
            await replay_temporal_history(
                await client.get_workflow_handle(handle.run_id).fetch_history()
            )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)
                assert process.returncode is not None
            await execution.close_context_execution(wait_timeout=5)
            await engine.aclose()
            target.close()
            original.close()

    asyncio.run(asyncio.wait_for(run(), 120))
