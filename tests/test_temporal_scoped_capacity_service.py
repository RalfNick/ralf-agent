"""Actual default scoped4096 pressure and old Worker capability compatibility."""

import asyncio
import json
import os
import uuid
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import pytest

from ralf_agent import Scope
from ralf_agent.errors import ValidationError
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import COMMAND_REGISTRY_CAPACITY
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import BusinessProbe, _agent, _eventually

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


def test_actual_default_scoped_capacity_keeps_original_first_cancel(tmp_path):
    async def run():
        from temporalio.client import WorkflowExecutionStatus

        clients, namespace = await _clients()
        client, queue = clients[0], "scoped-capacity-" + uuid.uuid4().hex
        scope, probe = Scope("scoped-capacity", queue), BusinessProbe()
        runtime = TemporalRuntime(providers={"default": probe}, tools=probe.tools(approval=True))
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=runtime.manifest,
            scope=scope,
            activity_timeout=5,
            drive_timeout=30,
        )
        worker = build_temporal_worker(
            client,
            task_queue=queue,
            runtime=runtime,
            graceful_shutdown_timeout=timedelta(seconds=1),
        )
        original = None
        try:
            async with worker:
                original = await engine.submit(_agent("original"), {}, command_id="original")
                await _eventually(
                    lambda: engine.status(original.run_id), lambda s: s.state == "waiting_approval"
                )
                registry = client.get_workflow_handle(engine.command_registry_id)
                for start in range(1, COMMAND_REGISTRY_CAPACITY, 48):
                    await asyncio.gather(
                        *[
                            engine._guard(
                                "drive",
                                f"fill:{i}",
                                original.run_id,
                                {"kind": "drive", "scope": asdict(scope)},
                            )
                            for i in range(start, min(start + 48, COMMAND_REGISTRY_CAPACITY))
                        ]
                    )
                    (tmp_path / "progress.json").write_text(
                        json.dumps({"accepted": min(start + 48, COMMAND_REGISTRY_CAPACITY)})
                    )
                view = await registry.query("view", {"scope": asdict(scope), "kind": "status"})
                assert view["accepted_commands"] == COMMAND_REGISTRY_CAPACITY
                with pytest.raises(ValidationError):
                    await engine.submit(_agent("new"), {}, command_id="refused-new")
                receipt = await engine.cancel(original.run_id, command_id="original-stop")
                assert (
                    receipt.apply_state == "applied"
                    and receipt.outcome["remote_stop_confirmed"] is True
                )
                assert (await engine.status(original.run_id)).state == "cancelled"
                assert (await engine.diagnostics(original.run_id)).workflow["quiescent"] is True
                assert await engine.cancel(original.run_id, command_id="original-stop") == receipt
                with pytest.raises(ValidationError):
                    await engine.cancel(original.run_id, command_id="different-stop")
                view = await registry.query("view", {"scope": asdict(scope), "kind": "status"})
                assert view["accepted_commands"] == COMMAND_REGISTRY_CAPACITY + 1
                assert probe.reads == []
                for name, handle in (
                    ("run", client.get_workflow_handle(original.run_id)),
                    ("registry", registry),
                ):
                    history = await handle.fetch_history()
                    await replay_temporal_history(history, namespace=namespace["name"])
                    (tmp_path / (name + "-history.json")).write_text(history.to_json())
                (tmp_path / "result.json").write_text(
                    json.dumps(
                        {
                            "capacity": COMMAND_REGISTRY_CAPACITY,
                            "accepted_after_cancel": view["accepted_commands"],
                            "tool_calls": 0,
                            "original_receipt_repeated": True,
                            "run_and_registry_replayed": True,
                            "external_model_calls": 0,
                        },
                        indent=2,
                    )
                )
        finally:
            probe.release.set()
            from temporalio.service import RPCError, RPCStatusCode

            for target in ([original.run_id] if original is not None else []) + [
                engine.command_registry_id
            ]:
                handle = client.get_workflow_handle(target)
                try:
                    if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                        await handle.terminate(reason="owned scoped capacity test cleanup")
                    assert (await handle.describe()).status != WorkflowExecutionStatus.RUNNING
                except RPCError as exc:
                    if exc.status != RPCStatusCode.NOT_FOUND:
                        raise
            await engine.aclose()
            assert worker.is_shutdown and not worker.is_running
            (tmp_path / "cleanup.json").write_text(
                json.dumps(
                    {
                        "worker_shutdown": True,
                        "engine_closed": engine._closed,
                        "owned_histories_closed": True,
                    }
                )
            )

    asyncio.run(asyncio.wait_for(run(), 180))


