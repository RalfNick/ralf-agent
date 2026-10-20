"""Selected3 SDK wake routing; original evidence remains the only authority."""

import asyncio
import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")
from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow, workflow
from ralf_agent.temporal_workflow import TemporalRunWorkflow
from tests.test_temporal_deployment_parent_wake import SleepReached, identity, parent


@pytest.mark.parametrize(
    "workflow_module", ["ralf_agent.temporal_workflow", "ralf_agent.temporal_parent_workflow"]
)
def test_sdk_runtime_importer_accepts_compact_request_without_late_projection_import(
    workflow_module,
):
    import importlib
    import warnings

    from temporalio.worker.workflow_sandbox._importer import Importer
    from temporalio.worker.workflow_sandbox._restrictions import RestrictionContext

    from ralf_agent.temporal import _workflow_runner
    from ralf_agent.temporal_parent_state import TemporalParentState
    from tests.test_temporal_deployment_control_projection import (
        add_child,
        bound_registry,
        original,
    )

    bootstrap = original(parent=True)
    state = TemporalParentState(
        bootstrap.run_id,
        bootstrap.scope,
        "one",
        bootstrap.request,
        bootstrap.manifest,
        bootstrap.epoch,
    )
    for name, value in vars(bootstrap).items():
        setattr(state, name, copy.deepcopy(value))
    call = add_child(state)
    _, registry_state, _, _, registry_request = bound_registry()
    importlib.import_module(workflow_module)
    context = RestrictionContext()
    importer = Importer(_workflow_runner().restrictions, context)
    with importer.applied():
        importlib.import_module(workflow_module)
        transport = importlib.import_module("ralf_agent.temporal_deployment_control_transport")
        projection = importlib.import_module("ralf_agent.temporal_deployment_control_projection")
        context.is_runtime = True
        context.in_activation = True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", UserWarning)
                request = transport.request(state, call, "observe")
                assert request["child_run_id"] == call["run_id"]
                assert request["parent_execution_epoch"] == state.epoch
                assert "runtime_manifest" not in request
                projected = projection.node(
                    state,
                    {
                        "kind": projection.NODE_QUERY,
                        "scope": copy.deepcopy(state.scope),
                        "run_id": state.run_id,
                        "execution_epoch": state.epoch,
                        "child_call_id": None,
                    },
                )
                assert projected["edge"] is None
                registered = projection.registry(registry_state, registry_request)
                assert registered["registry_execution_epoch"] == "original-registry-epoch"
                assert registered["held"] is True
        finally:
            context.in_activation = False
            context.is_runtime = False


def selected_parent(monkeypatch):
    value = parent(monkeypatch, 3)
    value.state.deployment_admission = {"root": {"namespace": {"name": "original", "id": "ns"}}}
    value.state.deployment_original_epoch = value.state.epoch
    value.state.children[0]["deployment_execution_epoch"] = "child-epoch"
    value._deployment_initialization_error = None
    monkeypatch.setattr(
        workflow,
        "info",
        lambda: SimpleNamespace(
            namespace="original",
            workflow_id="parent",
            run_id="parent-epoch",
            original_execution_run_id="parent-epoch",
            first_execution_run_id="parent-epoch",
            parent=None,
            task_queue="original-queue",
        ),
    )
    return value


def hint(value, token="a" * 64):
    return {
        "version": 1,
        "scope": copy.deepcopy(value.state.scope),
        "parent_run_id": "parent",
        "parent_execution_epoch": "parent-epoch",
        "child_run_id": "child",
        "child_execution_epoch": "child-epoch",
        "token": token,
    }


def test_initial_dirty_generation_is_cleared_only_after_unchanged_valid_adoption(monkeypatch):
    async def scenario():
        value = selected_parent(monkeypatch)
        call = value.state.children[0]
        first = value._deployment_child_generation(call)
        assert value._deployment_child_is_dirty(call)
        await value.deployment_child_wake(hint(value))
        assert value._deployment_child_generation(call) > first
        dirty = value._deployment_child_generation(call)
        await value.deployment_child_wake(hint(value))
        assert value._deployment_child_generation(call) == dirty
        assert not value._deployment_child_observed(call, first)
        current = value._deployment_child_generation(call)
        assert value._deployment_child_observed(call, current)
        assert not value._deployment_child_is_dirty(call)
        wake = value.wake_revision
        await value.deployment_child_wake(hint(value))
        assert value.wake_revision == wake + 1 and value._deployment_child_is_dirty(call)
        await value.deployment_child_wake(hint(value, "b" * 64))
        assert value._deployment_child_is_dirty(call)

    asyncio.run(scenario())


