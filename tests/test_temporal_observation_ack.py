"""An original atomic read may cover hints, never later forced recovery reads."""

import asyncio
import copy

import pytest

from ralf_agent import temporal_coding_composition_state as composition
from ralf_agent import temporal_deployment_control_transport as transport
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow
from tests.test_temporal_coding_observe_validation import environment
from tests.test_temporal_deployment_child_wake import hint, selected_parent


@pytest.mark.parametrize("forced", [False, True])
@pytest.mark.parametrize("ack", [None, "a" * 64, "b" * 64])
@pytest.mark.parametrize("legacy", [False, True])
def test_original_read_ack_covers_only_matching_hints(monkeypatch, forced, ack, legacy):
    async def run():
        value = selected_parent(monkeypatch)
        monkeypatch.setattr(workflow, "patched", lambda name: not legacy)
        call = value.state.children[0]
        generation = value._deployment_child_generation(call)
        force = getattr(value, "_deployment_forced", {}).get(call["run_id"], 0)
        await value.deployment_child_wake(hint(value))
        if forced:
            value._deployment_force_child_reads()
        accepted = value._deployment_child_observed(
            call, generation, acknowledged=ack, forced=force
        )
        assert accepted is (not forced and not legacy and ack == "a" * 64)
        assert value._deployment_child_is_dirty(call) is not accepted
        if accepted:
            # Even a previously observed/preplayed token remains a new hint.
            await value.deployment_child_wake(hint(value))
            assert value._deployment_child_is_dirty(call)

    asyncio.run(run())


def test_atomic_diagnostics_query_uses_acknowledged_hint_without_mutating_history(monkeypatch):
    e = environment(monkeypatch)
    state = e.client.states[e.call["run_id"]]
    value = object.__new__(TemporalRunWorkflow)
    value.state = state
    value._deployment_parent_notified = "a" * 64
    monkeypatch.setattr(value, "_deployment_query_epoch", lambda: None)
    # Query must not call workflow.patched or recompute a newer notification.
    monkeypatch.setattr(workflow, "patched", lambda name: pytest.fail("Query changed History"))
    before = copy.deepcopy(vars(state))
    result = value.view(
        {
            "kind": "diagnostics",
            "scope": state.scope,
            "deployment_child_observation": True,
            "run_id": state.run_id,
            "execution_epoch": state.epoch,
        }
    )
    assert result["deployment_child_observation"] == {
        "acknowledged": "a" * 64,
        "physical_proof": composition.physical_stop_view(state),
    }
    assert vars(state) == before


@pytest.mark.parametrize(
    "field", ["scope", "run_id", "execution_epoch", "deployment_child_observation"]
)
def test_atomic_query_refuses_changed_original_identity(monkeypatch, field):
    e = environment(monkeypatch)
    state = e.client.states[e.call["run_id"]]
    value = object.__new__(TemporalRunWorkflow)
    value.state = state
    monkeypatch.setattr(value, "_deployment_query_epoch", lambda: None)
    query = {
        "kind": "diagnostics",
        "scope": state.scope,
        "deployment_child_observation": True,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
    }
    query[field] = (
        {"workspace": "foreign", "principal": "foreign"} if field == "scope" else "foreign"
    )
    result = value.view(query)
    assert set(result) == {"error"}


