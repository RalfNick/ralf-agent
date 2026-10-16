"""Original SDK scheduling proves an Action slot, never physical termination."""

import asyncio
import copy
from dataclasses import asdict
from types import SimpleNamespace as NS

import pytest
from temporalio.api.history.v1 import HistoryEvent
from temporalio.converter import DataConverter

from ralf_agent import AgentSpec, Scope, TemporalRuntime, ToolExecutionOwner
from ralf_agent.errors import RalfError
from ralf_agent.temporal_state import (
    COMMAND_REGISTRY_NAME,
    TOOL_ACTIVITY,
    WORKFLOW_NAME,
    TemporalRunState,
)
from ralf_agent.types import digest, submission_request
from tests.test_temporal_engine import Provider, registry
from tests.test_temporal_tool_execution import admission

NS_ID = {"name": "default", "id": "11111111-1111-1111-1111-111111111111"}


async def fixture(*, owned=False, started=False, depth=None):
    scope, command = asdict(Scope()), "submit"
    target = "ralf-temporal-" + digest([scope, command])
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=registry(),
        **({"tool_execution": ToolExecutionOwner(version="proof")} if owned else {}),
    )
    state = TemporalRunState(
        target,
        scope,
        command,
        submission_request(AgentSpec("a", "read", tools=("read",)), "x"),
        runtime.manifest,
        "target-epoch",
    )
    state.tool_end_evidence_version = 1
    model, _ = state.next_operation()
    state.accept_model(
        model["id"],
        {
            "ok": True,
            "output": None,
            "usage": None,
            "tool_calls": [{"name": "read", "arguments": {"flag": 1}, "call_id": "c"}],
        },
    )
    action, tool_request = state.next_operation()
    if owned:
        state.admit_tool_dispatch(admission(tool_request))
    state.operation_unknown(action["id"], "lost")
    payload = {
        "kind": "reconcile",
        "scope": scope,
        "action_id": action["id"],
        "query": False,
        "result": "confirmed",
    }
    submission = {"command_id": command, "target": target, "payload_digest": digest(state.request)}
    value = {
        "mode": "scoped_manual",
        "scope": scope,
        "registry_execution_epoch": "registry-epoch",
        "namespace": "default",
        "submission": submission,
        "payload": payload,
    }
    converter = DataConverter.default

    async def start_event(epoch, workflow_type, queue, accepted):
        e = HistoryEvent(event_id=1)
        a = e.workflow_execution_started_event_attributes
        a.original_execution_run_id = a.first_execution_run_id = epoch
        a.workflow_type.name, a.task_queue.name = workflow_type, queue
        a.input.payloads.extend(await converter.encode([accepted]))
        return e

    registry_id = "ralf-temporal-commands-" + digest(scope)
    reg_start = await start_event(
        "registry-epoch", COMMAND_REGISTRY_NAME, "registry-queue", {"scope": scope}
    )
    target_start = await start_event(
        "target-epoch",
        WORKFLOW_NAME,
        "other-queue",
        {
            "scope": scope,
            "command_id": command,
            "request": state.request,
            "manifest": state.manifest,
            "activity_timeout": 1,
        },
    )
    if depth is not None:
        start = target_start.workflow_execution_started_event_attributes
        accepted = (await converter.decode(start.input.payloads))[0]
        accepted["depth"] = depth
        start.input.payloads.clear()
        start.input.payloads.extend(await converter.encode([accepted]))
    marker = HistoryEvent(event_id=2)
    marker.marker_recorded_event_attributes.marker_name = "core_patch"
    marker.marker_recorded_event_attributes.details["patch-data"].payloads.extend(
        await converter.encode([{"id": "ralf-unowned-tool-end-evidence-v1", "deprecated": False}])
    )
    scheduled = HistoryEvent(event_id=3)
    a = scheduled.activity_task_scheduled_event_attributes
    a.activity_type.name, a.activity_id, a.task_queue.name = (
        TOOL_ACTIVITY,
        action["attempts"][0]["id"],
        "other-queue",
    )
    a.input.payloads.extend(await converter.encode([tool_request]))
    events = [target_start, marker, scheduled]
    if started:
        e = HistoryEvent(event_id=4)
        e.activity_task_started_event_attributes.scheduled_event_id = 3
        events.append(e)

    class Handle:
        def __init__(self, identifier, epoch, kind, queue, history):
            self.id, self.epoch, self.kind, self.queue, self.history = (
                identifier,
                epoch,
                kind,
                queue,
                history,
            )

        async def describe(self):
            return NS(
                id=self.id,
                run_id=self.epoch,
                namespace="default",
                workflow_type=self.kind,
                task_queue=self.queue,
                raw_info=NS(first_run_id=self.epoch),
            )

        def fetch_history_events(self, **kwargs):
            async def read():
                for e in self.history:
                    yield e

            return read()

        async def query(self, name, request):
            assert (
                self.id == target
                and name == "view"
                and request == {"kind": "diagnostics", "scope": scope}
            )
            return state.diagnostics()

    handles = {
        registry_id: Handle(
            registry_id, "registry-epoch", COMMAND_REGISTRY_NAME, "registry-queue", [reg_start]
        ),
        target: Handle(target, "target-epoch", WORKFLOW_NAME, "other-queue", events),
    }

    class Client:
        namespace = "default"
        data_converter = converter

        def get_workflow_handle(self, identifier, **kwargs):
            h = handles[identifier]
            assert kwargs.get("run_id", h.epoch) == h.epoch
            return h

    info = NS(
        activity_type="ralf.temporal.control.v1",
        workflow_id=registry_id,
        workflow_run_id="registry-epoch",
        workflow_namespace="default",
        task_queue="registry-queue",
    )
    return runtime, Client(), value, info, state, handles