def test_untrusted_preplayed_token_cannot_suppress_later_genuine_hint(monkeypatch):
    async def scenario():
        value = selected_parent(monkeypatch)
        call = value.state.children[0]
        predicted_future_token = hint(value, "b" * 64)
        await value.deployment_child_wake(predicted_future_token)
        # A validated read adopts the current old facts; caller tokens never
        # become an observed watermark for future child facts.
        value._deployment_child_observed(call, value._deployment_child_generation(call))
        assert not value._deployment_child_is_dirty(call)
        await value.deployment_child_wake(predicted_future_token)
        assert value._deployment_child_is_dirty(call)

    asyncio.run(scenario())


def test_preplayed_token_cannot_hide_new_hint_during_original_observe_await(monkeypatch):
    async def scenario():
        value = selected_parent(monkeypatch)
        predicted_future_token = hint(value, "b" * 64)
        await value.deployment_child_wake(predicted_future_token)
        reads = []

        async def control(mode, call, activity_timeout):
            reads.append(mode)
            if len(reads) == 1:
                # The original SDK read already captured old facts. The genuine
                # new hint reuses the token an untrusted caller preplayed.
                await value.deployment_child_wake(predicted_future_token)
            return {"ok": True, "result": {}}

        async def wait(predicate, **options):
            assert options == {}
            if predicate():
                return
            raise SleepReached

        value._control = control
        monkeypatch.setattr(workflow, "wait_condition", wait)
        with pytest.raises(SleepReached):
            await value.run({"activity_timeout": 80})
        assert reads == ["observe", "observe"]
        assert not value._deployment_child_is_dirty(value.state.children[0])

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,changed",
    [
        ("scope", {}),
        ("parent_run_id", "foreign"),
        ("parent_execution_epoch", "foreign"),
        ("child_run_id", "foreign"),
        ("child_execution_epoch", "foreign"),
        ("token", "not-a-token"),
        ("version", True),
    ],
)
def test_forged_hint_never_adopts_child_or_changes_generation(monkeypatch, field, changed):
    async def scenario():
        value = selected_parent(monkeypatch)
        call = value.state.children[0]
        before = copy.deepcopy(call)
        generation = value._deployment_child_generation(call)
        payload = hint(value)
        payload[field] = changed
        await value.deployment_child_wake(payload)
        assert value._deployment_child_generation(call) == generation
        assert call == before and value.wake_revision == 0

    asyncio.run(scenario())


def test_sdk_registers_signal_and_inherits_node_query_on_original_parent(monkeypatch):
    for cls in (TemporalRunWorkflow, TemporalParentWorkflow):
        definition = workflow._Definition.must_from_class(cls)
        assert definition.signals["deployment_child_wake"].fn is cls.deployment_child_wake
        assert (
            definition.queries["deployment_coding_validation"].fn
            is cls.deployment_coding_validation
        )


def test_notify_uses_actual_parent_epoch_and_retries_same_token_after_lost_ack(monkeypatch):
    async def scenario():
        value = selected_parent(monkeypatch)
        value.state.run_id, value.state.epoch, value.state.deployment_original_epoch = (
            "child",
            "child-epoch",
            "child-epoch",
        )
        value.state.children = []
        info = SimpleNamespace(
            namespace="original",
            workflow_id="child",
            run_id="child-epoch",
            original_execution_run_id="child-epoch",
            first_execution_run_id="child-epoch",
            parent=SimpleNamespace(
                namespace="original", workflow_id="parent", run_id="parent-epoch"
            ),
        )
        monkeypatch.setattr(workflow, "info", lambda: info)
        calls, targets = [], []

        class Receiver:
            async def signal(self, name, payload):
                calls.append((name, copy.deepcopy(payload)))
                if len(calls) == 1:
                    raise TimeoutError("reply lost after real signal acceptance")

        def external(workflow_id, **options):
            targets.append((workflow_id, options))
            return Receiver()

        monkeypatch.setattr(workflow, "get_external_workflow_handle", external)
        assert not await value._notify_deployment_parent()
        assert value._deployment_parent_pending is not None
        assert value._deployment_parent_notification_retry, (
            value._deployment_parent_notification_error
        )
        assert await value._notify_deployment_parent()
        assert calls[0] == calls[1]
        assert targets == [("parent", {"run_id": "parent-epoch"})] * 2
        assert calls[0][0] == "deployment_child_wake"
        assert value._deployment_parent_pending is None
        assert await value._notify_deployment_parent()
        assert len(calls) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("during_observe", [False, True])
