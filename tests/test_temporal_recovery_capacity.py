"""A full public Registry retains bounded, original-root safety controls."""

import copy

import pytest

from ralf_agent.errors import AuthorizationDenied, IdempotencyConflict, ValidationError
from ralf_agent.temporal_state import TemporalCommandRegistryState
from ralf_agent.types import digest
from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY, SCOPE, setup


def full_registry(version=2):
    _, request = setup()
    state = TemporalCommandRegistryState(
        admission_policy=POLICY.identity,
        namespace=NAMESPACE,
        admission_protocol=version,
        capacity=1,
        **({"registry_execution_epoch": "registry-epoch"} if version == 4 else {}),
    )
    root = state.reserve(request)["root_admission"]
    state.bind_deployment_root(
        {
            **{
                k: root[k]
                for k in (
                    "scope",
                    "namespace",
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "admission_policy": POLICY.identity,
            "execution_epoch": "original-root-epoch",
        }
    )
    return state, request


def control(original, kind, command_id):
    return {
        **{k: original[k] for k in ("scope", "target", "admission_policy", "namespace")},
        "kind": kind,
        "command_id": command_id,
        "payload_digest": digest({"scope": SCOPE, "kind": kind}),
    }


def wake_id(request):
    return "drive:" + digest([request["scope"], request["target"]])


@pytest.mark.parametrize("version", [2, 3, 4])
def test_full_public_registry_keeps_original_cancel_and_drive_slots(version):
    state, request = full_registry(version)
    cancelled = state.reserve(control(request, "cancel", "stop-original"))
    driven = state.reserve(control(request, "drive", wake_id(request)))
    assert cancelled == {
        "command_id": "stop-original",
        "target": request["target"],
        "record_state": "durably_recorded",
        "apply_state": "not_applied",
    }
    assert driven["command_id"] == wake_id(request)
    for _ in range(10):
        assert state.reserve(control(request, "cancel", "stop-original")) == cancelled
        assert state.reserve(control(request, "drive", wake_id(request))) == driven
    assert len(state.deployment.commands) == 3
    assert len(state.deployment.roots) == 1
    for kind in ("cancel", "drive", "approve", "reconcile", "send_input", "patch"):
        with pytest.raises(ValidationError, match="capacity"):
            state.reserve(control(request, kind, "different-" + kind))
    fresh = copy.deepcopy(request)
    fresh["command_id"] = "new-submit"
    from ralf_agent.temporal_deployment_admission import root_run_id

    fresh["target"] = root_run_id(POLICY.deployment_id, SCOPE, "new-submit")
    with pytest.raises(ValidationError, match="capacity"):
        state.reserve(fresh)
    assert len(state.deployment.commands) == 3


def test_recovery_slots_do_not_bypass_payload_scope_or_command_identity():
    state, request = full_registry()
    before = copy.deepcopy(vars(state.deployment))
    forged = control(request, "cancel", "forged")
    forged["payload_digest"] = digest({"scope": SCOPE, "kind": "cancel", "extra": True})
    with pytest.raises(ValidationError):
        state.reserve(forged)
    foreign = control(request, "cancel", "foreign")
    foreign["scope"] = {"workspace": "other", "principal": "owner"}
    with pytest.raises(AuthorizationDenied):
        state.reserve(foreign)
    assert vars(state.deployment) == before
    state.reserve(control(request, "cancel", "stop-original"))
    before = copy.deepcopy(vars(state.deployment))
    with pytest.raises(IdempotencyConflict):
        state.reserve(control(request, "drive", "stop-original"))
    assert vars(state.deployment) == before


def test_recovery_identity_is_discoverable_only_in_its_scope_and_survives_retirement():
    state, request = full_registry()
    stopped = state.reserve(control(request, "cancel", "stop-original"))
    query = {
        "kind": "deployment_admission",
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
    }
    expected = [
        {
            "run_id": request["target"],
            "execution_epoch": "original-root-epoch",
            "kind": "cancel",
            "command_id": "stop-original",
        }
    ]
    assert state.deployment_admission(query)["recovery_controls"] == expected
    foreign = {**query, "scope": {"workspace": "other", "principal": "owner"}}
    assert state.deployment_admission(foreign).get("recovery_controls", []) == []
    # Model only an already verified retirement to isolate post-retirement
    # command behavior; the real retirement proof tests remain separate.
    state.deployment.roots.clear()
    assert state.reserve(control(request, "cancel", "stop-original")) == stopped
    with pytest.raises(AuthorizationDenied):
        state.reserve(control(request, "drive", "fresh-after-retirement"))
    assert len(state.deployment.commands) == 2


def test_unbound_root_cannot_use_recovery_allowance():
    _, request = setup()
    state = TemporalCommandRegistryState(
        admission_policy=POLICY.identity,
        namespace=NAMESPACE,
        admission_protocol=2,
        capacity=1,
    )
    state.reserve(request)
    with pytest.raises(ValidationError):
        state.reserve(control(request, "cancel", "not-running"))
    assert len(state.deployment.commands) == 1


def test_old_command_collision_keeps_original_and_offers_one_reusable_drive_hint():
    state, request = full_registry()
    state.deployment.capacity = 2
    original = state.reserve(control(request, "cancel", wake_id(request)))
    query = {
        "kind": "deployment_admission",
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
    }
    before = copy.deepcopy(vars(state.deployment))
    hint = state.deployment_admission(query)["recovery_drive_hints"][0]
    assert vars(state.deployment) == before
    assert hint["run_id"] == request["target"] and hint["execution_epoch"] == "original-root-epoch"
    assert hint["command_id"] != wake_id(request) and hint["durable"] is False
    with pytest.raises(IdempotencyConflict):
        state.reserve(control(request, "drive", wake_id(request)))
    first = state.reserve(control(request, "drive", hint["command_id"]))
    for _ in range(3):
        assert state.reserve(control(request, "drive", hint["command_id"])) == first
    assert state.reserve(control(request, "cancel", wake_id(request))) == original
    assert len(state.deployment.commands) == 3
    assert state.deployment_admission(query)["recovery_drive_hints"][0] == hint
    foreign = {**query, "scope": {"workspace": "other", "principal": "owner"}}
    assert state.deployment_admission(foreign).get("recovery_drive_hints", []) == []


@pytest.mark.parametrize("collision", [False, True])
def test_public_drive_reuses_identity_but_each_update_wakes_original_history(
    monkeypatch, collision
):
    import asyncio
    from types import SimpleNamespace

    pytest.importorskip("temporalio")
    from ralf_agent import Scope
    from ralf_agent.temporal import TemporalEngine
    from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow
    from ralf_agent.types import CommandReceipt

    state, request = full_registry()
    if collision:
        state.deployment.capacity = 2
        state.reserve(control(request, "cancel", wake_id(request)))
    envelope = request["root_admission"]["submission"]
    root = copy.deepcopy(
        state.deployment.submissions[digest([SCOPE, "one"])]["reservation"]["root_admission"]
    )
    monkeypatch.setattr(
        workflow,
        "info",
        lambda: SimpleNamespace(
            workflow_id=request["target"],
            run_id="original-root-epoch",
            original_execution_run_id="original-root-epoch",
            namespace=NAMESPACE["name"],
            task_queue=envelope["task_queue"],
            parent=None,
        ),
    )
    node = TemporalRunWorkflow(
        {
            "scope": SCOPE,
            "command_id": "one",
            "request": envelope["request"],
            "manifest": envelope["manifest"],
            "activity_timeout": 30,
            "deployment_admission": {"version": 1, "root": root, "lineage": []},
        }
    )
    assert node._deployment_initialization_error is None

    class Transport(TemporalEngine):
        # Only SDK transport is replaced. Registry, original Run state,
        # command acceptance, retry logic and Workflow wake all remain real.
        def __init__(self):
            self._release = envelope["manifest"]
            self.scope, self.drive_timeout = Scope(**SCOPE), 0

        async def _view(self, run_id, kind, **fields):
            assert run_id == request["target"]
            return node.view({"scope": SCOPE, "kind": kind, **fields})

        async def _command(self, run_id, kind, command_id, **values):
            assert values == {} and run_id == request["target"]
            state.reserve(control(request, kind, command_id))
            return CommandReceipt(
                **await node.command(
                    {
                        "command_id": command_id,
                        "payload": {"scope": SCOPE, "kind": kind},
                    }
                )
            )

        async def deployment_diagnostics(self):
            return state.deployment_admission(
                {
                    "kind": "deployment_admission",
                    "scope": SCOPE,
                    "admission_policy": POLICY.identity,
                    "namespace": NAMESPACE,
                }
            )

    async def run():
        client = Transport()
        for _ in range(5):
            await client.drive(request["target"], wait_seconds=0)
        assert node.wake_revision == 5
        assert len(state.deployment.commands) == (3 if collision else 2)
        assert len([e for e in node.state.event_log if e["kind"] == "command_recorded"]) == 1
        first = await client.cancel(request["target"], command_id="stop-from-sdk")
        assert await client.cancel(request["target"], command_id="stop-from-sdk") == first
        assert node.state.state == "cancelled"
        await client.drive(request["target"], wait_seconds=0)

    asyncio.run(run())
    assert node.wake_revision == 8
    assert len(state.deployment.commands) == (4 if collision else 3)
    assert len([e for e in node.state.event_log if e["kind"] == "command_recorded"]) == 2
    assert node.state.state == "cancelled"
    assert len(node.state.actions) == 0


@pytest.mark.parametrize("sealed", [False, True])
def test_repeated_public_parent_wake_rechecks_children_without_reopening_business(sealed):
    import asyncio

    pytest.importorskip("temporalio")
    from ralf_agent.temporal_parent_state import TemporalParentState
    from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow
    from tests.test_temporal_deployment_control_projection import add_child, original

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
    child = add_child(state)
    value = object.__new__(TemporalParentWorkflow)
    value.state, value.wake_revision = state, 0
    payload = {"command_id": "wake-original", "payload": {"scope": state.scope, "kind": "drive"}}

    async def run():
        first = await value.command(payload)
        generation = value._deployment_child_generation(child)
        value._deployment_child_observed(child, generation)
        before = state.memory_recovery_revision
        state.state = "cancelling"
        state.composition_stop_intent = {"terminal_state": "cancelled"}
        if sealed:
            # The original duplicate is read before seal validation. This
            # marker isolates the handler's no-new-recovery-after-seal guard.
            state.deployment_seal = {"original_seal": "present"}
        assert await value.command(payload) == first
        assert value._deployment_child_is_dirty(child) is (not sealed)
        assert state.memory_recovery_revision == before + (0 if sealed else 1)
        assert state.state == "cancelling" and state.composition_stop_intent is not None
        assert value.wake_revision == 2

    asyncio.run(run())
