"""Pure original native/physical proofs; no SDK, process or service verification."""

import copy
import importlib
from types import SimpleNamespace

import pytest

from relf_agent import temporal_deployment_execution_state as admission_state
from relf_agent import temporal_deployment_release_state as release
from relf_agent.errors import RalfError
from relf_agent.types import digest

from .test_temporal_coding_state import (
    grant,
    native_stop,
    owner_dead_payload,
    ready,
)
from .test_temporal_tool_execution import admission


def coding():
    name = "relf_agent.temporal_deployment_coding_state"
    assert importlib.util.find_spec(name), "Original pure Coding deployment bridge is missing"
    return importlib.import_module(name)


def attach(state, monkeypatch, *, version=3):
    state.manifest["deployment_admission_protocol"] = {"version": version}
    namespace = {"name": "original", "id": "12345678-1234-5678-1234-567812345678"}

    def original(current):
        return {
            "version": 1,
            "scope": current.scope,
            "run_id": current.run_id,
            "command_id": "submit",
            "execution_epoch": current.epoch,
            "original_execution_epoch": current.epoch,
            "namespace": copy.deepcopy(namespace),
            "request": copy.deepcopy(current.request),
            "request_digest": digest(current.request),
            "manifest": copy.deepcopy(current.manifest),
            "manifest_digest": digest(current.manifest),
            "admission": {"version": 1, "root": {"run_id": current.run_id}, "lineage": []},
            "admission_receipt": {
                "root": {"state": "held-bound", "execution_epoch": current.epoch}
            },
            "children": copy.deepcopy(getattr(current, "children", [])),
        }

    monkeypatch.setattr(admission_state, "view", original)
    monkeypatch.setattr(admission_state, "admitted", lambda current: True)
    release.initialize(state)
    return state


def native(monkeypatch, *, cost=None):
    """Record the real original native intent after selecting deployment3."""
    from relf_agent import temporal_coding_state, temporal_tool_execution_state

    state, action, _ = ready()
    action.pop("delegated_execution")
    state.tool_executions.pop(action["id"])
    attach(state, monkeypatch)
    if cost is not None:
        state.manifest["tools"]["read"]["cost"] = cost
        state.reservations[action["attempts"][0]["id"]]["amount"] = cost
    request = temporal_coding_state.prepare(state, action, state.envelope(action))
    request = temporal_tool_execution_state.prepare(state, action, request)
    assert request == action["delegated_execution"]["tool_request"]
    identity = {
        "version": 1,
        "scope": copy.deepcopy(state.scope),
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "activity_id": action["attempts"][0]["id"],
        "activity_name": "ralf.temporal.tool.v1",
        "attempt": 1,
        "invocation_id": "e" * 32,
        "request_digest": digest({"scope": state.scope, "_deployment_activity_request": request}),
        "manifest_digest": digest(state.manifest),
    }
    release.begin_activity(state, identity)
    grant(state, request)
    return state, action, request, identity


def cold(monkeypatch, *, cost=None):
    state, action, request, identity = native(monkeypatch, cost=cost)
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    state.operation_unknown(action["id"], "original-worker-lost")
    state.admit_coding_stop(admission(request, "c" * 32))
    native_stop(state, request)
    state.coding_owner_stopped(owner_dead_payload(request))
    return state, action, request, identity


def test_stopped_activity_and_tool_owner_cannot_replace_native_fence(monkeypatch):
    from .test_temporal_tool_execution import proof

    state, action, request, identity = native(monkeypatch)
    state.state = "cancelled"
    state.active_action = None
    state.tool_execution_ended(proof(request))
    action["status"] = "completed"
    state._settle(action)
    release.end_activity(state, identity)
    assert state.tool_executions[action["id"]]["execution_stopped"]
    assert release.closure(state)[0] is False
    assert "coding_native_not_stopped" in release.closure(state)[1]
    with pytest.raises(RalfError):
        release.seal(state, {"scope": state.scope, "children": []})