def test_selected3_observes_only_dirty_and_sleeps_without_idle_poll_timer(
    monkeypatch, during_observe
):
    async def scenario():
        value = selected_parent(monkeypatch)
        calls, waits = [], []

        async def control(mode, call, activity_timeout):
            calls.append(mode)
            if during_observe and len(calls) == 1:
                await value.deployment_child_wake(hint(value))
            return {"ok": True, "result": {}}

        async def wait(predicate, **options):
            assert options == {}, "Normal selected3 idle must have no periodic poll timer"
            waits.append(predicate())
            if waits[-1]:
                return
            raise SleepReached

        value._control = control
        monkeypatch.setattr(workflow, "wait_condition", wait)
        with pytest.raises(SleepReached):
            await value.run({"activity_timeout": 80})
        assert calls == ["observe"] * (2 if during_observe else 1)
        assert waits == ([True, False] if during_observe else [False])
        assert not value._deployment_child_is_dirty(value.state.children[0])

    asyncio.run(scenario())


def test_native_ledger_only_end_notifies_once_and_duplicate_ack_has_no_feedback(monkeypatch):
    async def scenario():
        model = selected_parent(monkeypatch)
        value = object.__new__(TemporalRunWorkflow)
        value.__dict__.update(model.__dict__)
        value.state.run_id = "child"
        value.state.epoch = value.state.deployment_original_epoch = "child-epoch"
        value.state.children = []
        info = SimpleNamespace(
            namespace="original",
            workflow_id="child",
            run_id="child-epoch",
            original_execution_run_id="child-epoch",
            first_execution_run_id="child-epoch",
            parent=SimpleNamespace(
                namespace="original", workflow_id="parent", run_id="parent-epoch"
            ),
        )
        monkeypatch.setattr(workflow, "info", lambda: info)
        notifications = []

        class Receiver:
            async def signal(self, name, payload):
                notifications.append(copy.deepcopy(payload))

        monkeypatch.setattr(
            workflow, "get_external_workflow_handle", lambda *args, **kwargs: Receiver()
        )
        proof = identity(value)
        proof["activity_name"] = "ralf.temporal.tool.v1"
        await value.deployment_call_started(proof)
        await value._notify_deployment_parent()
        revision = value.state.revision
        await value.deployment_call_ended(proof)
        assert value.state.revision == revision
        await value._notify_deployment_parent()
        assert len(notifications) == 2 and notifications[0]["token"] != notifications[1]["token"]
        await value.deployment_call_ended(proof)
        await value._notify_deployment_parent()
        assert len(notifications) == 2
        # New replay instance recomputes the same bounded token from original facts.
        replay = object.__new__(TemporalRunWorkflow)
        replay.__dict__.update(model.__dict__)
        replay._deployment_parent_notified = None
        replay._deployment_parent_pending = None
        await replay._notify_deployment_parent()
        assert notifications[-1] == notifications[1]

    asyncio.run(scenario())


