"""Original closure excludes unknown credits, handlers and mutable child evidence."""

import copy
import importlib
from types import SimpleNamespace

import pytest

from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.types import digest


def module():
    name = "relf_agent.temporal_deployment_release_state"
    assert importlib.util.find_spec(name), "Original persistent closure authority is missing"
    return importlib.import_module(name)


def original(monkeypatch, *, parent=False):
    from relf_agent import temporal_deployment_execution_state as admission

    manifest = {"deployment_admission_protocol": {"version": 2}}
    state = SimpleNamespace(
        manifest=manifest,
        scope={"workspace": "w", "principal": "p"},
        run_id="original",
        epoch="epoch",
        request={"definition": {"kind": "graph" if parent else "agent"}},
        state="succeeded",
        revision=1,
        reservations={},
        actions=[],
        active_action=None,
        remote_uncertain=False,
        pending_acks=[],
        deferred_acks=[],
        reconcile_requests=[],
        active_reconciliation=None,
        active_evidence_ack=None,
    )
    if parent:
        state.children = []
    proof = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "command_id": "submit",
        "execution_epoch": state.epoch,
        "original_execution_epoch": state.epoch,
        "namespace": {"name": "original", "id": "12345678-1234-5678-1234-567812345678"},
        "request": state.request,
        "request_digest": digest(state.request),
        "manifest": manifest,
        "manifest_digest": digest(manifest),
        "admission": {"version": 1, "root": {"run_id": state.run_id}, "lineage": []},
        "admission_receipt": {"root": {"state": "held-bound", "execution_epoch": state.epoch}},
        "children": getattr(state, "children", []),
    }
    monkeypatch.setattr(admission, "view", lambda current: copy.deepcopy(proof))
    monkeypatch.setattr(admission, "admitted", lambda current: True)
    module().initialize(state)
    return state


def identity(state, *, activity="activity", attempt=1, owner="a" * 32):
    return {
        "version": 1,
        "scope": copy.deepcopy(state.scope),
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "activity_id": activity,
        "activity_name": "business",
        "attempt": attempt,
        "invocation_id": owner,
        "request_digest": "b" * 64,
        "manifest_digest": digest(state.manifest),
    }


def test_public_closure_implementation_is_available():
    assert module()


def test_legacy_initialization_and_guard_preserve_state():
    state = SimpleNamespace(manifest={"deployment_admission_protocol": {"version": 1}})
    before = copy.deepcopy(vars(state))
    module().initialize(state)
    module().check_unsealed(state)
    assert vars(state) == before


def test_pending_admission_remains_readable_but_cannot_begin_or_seal(monkeypatch):
    from relf_agent import temporal_deployment_execution_state as admission

    state = original(monkeypatch)
    monkeypatch.setattr(admission, "admitted", lambda current: False)
    observed = module().view(state)
    assert observed["ready"] is False
    assert "deployment_not_admitted" in observed["reasons"]
    with pytest.raises(DefinitionMismatch):
        module().begin_activity(state, identity(state))
    with pytest.raises(DefinitionMismatch):
        module().seal(state, {"scope": state.scope, "children": []})


def test_live_actual_call_blocks_closure_then_exact_end_is_idempotent(monkeypatch):
    state = original(monkeypatch)
    value = identity(state)
    first = module().begin_activity(state, value)
    assert first["allowed"] is True
    assert module().begin_activity(state, copy.deepcopy(value)) == first
    assert module().closure(state)[0] is False
    with pytest.raises(DefinitionMismatch):
        module().begin_activity(state, identity(state, owner="c" * 32))
    with pytest.raises(DefinitionMismatch):
        module().begin_activity(state, identity(state, attempt=2, owner="c" * 32))
    ended = module().end_activity(state, value)
    assert ended["recorded"] is True
    assert module().end_activity(state, copy.deepcopy(value)) == ended
    assert module().closure(state) == (True, [])
    assert (
        module().begin_activity(state, identity(state, attempt=2, owner="c" * 32))["allowed"]
        is True
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(version=True),
        lambda value: value.update(attempt=True),
        lambda value: value.update(extra="foreign"),
        lambda value: value.update(run_id="foreign"),
        lambda value: value.update(execution_epoch="replacement"),
        lambda value: value.update(request_digest="invalid"),
        lambda value: value.update(invocation_id="foreign"),
        lambda value: value["scope"].update(principal="foreign"),
    ],
)
def test_malformed_call_identity_does_not_enter_ledger(monkeypatch, change):
    state = original(monkeypatch)
    value = identity(state)
    change(value)
    with pytest.raises((DefinitionMismatch, ValidationError)):
        module().begin_activity(state, value)
    assert state.deployment_calls == {}


