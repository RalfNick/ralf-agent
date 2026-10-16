"""Actual full-capacity repeated Parent recovery, without a second authority."""

import asyncio
import json
import os
import uuid
from dataclasses import asdict
from datetime import timedelta

import pytest

from ralf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    ModelResponse,
    Runtime,
    Scope,
    SessionBindingResource,
    SQLiteMemory,
    ToolRegistry,
)
from ralf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_state import workflow_id
from ralf_agent.temporal_session_topology import CompositeSessionTopology
from ralf_agent.temporal_state import COMMAND_REGISTRY_CAPACITY
from tests.test_temporal_deployment_admission_service import _clients
from tests.test_temporal_deployment_dispatch_service import _eventually
from tests.test_temporal_scoped_capacity_service import discover_owned_descendants

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


class Provider:
    identity = {"kind": "scoped-drive-service", "version": "1"}

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        return ModelResponse(output="answer")


class RecoverableMemory(SQLiteMemory):
    def __init__(self, path):
        super().__init__(path)
        self.fail_address, self.failures, self.appends = None, 0, []

    def inspect_message(self, scope, address, message_id):
        if address == self.fail_address and self.failures < 2:
            self.failures += 1
            raise RuntimeError("temporary original root inspection failure")
        return super().inspect_message(scope, address, message_id)

    def append(self, scope, address, message, *, expected_revision, message_id):
        result = super().append(
            scope, address, message, expected_revision=expected_revision, message_id=message_id
        )
        self.appends.append((address, message_id))
        return result