def test_native_physical_stop_does_not_clear_zero_cost_unknown_or_effect(monkeypatch):
    state, action, request, identity = cold(monkeypatch, cost=0)
    reservation = state.reservations[action["attempts"][0]["id"]]
    before = copy.deepcopy((action, reservation))
    candidate = coding().coding_call_candidate(state, identity)
    result = coding().adopt_call_fence(
        state,
        {"scope": state.scope, "identity": identity},
        {**candidate, "process_present": False, "native_fenced": True},
    )
    assert result == {
        "activity_id": identity["activity_id"],
        "attempt": 1,
        "invocation_id": "e" * 32,
        "recorded": True,
    }
    assert (action, reservation) == before
    assert reservation["status"] == "unknown" and action["status"] == "outcome_unknown"
    assert release.closure(state)[0] is False


def test_cold_candidate_requires_original_native_and_durable_owner_stop(monkeypatch):
    state, action, request, identity = cold(monkeypatch)
    candidate = coding().coding_call_candidate(state, identity)
    owner = action["delegated_execution"]["owner"]
    assert candidate == {
        "version": 1,
        "identity": identity,
        "action_id": action["id"],
        "tool_request_digest": digest(request),
        "owner": owner,
        "owner_stop_proof": state.tool_executions[action["id"]]["coding_owner_stop_proof"],
        "runner": action["delegated_execution"]["runner"],
        "namespace": {"name": "original", "id": "12345678-1234-5678-1234-567812345678"},
        "execution_epoch": state.epoch,
    }
    candidate["owner"]["pid"] = 999
    assert action["delegated_execution"]["owner"]["pid"] != 999


@pytest.mark.parametrize(
    "fault",
    [
        "model",
        "ordinary",
        "activity_id",
        "carrier",
        "epoch",
        "manifest",
        "owner_missing",
        "owner_changed",
        "tool_invocation",
        "owner_stop_missing",
        "owner_stop_foreign",
        "owner_stop_unadmitted",
        "owner_stop_alive",
        "native_unfenced",
        "pending_stop",
        "tool_not_stopped",
        "action_arguments",
        "runner",
    ],
)
def test_cold_candidate_refuses_unrelated_or_incomplete_original_facts(monkeypatch, fault):
    state, action, request, identity = cold(monkeypatch)
    value = action["delegated_execution"]
    tool = state.tool_executions[action["id"]]
    if fault == "model":
        identity["activity_name"] = "ralf.temporal.model.v1"
    elif fault == "ordinary":
        action.pop("delegated_execution")
    elif fault == "activity_id":
        identity["activity_id"] = "unrelated"
    elif fault == "carrier":
        identity["request_digest"] = digest(request)
    elif fault == "epoch":
        identity["execution_epoch"] = "replacement"
    elif fault == "manifest":
        identity["manifest_digest"] = "f" * 64
    elif fault == "owner_missing":
        value.pop("owner")
    elif fault == "owner_changed":
        value["owner"]["pid"] += 1
    elif fault == "tool_invocation":
        tool["invocation_id"] = "f" * 32
    elif fault == "owner_stop_missing":
        tool.pop("coding_owner_stop_proof")
    elif fault == "owner_stop_foreign":
        tool["coding_owner_stop_proof"]["run_id"] = "foreign"
    elif fault == "owner_stop_unadmitted":
        value["stop_invocations"] = []
    elif fault == "owner_stop_alive":
        tool["coding_owner_stop_proof"]["evidence"]["process_present"] = True
    elif fault == "native_unfenced":
        value["fenced"] = False
    elif fault == "pending_stop":
        value["pending_stop"] = True
    elif fault == "tool_not_stopped":
        tool["execution_stopped"] = False
    elif fault == "action_arguments":
        action["arguments"] = {"task": "foreign"}
    elif fault == "runner":
        value["runner"] = {"kind": "foreign"}
    before = copy.deepcopy(state.deployment_calls)
    with pytest.raises(RalfError):
        coding().coding_call_candidate(state, identity)
    assert state.deployment_calls == before


@pytest.mark.parametrize(
    "fault", ["caller_bool", "scope", "owner", "namespace", "epoch", "alive", "unfenced", "extra"]
)
def test_fence_rechecks_original_candidate_and_rejects_caller_facts(monkeypatch, fault):
    state, action, _, identity = cold(monkeypatch)
    candidate = coding().coding_call_candidate(state, identity)
    request = {"scope": copy.deepcopy(state.scope), "identity": identity}
    attestation = {**candidate, "process_present": False, "native_fenced": True}
    if fault == "caller_bool":
        request["process_present"] = False
    elif fault == "scope":
        request["scope"]["principal"] = "foreign"
    elif fault == "owner":
        attestation["owner"]["start"] = "replacement"
    elif fault == "namespace":
        attestation["namespace"]["id"] = "12345678-1234-5678-1234-567812345679"
    elif fault == "epoch":
        attestation["execution_epoch"] = "replacement"
    elif fault == "alive":
        attestation["process_present"] = True
    elif fault == "unfenced":
        attestation["native_fenced"] = False
    else:
        attestation["caller_closed"] = True
    before = copy.deepcopy((state.deployment_calls, action))
    with pytest.raises(RalfError):
        coding().adopt_call_fence(state, request, attestation)
    assert (state.deployment_calls, action) == before