@pytest.mark.parametrize("status", ["reserved", "unknown"])
def test_zero_value_reservation_is_an_obligation(monkeypatch, status):
    state = original(monkeypatch)
    state.reservations["zero"] = {"id": "zero", "amount": 0, "status": status}
    assert module().closure(state)[0] is False
    with pytest.raises(DefinitionMismatch):
        module().seal(state, {"scope": state.scope, "children": []})
    state.reservations["zero"]["status"] = "settled"
    assert module().closure(state)[0] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "running"),
        ("active_action", "action"),
        ("remote_uncertain", True),
        ("pending_acks", [{}]),
        ("deferred_acks", [{}]),
        ("reconcile_requests", [{}]),
        ("active_reconciliation", "action"),
        ("active_evidence_ack", "action"),
        ("memory_recovery", ["stage"]),
        ("session_recovery", ["stage"]),
        ("tool_executions", {"tool": {"execution_stopped": False}}),
        (
            "context_read_stages",
            {
                "read": {
                    "status": "awaiting_response_and_end",
                    "response_observed": True,
                    "execution_end_proof": None,
                    "fenced": False,
                }
            },
        ),
        (
            "session_stages",
            {"save": {"status": "completed", "write_action": "writer", "execution_stopped": False}},
        ),
        (
            "memory_stages",
            {"facts": {"status": "closed", "facts": [{"status": "outcome_unknown"}]}},
        ),
        ("context_artifact_dispatches", {"artifact": "a" * 64}),
    ],
)
def test_each_original_obligation_blocks_seal(monkeypatch, field, value):
    state = original(monkeypatch)
    setattr(state, field, value)
    assert module().closure(state)[0] is False
    with pytest.raises(DefinitionMismatch):
        module().seal(state, {"scope": state.scope, "children": []})


def test_seal_is_detached_immutable_and_denies_new_dispatch(monkeypatch):
    state = original(monkeypatch)
    payload = {"scope": copy.deepcopy(state.scope), "children": []}
    certificate = module().seal(state, payload)
    assert set(certificate) == {
        "version",
        "scope",
        "run_id",
        "command_id",
        "namespace",
        "execution_epoch",
        "original_execution_epoch",
        "request_digest",
        "manifest_digest",
        "admission_digest",
        "receipt_digest",
        "terminal_state",
        "closure_digest",
        "children",
        "proof_digest",
    }
    assert certificate["proof_digest"] == digest(
        {k: v for k, v in certificate.items() if k != "proof_digest"}
    )
    assert module().seal(state, copy.deepcopy(payload)) == certificate
    with pytest.raises(DefinitionMismatch):
        module().check_unsealed(state)
    with pytest.raises(DefinitionMismatch):
        module().begin_activity(state, identity(state))
    certificate["scope"]["principal"] = "mutated"
    assert state.deployment_seal["scope"] == state.scope
    observed = module().view(state)
    assert set(observed) == {"version", "deployment", "ready", "reasons", "calls", "seal"}
    assert observed["seal"]["scope"] == state.scope


def test_cancelled_undispatched_completion_can_close_without_adopting_output(monkeypatch):
    state = original(monkeypatch)
    state.state = "cancelled"
    state.pending_verification = "model"
    state.completion_stages = {"model": {"status": "prepared", "source": {"output": "retained"}}}
    assert module().closure(state)[0] is True
    module().seal(state, {"scope": state.scope, "children": []})
    assert state.completion_stages["model"]["status"] == "closed"
    assert state.completion_stages["model"]["source"] == {"output": "retained"}
    assert state.pending_verification is None


def test_child_certificate_must_match_original_intent_and_pinned_epoch(monkeypatch):
    state = original(monkeypatch, parent=True)
    call = {
        "id": "0:child",
        "run_id": "child",
        "command_id": "child-command",
        "request": {"input": "child"},
        "deployment_admission": {"root": "original"},
        "deployment_execution_epoch": "child-epoch",
        "dispatch_started": True,
        "started": True,
        "settled": True,
        "state": "succeeded",
    }
    state.children.append(call)
    child = {
        "call_id": call["id"],
        "run_id": call["run_id"],
        "command_id": call["command_id"],
        "execution_epoch": "child-epoch",
        "request_digest": digest(call["request"]),
        "admission_digest": digest(call["deployment_admission"]),
        "seal_digest": "d" * 64,
    }
    for field in ("execution_epoch", "request_digest", "admission_digest", "call_id"):
        bad = {**child, field: "wrong"}
        with pytest.raises((DefinitionMismatch, ValidationError)):
            module().seal(state, {"scope": state.scope, "children": [bad]})
    assert module().seal(state, {"scope": state.scope, "children": [child]})["children"] == [child]