@pytest.mark.parametrize(
    "owned,started,depth",
    [(False, False, None), (False, True, None), (True, True, None), (False, False, 1)],
)
def test_scoped_proof_uses_original_schedule_and_allows_distinct_target_queue(
    monkeypatch, owned, started, depth
):
    from ralf_agent.temporal_scoped_manual_recovery import verify

    async def run():
        runtime, client, value, info, state, _ = await fixture(
            owned=owned, started=started, depth=depth
        )

        async def namespace_id(client):
            return NS_ID["id"]

        monkeypatch.setattr("ralf_agent.temporal_session_activities.namespace_id", namespace_id)
        before = copy.deepcopy(vars(state))
        proof = await verify(runtime, client, value, info)
        assert proof["target"] == state.run_id and proof["execution_epoch"] == state.epoch
        assert proof["schedule_event_id"] == 3 and proof["started_event_id"] == (
            4 if started else None
        )
        assert proof["proof_digest"] == digest(
            {k: v for k, v in proof.items() if k != "proof_digest"}
        )
        assert vars(state) == before and not state.quiescent

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        "request",
        "scope",
        "registry-reset",
        "target-reset",
        "schedule",
        "tool-payload",
        "known",
        "native",
        "old-unowned",
        "namespace-change",
        "activity-change-await",
        "owner-grant",
        "numeric-bool",
        "marker-only",
        "activity-type",
        "port-swap",
    ],
)
def test_scoped_proof_rejects_changed_originals_without_writes(monkeypatch, fault):
    from ralf_agent.temporal_scoped_manual_recovery import verify

    async def run():
        runtime, client, value, info, state, handles = await fixture(owned=fault == "owner-grant")
        target = handles[state.run_id]
        if fault == "request":
            value["submission"]["payload_digest"] = "a" * 64
        elif fault == "scope":
            value["scope"] = {**state.scope, "principal": "other"}
        elif fault == "registry-reset":
            handles[info.workflow_id].history[
                0
            ].workflow_execution_started_event_attributes.original_execution_run_id = "old"
        elif fault == "target-reset":
            target.history[
                0
            ].workflow_execution_started_event_attributes.first_execution_run_id = "old"
        elif fault == "schedule":
            target.history.pop()
        elif fault == "tool-payload":
            target.history[-1].activity_task_scheduled_event_attributes.input.payloads.clear()
        elif fault == "known":
            state.actions[-1]["status"] = "completed"
        elif fault == "native":
            state.actions[-1]["delegated_execution"] = {"fenced": False}
        elif fault == "old-unowned":
            target.history.pop(1)
            state.actions[-1].pop("execution_unconfirmed", None)
        elif fault == "owner-grant":
            state.tool_executions[state.actions[-1]["id"]]["grant_allowed"] = False
        elif fault == "numeric-bool":
            call = target.history[-1].activity_task_scheduled_event_attributes
            args = await client.data_converter.decode(call.input.payloads)
            args[0]["arguments"]["flag"] = True
            call.input.payloads.clear()
            call.input.payloads.extend(await client.data_converter.encode(args))
        elif fault == "marker-only":
            target.history.pop(1)
        elif fault == "activity-type":
            info.activity_type = "unrelated"
        elif fault == "port-swap":
            original = client.get_workflow_handle

            def swap(identifier, **kw):
                h = original(identifier, **kw)
                if identifier == state.run_id:
                    handles[info.workflow_id].query = lambda *a: None
                return h

            client.get_workflow_handle = swap
        reads = []

        async def namespace_id(c):
            reads.append(True)
            if fault == "activity-change-await":
                info.activity_type = "unrelated-after-await"
            return (
                "22222222-2222-2222-2222-222222222222"
                if fault == "namespace-change" and len(reads) > 1
                else NS_ID["id"]
            )

        monkeypatch.setattr("ralf_agent.temporal_session_activities.namespace_id", namespace_id)
        before = copy.deepcopy(vars(state))
        with pytest.raises(RalfError):
            await verify(runtime, client, value, info)
        assert vars(state) == before

    asyncio.run(run())
