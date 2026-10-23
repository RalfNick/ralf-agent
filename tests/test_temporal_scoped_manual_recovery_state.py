"""Only verified original Actions gain a bounded scoped manual reservation."""

import copy
from importlib import import_module
from types import SimpleNamespace

import pytest

from relf_agent.errors import IdempotencyConflict, RalfError
from relf_agent.temporal_state import TemporalCommandRegistryState
from relf_agent.types import digest

SCOPE = {"workspace": "manual-scoped", "principal": "owner"}
NAMESPACE = {"name": "default", "id": "11111111-1111-1111-1111-111111111111"}
TARGET = "ralf-temporal-" + digest([SCOPE, "original"])


def api():
    return import_module("relf_agent.temporal_scoped_manual_recovery")


def original_state(*, capacity=1):
    state = TemporalCommandRegistryState(SCOPE, capacity=capacity)
    original = {
        "scope": SCOPE,
        "command_id": "original",
        "kind": "submit",
        "target": TARGET,
        "payload_digest": digest({"definition": "original", "input": "task"}),
    }
    state.reserve(original)
    return state, original


def manual_request(*, command_id="confirm", action_id="original-action", result="confirmed"):
    payload = {
        "kind": "reconcile",
        "scope": copy.deepcopy(SCOPE),
        "action_id": action_id,
        "query": False,
        "result": result,
    }
    return {
        "scope": copy.deepcopy(SCOPE),
        "command_id": command_id,
        "kind": "reconcile",
        "target": TARGET,
        "payload_digest": digest(payload),
        "recovery": {
            "version": 1,
            "registry_execution_epoch": "registry-epoch",
            "namespace": "default",
            "payload": payload,
        },
    }


def verified(prepared, request, *, epoch="original-epoch", started=None):
    body = {
        "version": 1,
        "scope": copy.deepcopy(SCOPE),
        "namespace": copy.deepcopy(NAMESPACE),
        "registry_execution_epoch": "registry-epoch",
        "target": TARGET,
        "execution_epoch": epoch,
        "submission_digest": digest(prepared["submission"]),
        "action_id": request["recovery"]["payload"]["action_id"],
        "action_digest": "a" * 64,
        "tool_request_digest": "b" * 64,
        "schedule_event_id": 7,
        "started_event_id": started,
    }
    return {**body, "proof_digest": digest(body)}


def binding(epoch="original-epoch"):
    return {
        "version": 1,
        "scope": copy.deepcopy(SCOPE),
        "namespace": copy.deepcopy(NAMESPACE),
        "target": TARGET,
        "target_execution_epoch": epoch,
    }


def expected_receipt(command_id="confirm"):
    return {
        "command_id": command_id,
        "target": TARGET,
        "record_state": "durably_recorded",
        "apply_state": "not_applied",
        "control_binding": binding(),
    }


@pytest.mark.parametrize("started", [None, 9])
def test_prepare_is_pure_and_commit_requires_original_verification(started):
    recovery = api()
    state, original = original_state()
    request = manual_request()
    before = copy.deepcopy(vars(state))
    prepared = recovery.prepare(state, request)
    assert prepared == {
        "submission": {k: original[k] for k in ("command_id", "target", "payload_digest")},
        "payload": request["recovery"]["payload"],
    }
    assert vars(state) == before
    assert recovery.receipt(state, request) is None
    result = recovery.commit(state, request, verified(prepared, request, started=started))
    assert result == expected_receipt()
    assert len(state.identities) == 2
    assert state.scoped_manual_slots == {
        digest([SCOPE, TARGET, "original-epoch", "original-action"]): "confirm"
    }
    assert state.scoped_manual_bindings == {"confirm": binding()}
    assert state.scoped_manual_epochs == {TARGET: "original-epoch"}


def test_duplicate_reads_original_detached_binding_before_remote_or_submission_checks():
    recovery = api()
    state, _ = original_state()
    request = manual_request()
    prepared = recovery.prepare(state, request)
    first = recovery.commit(state, request, verified(prepared, request))
    first["control_binding"]["namespace"]["id"] = "mutated-client-copy"
    del state.identities["original"]
    assert recovery.receipt(state, request) == expected_receipt()
    assert recovery.prepare(state, request) == {"receipt": expected_receipt()}
    assert recovery.commit(state, request, None) == expected_receipt()


@pytest.mark.parametrize("fault", ["payload", "target", "kind"])
def test_existing_global_command_identity_conflict_is_never_overridden(fault):
    recovery = api()
    state, _ = original_state()
    request = manual_request()
    recovery.commit(state, request, verified(recovery.prepare(state, request), request))
    changed = copy.deepcopy(request)
    if fault == "payload":
        changed["recovery"]["payload"]["result"] = "different"
        changed["payload_digest"] = digest(changed["recovery"]["payload"])
    else:
        changed[fault] = "different"
    before = copy.deepcopy(vars(state))
    for operation in (recovery.prepare, recovery.receipt):
        with pytest.raises(IdempotencyConflict):
            operation(state, changed)
    assert vars(state) == before


