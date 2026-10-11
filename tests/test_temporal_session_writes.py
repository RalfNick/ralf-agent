import asyncio
import copy
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, InMemoryMemory, Scope, ToolRegistry
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request

from .test_temporal_binding_isolation import advance
from .test_temporal_facts import Provider
from .test_temporal_memory_bindings import grant


def setup(*, backend=None, writes=True):
    source = backend if backend is not None else InMemoryMemory(backend_id="original")
    provider = Provider()
    runtime = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        session_store=source,
        session_writes=writes,
    )
    state = TemporalRunState(
        "run",
        asdict(Scope()),
        "c",
        submission_request(AgentSpec("a", "Answer"), "task"),
        runtime.manifest,
    )
    return runtime, state, source, provider


async def until_save(runtime, state):
    await advance(runtime, state)
    await advance(runtime, state)
    assert state.state != "succeeded", "model result cannot precede required save"
    action, request = state.next_operation()
    assert action["kind"] == "managed_session" and request["phase"] == "inspect"
    return action, request


async def save_step(runtime, state):
    action, request = state.next_operation()
    result = await runtime.manage_session(
        request, dispatch_guard=lambda request: grant(state, request)
    )
    state.accept_session(action["id"], result)
    return action, request, result


def test_unknown_save_blocks_automatic_model_dispatch_until_explicit_recovery():
    async def run():
        runtime, state, _, provider = setup()
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        action, request = state.next_operation()
        await grant(state, request)
        state.accept_session(
            action["id"],
            {
                "ok": False,
                "dispatched": True,
                "execution_stopped": False,
                "code": "activity_outcome_unknown",
            },
        )
        assert state.state == "waiting_reconciliation"
        assert state.next_operation() is None
        assert len(provider.messages) == 1
        await runtime.close_session_execution()

    asyncio.run(run())


def test_write_protocol_is_explicit_and_default_read_only_stays_unchanged():
    runtime, state, _, _ = setup(writes=False)
    assert "session_save_protocol" not in runtime.manifest
    assert not runtime.capabilities["external_session_store"]
    asyncio.run(advance(runtime, state))
    asyncio.run(advance(runtime, state))
    assert state.state == "succeeded"


@pytest.mark.parametrize("invalid", ["invalid_hash", "missing_resource", "extra_resource"])
def test_save_protocol_requires_exact_original_dataset_catalog(invalid):
    from ralf_agent.temporal_state import validate_manifest

    runtime, _, _, _ = setup()
    manifest = runtime.manifest
    policy = manifest["session_save_protocol"]
    key = next(iter(policy["dataset_ids"]))
    if invalid == "invalid_hash":
        policy["dataset_ids"][key] = "X" * 64
    elif invalid == "missing_resource":
        value = policy["dataset_ids"].pop(key)
        ports = policy["dataset_ports"].pop(key)
        policy["dataset_ids"]["0" * 64] = value
        policy["dataset_ports"]["0" * 64] = ports
    else:
        policy["dataset_ids"]["0" * 64] = policy["dataset_ids"][key]
        policy["dataset_ports"]["0" * 64] = policy["dataset_ports"][key]
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)


@pytest.mark.parametrize("writes", [True, 0, "yes"])
def test_writes_require_an_explicit_boolean_and_registered_source(writes):
    with pytest.raises(ValidationError):
        TemporalRuntime(
            providers={"default": Provider()}, tools=ToolRegistry(), session_writes=writes
        )


def test_success_waits_for_received_receipt_and_independent_adoption():
    async def run():
        runtime, state, source, provider = setup()
        action, request = await until_save(runtime, state)
        intent = copy.deepcopy(state.session_stages["0"]["intent"])
        state.accept_session(action["id"], await runtime.manage_session(request))
        assert state.session_stages["0"]["phase"] == "session-write"
        await save_step(runtime, state)
        assert state.state != "succeeded" and len(provider.messages) == 1
        await save_step(runtime, state)
        assert state.session_stages["0"]["phase"] == "adopt"
        assert state.state != "succeeded"
        restored = copy.deepcopy(state)
        await save_step(runtime, restored)
        assert restored.state == "succeeded" and restored.quiescent
        assert (
            source.inspect_message(Scope(), intent["address"], intent["message_id"])["receipt"][
                "message"
            ]
            == intent["message"]
        )
        assert len(source.read(Scope(), intent["address"])[1]) == 1
        assert len(provider.messages) == 1

    asyncio.run(run())