def test_permanent_parent_absence_keeps_pending_without_timer_or_repeated_send(monkeypatch):
    from temporalio.exceptions import ApplicationError

    async def scenario():
        value = selected_parent(monkeypatch)
        value.state.run_id, value.state.epoch, value.state.deployment_original_epoch = (
            "child",
            "child-epoch",
            "child-epoch",
        )
        value.state.children = []
        info = SimpleNamespace(
            namespace="original",
            workflow_id="child",
            run_id="child-epoch",
            original_execution_run_id="child-epoch",
            first_execution_run_id="child-epoch",
            parent=SimpleNamespace(
                namespace="original", workflow_id="parent", run_id="parent-epoch"
            ),
        )
        monkeypatch.setattr(workflow, "info", lambda: info)
        calls = []

        class Receiver:
            async def signal(self, name, payload):
                calls.append(payload)
                raise ApplicationError(
                    "original parent absent", type="ExternalWorkflowExecutionNotFound"
                )

        monkeypatch.setattr(
            workflow, "get_external_workflow_handle", lambda *args, **kwargs: Receiver()
        )
        assert not await value._notify_deployment_parent()
        assert value._deployment_parent_pending is not None
        assert value._deployment_parent_notification_retry is False
        assert not await value._notify_deployment_parent()
        assert len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault", ["first", "original", "current", "namespace", "initialization", "scope"]
)
def test_node_query_refuses_wrong_sdk_identity_without_calling_projector(monkeypatch, fault):
    from ralf_agent import temporal_deployment_control_projection as projection
    from ralf_agent.errors import AuthorizationDenied

    value = selected_parent(monkeypatch)
    calls = []
    monkeypatch.setattr(
        projection, "node", lambda state, request: calls.append(request) or {"ok": True}
    )

    def authorize(scope):
        if scope != value.state.scope:
            raise AuthorizationDenied("wrong Scope")

    value.state.authorize = authorize
    request = {
        "kind": projection.NODE_QUERY,
        "scope": copy.deepcopy(value.state.scope),
        "run_id": "parent",
        "execution_epoch": "parent-epoch",
        "child_call_id": None,
    }
    assert value.deployment_coding_validation(request) == {"ok": True}
    assert value.view(request) == {"ok": True}
    calls.clear()
    info = workflow.info()
    if fault in {"first", "original", "current"}:
        setattr(
            info,
            {
                "first": "first_execution_run_id",
                "original": "original_execution_run_id",
                "current": "run_id",
            }[fault],
            "foreign",
        )
        monkeypatch.setattr(workflow, "info", lambda: info)
    elif fault == "namespace":
        info.namespace = "foreign"
        monkeypatch.setattr(workflow, "info", lambda: info)
    elif fault == "initialization":
        value._deployment_initialization_error = "definition_mismatch"
    else:
        request["scope"] = {}
    before = value.state.revision
    assert "error" in value.deployment_coding_validation(request)
    assert "error" in value.view(request)
    assert calls == [] and value.state.revision == before


def test_registry_node_query_uses_constructor_sdk_epoch_and_refuses_later_drift(monkeypatch):
    from ralf_agent.temporal_workflow import TemporalCommandRegistryWorkflow
    from tests.test_temporal_deployment_registry_epoch import registry, sdk_info

    value = registry(monkeypatch, 3)
    observed = []
    assert value.commands.deployment.deployment_registry_execution_epoch == "first-sdk-epoch"
    value.commands.deployment.deployment_coding_validation = lambda request: (
        observed.append(request) or {"original": True}
    )
    assert value.deployment_coding_validation({"kind": "deployment_coding_validation"}) == {
        "original": True
    }
    assert value.view({"kind": "deployment_coding_validation"}) == {"original": True}
    monkeypatch.setattr(workflow, "info", lambda: sdk_info(first_execution_run_id="foreign"))
    assert value.deployment_coding_validation({"kind": "deployment_coding_validation"}) == {
        "error": "definition_mismatch"
    }
    assert value.view({"kind": "deployment_coding_validation"}) == {"error": "definition_mismatch"}
    assert len(observed) == 2
    definition = workflow._Definition.must_from_class(TemporalCommandRegistryWorkflow)
    assert (
        definition.queries["deployment_coding_validation"].fn
        is TemporalCommandRegistryWorkflow.deployment_coding_validation
    )


def test_external_drive_forces_original_child_read_without_new_hint(monkeypatch):
    async def scenario():
        value = selected_parent(monkeypatch)
        call = value.state.children[0]
        value._deployment_child_observed(call, value._deployment_child_generation(call))
        assert not value._deployment_child_is_dirty(call)

        def command(*args):
            value.state.revision += 1
            return {"record_state": "durably_recorded"}

        value.state.command = command
        await value.command({"command_id": "explicit-recovery", "payload": {"kind": "drive"}})
        assert value._deployment_child_is_dirty(call)

    asyncio.run(scenario())


