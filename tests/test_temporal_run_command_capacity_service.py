"""Original necessary controls survive SDK distinct-Update pressure."""

import asyncio
import json
import os
import uuid
from dataclasses import asdict
from datetime import timedelta

import pytest

from ralf_agent import GraphNode, GraphWorkflowSpec, Scope
from ralf_agent.errors import NotFound
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import BusinessProbe, _agent, _eventually
from tests.test_temporal_scoped_capacity_service import discover_owned_descendants

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal"
)


@pytest.mark.parametrize("parent", [False, True], ids=["native", "graph-child"])
def test_actual_original_run_cancel_after_2000_duplicate_drive_updates(tmp_path, parent):
    async def run():
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        clients, namespace = await _clients()
        client, queue = clients[0], "run-pressure-" + uuid.uuid4().hex
        scope, probe = Scope("run-pressure", queue), BusinessProbe()
        runtime = TemporalRuntime(providers={"default": probe}, tools=probe.tools(approval=True))
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=runtime.orchestration_release if parent else runtime.manifest,
            scope=scope,
            activity_timeout=5,
        )
        worker = build_temporal_worker(
            client,
            task_queue=queue,
            runtime=runtime,
            graceful_shutdown_timeout=timedelta(seconds=1),
        )
        owned, failure = {engine.command_registry_id}, None
        try:
            async with worker:
                definition = (
                    GraphWorkflowSpec("g", [GraphNode("child", agent=_agent("child"))])
                    if parent
                    else _agent("original")
                )
                original = await engine.submit(definition, {}, command_id="original")
                owned.add(original.run_id)
                targets = [original.run_id]
                if parent:
                    diagnostic = await _eventually(
                        lambda: engine.diagnostics(original.run_id),
                        lambda d: bool(d.workflow["children"]),
                    )
                    child = diagnostic.workflow["children"][0]["run_id"]
                    owned.add(child)
                    targets.append(child)

                async def child_status():
                    try:
                        return await engine.status(targets[-1])
                    except NotFound:
                        return None
                    except RPCError as exc:
                        if exc.status != RPCStatusCode.NOT_FOUND:
                            raise
                        return None

                await _eventually(
                    child_status, lambda s: s is not None and s.state == "waiting_approval"
                )
                request = {
                    "command_id": "same-logical-drive",
                    "payload": {"kind": "drive", "scope": asdict(scope)},
                }
                for target in targets:
                    handle = client.get_workflow_handle(target)
                    for fill_start in range(0, 2000, 8):
                        await asyncio.gather(
                            *[
                                handle.execute_update("command", request)
                                for _ in range(fill_start, min(fill_start + 8, 2000))
                            ]
                        )
                        (tmp_path / "progress.json").write_text(
                            json.dumps(
                                {"target": target, "distinct_updates": min(fill_start + 8, 2000)}
                            )
                        )
                assert (await engine.status(targets[-1])).state == "waiting_approval"
                receipt = await engine.cancel(original.run_id, command_id="first-stop")
                # Parent command acceptance precedes descendant termination;
                # its immutable receipt must not invent an already-stopped tree.
                assert receipt.outcome["remote_stop_confirmed"] is (not parent)
                assert await engine.cancel(original.run_id, command_id="first-stop") == receipt
                for target in targets:
                    await _eventually(
                        lambda target=target: engine.status(target),
                        lambda s: s.state == "cancelled",
                    )
                    await _eventually(
                        lambda target=target: engine.diagnostics(target),
                        lambda d: d.workflow["quiescent"],
                    )
                assert probe.reads == []
            # A new Worker must rebuild bounded observations and original receipts
            # from the same History, after both SDK Update ledgers are full.
            restarted = build_temporal_worker(
                client,
                task_queue=queue,
                runtime=runtime,
                graceful_shutdown_timeout=timedelta(seconds=1),
            )
            async with restarted:
                assert await engine.cancel(original.run_id, command_id="first-stop") == receipt
                for index, target in enumerate(sorted(owned)):
                    history = await client.get_workflow_handle(target).fetch_history()
                    await replay_temporal_history(history, namespace=namespace["name"])
                    if target in targets:
                        assert any(
                            e.HasField("workflow_execution_signaled_event_attributes")
                            and e.workflow_execution_signaled_event_attributes.signal_name
                            == "control_command"
                            for e in history.events
                        )
                    (tmp_path / f"history-{index}.json").write_text(history.to_json())
                (tmp_path / "result.json").write_text(
                    json.dumps(
                        {
                            "original_distinct_updates_per_run": 2000,
                            "pressured_runs": len(targets),
                            "logical_drive_commands": 1,
                            "first_cancel_applied": True,
                            "repeated_receipt": True,
                            "tool_calls": 0,
                            "histories_replayed": True,
                            "worker_restarted_original_receipt": True,
                            "tree_quiescent": True,
                            "external_model_calls": 0,
                        }
                    )
                )
        except BaseException as exc:
            failure = exc
        finally:
            failures = [failure] if failure is not None else []
            try:
                await discover_owned_descendants(client, owned)
            except BaseException as exc:
                failures.append(exc)
            for index, target in enumerate(sorted(owned)):
                try:
                    h = client.get_workflow_handle(target)
                    history = await h.fetch_history()
                    (tmp_path / f"retained-history-{index}.json").write_text(history.to_json())
                    if (await h.describe()).status == WorkflowExecutionStatus.RUNNING:
                        await h.terminate(reason="owned run command pressure cleanup")
                    assert (await h.describe()).status != WorkflowExecutionStatus.RUNNING
                except RPCError as exc:
                    if exc.status != RPCStatusCode.NOT_FOUND:
                        failures.append(exc)
                except BaseException as exc:
                    failures.append(exc)
            await engine.aclose()
            (tmp_path / "cleanup.json").write_text(
                json.dumps(
                    {
                        "owned_histories_closed": len(owned),
                        "worker_shutdown": worker.is_shutdown and not worker.is_running,
                        "restarted_worker_shutdown": (
                            "restarted" not in locals()
                            or (restarted.is_shutdown and not restarted.is_running)
                        ),
                        "engine_closed": engine._closed,
                        "body_failed": failure is not None,
                        "cleanup_failed": len(failures) > int(failure is not None),
                    }
                )
            )
            if failures:
                raise BaseExceptionGroup("Run command pressure and cleanup", failures)

    asyncio.run(asyncio.wait_for(run(), 180))