@pytest.mark.parametrize("damage", ["scope", "address", "message", "revision"])
def test_received_save_evidence_cannot_advance_another_original_intent(damage):
    async def run():
        runtime, state, _, _ = setup()
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        await save_step(runtime, state)
        action, request = state.next_operation()
        result = await runtime.manage_session(request)
        assert result["ok"]
        if damage == "scope":
            result["inspection"]["scope"]["principal"] = "other"
        elif damage == "address":
            result["inspection"]["session_id"] = "other"
        elif damage == "revision":
            result["inspection"]["receipt"]["revision"] = 99
        else:
            result["inspection"]["receipt"]["message"]["content"] = "forged"
        state.accept_session(action["id"], result)
        assert state.state != "succeeded" and state.budget["unknown"] > 0

    asyncio.run(run())


def test_replacing_write_source_before_dispatch_does_not_write():
    async def run():
        runtime, state, source, _ = setup()
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        action, request = state.next_operation()
        runtime.session_store = InMemoryMemory(backend_id="original")
        result = await runtime.manage_session(
            request, dispatch_guard=lambda request: grant(state, request)
        )
        assert not result["ok"] and not result["dispatched"]
        assert source.read(Scope(), request["intent"]["address"])[0] == 0

    asyncio.run(run())


def test_committed_record_with_lost_ack_recovers_without_model_or_append_repeat():
    class LostAck(InMemoryMemory):
        def append(self, *args, **kwargs):
            super().append(*args, **kwargs)
            raise OSError("reply lost after commit")

    async def run():
        runtime, state, source, provider = setup(backend=LostAck())
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        _, _, failure = await save_step(runtime, state)
        assert not failure["ok"] and failure["execution_stopped"]
        assert state.state == "waiting_reconciliation"
        state.retry_blocked()
        await save_step(runtime, state)
        await save_step(runtime, state)
        assert state.state == "succeeded" and state.quiescent
        intent = state.session_stages["0"]["intent"]
        assert source.read(Scope(), intent["address"])[0] == 1
        assert len(provider.messages) == 1

    asyncio.run(run())


def test_receipt_does_not_release_unknown_actual_execution_until_original_end_proof():
    async def run():
        runtime, state, _, provider = setup()
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        action, request = state.next_operation()
        actual = await runtime.manage_session(
            request, dispatch_guard=lambda request: grant(state, request)
        )
        assert actual["ok"]
        # Temporal lost the original Activity reply; the handler may still be active.
        state.accept_session(
            action["id"], {"ok": False, "dispatched": True, "code": "activity_outcome_unknown"}
        )
        state.retry_blocked()
        await save_step(runtime, state)
        await save_step(runtime, state)
        assert state.state == "waiting_reconciliation" and not state.quiescent
        assert state.budget["unknown"] == 1 and len(provider.messages) == 1
        proof = {
            "scope": state.scope,
            "action_id": action["id"],
            "request_digest": action["request_digest"],
            "release_digest": state.release_digest,
        }
        with pytest.raises(DefinitionMismatch):
            state.session_execution_ended({**proof, "request_digest": "other"})
        state.session_execution_ended(proof)
        state.retry_blocked()
        await save_step(runtime, state)
        await save_step(runtime, state)
        assert state.state == "succeeded" and state.quiescent and len(provider.messages) == 1

    asyncio.run(run())


def test_cancelled_save_can_settle_late_receipt_without_turning_into_success():
    async def run():
        runtime, state, source, provider = setup()
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        await save_step(runtime, state)
        state.command("cancel", {"kind": "cancel", "scope": state.scope})
        await save_step(runtime, state)
        await save_step(runtime, state)
        assert state.state == "cancelled" and state.quiescent
        assert len(provider.messages) == 1
        intent = state.session_stages["0"]["intent"]
        assert source.read(Scope(), intent["address"])[0] == 1

    asyncio.run(run())


