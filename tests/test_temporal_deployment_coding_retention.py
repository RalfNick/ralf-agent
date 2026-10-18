"""Offline SDK History evidence for fixture deletion, never execution authority."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent.types import digest
from tests.test_temporal_deployment_control_projection import bound_registry

pytest.importorskip("temporalio")
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import WorkflowHistory
from temporalio.converter import DataConverter


def description(identity, epoch):
    return SimpleNamespace(
        id=identity,
        run_id=epoch,
        workflow_type="ralf.temporal.commands.v1",
        raw_description=SimpleNamespace(
            workflow_execution_info=SimpleNamespace(first_run_id=epoch)
        ),
    )


async def started(identity, epoch, value):
    event = HistoryEvent(event_id=1)
    attrs = event.workflow_execution_started_event_attributes
    attrs.workflow_id = identity
    attrs.original_execution_run_id = attrs.first_execution_run_id = epoch
    attrs.input.payloads.extend(await DataConverter.default.encode([value]))
    return event


async def update(events, name, request, response=None, *, failed=False, pending=False):
    event = HistoryEvent(event_id=len(events) + 1)
    attrs = event.workflow_execution_update_accepted_event_attributes
    attrs.accepted_request.meta.update_id = str(event.event_id)
    attrs.accepted_request.input.name = name
    attrs.accepted_request.input.args.payloads.extend(await DataConverter.default.encode([request]))
    events.append(event)
    if not pending:
        done = HistoryEvent(event_id=len(events) + 1)
        completed = done.workflow_execution_update_completed_event_attributes
        completed.accepted_event_id = event.event_id
        completed.meta.update_id = str(event.event_id)
        if failed:
            completed.outcome.failure.message = "private sk-fixture-secret"
        else:
            completed.outcome.success.payloads.extend(
                await DataConverter.default.encode([response])
            )
        events.append(done)


async def signal(events, name, value):
    event = HistoryEvent(event_id=len(events) + 1)
    attrs = event.workflow_execution_signaled_event_attributes
    attrs.signal_name = name
    attrs.input.payloads.extend(await DataConverter.default.encode([value]))
    events.append(event)


async def release_activity(events, request, response, *, fault=None):
    scheduled = HistoryEvent(event_id=len(events) + 1)
    attrs = scheduled.activity_task_scheduled_event_attributes
    attrs.activity_id = "original-release"
    attrs.activity_type.name = "ralf.temporal.deployment-release.v2"
    attrs.task_queue.name = "original"
    attrs.input.payloads.extend(await DataConverter.default.encode([request]))
    events.append(scheduled)
    if fault == "missing_activity_completion":
        return
    completed = HistoryEvent(event_id=len(events) + 1)
    attrs = completed.activity_task_completed_event_attributes
    attrs.scheduled_event_id = scheduled.event_id
    if fault == "activity_schedule":
        attrs.scheduled_event_id += 100
    attrs.result.payloads.extend(await DataConverter.default.encode([response]))
    events.append(completed)


async def scenario(
    *, retired=True, pending=False, writes=None, fault=None, unused=False, transport="updates"
):
    from tests.temporal_deployment_coding_retention import deletion_evidence

    wrapper, state, request, root, _ = bound_registry()
    reserve = wrapper.reserve(request)
    certificate = {
        "version": 1,
        **{
            key: root[key]
            for key in (
                "scope",
                "run_id",
                "command_id",
                "namespace",
                "execution_epoch",
                "request_digest",
                "manifest_digest",
            )
        },
        "original_execution_epoch": root["execution_epoch"],
        "terminal_state": "cancelled",
        "admission_digest": "a" * 64,
        "receipt_digest": "b" * 64,
        "closure_digest": "c" * 64,
        "children": [],
    }
    certificate["proof_digest"] = digest(certificate)
    release_request = {
        **{
            key: root[key]
            for key in (
                "scope",
                "command_id",
                "run_id",
                "request_digest",
                "manifest_digest",
                "proof_digest",
                "execution_epoch",
                "namespace",
            )
        },
        "admission_policy": state.policy,
        "certificate": copy.deepcopy(certificate),
    }
    result = {
        "root": copy.deepcopy(root),
        "certificate": copy.deepcopy(certificate),
        "released": True,
    }
    if fault == "scope":
        result["root"]["scope"] = {"workspace": "other", "principal": "other"}
    if fault == "certificate":
        result["certificate"]["closure_digest"] = "d" * 64
    if fault == "epoch":
        result["certificate"]["execution_epoch"] = "other-epoch"
        result["certificate"]["proof_digest"] = digest(
            {k: v for k, v in result["certificate"].items() if k != "proof_digest"}
        )
    events = [
        await started(
            state.registry_id,
            "registry-original",
            {
                "deployment_admission": {
                    "version": 3,
                    "policy": state.policy,
                    "namespace": state.namespace,
                }
            },
        )
    ]
    if not unused and transport == "updates":
        await update(events, "reserve", request, reserve, pending=fault == "pending_reserve")
        if retired or pending:
            await update(
                events,
                "release_deployment_root",
                release_request,
                result,
                pending=pending,
                failed=fault == "failed_release",
            )
    elif not unused:
        envelope = {
            "kind": "deployment_reserve_receipt",
            "scope": root["scope"],
            "observation_id": "reserve-observation",
            "request": copy.deepcopy(request),
        }
        if fault == "reservation_namespace":
            envelope["request"]["namespace"]["id"] = "22222222-2222-2222-2222-222222222222"
        if fault == "reservation_submission":
            envelope["request"]["root_admission"]["submission"]["activity_timeout"] += 1
        if fault != "missing_reserve_signal":
            await signal(events, "reserve_command", envelope)
        if fault == "missing_acceptance_rejected_update":
            from ralf_agent.errors import IdempotencyConflict

            conflicting = copy.deepcopy(request)
            conflicting["payload_digest"] = "f" * 64
            with pytest.raises(IdempotencyConflict):
                wrapper.reserve(conflicting)
            assert state.roots[digest([root["scope"], root["command_id"]])] == root
            await update(events, "reserve", conflicting, failed=True)
        if fault == "untracked_reserve_signal":
            unknown = copy.deepcopy(envelope)
            unknown["observation_id"] = "another-reservation"
            unknown["request"]["command_id"] = "untracked"
            unknown["request"]["target"] = "untracked-root"
            await signal(events, "reserve_command", unknown)
        binding = {k: v for k, v in release_request.items() if k != "certificate"}
        if transport == "signals_record":
            run_receipt = {
                "command_id": root["command_id"],
                "run_id": root["run_id"],
                "kind": "submit",
                "record_state": "durably_recorded",
                "apply_state": "applied",
                "outcome": {"state_revision": 0},
            }
            accepted = {
                "reservation": {k: v for k, v in reserve.items() if k != "submission"},
                "submission": reserve["submission"],
                "run_receipt": run_receipt,
                "execution_epoch": root["execution_epoch"],
            }
            if fault == "accepted_submission":
                accepted["submission"] = copy.deepcopy(accepted["submission"])
                accepted["submission"]["activity_timeout"] += 1
            if fault == "accepted_receipt":
                accepted["run_receipt"] = {**run_receipt, "run_id": "other"}
            name, value, response = (
                "record_deployment_submission",
                {**binding, "receipt": run_receipt},
                accepted,
            )
        else:
            name, value, response = "bind_deployment_root", binding, root
        if fault == "accepted_epoch":
            value = {**value, "execution_epoch": "other"}
        if fault not in {"missing_acceptance", "missing_acceptance_rejected_update"}:
            await update(
                events,
                name,
                value,
                response,
                pending=fault == "pending_acceptance",
                failed=fault == "failed_acceptance",
            )
        retirement = {
            "version": 1,
            "scope": root["scope"],
            "namespace": state.namespace,
            "registry_id": state.registry_id,
            "execution_epoch": "registry-original",
            "observation_id": "retirement-observation",
            "request": copy.deepcopy(release_request),
        }
        if fault == "retirement_registry_epoch":
            retirement["execution_epoch"] = "replacement"
        if fault == "retirement_namespace":
            retirement["namespace"] = {
                **state.namespace,
                "id": "22222222-2222-2222-2222-222222222222",
            }
        if fault == "retirement_certificate":
            retirement["request"]["certificate"]["closure_digest"] = "d" * 64
        if retired and fault != "missing_retirement_signal":
            await signal(events, "retire_deployment_root", retirement)
    targets = set() if unused else {root["run_id"]}
    if fault in {"rejected_target", "unknown_target"}:
        from ralf_agent.temporal_deployment_admission import root_run_id

        refused = copy.deepcopy(request)
        refused["command_id"] = "capacity-refused"
        refused["target"] = root_run_id(
            state.policy["deployment_id"], refused["scope"], refused["command_id"]
        )
        targets.add(refused["target"])
        if fault == "rejected_target":
            await update(events, "reserve", refused, failed=True)
    close_request = {
        "scope": root["scope"],
        "admission_policy": state.policy,
        "namespace": state.namespace,
        "manifest_digest": root["manifest_digest"],
    }
    await update(
        events,
        "close_deployment_coding_submissions",
        close_request,
        {"manifest_digest": root["manifest_digest"], "close_requested": True, "candidates": []},
    )
    if fault == "update_id":
        events[
            -1
        ].workflow_execution_update_completed_event_attributes.meta.update_id = "other-update"
    root_events = [
        await started(
            root["run_id"],
            root["execution_epoch"],
            {
                "scope": root["scope"],
                "command_id": root["command_id"],
                "request": request["root_admission"]["submission"]["request"],
                "manifest": request["root_admission"]["submission"]["manifest"],
            },
        )
    ]
    if transport != "updates":
        initial = (
            await DataConverter.default.decode(
                root_events[0].workflow_execution_started_event_attributes.input.payloads
            )
        )[0]
        initial.update(
            activity_timeout=reserve["submission"]["activity_timeout"],
            deployment_admission={"version": 1, "root": reserve["root_admission"], "lineage": []},
        )
        root_events = [await started(root["run_id"], root["execution_epoch"], initial)]
        root_events[0].workflow_execution_started_event_attributes.task_queue.name = "original"
        activity_request = {
            "mode": "release",
            "scope": root["scope"],
            "run_id": root["run_id"],
            "execution_epoch": root["execution_epoch"],
        }
        if fault == "activity_epoch":
            activity_request["execution_epoch"] = "replacement"
        activity_result = {"ok": True, "result": result}
        if fault == "failed_activity":
            activity_result = {"ok": False, "code": "deployment_release_failed"}
        if retired and fault != "missing_release_activity":
            await release_activity(root_events, activity_request, activity_result, fault=fault)
    archived = []

    class Client:
        namespace = state.namespace["name"]
        data_converter = DataConverter.default

        def get_workflow_handle(self, identity, *, run_id=None):
            assert identity == root["run_id"]
            if run_id is not None:
                assert run_id == root["execution_epoch"]

            class Handle:
                async def describe(self, **options):
                    value = description(identity, root["execution_epoch"])
                    value.workflow_type = "ralf.temporal.run.v1"
                    value.namespace = state.namespace["name"]
                    value.task_queue = "original"
                    if fault == "root_reset":
                        value.raw_description.workflow_execution_info.first_run_id = "first-other"
                    if fault == "root_read_failure":
                        raise ConnectionError(
                            "postgresql://private:user-password sk-fixture-secret"
                        )
                    return value

                async def fetch_history(self, **options):
                    return WorkflowHistory(identity, root_events)

            return Handle()

    registry_description = description(state.registry_id, "registry-original")
    if fault == "registry_reset":
        registry_description.raw_description.workflow_execution_info.first_run_id = "first-other"
    gate = await deletion_evidence(
        Client(),
        registry_description,
        WorkflowHistory(state.registry_id, events),
        policy=state.policy,
        namespace=state.namespace,
        scope=root["scope"],
        manifest_digest=root["manifest_digest"],
        targets=targets,
        effects=writes or [],
        archive=lambda identity, history: archived.append(identity),
    )
    return gate, root, archived


def test_missing_retirement_retains_even_after_successful_scoped_close():
    gate, root, archived = asyncio.run(scenario(retired=False))
    assert not gate["deletion_allowed"]
    assert gate["retained_roots"] == [
        {
            "run_id": root["run_id"],
            "scope": root["scope"],
            "execution_epoch": root["execution_epoch"],
        }
    ]
    assert archived == [root["run_id"]]


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "certificate",
        "epoch",
        "registry_reset",
        "root_reset",
        "root_read_failure",
        "update_id",
        "failed_release",
        "pending_reserve",
        "unknown_target",
    ],
)
def test_false_release_identity_retains_original_data(fault):
    gate, _, _ = asyncio.run(scenario(fault=fault))
    assert not gate["deletion_allowed"]


def test_completed_capacity_refusal_is_not_a_missing_accepted_root():
    gate, _, _ = asyncio.run(scenario(fault="rejected_target"))
    assert gate["deletion_allowed"]


def test_adopted_zero_cost_write_and_private_evidence_do_not_leak_into_report():
    import json

    secret = "postgresql://private:user-password sk-fixture-secret"
    gate, _, _ = asyncio.run(
        scenario(writes=[{"effect": "write", "state": "adopted", "cost": 0, "result": secret}])
    )
    assert gate["deletion_allowed"] and secret not in json.dumps(gate)


def test_pending_release_retains_without_reading_any_query_or_mutating_authority():
    gate, _, _ = asyncio.run(scenario(retired=False, pending=True))
    assert not gate["deletion_allowed"] and "pending_registry_update" in gate["reasons"]


def test_completed_original_release_permits_deletion_without_root_reply_ack():
    gate, _, _ = asyncio.run(scenario())
    assert gate["deletion_allowed"] and gate["retained_roots"] == []


def test_zero_cost_unadopted_write_vetoes_even_completed_retirement():
    gate, _, _ = asyncio.run(scenario(writes=[{"effect": "write", "state": "received", "cost": 0}]))
    assert not gate["deletion_allowed"] and "unadopted_write" in gate["reasons"]


def test_never_used_positive_scoped_close_needs_no_root_or_empty_pg_inference():
    gate, _, archived = asyncio.run(scenario(unused=True))
    assert gate["deletion_allowed"] and gate["accepted_roots"] == [] and archived == []


@pytest.mark.parametrize("transport", ["signals_record", "signals_bind"])
def test_signal_submission_requires_completed_original_acceptance_and_release(transport):
    gate, root, archived = asyncio.run(scenario(transport=transport))
    assert gate["deletion_allowed"], gate
    assert gate["retired_roots"][0]["run_id"] == root["run_id"]
    assert archived == [root["run_id"]]


@pytest.mark.parametrize("transport", ["signals_record", "signals_bind"])
def test_conflicting_failed_update_cannot_clear_unconfirmed_submit_signal(transport):
    gate, _, archived = asyncio.run(
        scenario(
            retired=False,
            transport=transport,
            fault="missing_acceptance_rejected_update",
        )
    )
    assert not gate["deletion_allowed"], gate
    assert "target_acceptance_unresolved" in gate["reasons"]
    assert gate["accepted_roots"] == [] and archived == []


@pytest.mark.parametrize("transport", ["signals_record", "signals_bind"])
@pytest.mark.parametrize(
    "fault",
    [
        "missing_reserve_signal",
        "missing_acceptance",
        "pending_acceptance",
        "failed_acceptance",
        "accepted_epoch",
        "reservation_namespace",
        "reservation_submission",
        "missing_retirement_signal",
        "retirement_registry_epoch",
        "retirement_namespace",
        "retirement_certificate",
        "missing_release_activity",
        "missing_activity_completion",
        "activity_schedule",
        "activity_epoch",
        "failed_activity",
        "scope",
        "certificate",
        "epoch",
        "root_reset",
        "registry_reset",
        "unknown_target",
        "untracked_reserve_signal",
    ],
)
def test_signal_or_incomplete_receipts_never_authorize_fixture_deletion(transport, fault):
    gate, _, _ = asyncio.run(scenario(transport=transport, fault=fault))
    assert not gate["deletion_allowed"], gate


@pytest.mark.parametrize("fault", ["accepted_submission", "accepted_receipt"])
def test_completed_submission_record_must_match_original_signal(fault):
    gate, _, _ = asyncio.run(scenario(transport="signals_record", fault=fault))
    assert not gate["deletion_allowed"], gate


@pytest.mark.parametrize(
    "mode", ["retained", "delete", "read_failure", "close_failure", "worker_alive"]
)
def test_cleanup_deletion_gate_is_separate_from_assembly_close_and_keeps_private_recovery(
    tmp_path, monkeypatch, request, mode
):
    import socket
    import uuid
    from pathlib import Path

    from ralf_agent import Scope
    from ralf_agent.errors import CloseIncomplete
    from ralf_agent.governance import DeploymentAdmissionPolicy
    from tests import temporal_deployment_coding_retention as helper
    from tests import test_temporal_deployment_coding_service as service

    CodingSystem = service.CodingSystem

    events = []
    secret = "postgresql://private:user-password@127.0.0.1/private sk-fixture-secret"
    close_error = CloseIncomplete({"original_native_owner": "not_stopped"})
    socket_path = Path("/private/tmp") / ("ralf-dcoding-unit-" + uuid.uuid4().hex[:12] + ".sock")
    (tmp_path / "application.json").write_text('{"dsn_env":"TEST_ONLY_DSN"}')

    class Assembly:
        async def aclose(self, **options):
            events.append("assembly-close")
            if mode == "close_failure":
                raise close_error

    class Admin:
        async def execute(self, query, *args):
            if "DROP SCHEMA" in str(query):
                events.append("drop")

            class Cursor:
                async def fetchone(self):
                    return (None,)

            return Cursor()

        async def close(self):
            events.append("admin-close")

    class Socket:
        closed = False

        def __init__(self):
            self.owner = socket.socket(socket.AF_UNIX)
            self.owner.bind(str(socket_path))

        def close(self):
            self.owner.close()
            self.closed = True
            events.append("socket-close")

    class Handle:
        id = "original-registry"

        async def describe(self, **options):
            if mode == "read_failure":
                raise ConnectionError(secret)
            return description(self.id, "original-epoch")

        async def fetch_history(self, **options):
            return SimpleNamespace(to_json=lambda: "{}")

        async def terminate(self, **options):
            events.append("terminate")

    class Client:
        namespace = "original"

        def get_workflow_handle(self, *args, **options):
            return Handle()

    class Engine:
        async def aclose(self):
            events.append("engine-close")

    system = CodingSystem.__new__(CodingSystem)
    system.directory, system.schema = tmp_path, "original_schema"
    system.assembly, system.admin, system.client = Assembly(), Admin(), Client()
    system.socket_owner, system.socket_path = Socket(), socket_path
    socket_identity = socket_path.stat().st_dev, socket_path.stat().st_ino

    def finish_unit_owner():
        system.socket_owner.close()
        socket_path.unlink(missing_ok=True)

    request.addfinalizer(finish_unit_owner)
    system.scope = Scope("fixture", "original")
    system.policy = DeploymentAdmissionPolicy(deployment_id="fixture", max_active_root_runs=1)
    system.release = {"first": "manifest"}
    system.data = {"namespace": {"name": "original", "id": "original-id"}}
    system.targets, system.processes, system.engines = set(), [], [Engine()]
    if mode == "worker_alive":
        system.processes = [SimpleNamespace(poll=lambda: None)]

        async def still_active(process):
            events.append("owned-worker-still-active")

        monkeypatch.setattr(system, "kill", still_active)
    system.expected_retention, system.recovery = [], None

    async def capture():
        assert "assembly-close" in events
        events.append("post-close-snapshot")
        (tmp_path / "ralf_temporal_effects.json").write_text("[]")
        return {"ralf_temporal_effects": []}

    async def proof(*args, **options):
        assert events == ["assembly-close", "post-close-snapshot"]
        return {
            "deletion_allowed": mode == "delete",
            "accepted_roots": [],
            "retired_roots": [],
            "retained_roots": [],
            "reasons": [] if mode == "delete" else ["root_retirement_unconfirmed"],
        }

    async def replay(*args, **options):
        assert options == {"namespace": "original"}

    monkeypatch.setattr(system, "capture", capture)
    monkeypatch.setattr(helper, "deletion_evidence", proof)
    monkeypatch.setattr(service, "replay_temporal_history", replay)
    if mode == "close_failure":
        with pytest.raises(CloseIncomplete) as caught:
            asyncio.run(system.cleanup())
        assert caught.value is close_error
        assert close_error.deployment_coding_fixture_recovery is system.recovery
    else:
        asyncio.run(system.cleanup())
    text = (tmp_path / "cleanup.json").read_text()
    import json

    report = json.loads(text)
    assert report["assembly_close_succeeded"] == (mode != "close_failure")
    assert secret not in text and "password" not in text
    assert (tmp_path / "cleanup.json").stat().st_mode & 0o777 == 0o600
    assert report["schema_retained"] == (mode != "delete")
    if mode == "delete":
        assert not socket_path.exists() and system.socket_owner.closed
        assert events.index("terminate") < events.index("socket-close") < events.index("drop")
    else:
        assert socket_path.exists()
        assert (socket_path.stat().st_dev, socket_path.stat().st_ino) == socket_identity
        # Direct cleanup retains its caller-owned marker until the enclosing
        # coding_system context exits; it never unlinks or rebinds the address.
        assert not system.socket_owner.closed
        assert (system.socket_owner.owner.fileno() == -1) == system.socket_owner.closed
        assert "terminate" not in events and "drop" not in events
        assert system.recovery["socket"] is system.socket_owner
        assert system.recovery["assembly"] is system.assembly
        assert system.recovery["client"] is system.client
        assert (tmp_path / "cleanup-retention.json").exists()
        assert (tmp_path / "application.json").exists() and (
            tmp_path / "ralf_temporal_effects.json"
        ).exists()
    assert events[-2:] == ["engine-close", "admin-close"]


@pytest.mark.parametrize("outcome", ["retained", "close_failure", "active_owner"])
def test_fixture_exit_closes_only_dummy_fd_and_preserves_original_recovery(
    tmp_path, monkeypatch, outcome
):
    import json

    import psycopg

    from ralf_agent.errors import CloseIncomplete
    from tests import temporal_deployment_coding_worker_fixture as worker
    from tests import test_temporal_deployment_coding_service as service

    events, systems = [], []
    assembly = SimpleNamespace(active=outcome != "retained")
    original = CloseIncomplete({"original_owner": "still_active"})

    class Admin:
        async def execute(self, query, *args):
            events.append("drop" if "DROP SCHEMA" in str(query) else "sql")

        async def close(self):
            events.append("admin-close")

    class System:
        def __init__(self, directory, admin, schema, sock, path, data, built, client):
            assert built is assembly
            self.socket_owner, self.socket_path = sock, path
            self.original_inode = path.stat().st_dev, path.stat().st_ino
            self.release = {
                "deployment_admission_protocol": {"version": 3},
                "coding_execution_protocol": {"version": 6},
                "binding_protocol": 22,
            }
            self.recovery = {"socket": sock, "assembly": built, "application": directory}
            self.marker_fd = sock.fileno()
            systems.append(self)

        async def cleanup(self):
            assert self.socket_owner.fileno() == self.marker_fd
            if outcome == "close_failure":
                original.deployment_coding_fixture_recovery = self.recovery
                raise original

    async def connect(*args, **kwargs):
        return Admin()

    async def build(*args, **kwargs):
        return assembly

    async def clients(*args, **kwargs):
        return [object()], {"name": "original", "id": "original-id"}

    monkeypatch.setenv("RALF_TEST_POSTGRES_DSN", "postgresql://127.0.0.1/fixture_only")
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    monkeypatch.setattr(worker, "application", build)
    monkeypatch.setattr(service, "_clients", clients)
    monkeypatch.setattr(service, "CodingSystem", System)

    async def scenario():
        async with service.coding_system(tmp_path, monkeypatch):
            pass

    try:
        if outcome == "close_failure":
            with pytest.raises(CloseIncomplete) as caught:
                asyncio.run(scenario())
            assert caught.value is original
            assert caught.value.deployment_coding_fixture_recovery is systems[0].recovery
        else:
            asyncio.run(scenario())
        system = systems[0]
        assert system.socket_owner.fileno() == -1
        assert (system.socket_path.stat().st_dev, system.socket_path.stat().st_ino) == (
            system.original_inode
        )
        assert system.recovery["assembly"] is assembly
        assert assembly.active is (outcome != "retained")
        assert "drop" not in events
        assert json.loads((tmp_path / "application.json").read_text())
    finally:
        for system in systems:
            system.socket_owner.close()
            system.socket_path.unlink(missing_ok=True)