@pytest.mark.parametrize("bad", [None, "token", "proof", "revision", "null"])
def test_atomic_proof_is_adopted_and_invalid_carrier_is_rejected(monkeypatch, bad):
    async def run():
        e = environment(monkeypatch)
        original = e.client.get_workflow_handle
        touched = []

        class Port:
            def __init__(self, inner):
                self.inner = inner

            async def describe(self):
                return await self.inner.describe()

            def fetch_history_events(self, **kw):
                return self.inner.fetch_history_events(**kw)

            async def execute_update(self, *a, **kw):
                return await self.inner.execute_update(*a, **kw)

            async def query(self, name, query):
                result = await self.inner.query(name, query)
                if query.get("deployment_child_observation") is True:
                    child = e.client.states[e.call["run_id"]]
                    child._emit("new_original_fact")
                    result = child.diagnostics()
                    proof = composition.physical_stop_view(child)
                    carrier = {"acknowledged": "a" * 64, "physical_proof": proof}
                    if bad == "token":
                        carrier["acknowledged"] = "foreign"
                    elif bad == "proof":
                        proof["execution_epoch"] = "foreign"
                    elif bad == "revision":
                        result["snapshot"]["state_revision"] += 1
                    result["deployment_child_observation"] = None if bad == "null" else carrier
                    touched.append(proof["revision"])
                return result

        def handle(*a, **kw):
            return Port(original(*a, **kw))

        e.client.get_workflow_handle = handle
        operation = transport.execute(
            e.runtime, e.client, transport.request(e.parent, e.call, "observe"), e.info
        )
        if bad is None:
            response = await operation
            assert touched and response["observation"]["parent_notification_ack"] == "a" * 64
            expanded = transport.expand_response(
                e.parent, e.call, {"ok": True, "result": response}
            )["result"]
            assert expanded["coding_composition_proof"]["revision"] == touched[-1]
            assert expanded["snapshot"]["state_revision"] == touched[-1]
        else:
            with pytest.raises(DefinitionMismatch):
                await operation
            assert touched

    asyncio.run(run())


@pytest.mark.parametrize("forced", [False, True])
def test_parent_loop_passes_original_ack_after_adoption(monkeypatch, forced):
    from tests.test_temporal_deployment_parent_wake import SleepReached

    async def run():
        value = selected_parent(monkeypatch)
        call = value.state.children[0]
        reads = []

        async def control(mode, selected, activity_timeout):
            reads.append(mode)
            if len(reads) == 1:
                await value.deployment_child_wake(hint(value))
                if forced:
                    value._deployment_force_child_reads()
            return {"ok": True, "result": {"parent_notification_ack": "a" * 64}}

        async def wait(predicate, **options):
            if predicate():
                return
            raise SleepReached

        value._control = control
        monkeypatch.setattr(workflow, "wait_condition", wait)
        with pytest.raises(SleepReached):
            await value.run({"activity_timeout": 5})
        assert reads == ["observe"] * (2 if forced else 1)
        assert not value._deployment_child_is_dirty(call)

    asyncio.run(run())


@pytest.mark.parametrize("tokens", [("b" * 64, "a" * 64), ("a" * 64, "a" * 64)])
def test_ack_never_consumes_multiple_hints_including_replayed_old_token(monkeypatch, tokens):
    async def run():
        value = selected_parent(monkeypatch)
        call = value.state.children[0]
        generation = value._deployment_child_generation(call)
        value._deployment_observing = {call["run_id"]}
        for token in tokens:
            await value.deployment_child_wake(hint(value, token))
        assert not value._deployment_child_observed(
            call, generation, acknowledged="a" * 64, forced=0
        )
        assert value._deployment_child_is_dirty(call)

    asyncio.run(run())


@pytest.mark.parametrize("ack", [None, "", "A" * 64, False, {}])
@pytest.mark.parametrize("phase", ["pack", "expand"])
def test_compact_notification_ack_is_an_exact_digest(monkeypatch, ack, phase):
    e = environment(monkeypatch)
    child = e.client.states[e.call["run_id"]]
    value = {
        **child.diagnostics(),
        "scope": e.parent.scope,
        "coding_composition_proof": composition.physical_stop_view(child),
    }
    if phase == "pack":
        value["parent_notification_ack"] = ack
        with pytest.raises(DefinitionMismatch):
            transport.pack_response(e.parent, e.call, value)
    else:
        response = transport.pack_response(e.parent, e.call, value)
        response["observation"]["parent_notification_ack"] = ack
        with pytest.raises(DefinitionMismatch):
            transport.expand_response(e.parent, e.call, {"ok": True, "result": response})
