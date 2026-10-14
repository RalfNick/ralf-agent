"""Original SDK close visits independent leaves and checks complete PG intents."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent import temporal_coding_composition_control as control
from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.postgres_coding_resources import new_resource, receive_resource, validate_resource
from ralf_agent.temporal_parent_state import child_run_id
from ralf_agent.types import Scope, canonical, digest
from tests.test_temporal_coding_state import RUNNER, ready

SCOPE = {"workspace": "parallel-close", "principal": "original"}
NAMESPACE = {"name": "original", "id": "11111111-1111-1111-1111-111111111111"}
MANIFEST = {
    "kernel": "temporal-3",
    "binding_protocol": 13,
    "coding_composition_protocol": {"version": 2, "topology": "bounded-agent-graph"},
}


def history_proof(run_id, request, epoch):
    value = {
        "version": 1,
        "scope": SCOPE,
        "run_id": run_id,
        "execution_epoch": epoch,
        "original_execution_epoch": epoch,
        "namespace": NAMESPACE,
        "request": copy.deepcopy(request),
        "request_digest": digest(request),
        "manifest": MANIFEST,
        "release_digest": digest({"definition": request["definition"], "manifest": MANIFEST}),
        "revision": 1,
        "state": "running",
        "physical_stopped": False,
        "action_stops": [],
    }
    return signed(value)


def signed(value):
    value["proof_digest"] = digest({k: v for k, v in value.items() if k != "proof_digest"})
    return value


class Handle:
    def __init__(self, peer, run_id, epoch):
        self.peer, self.run_id, self.epoch = peer, run_id, epoch

    async def query(self, name, payload):
        assert name == "view" and payload["scope"] == SCOPE
        if self.run_id.startswith("ralf-temporal-commands-"):
            raise AssertionError("Close must use original registry Update")
        assert self.epoch == self.peer.proofs[self.run_id]["execution_epoch"]
        if payload["kind"] == "coding_composition_proof":
            return copy.deepcopy(self.peer.proofs[self.run_id])
        if payload["kind"] == "coding_composition_children":
            return copy.deepcopy(self.peer.children)
        if payload["kind"] == "coding_requests":
            return copy.deepcopy(self.peer.requests.get(self.run_id, []))
        raise AssertionError(payload)

    async def execute_update(self, name, payload, **options):
        if name == "close_coding_composition_submissions":
            self.peer.candidate["close_requested"] = True
            return {
                "manifest_digest": digest(MANIFEST),
                "close_requested": True,
                "candidates": [copy.deepcopy(self.peer.candidate)],
            }
        if name == "admit_coding_composition_submission":
            return self.peer.candidate | {"admitted": False}
        assert self.epoch == self.peer.proofs[self.run_id]["execution_epoch"]
        if name == "command":
            kind = payload["payload"]["kind"]
            self.peer.events.append((kind, self.run_id, self.epoch))
            if kind == "cancel":
                self.peer.cancelled.append(self.run_id)
                self.peer.proofs[self.run_id]["state"] = "cancelling"
            signed(self.peer.proofs[self.run_id])
            return {"run_id": self.run_id}
        if name in {"coding_composition_child_epoch", "coding_composition_child_stopped"}:
            run_id = payload["child_run_id"]
            call = next(c for c in self.peer.children if c["run_id"] == run_id)
            if name == "coding_composition_child_stopped":
                call["physical_stop_proof"] = copy.deepcopy(payload["evidence"])
                self.peer.adopted.append(run_id)
                root = self.peer.proofs["root"]
                root["physical_stopped"] = all(
                    c.get("physical_stop_proof", {}).get("physical_stopped") is True
                    for c in self.peer.children
                )
                if root["physical_stopped"]:
                    root["state"] = "cancelled"
                signed(root)
            return {"run_id": run_id, "recorded": True}
        raise AssertionError(name)


class Peer:
    namespace = "original"

    def __init__(self):
        self.cancelled, self.stopped, self.adopted = [], [], []
        self.events = []
        self.children, self.requests, self.records = [], {}, []
        root_request = {"definition": {"kind": "graph"}, "input": "work", "budget": 24}
        self.proofs = {"root": history_proof("root", root_request, "root-epoch")}
        self.candidate = {
            "command_id": "root-command",
            "run_id": "root",
            "request_digest": digest(root_request),
            "manifest_digest": digest(MANIFEST),
            "close_requested": False,
            "execution_epoch": "root-epoch",
            "namespace": NAMESPACE,
        }
        for index in (1, 2):
            command_id = f"child-{index}"
            run_id = child_run_id(SCOPE, command_id)
            epoch = f"child-epoch-{index}"
            base = {"definition": {"kind": "agent"}, "input": f"task-{index}", "budget": 8}
            request = base | {
                "coding_parent": {
                    "version": 1,
                    "scope": SCOPE,
                    "namespace": NAMESPACE,
                    "parent_run_id": "root",
                    "parent_execution_epoch": "root-epoch",
                    "parent_request_digest": digest(root_request),
                    "parent_release_digest": self.proofs["root"]["release_digest"],
                    "call_id": f"0:node-{index}",
                    "command_id": command_id,
                    "member": f"node-{index}",
                    "planning_revision": 0,
                    "child_run_id": run_id,
                    "child_projection_digest": digest(base),
                    "cap": 8,
                    "depth": 1,
                }
            }
            self.proofs[run_id] = history_proof(run_id, request, epoch)
            self.children.append(
                {
                    "id": f"0:node-{index}",
                    "call_id": f"node-{index}",
                    "member": f"node-{index}",
                    "command_id": command_id,
                    "run_id": run_id,
                    "request": request,
                    "cap": 8,
                    "depth": 1,
                    "dispatch_started": True,
                    "child_request_digest": digest(request),
                    "child_execution": {
                        "namespace": NAMESPACE,
                        "execution_epoch": epoch,
                        "original_execution_epoch": epoch,
                    },
                }
            )
            # Start with a native intent produced by the actual History rules.
            _, _, tool_request = ready()
            tool_request = copy.deepcopy(tool_request)
            tool_request.update(
                scope=SCOPE, run_id=run_id, execution_epoch=epoch, runtime_manifest=MANIFEST
            )
            native = tool_request["coding_request"]
            native["dispatch"].update(scope=SCOPE, run_id=run_id, execution_epoch=epoch)
            native["dispatch"]["effect_key"] = f"effect-{index}"
            native["release_digest"] = self.proofs[run_id]["release_digest"]
            native["request_digest"] = digest(
                {k: v for k, v in native.items() if k != "request_digest"}
            )
            self.requests[run_id] = [tool_request]
            self.records.append(self.resource(tool_request))
        self.failure = None
        self.scans = 0

    @staticmethod
    def resource(tool_request, *, fenced=False):
        native = tool_request["coding_request"]
        namespace = {
            "request": native,
            "runner": RUNNER,
            "dispatch": native["dispatch"],
            "environment": {
                "kind": "docker-coding-environment",
                "version": "2",
                "expected_generation": "a" * 32,
                "retire_on_stop": True,
                "resource_id": "original-resource",
            },
        }
        key = (SCOPE["workspace"], SCOPE["principal"], native["dispatch"]["effect_key"])
        record = new_resource(key, native, RUNNER, namespace)
        if fenced:
            record = receive_resource(
                record,
                "unprepared",
                {
                    "namespace_binding": namespace,
                    "prepare_granted": False,
                },
            )
        return validate_resource(canonical(record), key)

    def get_workflow_handle(self, workflow_id, **options):
        return Handle(self, workflow_id, options.get("run_id"))

    async def composition_resources(self, scope):
        assert scope == Scope(**SCOPE)
        self.scans += 1
        return tuple(copy.deepcopy(self.records))

    async def stop(self, runtime, request, factory):
        run_id = request["run_id"]
        self.stopped.append(run_id)
        self.events.append(("stop", run_id, request["execution_epoch"]))
        if run_id == self.failure:
            raise OSError("Original native stop unavailable")
        for index, record in enumerate(self.records):
            if record["request"] == request["coding_request"]:
                self.records[index] = receive_resource(
                    record,
                    "unprepared",
                    {
                        "namespace_binding": record["namespace_binding"],
                        "prepare_granted": False,
                    },
                )
        proof = self.proofs[run_id]
        proof.update(state="cancelled", physical_stopped=True, revision=proof["revision"] + 1)
        signed(proof)


@pytest.fixture
def transport(monkeypatch):
    from ralf_agent import (
        delegated_coding,
        temporal_bindings,
        temporal_coding_runtime,
        temporal_session_activities,
    )

    peer = Peer()

    async def namespace_id(client):
        return NAMESPACE["id"]

    monkeypatch.setattr(temporal_session_activities, "namespace_id", namespace_id)
    monkeypatch.setattr(temporal_coding_runtime, "stop", peer.stop)
    monkeypatch.setattr(temporal_coding_runtime, "callbacks", lambda *args: object())
    handler = SimpleNamespace(identity=RUNNER, runner=SimpleNamespace(_journal=peer))
    monkeypatch.setattr(delegated_coding, "registered_coding_tool", lambda tool: handler)
    monkeypatch.setattr(temporal_bindings, "selected_runtime", lambda runtime, request: runtime)

    def validate_release(value=None):
        if value is not None and value != MANIFEST:
            raise DefinitionMismatch("Original release changed")

    runtime = SimpleNamespace(
        orchestration_release=MANIFEST,
        validate_release=validate_release,
        tools=SimpleNamespace(_tools=["read"], get=lambda name: object()),
    )
    return peer, runtime


def test_first_leaf_stop_failure_does_not_leave_other_original_leaf_live(transport):
    peer, runtime = transport
    first, second = [call["run_id"] for call in peer.children]
    peer.failure = first
    with pytest.raises(CloseIncomplete):
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert peer.stopped == [first, second]
    assert second in peer.adopted and peer.proofs[second]["physical_stopped"]
    assert not peer.proofs["root"]["physical_stopped"]
    assert peer.records[0]["pending_stop"] and not peer.records[1]["pending_stop"]


@pytest.mark.parametrize("fenced", [False, True])
@pytest.mark.parametrize("changed", ["action_id", "effect_key", "arguments", "runner"])
def test_same_original_leaf_epoch_foreign_pg_request_prevents_close(transport, changed, fenced):
    peer, runtime = transport
    foreign = copy.deepcopy(next(iter(peer.requests.values()))[0])
    native = foreign["coding_request"]
    if changed == "runner":
        record = Peer.resource(foreign, fenced=fenced)
        record["runner"] = RUNNER | {"version": "foreign"}
        record["namespace_binding"]["runner"] = record["runner"]
        if fenced:
            record["unprepared"]["namespace_binding"]["runner"] = record["runner"]
        key = (SCOPE["workspace"], SCOPE["principal"], record["effect_key"])
        record = validate_resource(canonical(record), key)
    else:
        native["dispatch"][changed] = {"task": "foreign"} if changed == "arguments" else "foreign"
        native["request_digest"] = digest(
            {k: v for k, v in native.items() if k != "request_digest"}
        )
        record = Peer.resource(foreign, fenced=fenced)
    peer.records[0] = record
    with pytest.raises(CloseIncomplete):
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    second = peer.children[1]["run_id"]
    assert second in peer.stopped and peer.proofs[second]["physical_stopped"]


def test_successful_close_rescans_original_intents_after_fencing(transport):
    peer, runtime = transport
    asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert peer.scans >= 2
    assert all(not row["pending_stop"] for row in peer.records)


def test_wrong_child_identity_does_not_authorize_it_or_block_independent_leaf(transport):
    peer, runtime = transport
    first, second = [call["run_id"] for call in peer.children]
    peer.children[0]["child_execution"]["original_execution_epoch"] = "replacement"
    with pytest.raises(CloseIncomplete):
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert first not in peer.stopped and second in peer.stopped


def test_close_does_not_aggregate_caller_cancellation(transport, monkeypatch):
    peer, runtime = transport

    async def interrupted(runtime, request, factory):
        raise asyncio.CancelledError

    from ralf_agent import temporal_coding_runtime

    monkeypatch.setattr(temporal_coding_runtime, "stop", interrupted)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))


def test_close_retry_keeps_fenced_rows_and_adopts_every_original_leaf(transport):
    peer, runtime = transport
    first, second = [call["run_id"] for call in peer.children]
    peer.failure = first
    with pytest.raises(CloseIncomplete):
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    second_request = peer.records[1]["request"]
    assert not peer.records[1]["pending_stop"]
    peer.failure = None
    asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert peer.proofs["root"]["physical_stopped"]
    assert all(not row["pending_stop"] for row in peer.records)
    assert peer.records[1]["request"] == second_request
    assert first in peer.adopted and second in peer.adopted


def test_failed_initial_resource_query_does_not_skip_independent_stops_or_final_scan(
    transport, monkeypatch
):
    peer, runtime = transport
    original = peer.composition_resources
    calls = []

    async def unavailable_once(scope):
        calls.append(scope)
        if len(calls) == 1:
            raise OSError("Original PG resource scan unavailable")
        return await original(scope)

    monkeypatch.setattr(peer, "composition_resources", unavailable_once)
    with pytest.raises(CloseIncomplete) as exc:
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert len(calls) == 2
    assert peer.stopped == [c["run_id"] for c in peer.children]
    assert all(not row["pending_stop"] for row in peer.records)
    assert any(
        item.get("resources") == "original" for item in exc.value.report["coding_composition"]
    )


def test_final_scan_late_original_intent_cannot_be_ignored(transport, monkeypatch):
    peer, runtime = transport
    original = peer.composition_resources
    scans = []
    late_request = copy.deepcopy(next(iter(peer.requests.values()))[0])
    native = late_request["coding_request"]
    native["dispatch"].update(action_id="late-original-action", effect_key="late-original-effect")
    late_request["action_id"] = "late-original-action"
    native["request_digest"] = digest({k: v for k, v in native.items() if k != "request_digest"})
    late = Peer.resource(late_request)

    async def late_intent(scope):
        scans.append(scope)
        if len(scans) == 2:
            peer.records.append(late)
            peer.requests[late_request["run_id"]].append(late_request)
        return await original(scope)

    monkeypatch.setattr(peer, "composition_resources", late_intent)
    with pytest.raises(CloseIncomplete) as exc:
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert peer.records[-1]["pending_stop"]
    assert any(
        item.get("resource") == "late-original-effect"
        for item in exc.value.report["coding_composition"]
    )


def standalone(peer, kind):
    from ralf_agent.types import AgentSpec, WorkflowSpec, submission_request

    call = peer.children.pop(0)
    run_id = call["run_id"]
    spec = AgentSpec("standalone", "Original Coding work", tools=("read",))
    if kind == "sequence":
        spec = WorkflowSpec("standalone", steps=(spec,))
    accepted = submission_request(spec, "original", budget=8)
    proof = history_proof(run_id, accepted, "child-epoch-1")
    peer.proofs[run_id] = proof
    request = peer.requests[run_id][0]
    native = request["coding_request"]
    native["release_digest"] = proof["release_digest"]
    native["definition_digest"] = digest(accepted["definition"])
    native["request_digest"] = digest({k: v for k, v in native.items() if k != "request_digest"})
    peer.records[0] = Peer.resource(request)
    return run_id


@pytest.mark.parametrize("kind", ["agent", "sequence"])
def test_standalone_close_cancels_original_epoch_before_native_stop(transport, kind):
    peer, runtime = transport
    run_id = standalone(peer, kind)
    asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    relevant = [event for event in peer.events if event[1] == run_id]
    assert relevant == [
        ("cancel", run_id, "child-epoch-1"),
        ("drive", run_id, "child-epoch-1"),
        ("stop", run_id, "child-epoch-1"),
    ]
    assert peer.proofs[run_id]["physical_stopped"]


@pytest.mark.parametrize("kind", ["agent", "sequence"])
def test_standalone_fenced_native_with_unknown_actual_owner_retains_resources(
    transport, monkeypatch, kind
):
    from ralf_agent import temporal_coding_runtime

    peer, runtime = transport
    run_id = standalone(peer, kind)
    original_stop = peer.stop

    async def owner_unknown(runtime, request, factory):
        await original_stop(runtime, request, factory)
        if request["run_id"] == run_id:
            proof = peer.proofs[run_id]
            proof.update(state="cancelling", physical_stopped=False)
            signed(proof)
            return {
                "ok": True,
                "code": "effect_outcome_unknown",
                "dispatched": True,
                "queried": True,
            }

    monkeypatch.setattr(temporal_coding_runtime, "stop", owner_unknown)
    with pytest.raises(CloseIncomplete):
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert not peer.records[0]["pending_stop"]
    assert not peer.proofs[run_id]["physical_stopped"]
    assert peer.children[0]["run_id"] in peer.adopted


@pytest.mark.parametrize("missing", ["actual_owner", "ancestor", "child_adoption"])
def test_final_scan_late_fenced_row_requires_original_physical_and_ancestor_proof(
    transport, monkeypatch, missing
):
    peer, runtime = transport
    original_scan = peer.composition_resources
    calls = []
    command_id = "late-child-command"
    run_id = child_run_id(SCOPE, command_id)
    request = copy.deepcopy(peer.children[0]["request"])
    if missing == "actual_owner":
        request.pop("coding_parent")
    else:
        link = request["coding_parent"]
        link.update(command_id=command_id, child_run_id=run_id)
        if missing == "ancestor":
            link["parent_run_id"] = "missing-original-root"
    proof = history_proof(run_id, request, "late-original-epoch")
    if missing != "actual_owner":
        proof.update(state="cancelled", physical_stopped=True)
        signed(proof)
    peer.proofs[run_id] = proof
    tool_request = copy.deepcopy(next(iter(peer.requests.values()))[0])
    tool_request.update(
        run_id=run_id, execution_epoch="late-original-epoch", action_id="late-action"
    )
    native = tool_request["coding_request"]
    native["dispatch"].update(
        run_id=run_id,
        execution_epoch="late-original-epoch",
        action_id="late-action",
        effect_key="late-fenced-effect",
    )
    native["release_digest"] = proof["release_digest"]
    native["request_digest"] = digest({k: v for k, v in native.items() if k != "request_digest"})
    peer.requests[run_id] = [tool_request]
    late = Peer.resource(tool_request, fenced=True)

    async def late_fenced(scope):
        calls.append(scope)
        if len(calls) == 2:
            peer.records.append(late)
        return await original_scan(scope)

    monkeypatch.setattr(peer, "composition_resources", late_fenced)
    with pytest.raises(CloseIncomplete) as error:
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert peer.records[-1]["pending_stop"] is False
    assert any(
        item.get("resource") == "late-fenced-effect"
        for item in error.value.report["coding_composition"]
    )


@pytest.mark.parametrize("standalone_kind", [None, "agent", "sequence"])
def test_close_reopens_only_original_failed_stop_with_drive(
    transport, monkeypatch, standalone_kind
):
    """A duplicate cancel receipt cannot reset the native failed-stop latch."""
    from ralf_agent import temporal_coding_runtime
    from ralf_agent.temporal_coding_state import accept_stop
    from ralf_agent.temporal_workflow import TemporalRunWorkflow

    peer, runtime = transport
    first = peer.children[0]["run_id"]
    if standalone_kind is not None:
        first = standalone(peer, standalone_kind)
    state, action, original_request = ready()
    state.scope = copy.deepcopy(SCOPE)
    owner_id = "root" if standalone_kind is None else first
    cancel_id = "ralf-parent-stop:" + digest([owner_id, first])
    state.command(cancel_id, {"kind": "cancel", "scope": SCOPE})
    state.operation_unknown(action["id"], "original-failed-stop")
    operation = state.next_operation()
    assert operation[0]["kind"] == "coding_stop"
    accept_stop(state, action["id"], {"ok": False, "code": "original_stop_unavailable"})
    assert state.actions[-1]["delegated_execution"]["stop_retry"] is True
    assert state.next_operation() is None
    original_attempts = copy.deepcopy(action["attempts"])
    workflow = TemporalRunWorkflow.__new__(TemporalRunWorkflow)
    workflow.state, workflow.wake_revision = state, 0
    original_update = Handle.execute_update
    original_stop = peer.stop
    commands = []
    recovering = False

    async def original_command(handle, name, payload, **options):
        nonlocal recovering
        if name == "command" and handle.run_id == first:
            commands.append((payload["payload"]["kind"], handle.epoch))
            await workflow.command(payload)
            if payload["payload"]["kind"] == "cancel":
                assert state.actions[-1]["delegated_execution"]["stop_retry"] is True
                assert state.next_operation() is None
            if payload["payload"]["kind"] == "drive":
                resumed = state.next_operation()
                assert resumed is not None and resumed[0]["kind"] == "coding_stop"
                assert state.state in {"cancelling", "cancelled"}
                assert action["attempts"] == original_attempts
                recovering = True
        return await original_update(handle, name, payload, **options)

    async def require_original_stop_recovery(runtime, request, factory):
        if request["run_id"] == first and not recovering:
            raise OSError("Original failed stop remains latched until drive")
        return await original_stop(runtime, request, factory)

    monkeypatch.setattr(Handle, "execute_update", original_command)
    monkeypatch.setattr(temporal_coding_runtime, "stop", require_original_stop_recovery)
    asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert commands == [("cancel", "child-epoch-1"), ("drive", "child-epoch-1")]
    assert peer.proofs[first]["physical_stopped"]
    assert action["attempts"] == original_attempts
    assert original_request["coding_request"]["reservation"]["id"] == original_attempts[0]["id"]


def test_stop_recovery_does_not_drive_a_leaf_still_running_after_cancel_ack(transport, monkeypatch):
    peer, runtime = transport
    first, second = [c["run_id"] for c in peer.children]
    original = Handle.execute_update

    async def unchanged_cancel(handle, name, payload, **options):
        if name == "command" and handle.run_id == first and payload["payload"]["kind"] == "cancel":
            return {"run_id": first}
        return await original(handle, name, payload, **options)

    monkeypatch.setattr(Handle, "execute_update", unchanged_cancel)
    with pytest.raises(CloseIncomplete):
        asyncio.run(control.close(runtime, client=peer, scope=Scope(**SCOPE)))
    assert first not in peer.stopped
    assert not any(event[:2] == ("drive", first) for event in peer.events)
    assert second in peer.stopped
