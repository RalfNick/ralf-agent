"""A real accepted Tool ends independently of the original Run Update ledger."""

import asyncio
import json
import os
import sqlite3
import uuid
from dataclasses import asdict
from datetime import timedelta

import pytest

from relf_agent import AgentSpec, Scope, ToolExecutionOwner
from relf_agent.errors import CloseIncomplete
from relf_agent.governance import DeploymentAdmissionPolicy
from relf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.types import digest
from tests.test_temporal_deployment_admission_service import _clients, _request
from tests.test_temporal_deployment_dispatch_service import _eventually
from tests.test_temporal_deployment_public_service import (
    CommittedThreadWrite,
    SQLiteEffectEvidence,
    WriteProvider,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class EndRecorder:
    """Forward genuine SDK calls, recording end transport without injecting faults."""

    def __init__(self, client):
        self.original = client
        self.ends, self.signals, self.start_failures = [], [], []

    def __getattr__(self, name):
        return getattr(self.original, name)

    def get_workflow_handle(self, *args, **kwargs):
        return RecordedHandle(self, self.original.get_workflow_handle(*args, **kwargs))


class RecordedHandle:
    def __init__(self, owner, handle):
        self.owner, self.original = owner, handle

    def __getattr__(self, name):
        return getattr(self.original, name)

    async def execute_update(self, name, *args, **kwargs):
        try:
            result = await self.original.execute_update(name, *args, **kwargs)
        except Exception as exc:
            if name == "tool_execution_ended" and len(self.owner.ends) < 32:
                self.owner.ends.append({"operation": name, "error": str(exc)})
            if name == "deployment_call_started" and len(self.owner.start_failures) < 32:
                self.owner.start_failures.append(
                    {"activity_name": args[0]["activity_name"], "error": str(exc)}
                )
            raise
        if name == "tool_execution_ended" and len(self.owner.ends) < 32:
            self.owner.ends.append({"operation": name, "completed": True})
        return result

    async def signal(self, name, value):
        if name == "execution_ended":
            self.owner.signals.append({"operation": value["operation"]})
        return await self.original.signal(name, value)


@pytest.mark.parametrize(
    ("public", "registry_pressure"),
    [(False, False), (True, False), (True, True)],
    ids=["tool", "public-tool-and-call", "public-registry-retirement"],
)
def test_actual_original_tool_end_ack_after_2000_updates(tmp_path, public, registry_pressure):
    async def run():
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        clients, namespace = await _clients()
        client, queue = EndRecorder(clients[0]), "end-pressure-" + uuid.uuid4().hex
        scope = Scope("execution-end-pressure", queue)
        write = CommittedThreadWrite(tmp_path / "business.sqlite")
        journal = SQLiteEffectEvidence(tmp_path / "evidence.sqlite")
        policy = DeploymentAdmissionPolicy(queue, max_active_root_runs=1)
        runtime = TemporalRuntime(
            providers={"default": WriteProvider()},
            tools=write.tools(),
            tool_execution=ToolExecutionOwner(version="end-pressure-1"),
            journal=journal,
            admission_policy=policy if public else None,
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            release=runtime.orchestration_release if public else runtime.manifest,
            scope=scope,
            activity_timeout=60,
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
                original = await engine.submit(
                    AgentSpec("writer", "Write once", ("write",)), {}, command_id="original"
                )
                owned.add(original.run_id)
                (tmp_path / "original-identities.json").write_text(
                    json.dumps({"scope": asdict(scope), "owned": sorted(owned)})
                )
                assert await asyncio.to_thread(write.started.wait, 10)
                assert write.committed()[0][1] == 1 and not write.ended.is_set()
                pressure_target = (
                    engine.command_registry_id if registry_pressure else original.run_id
                )
                handle = client.get_workflow_handle(pressure_target)
                history = await handle.fetch_history()
                already = sum(
                    e.HasField("workflow_execution_update_accepted_event_attributes")
                    for e in history.events
                )
                assert 1 <= already < 2000
                request = {
                    "command_id": "one-drive",
                    "payload": {"kind": "drive", "scope": asdict(scope)},
                }
                if registry_pressure:
                    request = _request(
                        policy.identity,
                        namespace,
                        asdict(scope),
                        "one-drive",
                        kind="drive",
                        target=original.run_id,
                    )
                for start in range(already, 2000, 8):
                    await asyncio.gather(
                        *[
                            handle.execute_update(
                                "reserve" if registry_pressure else "command", request
                            )
                            for _ in range(start, min(start + 8, 2000))
                        ]
                    )
                pressure = await handle.fetch_history()
                accepted = sum(
                    e.HasField("workflow_execution_update_accepted_event_attributes")
                    for e in pressure.events
                )
                completed = sum(
                    e.HasField("workflow_execution_update_completed_event_attributes")
                    for e in pressure.events
                )
                assert accepted == completed == 2000
                (tmp_path / "pressure-history.json").write_text(pressure.to_json())
                (tmp_path / "pressure.json").write_text(
                    json.dumps(
                        {
                            "target": pressure_target,
                            "registry_pressure": registry_pressure,
                            "accepted_updates": accepted,
                            "completed_updates": completed,
                        }
                    )
                )
                before = await engine.diagnostics(original.run_id)
                assert (
                    not before.workflow["quiescent"]
                    and not before.workflow["tool_executions"][0]["execution_stopped"]
                )
                receipt = await engine.cancel(original.run_id, command_id="original-stop")
                assert receipt.outcome["remote_stop_confirmed"] is False
                write.release.set()
                assert await asyncio.to_thread(write.ended.wait, 10)
                drained = await runtime.wait_context_executions(wait_timeout=5)
                if public:
                    from relf_agent.temporal_deployment_release import check_owner

                    drained = drained and await check_owner(runtime).wait(wait_timeout=5)
                observed = await engine.diagnostics(original.run_id)
                closure = (
                    await engine._view(original.run_id, "deployment_closure") if public else None
                )
                (tmp_path / "after-end.json").write_text(
                    json.dumps(
                        {
                            "physical_ended": write.ended.is_set(),
                            "end_ack_drained": drained,
                            "tool_executions": observed.workflow["tool_executions"],
                            "quiescent": observed.workflow["quiescent"],
                            "end_updates": client.ends,
                            "end_signals": client.signals,
                            "actual_call_start_failures": client.start_failures,
                            "deployment_closure": closure,
                        }
                    )
                )
                assert drained, (
                    "Original handler ended, but an execution or actual-call obligation remains; "
                    "retain end proofs and original begin failures"
                )
                final = await _eventually(
                    lambda: engine.diagnostics(original.run_id), lambda d: d.workflow["quiescent"]
                )
                assert final.workflow["tool_executions"][0]["execution_stopped"] is True
                assert final.snapshot.state == "cancelled" and write.committed()[0][1] == 1
                if public:
                    deployment = await _eventually(
                        engine.deployment_diagnostics,
                        lambda value: value["counts"]["held_root_runs"] == 0,
                    )
                    closure = await engine._view(original.run_id, "deployment_closure")
                    assert all(call["stopped"] for call in closure["calls"].values())
                    assert closure["seal"] is not None
                    with sqlite3.connect(journal.path) as db:
                        effects = db.execute("SELECT state,adopted_digest FROM effects").fetchall()
                    assert len(effects) == 1 and effects[0][0] == "adopted" and effects[0][1]
                    if registry_pressure:
                        retired_history = await handle.fetch_history()
                        assert (
                            sum(
                                e.HasField("workflow_execution_update_accepted_event_attributes")
                                for e in retired_history.events
                            )
                            == 2000
                        )
                        assert any(
                            e.HasField("workflow_execution_signaled_event_attributes")
                            and e.workflow_execution_signaled_event_attributes.signal_name
                            == "retire_deployment_root"
                            for e in retired_history.events
                        )
                    (tmp_path / "deployment-retirement.json").write_text(
                        json.dumps(
                            {
                                "registry": deployment,
                                "closure": closure,
                                "effect_acknowledged": True,
                            }
                        )
                    )
                assert await engine.cancel(original.run_id, command_id="original-stop") == receipt
                for index, target in enumerate(sorted(owned)):
                    history = await client.get_workflow_handle(target).fetch_history()
                    await replay_temporal_history(history, namespace=namespace["name"])
                    (tmp_path / f"history-{index}.json").write_text(history.to_json())
                (tmp_path / "result.json").write_text(
                    json.dumps(
                        {
                            "sdk_update_limit": 2000,
                            "registry_pressure": registry_pressure,
                            "business_calls": 1,
                            "actual_end_acknowledged": True,
                            "original_cancel_receipt": True,
                            "histories_replayed": True,
                            "external_model_calls": 0,
                            "public_actual_call": public,
                            "retirement_capacity_gate_closed": public,
                        }
                    )
                )
            restarted = build_temporal_worker(
                client,
                task_queue=queue,
                runtime=runtime,
                graceful_shutdown_timeout=timedelta(seconds=1),
            )
            async with restarted:
                from relf_agent.temporal_execution_end_transport import execute

                diagnostic = await engine.diagnostics(original.run_id)
                ended_proof = diagnostic.workflow["tool_executions"][0]["end_proof"]
                ack = await execute(
                    client,
                    original.run_id,
                    "tool_execution_ended",
                    ended_proof,
                    execution_epoch=ended_proof["execution_epoch"],
                    legacy_update_id="ralf-tool-ended:" + digest(ended_proof),
                )
                assert ack == {"action_id": ended_proof["action_id"], "recorded": True}
                for index, target in enumerate(sorted(owned)):
                    history = await client.get_workflow_handle(target).fetch_history()
                    await replay_temporal_history(history, namespace=namespace["name"])
                    (tmp_path / f"restarted-history-{index}.json").write_text(history.to_json())
                (tmp_path / "restart.json").write_text(
                    json.dumps(
                        {
                            "same_original_end_ack": True,
                            "histories_replayed": True,
                            "business_calls": write.committed()[0][1],
                        }
                    )
                )
        except BaseException as exc:
            failure = exc
        finally:
            failures = [failure] if failure is not None else []
            write.release.set()
            if write.started.is_set():
                try:
                    assert await asyncio.to_thread(write.ended.wait, 5)
                except BaseException as exc:
                    failures.append(exc)
            pending = False
            try:
                await runtime.close_context_execution(wait_timeout=1)
            except CloseIncomplete:
                pending = True
                if failure is None:
                    failures.append(
                        AssertionError("Successful case left original end proof pending")
                    )
            except BaseException as exc:
                failures.append(exc)
            try:
                await runtime.tool_execution.aclose(wait_timeout=2)
            except BaseException as exc:
                failures.append(exc)
            if public:
                try:
                    await runtime.close_deployment_execution(wait_timeout=2)
                except BaseException as exc:
                    failures.append(exc)
            closed, absent = [], []
            for index, target in enumerate(sorted(owned)):
                try:
                    handle = client.get_workflow_handle(target)
                except BaseException as exc:
                    failures.append(exc)
                    continue
                try:
                    history = await handle.fetch_history()
                    (tmp_path / f"retained-history-{index}.json").write_text(history.to_json())
                except RPCError as exc:
                    if exc.status != RPCStatusCode.NOT_FOUND:
                        failures.append(exc)
                except BaseException as exc:
                    failures.append(exc)
                try:
                    if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                        await handle.terminate(reason="owned execution-end pressure cleanup")
                    assert (await handle.describe()).status != WorkflowExecutionStatus.RUNNING
                    closed.append(target)
                except RPCError as exc:
                    if exc.status == RPCStatusCode.NOT_FOUND:
                        absent.append(target)
                    else:
                        failures.append(exc)
                except BaseException as exc:
                    failures.append(exc)
            for resource in (engine, journal):
                try:
                    await resource.aclose()
                except BaseException as exc:
                    failures.append(exc)
            (tmp_path / "cleanup.json").write_text(
                json.dumps(
                    {
                        "worker_shutdown": worker.is_shutdown and not worker.is_running,
                        "restarted_worker_shutdown": "restarted" not in locals()
                        or (restarted.is_shutdown and not restarted.is_running),
                        "owned_histories_closed": len(closed),
                        "owned_histories_not_found": absent,
                        "original_thread_ended": write.ended.is_set(),
                        "end_obligation_retained": pending,
                        "body_failed": failure is not None,
                        "cleanup_failed": len(failures) > int(failure is not None),
                    }
                )
            )
            if failures:
                raise BaseExceptionGroup("Original execution end and owned cleanup", failures)

    asyncio.run(asyncio.wait_for(run(), 120))