def test_fence_retry_is_detached_and_changed_original_facts_cannot_replace_proof(monkeypatch):
    state, action, _, identity = cold(monkeypatch)
    candidate = coding().coding_call_candidate(state, identity)
    attestation = {**candidate, "process_present": False, "native_fenced": True}
    request = {"scope": state.scope, "identity": identity}
    ack = coding().adopt_call_fence(state, request, attestation)
    assert coding().adopt_call_fence(state, request, copy.deepcopy(attestation)) == ack
    record = next(iter(state.deployment_calls.values()))
    assert record["stopped"] is True and record["end_proof"] == identity
    assert record["fence_proof"] == attestation
    attestation["owner"]["pid"] = 99
    assert record["fence_proof"]["owner"]["pid"] != 99
    action["delegated_execution"]["owner"]["pid"] = 88
    with pytest.raises(RalfError):
        coding().adopt_call_fence(state, request, record["fence_proof"])


def test_owner_before_first_grant_uncertainty_cannot_use_pid_only_fence(monkeypatch):
    state, _, _, identity = native(monkeypatch)
    tool = next(iter(state.tool_executions.values()))
    tool.pop("coding_owner_stop_proof", None)
    tool["execution_stopped"] = True
    with pytest.raises(RalfError):
        coding().coding_call_candidate(state, identity)


def test_v3_call_fence_shape_does_not_rewrite_v2_records(monkeypatch):
    state, _, _, _ = native(monkeypatch)
    assert next(iter(state.deployment_calls.values()))["fence_proof"] is None
    from .test_temporal_deployment_release_state import identity, original

    ordinary = original(monkeypatch)
    release.begin_activity(ordinary, identity(ordinary))
    assert set(next(iter(ordinary.deployment_calls.values()))) == {
        "identity",
        "allowed",
        "stopped",
        "end_proof",
    }


def test_only_v3_seals_guard_new_mutations_preserving_exact_recorded_duplicates():
    module = coding()
    for version in [None, 1, 2, True, "3"]:
        manifest = (
            {} if version is None else {"deployment_admission_protocol": {"version": version}}
        )
        state = SimpleNamespace(manifest=manifest, deployment_seal={"proof_digest": "a" * 64})
        assert not module.selected(manifest)
        assert module.guard_mutation(state, None, {"new": True}) is False
    state = SimpleNamespace(
        manifest={"deployment_admission_protocol": {"version": 3}}, deployment_seal=None
    )
    assert module.guard_mutation(state, {"original": True}, {"original": True}) is False
    state.deployment_seal = {"proof_digest": "a" * 64}
    assert module.guard_mutation(state, {"original": True}, {"original": True}) is True
    for previous, requested in [(None, None), (None, {}), ({"original": True}, {"new": True})]:
        with pytest.raises(RalfError):
            module.guard_mutation(state, previous, requested)


def composition_parent(monkeypatch):
    from .test_temporal_coding_composition_state import bind_namespace, parent

    state = parent()
    state.manifest["coding_composition_protocol"] = {
        "version": 7,
        "topology": "bounded-recursive-orchestration",
    }
    state.manifest["binding_protocol"] = 23
    state.manifest["coding_execution_protocol"] = {"version": 6}
    attach(state, monkeypatch)
    bind_namespace(state)
    state.composition_namespace = {"name": "original", "id": "12345678-1234-5678-1234-567812345678"}
    state.composition_admission = {
        "namespace": copy.deepcopy(state.composition_namespace),
        "execution_epoch": state.epoch,
        "admitted": False,
    }
    state.state = "cancelled"
    return state


