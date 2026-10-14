"""Original Registry admission must be atomic, scoped and permanently held."""

import copy

import pytest

from ralf_agent.errors import (
    AuthorizationDenied,
    CapacityExceeded,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from ralf_agent.temporal_state import TemporalCommandRegistryState
from ralf_agent.types import digest

POLICY = {
    "kind": "deployment-admission-policy",
    "deployment_id": "state-deployment",
    "version": "original",
    "max_active_root_runs": 2,
    "max_active_root_runs_per_scope": 1,
}
NAMESPACE = {"name": "state-test", "id": "12345678-1234-5678-1234-567812345678"}
SCOPE = {"workspace": "workspace-a", "principal": "principal-a"}
OTHER = {"workspace": "workspace-b", "principal": "principal-b"}


def registry(**kwargs):
    return TemporalCommandRegistryState(
        admission_policy=copy.deepcopy(POLICY), namespace=copy.deepcopy(NAMESPACE), **kwargs
    )


def submit(command_id="command-a", scope=SCOPE):
    return {
        "scope": copy.deepcopy(scope),
        "command_id": command_id,
        "kind": "submit",
        "target": "ralf-temporal-" + digest(["state-deployment", scope, command_id]),
        "payload_digest": "a" * 64,
        "admission_policy": copy.deepcopy(POLICY),
        "namespace": copy.deepcopy(NAMESPACE),
        "root_admission": {"version": 1, "manifest_digest": "b" * 64},
    }


def view(state, scope=SCOPE):
    return state.deployment_admission(
        {
            "kind": "deployment_admission",
            "scope": copy.deepcopy(scope),
            "admission_policy": copy.deepcopy(POLICY),
            "namespace": copy.deepcopy(NAMESPACE),
        }
    )


def binding(receipt, epoch="sdk-epoch-original"):
    root = receipt["root_admission"]
    return {
        **{
            k: copy.deepcopy(root[k])
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
        "admission_policy": copy.deepcopy(POLICY),
        "execution_epoch": epoch,
    }


def test_atomic_scope_refusal_leaves_no_command_or_root_and_full_duplicate_keeps_first_release():
    state = registry()
    request = submit()
    original = state.reserve(request)
    before = view(state)
    with pytest.raises(CapacityExceeded):
        state.reserve(submit("refused"))
    assert view(state) == before
    state.reserve(submit(scope=OTHER))
    moved = copy.deepcopy(request)
    moved["root_admission"]["manifest_digest"] = "c" * 64
    assert state.reserve(moved) == original
    assert view(state)["counts"] == {
        "held_root_runs": 2,
        "held_root_runs_for_scope": 1,
        "command_records": 2,
    }


def test_same_command_across_scopes_is_independent_and_view_has_no_foreign_locators():
    state = registry()
    own = state.reserve(submit())
    foreign = state.reserve(submit(scope=OTHER))
    assert own["target"] != foreign["target"]
    observed = view(state)
    assert len(observed["held_roots"]) == 1
    assert observed["held_roots"][0]["run_id"] == own["target"]
    assert foreign["target"] not in str(observed)
    assert OTHER["principal"] not in str(observed)
    assert OTHER["workspace"] not in str(observed)


def test_full_capacity_allows_controls_only_for_original_root_in_same_scope():
    state = registry()
    root = state.reserve(submit())
    state.reserve(submit(scope=OTHER))
    control = submit("cancel-a")
    control.pop("root_admission")
    control.update(kind="cancel", target=root["target"])
    assert state.reserve(control)["apply_state"] == "not_applied"
    assert state.reserve(control)["target"] == root["target"]
    before = view(state)
    foreign = copy.deepcopy(control)
    foreign.update(command_id="foreign-control", scope=copy.deepcopy(OTHER))
    with pytest.raises(AuthorizationDenied):
        state.reserve(foreign)
    unknown = copy.deepcopy(control)
    unknown.update(command_id="unknown-control", target="unknown-root")
    with pytest.raises(AuthorizationDenied):
        state.reserve(unknown)
    assert view(state) == before
    assert before["counts"]["held_root_runs"] == 2
    assert before["counts"]["command_records"] == 3


def test_cumulative_command_capacity_is_separate_and_duplicates_survive_it():
    state = registry(capacity=1)
    original = state.reserve(submit())
    with pytest.raises(ValidationError):
        state.reserve(submit(scope=OTHER))
    assert state.reserve(submit()) == original
    assert view(state)["counts"]["command_records"] == 1


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("target", "wrong-derived-root", DefinitionMismatch),
        ("payload_digest", "not-sha", ValidationError),
        ("scope", {"workspace": "workspace-a", "principal": ""}, ValidationError),
        ("scope", {**SCOPE, "extra": True}, ValidationError),
        ("kind", "submit_child", ValidationError),
        ("admission_policy", {**POLICY, "version": "moved"}, DefinitionMismatch),
        (
            "namespace",
            {**NAMESPACE, "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
            DefinitionMismatch,
        ),
        ("root_admission", {"version": True, "manifest_digest": "b" * 64}, ValidationError),
        ("root_admission", {"version": 1, "manifest_digest": "wrong"}, ValidationError),
    ],
)
def test_invalid_fresh_reservation_does_not_consume_identity(field, value, error):
    state = registry()
    before = view(state)
    request = submit()
    request[field] = value
    with pytest.raises(error):
        state.reserve(request)
    assert view(state) == before
    assert state.reserve(submit())["record_state"] == "durably_recorded"


def test_request_exactness_and_duplicate_identity_conflicts_do_not_mutate():
    state = registry()
    original = state.reserve(submit())
    before = view(state)
    for field in ("kind", "target", "payload_digest"):
        changed = submit()
        changed[field] = {"kind": "cancel", "target": "other-root", "payload_digest": "d" * 64}[
            field
        ]
        if field == "kind":
            changed.pop("root_admission")
        with pytest.raises(IdempotencyConflict):
            state.reserve(changed)
    for change in (
        {"coding_composition": {}},
        {"root_admission": {"version": 1, "manifest_digest": "bad"}},
    ):
        with pytest.raises(ValidationError):
            state.reserve({**submit(), **change})
    assert view(state) == before
    assert state.reserve(submit()) == original


def test_binding_pins_first_epoch_and_original_manifest_request_namespace_proof():
    state = registry()
    original = state.reserve(submit())
    root = original["root_admission"]
    assert root["state"] == "held-unbound"
    assert root["execution_epoch"] is None
    assert root["request_digest"] == "a" * 64
    assert root["manifest_digest"] == "b" * 64
    bound = state.bind_deployment_root(binding(original))
    assert bound["state"] == "held-bound"
    assert bound["execution_epoch"] == "sdk-epoch-original"
    assert state.bind_deployment_root(binding(original)) == bound
    before = view(state)
    for field, value in (
        ("execution_epoch", "replacement"),
        ("manifest_digest", "c" * 64),
        ("request_digest", "d" * 64),
        ("proof_digest", "e" * 64),
        ("run_id", "foreign-root"),
        ("command_id", "foreign-command"),
        ("scope", OTHER),
        ("namespace", {**NAMESPACE, "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}),
        ("admission_policy", {**POLICY, "version": "replacement"}),
    ):
        request = binding(original)
        request[field] = value
        with pytest.raises(DefinitionMismatch):
            state.bind_deployment_root(request)
        assert view(state) == before
    assert state.reserve(submit()) == original


def test_caller_mutation_cannot_change_held_root_receipts_or_pinned_policy():
    state = registry()
    request = submit()
    original = state.reserve(request)
    before = view(state)
    request["scope"]["principal"] = "mutated"
    original["root_admission"]["namespace"]["name"] = "mutated"
    observed = view(state)
    observed["held_roots"][0]["state"] = "released"
    observed["policy"]["max_active_root_runs"] = 999
    assert view(state) == before
    assert state.reserve(submit())["root_admission"]["namespace"] == NAMESPACE


@pytest.mark.parametrize("missing", list(POLICY))
def test_initialization_requires_complete_policy_identity(missing):
    policy = copy.deepcopy(POLICY)
    policy.pop(missing)
    with pytest.raises(ValidationError):
        TemporalCommandRegistryState(admission_policy=policy, namespace=NAMESPACE)


@pytest.mark.parametrize(
    "namespace",
    [
        None,
        {"name": "state-test"},
        {**NAMESPACE, "id": "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"},
        {**NAMESPACE, "id": "invalid"},
        {**NAMESPACE, "extra": True},
    ],
)
def test_initialization_rejects_incomplete_or_noncanonical_namespace(namespace):
    with pytest.raises((ValidationError, DefinitionMismatch)):
        TemporalCommandRegistryState(admission_policy=POLICY, namespace=namespace)


def test_selected_mode_refuses_old_composition_routes_and_unknown_queries():
    state = registry()
    state.reserve(submit())
    before = view(state)
    for invoke in (
        lambda: state.composition_candidates("b" * 64),
        lambda: state.close_composition_submissions("b" * 64),
        lambda: state.composition_admission("command-a", "root", "a" * 64, "b" * 64),
        lambda: state.bind_composition_submission(
            "command-a", "root", "a" * 64, "b" * 64, "epoch", NAMESPACE
        ),
    ):
        with pytest.raises(DefinitionMismatch):
            invoke()
    with pytest.raises(ValidationError):
        state.deployment_admission({"kind": "all_roots"})
    assert view(state) == before


def test_stable_ids_exclude_policy_queue_and_separate_scopes_and_deployments():
    from ralf_agent.temporal_deployment_admission import registry_id, root_run_id

    assert registry_id("state-deployment") == "ralf-temporal-deployment-" + digest(
        "state-deployment"
    )
    assert root_run_id("state-deployment", SCOPE, "command-a") == submit()["target"]
    assert root_run_id("state-deployment", OTHER, "command-a") != submit()["target"]
    assert root_run_id("different-deployment", SCOPE, "command-a") != submit()["target"]


@pytest.mark.parametrize("kind", [[], {}, None, True, 1])
def test_malformed_command_kind_is_a_typed_refusal_without_mutation(kind):
    state = registry()
    before = view(state)
    request = submit()
    request["kind"] = kind
    with pytest.raises(ValidationError):
        state.reserve(request)
    assert view(state) == before


def test_total_limit_applies_across_fresh_scopes_without_retaining_refusal():
    state = registry()
    state.reserve(submit())
    state.reserve(submit(scope=OTHER))
    third = {"workspace": "third-workspace", "principal": "third-principal"}
    before = view(state, third)
    with pytest.raises(CapacityExceeded):
        state.reserve(submit("third-command", third))
    assert view(state, third) == before
    assert before["held_roots"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("admission_policy", {**POLICY, "version": "changed"}),
        ("namespace", {**NAMESPACE, "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}),
    ],
)
def test_full_duplicate_still_requires_original_policy_and_namespace(field, value):
    state = registry()
    state.reserve(submit())
    state.reserve(submit(scope=OTHER))
    before = view(state)
    request = submit()
    request[field] = value
    with pytest.raises(DefinitionMismatch):
        state.reserve(request)
    assert view(state) == before


@pytest.mark.parametrize("epoch", ["", " " * 10, "x" * 1025, True, None])
def test_invalid_sdk_epoch_does_not_bind_original_root(epoch):
    state = registry()
    receipt = state.reserve(submit())
    before = view(state)
    with pytest.raises(ValidationError):
        state.bind_deployment_root(binding(receipt, epoch))
    assert view(state) == before


def test_constructor_refuses_combining_default_scope_and_selected_deployment():
    with pytest.raises(ValidationError):
        registry(scope=SCOPE)
