"""Real SDK Parent loop with deterministic History events; no service or business I/O."""

import asyncio
import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")
from relf_agent import temporal_deployment_execution_state as admission
from relf_agent.temporal_parent_workflow import CONTROL_ACTIVITY, TemporalParentWorkflow, workflow
from relf_agent.types import digest


class SleepReached(Exception):
    pass


def parent(monkeypatch, version=2, *, terminal=False):
    """History transport is isolated; use the real actual-call ledger and SDK handlers."""
    manifest = {"kernel": "temporal-1"}
    if version is not None:
        manifest["deployment_admission_protocol"] = {"version": version}
    child = {"run_id": "child", "dispatch_started": True, "settled": False}
    state = SimpleNamespace(
        manifest=manifest,
        scope={"workspace": "wake", "principal": "owner"},
        run_id="parent",
        epoch="parent-epoch",
        request={"definition": {"kind": "graph"}},
        state="succeeded" if terminal else "waiting_approval",
        revision=0,
        policy=SimpleNamespace(run_timeout_seconds=None),
        parent_completion_enabled=False,
        children=[] if terminal else [child],
        stage="execute",
        memory_recovery_revision=0,
        quiescent=terminal,
        children_quiescent=terminal,
        deployment_calls={},
        deployment_seal=None,
        next_session_operation=lambda: None,
        next_parent_completion_operation=lambda: None,
        next_calls=lambda: [],
        observe=lambda *args: None,
    )
    value = object.__new__(TemporalParentWorkflow)
    value.state, value.wake_revision = state, 0

    async def admitted(*args):
        return True

    async def noop(*args):
        pass

    value._ensure_deployment_admission = admitted
    value._notify_session = noop
    value._ensure_deployment_retirement = noop
    monkeypatch.setattr(workflow, "info", lambda: SimpleNamespace(task_queue="original-queue"))
    monkeypatch.setattr(workflow, "patched", lambda name: True)
    monkeypatch.setattr(admission, "view", lambda current: {"scope": current.scope})
    monkeypatch.setattr(admission, "admitted", lambda current: True)
    return value


def identity(parent, index=1):
    state = parent.state
    return {
        "version": 1,
        "scope": copy.deepcopy(state.scope),
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "activity_id": str(index),
        "activity_name": CONTROL_ACTIVITY,
        "attempt": 1,
        "invocation_id": "a" * 32,
        "request_digest": "b" * 64,
        "manifest_digest": digest(state.manifest),
    }


@pytest.mark.parametrize("version", [2, 3])
def test_own_observe_start_and_end_cannot_bypass_half_second_wait(monkeypatch, version):
    async def run():
        value = parent(monkeypatch, version)
        calls = []

        async def activity(name, payload, **options):
            calls.append(name)
            proof = identity(value, len(calls))
            await value.deployment_call_started(proof)
            await value.deployment_call_ended(proof)
            return {"ok": True, "result": {}}

        async def wait(predicate, **options):
            assert options == {"timeout": timedelta(seconds=0.5)}
            assert predicate() is False, "Own mechanical ACKs must not self-wake the polling loop"
            raise SleepReached

        monkeypatch.setattr(workflow, "execute_activity", activity)
        monkeypatch.setattr(workflow, "wait_condition", wait)
        with pytest.raises(SleepReached):
            await value.run({"activity_timeout": 5})
        assert calls == [CONTROL_ACTIVITY]
        assert all(record["stopped"] for record in value.state.deployment_calls.values())

    asyncio.run(run())