@pytest.mark.parametrize(
    "fault", ["namespace", "epoch", "admission", "child_missing", "child_epoch", "auxiliary"]
)
def test_composition_original_identity_and_physical_children_block_seal(monkeypatch, fault):
    state = composition_parent(monkeypatch)
    if fault == "namespace":
        state.composition_namespace["id"] = "12345678-1234-5678-1234-567812345679"
    elif fault == "epoch":
        state.composition_original_epoch = "replacement"
    elif fault == "admission":
        state.composition_admission = None
    elif fault == "auxiliary":
        state.context_read_stages = {"hidden-read": {"response_observed": True}}
    else:
        state.children.append(
            {
                "id": "prior-revision-child",
                "member": "@verifier",
                "planning_revision": 0,
                "settled": True,
                "dispatch_started": True,
                "deployment_execution_epoch": "original-child",
                "child_execution": {
                    "execution_epoch": "replacement",
                    "original_execution_epoch": "replacement",
                    "namespace": state.composition_namespace,
                },
                "physical_stop_proof": {}
                if fault == "child_missing"
                else {"physical_stopped": True},
            }
        )
    assert release.closure(state)[0] is False
    with pytest.raises(RalfError):
        release.seal(state, {"scope": state.scope, "children": []})


def test_native_unknown_remains_held_after_physical_and_ledger_end(monkeypatch):
    state, action, _, identity = cold(monkeypatch)
    release.end_activity(state, identity)
    action["status"] = "completed"
    state._settle(action)
    assert action["delegated_execution"]["native_unknown"] is True
    assert "coding_native_unknown" in release.closure(state)[1]


def test_v3_composition_identity_and_stop_intent_enter_certificate_digest_only_for_v3(monkeypatch):
    state = composition_parent(monkeypatch)
    assert release.closure(state) == (True, [])
    before = copy.deepcopy(state)
    state.composition_stop_intent = {
        "terminal_state": "cancelled",
        "reason": {"code": "original"},
        "child_intent_ids": [],
    }
    first = release.seal(state, {"scope": state.scope, "children": []})
    other = release.seal(before, {"scope": before.scope, "children": []})
    assert first["closure_digest"] != other["closure_digest"]
    assert set(first) == release.CERTIFICATE_FIELDS
    from .test_temporal_deployment_release_state import original

    ordinary = original(monkeypatch)
    baseline = copy.deepcopy(ordinary)
    ordinary.composition_stop_intent = {"foreign": True}
    assert release.seal(ordinary, {"scope": ordinary.scope, "children": []}) == release.seal(
        baseline, {"scope": baseline.scope, "children": []}
    )


def test_stop_activity_cannot_borrow_dead_native_owner_for_its_own_handler(monkeypatch):
    state, action, _, identity = cold(monkeypatch)
    operation, _ = state.next_operation()
    assert operation["kind"] == "coding_stop"
    stop_identity = {
        **identity,
        "activity_name": "ralf_coding_stop",
        "activity_id": operation["id"],
        "invocation_id": "f" * 32,
    }
    release.begin_activity(state, stop_identity)
    with pytest.raises(RalfError):
        coding().coding_call_candidate(state, stop_identity)
    assert state.deployment_calls[digest([stop_identity["activity_id"], 1])]["stopped"] is False


def test_confirmed_label_without_strict_original_native_candidate_stays_unknown(monkeypatch):
    state, action, _, identity = cold(monkeypatch)
    release.end_activity(state, identity)
    action["status"] = "completed"
    action["result"] = {"caller_claim": "closed"}
    state._settle(action)
    action["delegated_execution"]["effect_case"] = "confirmed"
    assert "coding_native_unknown" in release.closure(state)[1]


def test_strict_native_recovery_still_waits_for_original_effect_ack(monkeypatch):
    from .test_temporal_coding_state import completed_native

    state, action, request, identity = native(monkeypatch)
    result = completed_native(state, action, request)
    state.operation_unknown(action["id"], "original-response-lost")
    state.admit_coding_stop(admission(request, "c" * 32))
    state.coding_owner_stopped(owner_dead_payload(request))
    state.accept_tool(action["id"], {"ok": True, "result": result}, reconciled=True)
    state.state = "cancelled"
    release.end_activity(state, identity)
    assert action["delegated_execution"]["native_unknown"] is True
    assert coding().closure_reasons(state) == []
    assert state.reservations[action["attempts"][0]["id"]]["status"] == "settled"
    assert "pending_acks" in release.closure(state)[1]