@pytest.mark.skipif(
    not os.getenv("RALF_TEST_LEGACY_PYTHON"), reason="requires immutable basic SDK interpreter"
)
def test_actual_old_scoped_worker_uses_confirmed_legacy_update_and_replays(tmp_path):
    async def run():
        clients, namespace = await _clients()
        client, queue = clients[0], "scoped-legacy-" + uuid.uuid4().hex
        scope, probe = Scope("scoped-legacy", queue), BusinessProbe()
        runtime = TemporalRuntime(providers={"default": probe}, tools=probe.tools())
        engine = TemporalEngine(client, task_queue=queue, release=runtime.manifest, scope=scope)
        environment = {
            k: os.environ[k]
            for k in ("PATH", "HOME", "TMPDIR", "RALF_TEST_TEMPORAL_ADDRESS")
            if k in os.environ
        }
        environment["RALF_TEST_TEMPORAL_NAMESPACE"] = namespace["name"]
        with (tmp_path / "legacy.log").open("w") as log:
            process = await asyncio.create_subprocess_exec(
                os.environ["RALF_TEST_LEGACY_PYTHON"],
                "-I",
                str(Path(__file__).with_name("scoped_registry_legacy_fixture.py")),
                queue,
                str(tmp_path),
                env=environment,
                stdout=log,
                stderr=log,
            )
            failure = None
            try:
                async with asyncio.timeout(15):
                    while not (tmp_path / "ready.json").exists():
                        assert process.returncode is None, (
                            "original legacy Worker exited before readiness"
                        )
                        await asyncio.sleep(0.02)
                await engine._guard(
                    "submit", "original", "original-run", {"definition": "legacy-probe"}
                )
                handle = client.get_workflow_handle(engine.command_registry_id)
                status = await handle.query("view", {"scope": asdict(scope), "kind": "status"})
                assert status["accepted_commands"] == 1
                history = await handle.fetch_history()
                assert not any(
                    e.HasField("workflow_execution_signaled_event_attributes")
                    for e in history.events
                )
                await replay_temporal_history(history, namespace=namespace["name"])
                (tmp_path / "legacy-registry-history.json").write_text(history.to_json())
            except BaseException as exc:
                failure = exc
            finally:
                from temporalio.client import WorkflowExecutionStatus
                from temporalio.service import RPCError, RPCStatusCode

                failures = [failure] if failure is not None else []
                try:
                    handle = client.get_workflow_handle(engine.command_registry_id)
                    try:
                        if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                            await handle.terminate(reason="owned legacy Registry probe cleanup")
                        assert (await handle.describe()).status != WorkflowExecutionStatus.RUNNING
                    except RPCError as exc:
                        if exc.status != RPCStatusCode.NOT_FOUND:
                            raise
                except BaseException as exc:
                    failures.append(exc)
                try:
                    if process.returncode is None:
                        process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 10)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                except BaseException as exc:
                    failures.append(exc)
                try:
                    await engine.aclose()
                except BaseException as exc:
                    failures.append(exc)
                if failures:
                    raise BaseExceptionGroup("legacy Registry probe and cleanup", failures)
            assert process.returncode == 0
            closed = json.loads((tmp_path / "closed.json").read_text())
            assert closed["worker_shutdown"]
            assert Path(closed["package_file"]).is_relative_to(
                Path(os.environ["RALF_TEST_LEGACY_PYTHON"]).parent.parent
            )
            (tmp_path / "legacy-result.json").write_text(
                json.dumps(
                    {
                        "legacy_update_confirmed": True,
                        "signals_sent": 0,
                        "current_worker_replay": True,
                        "legacy_package": closed["package_file"],
                    },
                    indent=2,
                )
            )

    asyncio.run(asyncio.wait_for(run(), 60))