@pytest.mark.parametrize("version", [None, 1])
def test_unselected_and_private_parent_keep_original_handler_wakes(monkeypatch, version):
    async def run():
        value = parent(monkeypatch, version)
        proof = identity(value)
        assert await value.deployment_call_started(proof) is None
        assert await value.deployment_call_ended(proof) is None
        assert value.wake_revision == 2

    asyncio.run(run())


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("external", ["cancel", "child-pin", "stop-ack"])
def test_external_business_wake_during_own_activity_is_not_consumed(monkeypatch, version, external):
    async def run():
        value = parent(monkeypatch, version)
        observed = value.wake_revision
        # Pure business adoption ports isolate receipt DTOs from the wake race.
        if external == "cancel":
            value.state.command = lambda *args: {"record_state": "durably_recorded"}
        else:
            from relf_agent import temporal_coding_composition_state as composition

            monkeypatch.setattr(composition, "validate_parent_update", lambda *args: ("child", {}))
            monkeypatch.setattr(
                composition, "pin_child_execution", lambda *args: {"recorded": True}
            )
            monkeypatch.setattr(composition, "adopt_child_stop", lambda *args: {"recorded": True})

        async def activity(*args, **kwargs):
            proof = identity(value)
            await value.deployment_call_started(proof)
            if external == "cancel":
                await value.command(
                    {"command_id": "external-cancel", "payload": {"kind": "cancel"}}
                )
            elif external == "child-pin":
                await value.coding_composition_child_epoch({})
            else:
                await value.coding_composition_child_stopped({})
            await value.deployment_call_ended(proof)
            return {"ok": True, "result": {}}

        monkeypatch.setattr(workflow, "execute_activity", activity)
        await value._control("observe", value.state.children[0], timedelta(seconds=5))
        assert value.wake_revision == observed + 1

    asyncio.run(run())


@pytest.mark.parametrize("version", [2, 3])
def test_first_end_during_retirement_await_wakes_once_without_duplicate_spin(monkeypatch, version):
    async def run():
        value = parent(monkeypatch, version, terminal=True)
        proof = identity(value)
        await value.deployment_call_started(proof)
        attempts, wakes = [], []

        async def retirement(*args):
            attempts.append(True)
            # The verifier observed the pending call before its awaited read.
            # Its end ACK arrives now, before the Parent reaches its wait.
            await value.deployment_call_ended(proof)

        async def wait(predicate, **options):
            assert options == {}
            wakes.append(predicate())
            if len(wakes) == 1:
                assert wakes[-1] is True, "A late end ACK must retry original retirement"
                return
            assert wakes[-1] is False, "The exact duplicate end ACK must not self-wake forever"
            raise SleepReached

        value._ensure_deployment_retirement = retirement
        monkeypatch.setattr(workflow, "wait_condition", wait)
        with pytest.raises(SleepReached):
            await value.run({"activity_timeout": 5})
        assert len(attempts) == 2 and wakes == [True, False]
        assert value.wake_revision == 1
        record = next(iter(value.state.deployment_calls.values()))
        assert record["stopped"] and record["end_proof"] == proof

    asyncio.run(run())


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("physical_stopped", [False, True])
def test_terminal_financial_quiescence_does_not_replace_composition_physical_stop(
    monkeypatch, version, physical_stopped
):
    from relf_agent import temporal_coding_composition_state as composition

    async def run():
        value = parent(monkeypatch, version, terminal=True)
        assert value.state.quiescent
        monkeypatch.setattr(composition, "enabled", lambda manifest: True)
        monkeypatch.setattr(
            composition, "physical_stop_view", lambda state: {"physical_stopped": physical_stopped}
        )
        proof = identity(value)
        await value.deployment_call_started(proof)
        assert value.wake_revision == 0
        await value.deployment_call_ended(proof)
        assert value.wake_revision == int(physical_stopped)
        await value.deployment_call_ended(proof)
        assert value.wake_revision == int(physical_stopped)
        assert next(iter(value.state.deployment_calls.values()))["stopped"] is True

    asyncio.run(run())


def test_sdk_registers_parent_overrides_for_the_original_update_names():
    from relf_agent.temporal_workflow import TemporalRunWorkflow

    definition = workflow._Definition.must_from_class(TemporalParentWorkflow)
    for name in ("deployment_call_started", "deployment_call_ended"):
        assert definition.updates[name].fn is getattr(TemporalParentWorkflow, name)
        assert definition.updates[name].fn is not getattr(TemporalRunWorkflow, name)