def test_two_prepared_commands_for_one_action_only_first_commit_wins():
    recovery = api()
    state, _ = original_state()
    first, second = manual_request(), manual_request(command_id="another", result="other")
    first_proof = verified(recovery.prepare(state, first), first)
    second_proof = verified(recovery.prepare(state, second), second)
    assert recovery.commit(state, second, second_proof) == expected_receipt("another")
    before = copy.deepcopy(vars(state))
    with pytest.raises(IdempotencyConflict):
        recovery.commit(state, first, first_proof)
    assert vars(state) == before and len(state.scoped_manual_slots) == 1


def test_other_original_actions_get_distinct_slots_but_target_epoch_cannot_change():
    recovery = api()
    state, _ = original_state()
    first = manual_request()
    recovery.commit(state, first, verified(recovery.prepare(state, first), first))
    second = manual_request(command_id="second", action_id="second-original-action")
    recovery.commit(state, second, verified(recovery.prepare(state, second), second))
    assert len(state.identities) == 3 and len(state.scoped_manual_slots) == 2
    reset = manual_request(command_id="reset", action_id="third-original-action")
    proof = verified(recovery.prepare(state, reset), reset, epoch="reset-epoch")
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        recovery.commit(state, reset, proof)
    assert vars(state) == before and state.scoped_manual_epochs[TARGET] == "original-epoch"


@pytest.mark.parametrize("race", ["command-id", "submission-changed", "submission-removed"])
def test_commit_rechecks_global_identity_and_original_submission_after_verifier_await(race):
    recovery = api()
    state, _ = original_state()
    request = manual_request()
    proof = verified(recovery.prepare(state, request), request)
    if race == "command-id":
        state.reserve(
            {
                "scope": SCOPE,
                "command_id": "confirm",
                "kind": "cancel",
                "target": TARGET,
                "payload_digest": digest({"scope": SCOPE, "kind": "cancel"}),
            }
        )
    elif race == "submission-changed":
        state.identities["original"]["payload_digest"] = "c" * 64
    else:
        del state.identities["original"]
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        recovery.commit(state, request, proof)
    assert vars(state) == before


@pytest.mark.parametrize("fault", ["missing-result", "query", "scope", "digest", "missing-payload"])
def test_invalid_manual_request_never_creates_a_protected_record(fault):
    recovery = api()
    state, _ = original_state()
    request = manual_request()
    if fault == "missing-result":
        del request["recovery"]["payload"]["result"]
    elif fault == "query":
        request["recovery"]["payload"]["query"] = True
    elif fault == "scope":
        request["scope"] = {**SCOPE, "principal": "foreign"}
    elif fault == "digest":
        request["payload_digest"] = "c" * 64
    else:
        del request["recovery"]["payload"]
    if fault in {"missing-result", "query"}:
        request["payload_digest"] = digest(request["recovery"]["payload"])
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        recovery.prepare(state, request)
    assert vars(state) == before


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "target",
        "registry-epoch",
        "namespace",
        "action",
        "submission",
        "digest",
        "schedule",
        "started",
    ],
)
def test_commit_refuses_changed_or_malformed_original_proof_without_mutation(fault):
    recovery = api()
    state, _ = original_state()
    request = manual_request()
    proof = verified(recovery.prepare(state, request), request)
    if fault == "scope":
        proof["scope"] = {**SCOPE, "principal": "foreign"}
    elif fault == "target":
        proof["target"] = "foreign-run"
    elif fault == "registry-epoch":
        proof["registry_execution_epoch"] = "foreign-registry-epoch"
    elif fault == "namespace":
        proof["namespace"]["name"] = "foreign"
    elif fault == "action":
        proof["action_id"] = "foreign-action"
    elif fault == "submission":
        proof["submission_digest"] = "c" * 64
    elif fault == "schedule":
        proof["schedule_event_id"] = True
    elif fault == "started":
        proof["started_event_id"] = proof["schedule_event_id"]
    proof["proof_digest"] = (
        "c" * 64
        if fault == "digest"
        else digest({k: v for k, v in proof.items() if k != "proof_digest"})
    )
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        recovery.commit(state, request, proof)
    assert vars(state) == before


@pytest.mark.parametrize("capacity", [1, 4])
def test_unverified_recovery_metadata_cannot_bypass_normal_reserve_or_signal(capacity):
    from relf_agent.temporal_scoped_reservation import accept

    state, _ = original_state(capacity=capacity)
    request = manual_request()
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        state.reserve(request)
    assert vars(state) == before
    host = SimpleNamespace(commands=state)
    info = SimpleNamespace(
        workflow_id="ralf-temporal-commands-" + digest(SCOPE),
        namespace="default",
        run_id="registry-epoch",
        first_execution_run_id="registry-epoch",
        original_execution_run_id="registry-epoch",
    )
    accept(
        host,
        {
            "kind": "scoped_reserve_receipt",
            "scope": SCOPE,
            "namespace": "default",
            "execution_epoch": "registry-epoch",
            "observation_id": "unverified-observation",
            "request": request,
        },
        info,
    )
    assert vars(state) == before