def test_fence_duplicate_after_seal_returns_original_ack_without_mutating_facts(monkeypatch):
    state, action, _, identity = cold(monkeypatch)
    candidate = coding().coding_call_candidate(state, identity)
    attestation = {**candidate, "process_present": False, "native_fenced": True}
    request = {"scope": state.scope, "identity": identity}
    ack = coding().adopt_call_fence(state, request, attestation)
    state.deployment_seal = {"proof_digest": "a" * 64}
    before = copy.deepcopy((state.deployment_calls, action, state.event_log))
    assert coding().adopt_call_fence(state, request, copy.deepcopy(attestation)) == ack
    assert (state.deployment_calls, action, state.event_log) == before


def test_no_original_owner_before_grant_retains_unended_call(monkeypatch):
    state, action, _, identity = native(monkeypatch)
    value = action["delegated_execution"]
    value.pop("owner")
    value["grants"] = {}
    value["fenced"], value["pending_stop"] = True, False
    state.tool_executions[action["id"]]["execution_stopped"] = True
    with pytest.raises(RalfError):
        coding().coding_call_candidate(state, identity)
    assert next(iter(state.deployment_calls.values()))["stopped"] is False


def test_pure_cold_association_runs_with_optional_sdk_imports_blocked():
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import builtins
original = builtins.__import__
def pure_import(name, *args, **kwargs):
    if name == 'temporalio' or name.startswith('temporalio.'):
        raise AssertionError('Pure state attempted optional SDK import')
    return original(name, *args, **kwargs)
builtins.__import__ = pure_import
import pytest
from tests.test_temporal_deployment_coding_state import cold, coding
with pytest.MonkeyPatch.context() as patches:
    state, action, request, identity = cold(patches)
    candidate = coding().coding_call_candidate(state, identity)
    ack = coding().adopt_call_fence(state, {'scope': state.scope, 'identity': identity},
        dict(candidate, process_present=False, native_fenced=True))
    assert ack['recorded'] and action['status'] == 'outcome_unknown'
""",
        ],
        cwd=root,
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(root / "src") + os.pathsep + str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_replacement_sdk_attempt_cannot_borrow_original_native_owner(monkeypatch):
    state, _, _, original = cold(monkeypatch)
    release.end_activity(state, original)
    replacement = {**original, "attempt": 2, "invocation_id": "f" * 32}
    release.begin_activity(state, replacement)
    with pytest.raises(RalfError):
        coding().coding_call_candidate(state, replacement)
    assert state.deployment_calls[digest([replacement["activity_id"], 2])]["stopped"] is False


@pytest.mark.parametrize(
    "target",
    ["native_alias", "composition_alias", "canonical_guard", "candidate", "adopter", "code"],
)
def test_v3_guard_registration_rejects_actual_binding_drift_before_mutation(monkeypatch, target):
    from relf_agent import temporal_coding_composition_state, temporal_coding_state

    module = coding()
    assert hasattr(module, "check_guard_registration"), (
        "Selected3 guard binding validation is missing"
    )
    if target == "native_alias":
        monkeypatch.setattr(temporal_coding_state, "guard_mutation", lambda *_: False)
    elif target == "composition_alias":
        monkeypatch.setattr(temporal_coding_composition_state, "guard_mutation", lambda *_: False)
    elif target == "canonical_guard":
        monkeypatch.setattr(module, "guard_mutation", lambda *_: False)
    elif target == "candidate":
        monkeypatch.setattr(module, "coding_call_candidate", lambda *_: {})
    elif target == "adopter":
        monkeypatch.setattr(module, "adopt_call_fence", lambda *_: {"recorded": True})
    else:
        monkeypatch.setattr(module.guard_mutation, "__code__", (lambda *_: False).__code__)
    with pytest.raises(RalfError):
        module.check_guard_registration({"deployment_admission_protocol": {"version": 3}})
    module.check_guard_registration({})
    module.check_guard_registration({"deployment_admission_protocol": {"version": 2}})


def test_original_v3_guard_registration_is_available_without_sdk(monkeypatch):
    module = coding()
    assert hasattr(module, "check_guard_registration"), (
        "Selected3 guard binding validation is missing"
    )
    module.check_guard_registration({"deployment_admission_protocol": {"version": 3}})