def test_selected3_end_during_retirement_preserves_dirty_wake_and_waits_without_timer(monkeypatch):
    async def scenario():
        value = selected_parent(monkeypatch)
        value.state.state, value.state.quiescent, value.state.children_quiescent = (
            "succeeded",
            True,
            True,
        )
        value.state.children = []
        proof = identity(value)
        await value.deployment_call_started(proof)
        attempts = []

        async def retirement(*args):
            attempts.append(True)
            await value.deployment_call_ended(proof)

        async def wait(predicate, **options):
            assert options == {}
            if len(attempts) == 1:
                assert predicate()
                return
            assert not predicate()
            raise SleepReached

        value._ensure_deployment_retirement = retirement
        monkeypatch.setattr(workflow, "wait_condition", wait)
        with pytest.raises(SleepReached):
            await value.run({"activity_timeout": 80})
        assert len(attempts) == 2 and value.wake_revision == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["transient", "permanent", "exhausted"])
def test_observe_failure_retries_only_bounded_reads_without_a_future_child_hint(
    monkeypatch, failure
):
    async def scenario():
        value = selected_parent(monkeypatch)
        calls, waits = [], []

        async def control(mode, call, activity_timeout):
            assert mode == "observe", "A failed read cannot retry business start/grants"
            calls.append(mode)
            if failure == "transient" and len(calls) > 1:
                return {"ok": True, "result": {}}
            return {
                "ok": False,
                "code": "authorization_denied"
                if failure == "permanent"
                else "parent_activity_unavailable",
            }

        async def wait(predicate, **options):
            assert not predicate(), "No second hint or external command is supplied"
            waits.append(options)
            if options:
                assert options == {"timeout": timedelta(seconds=1)}
                raise TimeoutError
            raise SleepReached

        value._control = control
        monkeypatch.setattr(workflow, "wait_condition", wait)
        with pytest.raises(SleepReached):
            await value.run({"activity_timeout": 80})
        assert len(calls) == {"transient": 2, "permanent": 1, "exhausted": 3}[failure]
        assert waits[-1] == {}
        assert value._deployment_child_is_dirty(value.state.children[0]) == (failure != "transient")
        if failure != "transient":
            assert not value._deployment_child_retry_pending()

            # Explicit drive creates a new generation and resets its read allowance.
            def command(*args):
                value.state.revision += 1
                return {"record_state": "durably_recorded"}

            value.state.command = command
            await value.command({"command_id": "receiver-recovery", "payload": {"kind": "drive"}})
            call = value.state.children[0]
            assert value._deployment_child_read_ready(
                call, value._deployment_child_generation(call)
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "version,dirty,unknown,during_observe,expected_reads",
    [
        (3, True, False, False, 1),
        (3, False, False, False, 0),
        (3, True, True, False, 1),
        (3, True, False, True, 2),
        (2, True, False, False, 0),
    ],
)
def test_stopped_unsettled_child_adopts_only_fresh_selected3_observation(
    monkeypatch, version, dirty, unknown, during_observe, expected_reads
):
    from ralf_agent import temporal_coding_composition_state as composition
    from ralf_agent.temporal_bindings import request_release_digest
    from ralf_agent.temporal_parent_state import TemporalParentState
    from tests.test_temporal_deployment_control_projection import add_child, original

    async def scenario():
        value = selected_parent(monkeypatch)
        bootstrap = original(parent=True)
        state = TemporalParentState(
            bootstrap.run_id,
            bootstrap.scope,
            "one",
            bootstrap.request,
            bootstrap.manifest,
            bootstrap.epoch,
        )
        for name, field in vars(bootstrap).items():
            setattr(state, name, copy.deepcopy(field))
        call = add_child(state)
        call.update(
            run_id="child",
            state="cancelling",
            settled=False,
            spent=0,
            cancel_confirmed=True,
            physical_stop_proof={"physical_stopped": True},
            physical_recovered_revision=0,
        )
        state.state, state.stage = "cancelling", "execute"
        state.composition_stop_intent = {"terminal_state": "cancelled"}
        state.composition_admission = None
        state.manifest["deployment_admission_protocol"]["version"] = version
        value.state = state
        info = workflow.info()
        info.workflow_id = state.run_id
        info.namespace = state.deployment_admission["root"]["namespace"]["name"]
        info.run_id = info.first_execution_run_id = info.original_execution_run_id = state.epoch
        monkeypatch.setattr(workflow, "info", lambda: info)

        def payload(token="a" * 64):
            return {
                **hint(value, token),
                "parent_run_id": state.run_id,
                "parent_execution_epoch": state.epoch,
            }

        # The original physical proof was already validated and adopted; exercise
        # the real SDK loop and real financial observation, not another stop grant.
        monkeypatch.setattr(composition, "refresh_parent_stop", lambda state: None)
        monkeypatch.setattr(
            composition, "physical_stop_view", lambda state: {"physical_stopped": True}
        )

        def observe(run_id, evidence):
            state.observe(run_id, evidence)
            return True

        value._observe_composition = observe
        value._deployment_child_observed(call, value._deployment_child_generation(call))
        if dirty:
            await value.deployment_child_wake(payload())
        reads = []

        async def control(mode, current, activity_timeout):
            assert mode == "observe" and current is call
            reads.append(mode)
            waiting = unknown or (during_observe and len(reads) == 1)
            if during_observe and len(reads) == 1:
                await value.deployment_child_wake(payload("b" * 64))
            return {
                "ok": True,
                "result": {
                    "scope": state.scope,
                    "manifest": state.manifest,
                    "release_digest": request_release_digest(call["request"], state.manifest),
                    "snapshot": {
                        "run_id": "child",
                        "state": "outcome_unknown" if waiting else "cancelled",
                        "state_revision": len(reads) + 20,
                        "pending": [],
                        "actions": [],
                        "result": None,
                        "error": None,
                    },
                    "budget": {
                        "allowance": 8,
                        "spent": 2,
                        "reserved": 0,
                        "unknown": 1 if waiting else 0,
                        "remaining": 5 if waiting else 6,
                    },
                    "workflow": {
                        "quiescent": not waiting,
                        "remote_stop_confirmed": not waiting,
                        "unknown_remote_execution": waiting,
                        "evidence_ack_pending": False,
                        "reconciliation_pending": waiting,
                    },
                },
            }

        async def wait(predicate, **options):
            assert options == ({} if version == 3 else {"timeout": timedelta(seconds=0.5)})
            if predicate():
                return
            raise SleepReached

        value._control = control
        monkeypatch.setattr(workflow, "wait_condition", wait)
        with pytest.raises(SleepReached):
            await value.run({"activity_timeout": 80})
        assert reads == ["observe"] * expected_reads
        assert call["settled"] is (expected_reads > 0 and not unknown)
        if call["settled"]:
            assert state.budget["reserved"] == state.budget["unknown"] == 0
            assert state.budget["spent"] == 2
        elif unknown:
            assert state.budget["unknown"] == 8
        else:
            assert state.budget["reserved"] == 8

    asyncio.run(scenario())


