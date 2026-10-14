"""Original first acceptance and safe occupancy; no optional SDK or service."""

import copy
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, DeploymentAdmissionPolicy, ModelResponse, Scope, ToolRegistry
from ralf_agent.errors import (
    CapacityExceeded,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_state import TemporalCommandRegistryState
from ralf_agent.types import digest, submission_request

POLICY = DeploymentAdmissionPolicy("public-registry", max_active_root_runs=1)
NAMESPACE = {"name": "default", "id": "11111111-1111-1111-1111-111111111111"}
SCOPE = asdict(Scope())


class Provider:
    identity = {"kind": "public-registry-model", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output="done")


def setup():
    runtime = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), admission_policy=POLICY
    )
    registry = TemporalCommandRegistryState(
        admission_policy=POLICY.identity, namespace=NAMESPACE, admission_protocol=2
    )
    request = submission_request(AgentSpec("a", "Answer"), "task", budget=4)
    envelope = {
        "version": 1,
        "request": request,
        "manifest": runtime.manifest,
        "activity_timeout": 30,
        "task_queue": "original",
    }
    reserve = {
        "scope": SCOPE,
        "command_id": "one",
        "kind": "submit",
        "target": root_run_id(POLICY.deployment_id, SCOPE, "one"),
        "payload_digest": digest(request),
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "root_admission": {
            "version": 2,
            "manifest_digest": digest(runtime.manifest),
            "submission": envelope,
        },
    }
    return registry, reserve


def lookup(reserve):
    return {
        "kind": "deployment_submission",
        **{
            key: reserve[key]
            for key in ("scope", "command_id", "payload_digest", "admission_policy", "namespace")
        },
    }


def test_public_reservation_and_first_envelope_are_atomic_and_detached():
    state, request = setup()
    assert state.deployment_submission(lookup(request)) is None
    result = state.reserve(request)
    saved = state.deployment_submission(lookup(request))
    assert saved == {
        "reservation": {k: v for k, v in result.items() if k != "submission"},
        "submission": request["root_admission"]["submission"],
        "run_receipt": None,
        "execution_epoch": None,
    }
    result["submission"]["task_queue"] = "changed"
    request["root_admission"]["submission"]["manifest"]["tools"] = []
    assert state.deployment_submission(lookup(request)) == saved


def test_racing_alias_queue_and_timeout_keep_original_envelope_while_full():
    state, request = setup()
    first = state.reserve(request)
    moved = copy.deepcopy(request)
    moved["root_admission"]["submission"]["task_queue"] = "moved"
    moved["root_admission"]["submission"]["activity_timeout"] = 60
    assert state.reserve(moved) == first
    assert state.deployment_submission(lookup(request))["submission"]["task_queue"] == "original"


@pytest.mark.parametrize(
    "field", ["request", "manifest", "task_queue", "activity_timeout", "version"]
)
def test_malformed_fresh_envelope_never_records_or_holds_capacity(field):
    state, request = setup()
    request["root_admission"]["submission"][field] = None
    with pytest.raises((ValidationError, DefinitionMismatch)):
        state.reserve(request)
    assert not state.deployment.commands and not state.deployment.roots


def test_full_capacity_and_changed_original_request_have_distinct_refusals():
    state, request = setup()
    state.reserve(request)
    conflicting = lookup(request)
    conflicting["payload_digest"] = "a" * 64
    with pytest.raises(IdempotencyConflict):
        state.deployment_submission(conflicting)
    second = copy.deepcopy(request)
    second["command_id"] = "two"
    second["target"] = root_run_id(POLICY.deployment_id, SCOPE, "two")
    with pytest.raises(CapacityExceeded):
        state.reserve(second)
    assert len(state.deployment.commands) == len(state.deployment.roots) == 1


def test_actual_original_receipt_is_immutable_and_pins_same_epoch():
    state, request = setup()
    root = state.reserve(request)["root_admission"]
    payload = {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        **{
            key: root[key]
            for key in ("command_id", "run_id", "request_digest", "manifest_digest", "proof_digest")
        },
        "execution_epoch": "original-sdk",
        "receipt": {
            "command_id": "one",
            "run_id": root["run_id"],
            "kind": "submit",
            "record_state": "durably_recorded",
            "apply_state": "applied",
            "outcome": {"state_revision": 0},
        },
    }
    first = state.record_deployment_submission(payload)
    assert first["execution_epoch"] == "original-sdk"
    assert first["run_receipt"] == payload["receipt"]
    assert state.record_deployment_submission(payload) == first
    for field, value in (
        ("execution_epoch", "replacement"),
        ("receipt", {**payload["receipt"], "apply_state": "not_applied"}),
    ):
        changed = {**payload, field: value}
        with pytest.raises((ValidationError, DefinitionMismatch)):
            state.record_deployment_submission(changed)
    assert state.deployment_submission(lookup(request)) == first


def test_public_configuration_distinguishes_v1_and_preserves_legacy_claim():
    legacy = TemporalCommandRegistryState(admission_policy=POLICY.identity, namespace=NAMESPACE)
    query = {
        "kind": "deployment_configuration",
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
    }
    assert legacy.deployment_configuration(query)["version"] == 1
    state, _ = setup()
    assert state.deployment_configuration(query)["version"] == 2
    assert legacy.deployment is not None


@pytest.mark.parametrize("mutation", ["kernel", "source_inventory", "registry_id"])
def test_impossible_public_manifest_is_rejected_before_durable_acceptance(mutation):
    state, request = setup()
    manifest = request["root_admission"]["submission"]["manifest"]
    if mutation == "kernel":
        manifest["kernel"] = "invalid-kernel"
    elif mutation == "source_inventory":
        manifest["deployment_admission_protocol"]["implementation"].pop("temporal.py")
    else:
        manifest["deployment_admission_protocol"]["registry_id"] = "foreign"
    request["root_admission"]["manifest_digest"] = digest(manifest)
    with pytest.raises((ValidationError, DefinitionMismatch)):
        state.reserve(request)
    assert not state.deployment.commands and not state.deployment.roots


def test_recorded_duplicate_returns_original_before_new_manifest_validation():
    state, request = setup()
    original = state.reserve(request)
    changed = copy.deepcopy(request)
    changed["root_admission"]["submission"]["manifest"]["kernel"] = "invalid-kernel"
    assert state.reserve(changed) == original
