"""Pure first Session acceptance and claim/fence races; no SDK or service."""

import copy

import pytest

from relf_agent import AgentSpec, DeploymentAdmissionPolicy, ToolRegistry
from relf_agent.errors import (
    AuthorizationDenied,
    CapacityExceeded,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from relf_agent.runtime_builder import EchoProvider
from relf_agent.session_types import SessionKey
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_session_state import resource_id, workflow_id
from relf_agent.types import digest, submission_request

SCOPE = {"workspace": "workspace", "principal": "owner"}
NAMESPACE = {"name": "original", "id": "11111111-1111-4111-8111-111111111111"}
POLICY = DeploymentAdmissionPolicy("original-deployment", max_active_root_runs=1)


def state(capacity=16):
    from relf_agent.temporal_deployment_session_registry import SessionDeploymentAdmissionState

    return SessionDeploymentAdmissionState(
        POLICY.identity, NAMESPACE, capacity=capacity, registry_execution_epoch="registry-original"
    )


def command(command_id="open"):
    binding = {
        "request": submission_request(AgentSpec("ordinary", "Answer"), None),
        "manifest": TemporalRuntime(
            providers={"default": EchoProvider("registry-fixture")},
            tools=ToolRegistry(),
            enable_sessions=True,
        ).manifest,
        "task_queue": "original-queue",
        "activity_timeout": 30,
    }
    from relf_agent.temporal_deployment_protocol import publish

    binding["manifest"] = publish(
        binding["manifest"], POLICY.identity, public=True, session_deployment=True
    )
    key = SessionKey(
        **SCOPE, resource_id=resource_id(NAMESPACE["id"]), namespace=None, session_id="chat"
    )
    logical = {
        "kind": "open",
        "scope": SCOPE,
        "command_id": command_id,
        "session_namespace": None,
        "session_id": "chat",
        "request": binding["request"],
    }
    return {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "command_id": command_id,
        "kind": "session_open",
        "target": workflow_id(key),
        "payload_digest": digest(logical),
        "session_submission": {
            "version": 1,
            "session_key": key.to_dict(),
            "logical_payload": logical,
            "binding": binding,
            "payload": {
                "kind": "open",
                "scope": SCOPE,
                "command_id": command_id,
                "binding": binding,
            },
        },
    }


def lookup(request):
    return {
        "kind": "deployment_session_command",
        **{
            key: request[key]
            for key in ("scope", "admission_policy", "namespace", "command_id", "payload_digest")
        },
    }


def test_zero_root_first_envelope_replays_before_moved_binding_resolution():
    registry, request = state(), command()
    assert registry.deployment_session_command(lookup(request)) is None
    receipt = registry.reserve(request)
    saved = registry.deployment_session_command(lookup(request))
    assert receipt == {
        "command_id": "open",
        "target": request["target"],
        "record_state": "durably_recorded",
        "apply_state": "not_applied",
    }
    assert saved == {
        "reservation": receipt,
        "session_submission": request["session_submission"],
        "session_receipt": None,
    }
    moved = copy.deepcopy(request)
    moved["session_submission"]["payload"]["binding"] = {"unavailable": True}
    assert registry.reserve(moved) == receipt
    saved["session_submission"]["payload"]["binding"]["task_queue"] = "tampered"
    assert (
        registry.deployment_session_command(lookup(request))["session_submission"]["payload"][
            "binding"
        ]["task_queue"]
        == "original-queue"
    )
    assert registry.roots == {} and len(registry.commands) == 1


@pytest.mark.parametrize("mutation", ["target", "kind", "logical_address", "digest"])
def test_shared_command_identity_conflicts_preserve_first_record(mutation):
    registry, request = state(), command()
    first = registry.reserve(request)
    changed = copy.deepcopy(request)
    if mutation == "logical_address":
        changed["session_submission"]["logical_payload"]["session_namespace"] = "moved"
        changed["payload_digest"] = digest(changed["session_submission"]["logical_payload"])
    elif mutation == "digest":
        changed["payload_digest"] = "a" * 64
    elif mutation == "target":
        changed["target"] = "other-coordinator"
    else:
        changed["kind"] = "session_submit"
    with pytest.raises(IdempotencyConflict):
        registry.reserve(changed)
    assert registry.reserve(request) == first and not registry.roots


@pytest.mark.parametrize("field", ["session_key", "logical_payload", "payload", "version"])
def test_invalid_first_session_envelope_does_not_accept(field):
    registry, request = state(), command()
    request["session_submission"][field] = None
    with pytest.raises((DefinitionMismatch, ValidationError)):
        registry.reserve(request)
    assert not registry.commands and not registry.roots


def test_command_allowance_is_independent_of_business_capacity():
    registry, request = state(capacity=1), command()
    registry.reserve(request)
    with pytest.raises(ValidationError, match="capacity"):
        registry.reserve(command("second"))
    assert len(registry.commands) == 1 and not registry.roots


def deployment_intent():
    from relf_agent.temporal_deployment_protocol import publish
    from tests.test_temporal_session_deployment_dto import intent, seal

    value = intent()
    manifest = publish(
        value["binding"]["manifest"], POLICY.identity, public=True, session_deployment=True
    )
    value["binding"]["manifest"] = manifest
    value["submission"]["manifest"] = copy.deepcopy(manifest)
    value["session_ref"]["definition_digest"] = digest(value["binding"])
    value["submission"]["request"]["session_turn"]["session_ref"] = copy.deepcopy(
        value["session_ref"]
    )
    return seal(value)


def intent_request(registry, *, command_id="session-submit-1"):
    from tests.test_temporal_session_deployment_dto import origin, seal

    value = deployment_intent()
    if command_id != value["session_command_id"]:
        key = value["session_ref"]["key"]
        value["session_command_id"] = command_id
        value["turn_id"] = "ralf-turn-" + digest([key, command_id])
        value["run_command_id"] = "ralf-session-run:" + digest([key, command_id])
        from relf_agent.temporal_deployment_admission import root_run_id

        value["run_id"] = root_run_id(POLICY.deployment_id, SCOPE, value["run_command_id"])
        value["submission"]["request"]["session_turn"]["turn_id"] = value["turn_id"]
        seal(value)
    payload = {
        "kind": "submit",
        "scope": SCOPE,
        "command_id": command_id,
        "session_ref": value["session_ref"],
        "input": value["submission"]["request"]["input"],
        "budget": value["submission"]["request"]["budget"],
    }
    registry.reserve(
        {
            "scope": SCOPE,
            "admission_policy": POLICY.identity,
            "namespace": NAMESPACE,
            "command_id": command_id,
            "kind": "session_submit",
            "target": value["coordinator_id"],
            "payload_digest": digest(payload),
            "session_submission": {
                "version": 1,
                "session_key": value["session_ref"]["key"],
                "payload": payload,
                "logical_payload": payload,
                "binding": value["binding"],
            },
        }
    )
    request = {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "command_id": value["run_command_id"],
        "kind": "submit",
        "target": value["run_id"],
        "payload_digest": digest(value["submission"]["request"]),
        "root_admission": {
            "version": 4,
            "manifest_digest": digest(value["submission"]["manifest"]),
            "submission": value["submission"],
            "session_origin": origin(value),
        },
    }
    return value, request


def verified(value, request):
    return {"intent": value, "session_origin": request["root_admission"]["session_origin"]}


def refusal_request(value):
    from tests.test_temporal_session_deployment_dto import seal

    barrier = seal(
        {
            "version": 1,
            "intent_digest": value["intent_digest"],
            "coordinator_execution_epoch": value["coordinator_execution_epoch"],
            "start_issued": False,
            "code": "definition_mismatch",
        },
        "barrier_digest",
    )
    return {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "intent": value,
        "barrier": barrier,
        "code": "definition_mismatch",
    }


def refusal_verification(request, root_request):
    return {**verified(request["intent"], root_request), "barrier": request["barrier"]}


def root_lookup(request):
    return {**lookup(request), "kind": "deployment_session_root"}


def fence_lookup(value):
    return {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "intent": value,
    }


def test_public_session_root_attestation_is_refused_without_mutation():
    registry = state()
    value, request = intent_request(registry)
    with pytest.raises(AuthorizationDenied):
        registry.reserve(request)
    assert not registry.roots and len(registry.commands) == 1


def test_internal_root_commit_freezes_envelope_and_is_idempotent():
    registry = state()
    value, request = intent_request(registry)
    prepared = registry.prepare_session_root(request, value)
    assert prepared == {"request": request, **verified(value, request)}
    assert not registry.roots
    receipt = registry.commit_session_root(request, value, verified(value, request))
    assert receipt["submission"]["task_queue"] == "original-queue"
    assert registry.prepare_session_root(request, value) == {"receipt": receipt}
    assert registry.commit_session_root(request, value, None) == receipt
    result = registry.deployment_session_root(root_lookup(request))
    assert set(registry.submissions[digest([SCOPE, value["run_command_id"]])]) == {
        "reservation",
        "submission",
        "run_receipt",
        "execution_epoch",
    }
    assert (
        result["intent"] == value
        and result["session_origin"] == request["root_admission"]["session_origin"]
    )
    result["intent"]["binding"]["task_queue"] = "changed"
    assert (
        registry.deployment_session_root(root_lookup(request))["intent"]["binding"]["task_queue"]
        == "original-queue"
    )
    assert len(registry.commands) == 2 and len(registry.roots) == 1


def test_capacity_is_rechecked_after_competing_prepares():
    registry = state()
    one, request_one = intent_request(registry)
    two, request_two = intent_request(registry, command_id="second-turn")
    registry.prepare_session_root(request_one, one)
    registry.prepare_session_root(request_two, two)
    registry.commit_session_root(request_one, one, verified(one, request_one))
    with pytest.raises(CapacityExceeded):
        registry.commit_session_root(request_two, two, verified(two, request_two))
    assert len(registry.roots) == 1 and len(registry.commands) == 3


def test_fence_winning_after_root_prepare_prevents_late_commit_and_replies_recover():
    registry = state()
    value, request = intent_request(registry)
    registry.prepare_session_root(request, value)
    refused = refusal_request(value)
    registry.prepare_session_never_claimed(refused)
    proof = registry.commit_session_never_claimed(refused, refusal_verification(refused, request))
    assert (
        proof["never_claimed"] is True and proof["registry_execution_epoch"] == "registry-original"
    )
    assert registry.deployment_session_never_claimed(fence_lookup(value)) == proof
    assert registry.commit_session_never_claimed(refused, None) == proof
    with pytest.raises(DefinitionMismatch, match="fence"):
        registry.commit_session_root(request, value, verified(value, request))
    assert not registry.roots and len(registry.commands) == 1


def test_claim_winning_after_fence_prepare_prevents_certificate_even_after_retirement():
    registry = state()
    value, request = intent_request(registry)
    refused = refusal_request(value)
    registry.prepare_session_never_claimed(refused)
    registry.commit_session_root(request, value, verified(value, request))
    with pytest.raises(DefinitionMismatch, match="claim"):
        registry.commit_session_never_claimed(refused, refusal_verification(refused, request))
    key = digest([SCOPE, value["run_command_id"]])
    registry.retirements[key] = {"root": registry.roots.pop(key)}
    with pytest.raises(DefinitionMismatch, match="claim"):
        registry.commit_session_never_claimed(refused, refusal_verification(refused, request))
    assert registry.deployment_session_never_claimed(fence_lookup(value)) is None


def test_conflicting_command_retains_first_receipt_when_other_intent_is_fenced():
    registry = state()
    value, request = intent_request(registry)
    collision = command(value["run_command_id"])
    original = registry.reserve(collision)
    with pytest.raises(IdempotencyConflict):
        registry.prepare_session_root(request, value)
    refused = refusal_request(value)
    registry.commit_session_never_claimed(refused, refusal_verification(refused, request))
    assert registry.reserve(collision) == original
    assert registry.deployment_session_command(lookup(collision))["reservation"] == original
    assert not registry.roots and len(registry.commands) == 2


@pytest.mark.parametrize(
    "mutation", ["start_issued", "code", "barrier_digest", "intent_digest", "verification"]
)
def test_never_claimed_refuses_unknown_start_or_forged_internal_verification(mutation):
    registry = state()
    value, request = intent_request(registry)
    refused = refusal_request(value)
    verification = refusal_verification(refused, request)
    if mutation == "verification":
        verification = {"verified": True}
    else:
        refused = copy.deepcopy(refused)
        refused["barrier"][mutation] = {
            "start_issued": True,
            "code": "capacity_exceeded",
            "barrier_digest": "a" * 64,
            "intent_digest": "a" * 64,
        }[mutation]
    with pytest.raises((DefinitionMismatch, ValidationError)):
        registry.commit_session_never_claimed(refused, verification)
    assert not registry.session_fences and not registry.roots


def test_session_receipt_index_requires_exact_original_and_is_immutable():
    registry, request = state(), command()
    registry.reserve(request)
    receipt = {
        "command_id": "open",
        "kind": "session_open",
        "run_id": None,
        "record_state": "durably_recorded",
        "apply_state": "applied",
        "outcome": {"session_ref": {"original": True}},
    }
    record = {
        key: request[key]
        for key in ("scope", "admission_policy", "namespace", "command_id", "payload_digest")
    }
    record["receipt"] = receipt
    prepared = registry.prepare_session_receipt(record)
    assert prepared == {"session_submission": request["session_submission"], "receipt": receipt}
    with pytest.raises((DefinitionMismatch, ValidationError)):
        registry.commit_session_receipt(record, {"verified": True})
    first = registry.commit_session_receipt(record, prepared)
    assert first["session_receipt"] == receipt
    assert registry.commit_session_receipt(record, None) == first
    changed = copy.deepcopy(record)
    changed["receipt"]["apply_state"] = "rejected"
    with pytest.raises(DefinitionMismatch):
        registry.commit_session_receipt(changed, prepared)


def ordinary_request(command_id="ordinary"):
    from relf_agent.temporal_deployment_admission import root_run_id

    manifest = TemporalRuntime(
        providers={"default": EchoProvider("ordinary-fixture")},
        tools=ToolRegistry(),
        admission_policy=POLICY,
    ).manifest
    request = submission_request(AgentSpec("ordinary", "Answer"), "business")
    return {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "command_id": command_id,
        "kind": "submit",
        "target": root_run_id(POLICY.deployment_id, SCOPE, command_id),
        "payload_digest": digest(request),
        "root_admission": {
            "version": 2,
            "manifest_digest": digest(manifest),
            "submission": {
                "version": 1,
                "request": request,
                "manifest": manifest,
                "task_queue": "ordinary-queue",
                "activity_timeout": 30,
            },
        },
    }


def test_business_and_session_commands_use_one_collision_and_capacity_authority():
    registry = state()
    ordinary = ordinary_request("used")
    first = registry.reserve(ordinary)
    with pytest.raises(IdempotencyConflict):
        registry.reserve(command("used"))
    registry.reserve(command("zero-root"))
    value, request = intent_request(registry)
    with pytest.raises(CapacityExceeded):
        registry.prepare_session_root(request, value)
    assert registry.reserve(ordinary) == first
    assert len(registry.roots) == 1 and len(registry.commands) == 3


def test_fencing_conflicted_intent_preserves_other_accepted_business_root():
    registry = state()
    value, request = intent_request(registry)
    other = ordinary_request(value["run_command_id"])
    first = registry.reserve(other)
    refused = refusal_request(value)
    registry.commit_session_never_claimed(refused, refusal_verification(refused, request))
    assert registry.reserve(other) == first
    assert len(registry.roots) == 1 and len(registry.commands) == 2
    assert (
        registry.roots[digest([SCOPE, value["run_command_id"]])]["request_digest"]
        == other["payload_digest"]
    )


@pytest.mark.parametrize("kind", ["submit", "rebind"])
def test_nonopen_session_commands_keep_exact_first_envelope_with_zero_roots(kind):
    registry, request = state(), command()
    value = deployment_intent()
    payload = {
        "kind": kind,
        "scope": SCOPE,
        "command_id": "next",
        "session_ref": value["session_ref"],
    }
    if kind == "submit":
        payload.update(input="task", budget=5)
        logical = payload
    else:
        payload.update(binding=value["binding"], expected_binding_revision=1)
        logical = {k: v for k, v in payload.items() if k != "binding"}
        logical["request"] = value["binding"]["request"]
    request.update(command_id="next", kind="session_" + kind, payload_digest=digest(logical))
    request["session_submission"].update(payload=payload, logical_payload=logical)
    request["session_submission"]["binding"] = value["binding"]
    first = registry.reserve(request)
    assert registry.reserve(request) == first
    assert (
        registry.deployment_session_command(lookup(request))["session_submission"]
        == request["session_submission"]
    )
    assert not registry.roots


def test_late_prepared_claim_refuses_conflicting_command_that_won_in_between():
    registry = state()
    value, request = intent_request(registry)
    registry.prepare_session_root(request, value)
    other = command(value["run_command_id"])
    first = registry.reserve(other)
    with pytest.raises(IdempotencyConflict):
        registry.commit_session_root(request, value, verified(value, request))
    assert registry.reserve(other) == first and not registry.roots


@pytest.mark.parametrize("mutation", ["origin", "envelope", "intent", "policy", "namespace"])
def test_root_prepare_rejects_altered_original_identity_without_claim(mutation):
    registry = state()
    value, request = intent_request(registry)
    changed = copy.deepcopy(request)
    if mutation == "origin":
        changed["root_admission"]["session_origin"]["coordinator_execution_epoch"] = "replacement"
    elif mutation == "envelope":
        changed["root_admission"]["submission"]["task_queue"] = "moved"
    elif mutation == "intent":
        value = copy.deepcopy(value)
        value["coordinator_execution_epoch"] = "replacement"
    elif mutation == "policy":
        changed["admission_policy"]["max_active_root_runs"] = 2
    else:
        changed["namespace"]["id"] = "22222222-2222-4222-8222-222222222222"
    with pytest.raises((DefinitionMismatch, ValidationError)):
        registry.prepare_session_root(changed, value)
    assert len(registry.commands) == 1 and not registry.roots


def test_first_session_binding_requires_full_ordinary_publication4():
    registry, request = state(), command()
    manifest = request["session_submission"]["payload"]["binding"]["manifest"]
    manifest.pop("deployment_admission_protocol")
    manifest.pop("session_deployment_protocol")
    with pytest.raises(DefinitionMismatch):
        registry.reserve(request)
    assert not registry.commands and not registry.roots


def test_descendant_control_revalidates_accepted_session_root_with_retained_origin():
    registry = state()
    value, request = intent_request(registry)
    root = registry.commit_session_root(request, value, verified(value, request))["root_admission"]
    registry.bind_deployment_root(
        {
            "scope": SCOPE,
            "admission_policy": POLICY.identity,
            "namespace": NAMESPACE,
            **{
                key: root[key]
                for key in (
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "execution_epoch": "original-run-epoch",
        }
    )
    control = {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "command_id": "approve-descendant",
        "kind": "approve",
        "target": "original-descendant",
        "payload_digest": digest({"original": "approval"}),
        "descendant": {
            "root_command_id": value["run_command_id"],
            "execution_epoch": "original-child-epoch",
        },
    }
    prepared = registry.prepare_deployment_control(control)
    assert prepared["submission"] == value["submission"]
    receipt = registry.commit_deployment_control(
        control,
        {
            "version": 1,
            "scope": SCOPE,
            "namespace": NAMESPACE,
            "target": "original-descendant",
            "target_execution_epoch": "original-child-epoch",
            "root_run_id": value["run_id"],
            "root_execution_epoch": "original-run-epoch",
        },
    )
    assert receipt["control_binding"]["root_run_id"] == value["run_id"]
    assert len(registry.roots) == 1 and len(registry.commands) == 3


def test_metadata2_cannot_introduce_new_session_turn_without_verified_commit():
    registry = state()
    value, request = intent_request(registry)
    unverified = copy.deepcopy(request)
    unverified["root_admission"].pop("session_origin")
    unverified["root_admission"]["version"] = 2
    with pytest.raises(DefinitionMismatch):
        registry.reserve(unverified)
    assert not registry.roots and len(registry.commands) == 1


@pytest.mark.parametrize("mutation", ["command_kind", "logical_request", "receipt_apply_state"])
def test_malformed_session_boundary_returns_typed_refusal_without_second_acceptance(mutation):
    registry, request = state(), command()
    if mutation == "command_kind":
        request["kind"] = []
    elif mutation == "logical_request":
        request["session_submission"]["logical_payload"]["request"] = None
        request["payload_digest"] = digest(request["session_submission"]["logical_payload"])
    else:
        registry.reserve(request)
        receipt_request = {
            key: request[key]
            for key in ("scope", "admission_policy", "namespace", "command_id", "payload_digest")
        }
        receipt_request["receipt"] = {
            "command_id": "open",
            "kind": "session_open",
            "run_id": None,
            "record_state": "durably_recorded",
            "apply_state": [],
            "outcome": {},
        }
        with pytest.raises((ValidationError, DefinitionMismatch)):
            registry.prepare_session_receipt(receipt_request)
        assert registry.deployment_session_command(lookup(request))["session_receipt"] is None
        return
    with pytest.raises((ValidationError, DefinitionMismatch)):
        registry.reserve(request)
    assert not registry.commands and not registry.roots


def test_submit_command_keeps_full_original_binding_and_refuses_replaced_binding():
    registry = state()
    value, request = intent_request(registry)
    command_key = digest([SCOPE, value["session_command_id"]])
    assert (
        registry.session_commands[command_key]["session_submission"]["binding"] == value["binding"]
    )
    changed_registry = state()
    changed = copy.deepcopy(registry.session_commands[command_key]["session_submission"])
    changed["binding"]["task_queue"] = "moved"
    payload = changed["payload"]
    with pytest.raises(DefinitionMismatch):
        changed_registry.reserve(
            {
                "scope": SCOPE,
                "admission_policy": POLICY.identity,
                "namespace": NAMESPACE,
                "command_id": payload["command_id"],
                "kind": "session_submit",
                "target": value["coordinator_id"],
                "payload_digest": digest(changed["logical_payload"]),
                "session_submission": changed,
            }
        )
    assert not changed_registry.commands


def test_internal_root_verification_is_exact_json_not_boolean_integer_alias():
    registry = state()
    value, request = intent_request(registry)
    verification = copy.deepcopy(verified(value, request))
    verification["intent"]["turn_seq"] = True
    with pytest.raises(DefinitionMismatch):
        registry.commit_session_root(request, value, verification)
    assert not registry.roots


def test_internal_receipt_verification_is_exact_json():
    registry, request = state(), command()
    registry.reserve(request)
    payload = {
        key: request[key]
        for key in ("scope", "admission_policy", "namespace", "command_id", "payload_digest")
    }
    payload["receipt"] = {
        "command_id": "open",
        "kind": "session_open",
        "run_id": None,
        "record_state": "durably_recorded",
        "apply_state": "applied",
        "outcome": {"binding_revision": 1},
    }
    verification = registry.prepare_session_receipt(payload)
    verification["receipt"]["outcome"]["binding_revision"] = True
    with pytest.raises(DefinitionMismatch):
        registry.commit_session_receipt(payload, verification)
    assert registry.deployment_session_command(lookup(request))["session_receipt"] is None


def close_request(manifest):
    return {
        "scope": SCOPE,
        "admission_policy": POLICY.identity,
        "namespace": NAMESPACE,
        "manifest_digest": digest(manifest),
    }


def test_close_inventory_includes_zero_root_original_envelope_and_keeps_duplicates():
    registry, request = state(), command()
    first = registry.reserve(request)
    closing = close_request(request["session_submission"]["binding"]["manifest"])
    result = registry.close_deployment_sessions(closing)
    assert result == {
        "manifest_digest": closing["manifest_digest"],
        "close_requested": True,
        "candidates": [registry.deployment_session_command(lookup(request))],
    }
    result["candidates"][0]["session_submission"]["binding"]["task_queue"] = "changed"
    assert (
        registry.close_deployment_sessions(closing)["candidates"][0]["session_submission"][
            "binding"
        ]["task_queue"]
        == "original-queue"
    )
    assert registry.reserve(request) == first
    with pytest.raises(DefinitionMismatch, match="closed"):
        registry.reserve(command("fresh"))
    assert not registry.roots and len(registry.commands) == 1


def test_close_blocks_late_prepared_claim_but_preserves_exact_accepted_claim():
    registry = state()
    value, request = intent_request(registry)
    registry.prepare_session_root(request, value)
    closing = close_request(value["binding"]["manifest"])
    registry.close_deployment_sessions(closing)
    with pytest.raises(DefinitionMismatch, match="closed"):
        registry.commit_session_root(request, value, verified(value, request))
    assert not registry.roots and len(registry.commands) == 1
    another = state()
    value, request = intent_request(another)
    original = another.commit_session_root(request, value, verified(value, request))
    another.close_deployment_sessions(close_request(value["binding"]["manifest"]))
    assert another.commit_session_root(request, value, None) == original
    assert len(another.roots) == 1


def test_close_is_scope_and_publication_bound_without_changing_ordinary_roots():
    registry, request = state(), command()
    registry.reserve(request)
    closing = close_request(request["session_submission"]["binding"]["manifest"])
    other_scope = {"workspace": "other", "principal": "owner"}
    registry.close_deployment_sessions({**closing, "scope": other_scope})
    assert registry.reserve(command("same-scope-fresh"))["command_id"] == "same-scope-fresh"
    registry.close_deployment_sessions(closing)
    other = command("other-publication")
    binding = other["session_submission"]["binding"]
    binding["manifest"]["providers"]["default"] = EchoProvider("other-publication").identity
    other["session_submission"]["payload"]["binding"] = copy.deepcopy(binding)
    assert registry.reserve(other)["command_id"] == "other-publication"
    assert registry.reserve(ordinary_request())["command_id"] == "ordinary"
    assert len(registry.roots) == 1
