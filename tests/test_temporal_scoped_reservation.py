"""Default scoped reservations retain one bounded original-target cancellation."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent.errors import RalfError, ValidationError
from ralf_agent.temporal_state import TemporalCommandRegistryState
from ralf_agent.types import digest

SCOPE = {"workspace": "scoped", "principal": "owner"}


def request(kind="submit", command_id="original", target="original-run"):
    return {
        "scope": SCOPE,
        "kind": kind,
        "command_id": command_id,
        "target": target,
        "payload_digest": digest({"scope": SCOPE, "kind": kind}),
    }


def test_full_scoped_registry_keeps_exact_original_cancel_and_one_slot():
    state = TemporalCommandRegistryState(SCOPE, capacity=1)
    state.reserve(request())
    cancel = request("cancel", "stop")
    first = state.reserve(cancel)
    assert state.reserve(cancel) == first and len(state.identities) == 2
    for other in (
        request("cancel", "fresh"),
        request("drive", "wake"),
        request("submit", "next"),
        {**cancel, "command_id": "changed", "payload_digest": "a" * 64},
        request("cancel", "foreign", "another-run"),
    ):
        before = copy.deepcopy(vars(state))
        with pytest.raises(RalfError):
            state.reserve(other)
        assert vars(state) == before
    with pytest.raises(RalfError):
        state.reserve({**cancel, "kind": "drive"})


def test_unregistered_and_cross_scope_cannot_claim_cancellation_allowance():
    state = TemporalCommandRegistryState(SCOPE, capacity=1)
    state.reserve(request("drive", "fill"))
    with pytest.raises(ValidationError):
        state.reserve(request("cancel", "stop"))
    with pytest.raises(RalfError):
        state.reserve({**request("cancel", "stop"), "scope": {**SCOPE, "principal": "foreign"}})
    assert len(state.identities) == 1


def owner():
    state = TemporalCommandRegistryState(SCOPE, capacity=1)
    info = SimpleNamespace(
        workflow_id="ralf-temporal-commands-" + digest(SCOPE),
        run_id="epoch",
        first_execution_run_id="epoch",
        original_execution_run_id="epoch",
        namespace="default",
    )
    return SimpleNamespace(commands=state), info


def envelope(value=None):
    return {
        "kind": "scoped_reserve_receipt",
        "scope": SCOPE,
        "namespace": "default",
        "execution_epoch": None,
        "observation_id": "observe",
        "request": value or request(),
    }


def test_signal_delivery_is_not_acceptance_and_observations_never_evict_commands():
    from ralf_agent.temporal_scoped_reservation import accept, observe

    host, info = owner()
    value = envelope()
    initial = observe(host, value, info)
    assert initial["result"] is None and initial["execution_epoch"] == "epoch"
    initial["scope"]["principal"] = "mutated-client-copy"
    assert host.commands.scope == SCOPE
    value["execution_epoch"] = "epoch"
    accept(host, value, info)
    assert observe(host, value, info)["result"]["ok"] is True
    for i in range(70):
        attempt = {**value, "observation_id": str(i)}
        accept(host, attempt, info)
    assert len(host._scoped_reserve_observations) == 64 and len(host.commands.identities) == 1
    assert observe(host, value, info)["result"] is None
    assert host.commands.reserve(request())["record_state"] == "durably_recorded"


@pytest.mark.parametrize(
    "fault", ["scope", "namespace", "epoch", "reset", "payload", "unbound-signal"]
)
def test_invalid_observations_and_signals_do_not_mutate_identity_or_cache(fault):
    from ralf_agent.temporal_scoped_reservation import accept, observe

    host, info = owner()
    value = envelope()
    value["execution_epoch"] = "epoch"
    if fault == "scope":
        value["scope"] = {**SCOPE, "principal": "foreign"}
    elif fault == "namespace":
        value["namespace"] = "foreign"
    elif fault == "epoch":
        value["execution_epoch"] = "foreign"
    elif fault == "reset":
        info.first_execution_run_id = "before-reset"
    elif fault == "payload":
        value["request"] = {**request(), "scope": {**SCOPE, "principal": "foreign"}}
    elif fault == "unbound-signal":
        value["execution_epoch"] = None
    accept(host, value, info)
    assert not host.commands.identities and not getattr(host, "_scoped_reserve_observations", {})
    if fault != "unbound-signal":
        with pytest.raises(RalfError):
            observe(host, value, info)


def test_client_confirms_old_worker_before_update_and_never_falls_back_after_signal():
    from ralf_agent.temporal_scoped_reservation import reserve

    class Handle:
        def __init__(self, legacy=False):
            self.legacy, self.signals, self.updates = legacy, 0, 0

        async def query(self, name, value):
            if self.legacy:
                return {"scope": SCOPE, "capacity": 4096, "accepted_commands": 0}
            return {
                "version": 1,
                "scope": SCOPE,
                "namespace": "default",
                "execution_epoch": "epoch",
                "observation_id": value["observation_id"],
                "request_digest": digest(value["request"]),
                "result": None,
            }

        async def execute_update(self, name, value):
            self.updates += 1
            return {
                "command_id": value["command_id"],
                "target": value["target"],
                "record_state": "durably_recorded",
                "apply_state": "not_applied",
            }

        async def signal(self, name, value):
            self.signals += 1
            raise TimeoutError("delivery outcome unknown")

    async def run():
        old = Handle(legacy=True)
        assert (await reserve(old, request(), namespace="default"))[
            "record_state"
        ] == "durably_recorded"
        assert old.updates == 1 and old.signals == 0
        current = Handle()
        with pytest.raises(TimeoutError):
            await reserve(current, request(), namespace="default")
        assert current.signals == 1 and current.updates == 0

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["bool-capacity", "extra", "scope", "unknown"])
def test_client_does_not_guess_legacy_capability_from_invalid_response(fault):
    from ralf_agent.temporal_scoped_reservation import reserve

    class Handle:
        writes = 0

        async def query(self, name, value):
            result = {"scope": copy.deepcopy(SCOPE), "capacity": 4096, "accepted_commands": 0}
            if fault == "bool-capacity":
                result["capacity"] = True
            elif fault == "extra":
                result["extra"] = True
            elif fault == "scope":
                result["scope"]["principal"] = "foreign"
            elif fault == "unknown":
                result = None
            return result

        async def signal(self, *args):
            self.writes += 1

        async def execute_update(self, *args):
            self.writes += 1

    async def run():
        handle = Handle()
        with pytest.raises(RalfError):
            await reserve(handle, request(), namespace="default")
        assert handle.writes == 0

    asyncio.run(run())


def test_current_transport_waiter_cancellation_does_not_undo_actual_reservation():
    from ralf_agent.temporal_scoped_reservation import accept, observe, reserve

    host, info = owner()
    sent = asyncio.Event()

    class Handle:
        updates = 0

        async def query(self, name, value):
            if sent.is_set():
                await asyncio.Event().wait()
            return observe(host, value, info)

        async def signal(self, name, value):
            accept(host, value, info)
            sent.set()

        async def execute_update(self, *args):
            self.updates += 1

    async def run():
        handle = Handle()
        task = asyncio.create_task(reserve(handle, request(), namespace="default"))
        await sent.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert handle.updates == 0 and len(host.commands.identities) == 1
        assert host.commands.reserve(request())["record_state"] == "durably_recorded"

    asyncio.run(run())


def test_protection_is_bounded_by_original_submit_targets_and_global_identity_first():
    state = TemporalCommandRegistryState(SCOPE, capacity=2)
    state.reserve(request(command_id="one", target="one"))
    state.reserve(request(command_id="two", target="two"))
    for target in ("one", "two"):
        state.reserve(request("cancel", "stop:" + target, target))
    assert len(state.identities) == 4 and len(state.scoped_cancellations) == 2
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        state.reserve(request("cancel", "one", "one"))
    assert vars(state) == before


@pytest.mark.parametrize("kind", ["session_open", "session_submit", "session_rebind"])
def test_existing_session_guard_preserves_update_transport(kind):
    from ralf_agent import Scope
    from ralf_agent.temporal import TemporalEngine

    state = TemporalCommandRegistryState(SCOPE)

    class Handle:
        updates = 0

        async def query(self, *args):
            pytest.fail("existing Session reservations must retain their Update contract")

        async def signal(self, *args):
            pytest.fail("Run reservation transport must not capture Session commands")

        async def execute_update(self, name, value):
            assert name == "reserve"
            self.updates += 1
            return state.reserve(value)

    async def run():
        engine = object.__new__(TemporalEngine)
        engine._release, engine._closed = {}, False
        engine.scope, engine.client = Scope(**SCOPE), SimpleNamespace(namespace="default")
        engine._registry = Handle()
        payload = {"kind": kind, "scope": SCOPE}
        await engine._guard(kind, "original", "session-target", payload)
        await engine._guard(kind, "original", "session-target", payload)
        assert engine._registry.updates == 2 and len(state.identities) == 1

    asyncio.run(run())