def test_missing_record_can_retry_same_intent_only_after_actual_handler_ended():
    class FailOnce(InMemoryMemory):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def append(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise OSError("stopped before commit")
            return super().append(*args, **kwargs)

    async def run():
        runtime, state, source, provider = setup(backend=FailOnce())
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        await save_step(runtime, state)
        state.retry_blocked()
        await save_step(runtime, state)
        assert state.session_stages["0"]["phase"] == "session-write"
        await save_step(runtime, state)
        await save_step(runtime, state)
        await save_step(runtime, state)
        assert state.state == "succeeded" and state.quiescent
        assert source.calls == 2 and len(provider.messages) == 1
        assert state.budget["spent"] == 3 and state.budget["unknown"] == 0

    asyncio.run(run())


def test_late_end_from_previous_node_does_not_clear_new_model_uncertainty():
    from ralf_agent import WorkflowSpec

    async def run():
        runtime, _, _, _ = setup()
        spec = WorkflowSpec("s", [AgentSpec("a", "Answer"), AgentSpec("b", "Answer")])
        state = TemporalRunState(
            "run", asdict(Scope()), "c", submission_request(spec, "task"), runtime.manifest
        )
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        write, _, _ = await save_step(runtime, state)
        await save_step(runtime, state)
        await save_step(runtime, state)
        assert state.node == 1
        await advance(runtime, state)
        model, _ = state.next_operation()
        assert model["kind"] == "model"
        state.operation_unknown(model["id"], "activity_outcome_unknown")
        state.session_execution_ended(
            {
                "scope": state.scope,
                "action_id": write["id"],
                "request_digest": write["request_digest"],
                "release_digest": state.release_digest,
            }
        )
        assert state.remote_uncertain and not state.quiescent

    asyncio.run(run())


def test_distinct_original_execution_epochs_do_not_share_data_effect_ids():
    async def run():
        runtime, _, _, _ = setup()
        intents = []
        for epoch in ("first-execution", "second-execution"):
            state = TemporalRunState(
                "run",
                asdict(Scope()),
                "c",
                submission_request(AgentSpec("a", "Answer"), "task"),
                runtime.manifest,
                epoch,
            )
            await until_save(runtime, state)
            intents.append(state.session_stages["0"]["intent"])
        assert intents[0]["message_id"] != intents[1]["message_id"]

    asyncio.run(run())


def test_actual_execution_owner_replacement_refused_before_dispatch():
    from ralf_agent.temporal_session_execution import SessionExecutionOwner

    runtime, _, _, _ = setup()
    runtime.session_execution = SessionExecutionOwner()
    with pytest.raises(DefinitionMismatch):
        runtime.validate_release()


def test_cancelled_stopped_save_with_no_record_settles_without_retrying_write():
    class NoCommit(InMemoryMemory):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def append(self, *args, **kwargs):
            self.calls += 1
            raise OSError("handler stopped before commit")

    async def run():
        runtime, state, source, provider = setup(backend=NoCommit())
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        await save_step(runtime, state)
        assert state.session_stages["0"]["execution_stopped"]
        state.command("cancel", {"kind": "cancel", "scope": state.scope})
        state.retry_blocked()
        await save_step(runtime, state)
        assert state.state == "cancelled" and state.quiescent
        assert state.budget["unknown"] == state.budget["reserved"] == 0
        assert source.calls == len(provider.messages) == 1
        assert state.next_operation() is None
        await runtime.close_session_execution()

    asyncio.run(run())


def test_first_inspection_failure_recovers_original_inspect_and_completes_once():
    class TransientInspect(InMemoryMemory):
        def __init__(self):
            super().__init__()
            self.inspections = 0

        def inspect_message(self, *args, **kwargs):
            self.inspections += 1
            if self.inspections == 1:
                raise OSError("transient initial read error")
            return super().inspect_message(*args, **kwargs)

    async def run():
        runtime, state, source, provider = setup(backend=TransientInspect())
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        assert state.state == "waiting_reconciliation"
        state.retry_blocked()
        _, request, _ = await save_step(runtime, state)
        assert request["phase"] == "inspect"
        for _ in range(3):
            await save_step(runtime, state)
        assert state.state == "succeeded" and state.quiescent
        intent = state.session_stages["0"]["intent"]
        assert source.read(Scope(), intent["address"])[0] == len(provider.messages) == 1
        await runtime.close_session_execution()

    asyncio.run(run())


def test_late_end_of_previous_attempt_is_acknowledged_without_stopping_current_write():
    class FailOnce(InMemoryMemory):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def append(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise OSError("original attempt stopped without a record")
            return super().append(*args, **kwargs)

    async def run():
        runtime, state, _, _ = setup(backend=FailOnce())
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        old, old_request, _ = await save_step(runtime, state)
        state.retry_blocked()
        await save_step(runtime, state)
        current, current_request = state.next_operation()
        await grant(state, current_request)
        state.accept_session(
            current["id"],
            {
                "ok": False,
                "dispatched": True,
                "execution_stopped": False,
                "code": "activity_outcome_unknown",
            },
        )
        proof = {k: old_request[k] for k in ("scope", "action_id", "release_digest")}
        proof["request_digest"] = old["request_digest"]
        assert state.session_execution_ended(proof)["execution_stopped"]
        assert state.session_execution_ended(proof)["execution_stopped"]
        assert not state.session_stages["0"]["execution_stopped"]
        assert state.remote_uncertain and state.budget["unknown"] == 1
        await runtime.close_session_execution()

    asyncio.run(run())


def test_oversized_received_inspection_is_rejected_before_activity_result():
    from dataclasses import asdict

    from ralf_agent.types import canonical

    class Oversized(InMemoryMemory):
        def inspect_message(self, scope, address, message_id):
            return {
                "scope": asdict(scope),
                "session_id": address,
                "message_id": message_id,
                "revision": 1,
                "receipt": {"revision": 1, "message": {"content": "X" * (3 * 1024 * 1024)}},
            }

    async def run():
        runtime, state, _, provider = setup(backend=Oversized())
        action, request = await until_save(runtime, state)
        response = await runtime.manage_session(request)
        assert not response["ok"]
        assert len(canonical(response)) < 1024
        state.accept_session(action["id"], response)
        assert state.state == "waiting_reconciliation" and len(provider.messages) == 1
        await runtime.close_session_execution()

    asyncio.run(run())


@pytest.mark.parametrize("cancelled", [False, True])
def test_timeout_before_admission_fences_late_dispatch_and_recovers_no_effect(cancelled):
    async def run():
        runtime, state, source, provider = setup()
        action, request = await until_save(runtime, state)
        state.accept_session(action["id"], await runtime.manage_session(request))
        original, original_request = state.next_operation()
        # Actual Activity never received History admission, so cannot call append.
        state.accept_session(
            original["id"],
            {
                "ok": False,
                "dispatched": True,
                "execution_stopped": False,
                "code": "activity_outcome_unknown",
            },
        )
        assert not (await grant(state, original_request))["allowed"]
        if cancelled:
            state.command("cancel", {"kind": "cancel", "scope": state.scope})
        state.retry_blocked()
        await save_step(runtime, state)
        if cancelled:
            assert state.quiescent and state.state == "cancelled"
            assert state.budget["spent"] == 1
        else:
            for _ in range(3):
                await save_step(runtime, state)
            assert state.quiescent and state.state == "succeeded"
            assert state.budget["spent"] == 2
        assert state.budget["unknown"] == state.budget["reserved"] == 0
        assert not (await grant(state, original_request))["allowed"]
        intent = state.session_stages["0"]["intent"]
        assert source.read(Scope(), intent["address"])[0] == (0 if cancelled else 1)
        assert len(provider.messages) == 1
        await runtime.close_session_execution()

    asyncio.run(run())