def test_actual_cancelled_completion_stage_seals_without_running_verifier(monkeypatch):
    import asyncio
    from functools import partial

    from relf_agent import DeploymentAdmissionPolicy, TemporalRuntime
    from relf_agent import temporal_deployment_execution_state as admission
    from relf_agent.temporal_deployment_admission import registry_id, root_run_id
    from relf_agent.temporal_state import TemporalRunState
    from tests import test_temporal_completion as fixture

    policy = DeploymentAdmissionPolicy("actual-closure-stage")
    monkeypatch.setattr(
        fixture, "TemporalRuntime", partial(TemporalRuntime, admission_policy=policy)
    )

    async def run():
        runtime, template, provider, verifier = fixture.setup()
        state = TemporalRunState(
            root_run_id(policy.deployment_id, template.scope, "submit"),
            template.scope,
            "submit",
            template.request,
            runtime.manifest,
            "original-epoch",
        )
        root = {
            "version": 1,
            "registry_id": registry_id(policy.deployment_id),
            "scope": state.scope,
            "command_id": "submit",
            "run_id": state.run_id,
            "request_digest": digest(state.request),
            "manifest_digest": digest(state.manifest),
            "namespace": {"name": "original", "id": "12345678-1234-5678-1234-567812345678"},
        }
        root.update(proof_digest=digest(root), state="held-unbound", execution_epoch=None)
        metadata = {"version": 1, "root": root, "lineage": []}
        admission.initialize(
            state,
            metadata,
            namespace="original",
            epoch=state.epoch,
            original_epoch=state.epoch,
            parent=None,
        )
        receipt = {
            "version": 1,
            "run_id": state.run_id,
            "execution_epoch": state.epoch,
            "root": {**root, "state": "held-bound", "execution_epoch": state.epoch},
            "metadata_digest": digest(metadata),
        }
        admission.adopt(state, {**receipt, "proof_digest": digest(receipt)})
        module().initialize(state)
        action, request = state.next_operation()
        if action["kind"] == "context":
            state.accept_context(action["id"], await runtime.prepare_context(request))
            await fixture.model(runtime, state)
        else:
            assert action["kind"] == "model"
            state.accept_model(
                action["id"],
                await runtime.complete_model(
                    request, dispatch_guard=lambda value: fixture.grant(state, value)
                ),
            )
        assert state.pending_verification is not None
        retained = copy.deepcopy(state.completion_stages[state.pending_verification]["source"])
        state.state = "cancelled"  # Same terminal transition as the original deadline.
        assert module().closure(state) == (True, [])
        module().seal(state, {"scope": state.scope, "children": []})
        stage = next(iter(state.completion_stages.values()))
        assert stage["status"] == "closed" and stage["source"] == retained
        assert len(provider.calls) == 1 and verifier.calls == []
        await runtime.close_deployment_execution(wait_timeout=2)

    asyncio.run(run())


def test_uncertain_start_is_never_an_undispatched_child(monkeypatch):
    state = original(monkeypatch, parent=True)
    call = {
        "id": "0:child",
        "run_id": "child",
        "command_id": "child-command",
        "request": {},
        "deployment_admission": {},
        "deployment_execution_epoch": None,
        "dispatch_started": True,
        "started": False,
        "settled": True,
        "state": "cancelled",
        "uncertain": True,
    }
    state.children.append(call)
    child = {
        "call_id": call["id"],
        "run_id": call["run_id"],
        "command_id": call["command_id"],
        "execution_epoch": None,
        "request_digest": digest(call["request"]),
        "admission_digest": digest(call["deployment_admission"]),
        "seal_digest": None,
    }
    with pytest.raises(DefinitionMismatch):
        module().seal(state, {"scope": state.scope, "children": [child]})
    call.update(dispatch_started=False, uncertain=False)
    assert module().seal(state, {"scope": state.scope, "children": [child]})["children"] == [child]