@pytest.mark.parametrize("legacy", [False, True])
def test_running_control_ledger_does_not_echo_an_observation_back_to_parent(monkeypatch, legacy):
    value = selected_parent(monkeypatch)
    monkeypatch.setattr(workflow, "patched", lambda name: not legacy)
    value.state.state = "running"
    value.state.deployment_calls = {}
    before = value._deployment_notification_token()
    value.state.deployment_calls["observe"] = {
        "identity": {"activity_name": "ralf.temporal.control.v1"},
        "stopped": False,
        "fence_proof": None,
    }
    begun = value._deployment_notification_token()
    value.state.deployment_calls["observe"]["stopped"] = True
    ended = value._deployment_notification_token()
    if legacy:
        assert len({before, begun, ended}) == 3
    else:
        assert before == begun == ended
    value.state.revision += 1
    assert value._deployment_notification_token() != ended


@pytest.mark.parametrize("phase", ["succeeded", "cancelled", "failed", "stopping"])
def test_terminal_or_stopping_control_end_still_notifies_physical_ownership(monkeypatch, phase):
    value = selected_parent(monkeypatch)
    value.state.state = "running" if phase == "stopping" else phase
    value.state.composition_stop_intent = {"reason": "closing"} if phase == "stopping" else None
    value.state.deployment_calls = {
        "observe": {
            "identity": {"activity_name": "ralf.temporal.control.v1"},
            "stopped": False,
            "fence_proof": None,
        }
    }
    before = value._deployment_notification_token()
    value.state.deployment_calls["observe"]["stopped"] = True
    assert value._deployment_notification_token() != before