def test_actual_full_scoped_parent_repeats_one_drive_to_recover_original_save(tmp_path):
    async def run():
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        clients, namespace = await _clients()
        client, queue = clients[0], "scoped-drive-" + uuid.uuid4().hex
        scope = Scope("scoped-drive", queue)
        backend, provider = RecoverableMemory(tmp_path / "data.sqlite"), Provider()
        execution = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            session_store=SessionBindingResource(
                backend, namespaces=("chat",), default_namespace="chat"
            ),
            enable_sessions=True,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
        )
        engine = TemporalEngine(
            client,
            task_queue=queue,
            scope=scope,
            release=execution.orchestration_release,
            activity_timeout=3,
            drive_timeout=20,
        )
        host = Runtime.from_temporal(engine)
        worker = build_temporal_worker(
            client,
            task_queue=queue,
            runtime=execution,
            graceful_shutdown_timeout=timedelta(seconds=1),
        )
        owned, failure = {engine.command_registry_id}, None
        try:
            async with worker:
                definition = GraphWorkflowSpec(
                    "g", [GraphNode("writer", agent=AgentSpec("a", "Answer"))]
                )
                entry = await host.open_session(definition, "chat", command_id="open")
                owned.add(workflow_id(entry.ref.key))
                backend.fail_address = entry.ref.key.storage_key
                turn = await entry.submit("task", command_id="turn", budget=32)
                run_id = turn.ref.run_id
                owned.add(run_id)
                (tmp_path / "original-identities.json").write_text(
                    json.dumps({"scope": asdict(scope), "run_id": run_id, "owned": sorted(owned)})
                )

                async def diagnostic():
                    value = await engine.diagnostics(run_id)
                    (tmp_path / "latest-observation.json").write_text(
                        json.dumps(
                            {
                                "state": value.snapshot.state,
                                "quiescent": value.workflow["quiescent"],
                                "reconciliation_pending": value.workflow["reconciliation_pending"],
                                "inspection_failures": backend.failures,
                                "model_calls": provider.calls,
                            }
                        )
                    )
                    return value

                def held(value):
                    return (
                        value.workflow["reconciliation_pending"] and not value.workflow["quiescent"]
                    )

                original = await _eventually(diagnostic, held)
                assert backend.failures == 1 and not original.workflow["quiescent"]
                assert any(
                    s["node"] == "root" and s["status"] == "outcome_unknown"
                    for s in await engine.session_stages(run_id)
                )
                owned.update(c["run_id"] for c in original.workflow["children"])
                registry = client.get_workflow_handle(engine.command_registry_id)
                before = await registry.query("view", {"scope": asdict(scope), "kind": "status"})
                for start in range(before["accepted_commands"], COMMAND_REGISTRY_CAPACITY, 48):
                    await asyncio.gather(
                        *[
                            engine._guard(
                                "drive",
                                f"fill:{i}",
                                run_id,
                                {"scope": asdict(scope), "kind": "drive"},
                            )
                            for i in range(start, min(start + 48, COMMAND_REGISTRY_CAPACITY))
                        ]
                    )
                    (tmp_path / "progress.json").write_text(
                        json.dumps({"accepted": min(start + 48, COMMAND_REGISTRY_CAPACITY)})
                    )
                assert (await registry.query("view", {"scope": asdict(scope)}))[
                    "accepted_commands"
                ] == 4096
                await engine.drive(run_id, wait_seconds=0)
                await _eventually(diagnostic, lambda d: backend.failures == 2 and held(d))
                assert backend.read(scope, entry.ref.key.storage_key)[0] == 0
                await engine.drive(run_id, wait_seconds=0)
                final = await _eventually(
                    diagnostic,
                    lambda d: d.snapshot.state == "succeeded" and d.workflow["quiescent"],
                )
                await _eventually(entry.status, lambda s: not s.busy)
                assert provider.calls == 1
                assert backend.read(scope, entry.ref.key.storage_key)[0] == 1
                assert len([a for a in backend.appends if a[0] == backend.fail_address]) == 1
                assert final.budget["reserved"] == final.budget["unknown"] == 0
                events = await engine.events(run_id)
                assert (
                    len(
                        [
                            e
                            for e in events
                            if e.kind == "command_recorded" and e.data["kind"] == "drive"
                        ]
                    )
                    == 1
                )
                view = await registry.query("view", {"scope": asdict(scope)})
                assert view["accepted_commands"] == 4097
                for index, target in enumerate(sorted(owned)):
                    history = await client.get_workflow_handle(target).fetch_history()
                    await replay_temporal_history(history, namespace=namespace["name"])
                    (tmp_path / f"history-{index}.json").write_text(history.to_json())
                    if target == run_id:
                        assert any(
                            b"ralf-scoped-parent-repeat-drive-v1" in p.data
                            for e in history.events
                            if e.HasField("marker_recorded_event_attributes")
                            for v in e.marker_recorded_event_attributes.details.values()
                            for p in v.payloads
                        )
                (tmp_path / "result.json").write_text(
                    json.dumps(
                        {
                            "normal_capacity": 4096,
                            "accepted_after_recovery": 4097,
                            "inspection_failures": 2,
                            "model_calls": 1,
                            "root_writes": 1,
                            "drive_commands": 1,
                            "all_histories_replayed": True,
                            "original_turn_released": True,
                            "patch_marker_present": True,
                            "external_model_calls": 0,
                        },
                        indent=2,
                    )
                )
        except BaseException as exc:
            failure = exc
        finally:
            failures = [failure] if failure is not None else []
            descendants = owned - {engine.command_registry_id}
            try:
                await discover_owned_descendants(client, descendants)
            except BaseException as exc:
                failures.append(exc)
            owned.update(descendants)
            for target in sorted(owned):
                try:
                    handle = client.get_workflow_handle(target)
                    if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                        await handle.terminate(reason="owned scoped drive acceptance cleanup")
                    assert (await handle.describe()).status != WorkflowExecutionStatus.RUNNING
                except RPCError as exc:
                    if exc.status != RPCStatusCode.NOT_FOUND:
                        failures.append(exc)
                except BaseException as exc:
                    failures.append(exc)
            for operation in (host.aclose, engine.aclose):
                try:
                    await operation()
                except BaseException as exc:
                    failures.append(exc)
            backend.close()
            assert worker.is_shutdown and not worker.is_running
            (tmp_path / "cleanup.json").write_text(
                json.dumps(
                    {
                        "owned_histories_closed": len(owned),
                        "worker_shutdown": True,
                        "engine_closed": engine._closed,
                        "body_failed": failure is not None,
                        "cleanup_failed": len(failures) > int(failure is not None),
                    }
                )
            )
            if failures:
                raise BaseExceptionGroup("scoped drive acceptance and cleanup", failures)

    asyncio.run(asyncio.wait_for(run(), 180))


def test_actual_empty_scope_drive_returns_not_found_without_creating_registry(tmp_path):
    async def run():
        from temporalio.service import RPCError, RPCStatusCode

        from ralf_agent.errors import NotFound

        clients, _ = await _clients()
        client, queue = clients[0], "missing-scope-" + uuid.uuid4().hex
        runtime = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
        engine = TemporalEngine(
            client, task_queue=queue, release=runtime.manifest, scope=Scope("missing", queue)
        )
        try:
            with pytest.raises(NotFound):
                await engine.drive("missing-run", wait_seconds=0)
            with pytest.raises(RPCError) as absent:
                await client.get_workflow_handle(engine.command_registry_id).describe()
            assert absent.value.status == RPCStatusCode.NOT_FOUND
        finally:
            await engine.aclose()
        (tmp_path / "missing-result.json").write_text(
            json.dumps(
                {"not_found": True, "registry_not_created": True, "engine_closed": engine._closed}
            )
        )

    asyncio.run(asyncio.wait_for(run(), 20))
