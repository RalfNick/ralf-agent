"""Pure original Registry controls consume proof, never another root slot or SDK."""

import copy
import subprocess
import sys

import pytest

from relf_agent.errors import RalfError
from relf_agent.temporal_state import TemporalCommandRegistryState
from relf_agent.types import digest
from tests.test_temporal_deployment_coding_registry import coding_request
from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY, SCOPE, setup

MODES = ((2, 2), (3, 2), (3, 3))


def original(mode=(2, 2), *, capacity=4096, bound=True):
    protocol, publication = mode
    state = TemporalCommandRegistryState(
        admission_policy=POLICY.identity,
        namespace=NAMESPACE,
        admission_protocol=protocol,
        capacity=capacity,
    )
    _, root_request = setup()
    if publication == 3:
        root_request = coding_request()
    receipt = state.reserve(root_request)
    root = receipt["root_admission"]
    if bound:
        root = state.bind_deployment_root(
            {
                "scope": SCOPE,
                "admission_policy": POLICY.identity,
                "namespace": NAMESPACE,
                **{
                    name: root[name]
                    for name in (
                        "command_id",
                        "run_id",
                        "request_digest",
                        "manifest_digest",
                        "proof_digest",
                    )
                },
                "execution_epoch": "original-root-epoch",
            }
        )
    request = {
        "scope": copy.deepcopy(SCOPE),
        "command_id": "approve-child",
        "kind": "approve",
        "target": "original-child",
        "payload_digest": digest({"kind": "approve", "scope": SCOPE, "approved": True}),
        "admission_policy": POLICY.identity,
        "namespace": copy.deepcopy(NAMESPACE),
        "descendant": {"root_command_id": "one", "execution_epoch": "original-child-epoch"},
    }
    verification = {
        "version": 1,
        "scope": copy.deepcopy(SCOPE),
        "namespace": copy.deepcopy(NAMESPACE),
        "target": request["target"],
        "target_execution_epoch": "original-child-epoch",
        "root_run_id": root["run_id"],
        "root_execution_epoch": "original-root-epoch",
    }
    return state, root_request, root, request, verification


def query(request):
    return {
        **{name: copy.deepcopy(value) for name, value in request.items() if name != "descendant"},
        "kind": "deployment_control",
        "command_kind": request["kind"],
    }


def snapshot(state):
    return copy.deepcopy(vars(state.deployment))


def retire(state, root):
    """Exercise the existing atomic retirement with its fixed certificate DTO."""
    certificate = {
        "version": 1,
        **{
            name: copy.deepcopy(root[name])
            for name in (
                "scope",
                "run_id",
                "command_id",
                "namespace",
                "execution_epoch",
                "request_digest",
                "manifest_digest",
            )
        },
        "original_execution_epoch": root["execution_epoch"],
        "admission_digest": "a" * 64,
        "receipt_digest": "b" * 64,
        "terminal_state": "succeeded",
        "closure_digest": "c" * 64,
        "children": [],
    }
    certificate["proof_digest"] = digest(certificate)
    payload = {
        **{
            name: copy.deepcopy(root[name])
            for name in (
                "scope",
                "namespace",
                "command_id",
                "run_id",
                "execution_epoch",
                "request_digest",
                "manifest_digest",
                "proof_digest",
            )
        },
        "admission_policy": POLICY.identity,
        "certificate": certificate,
    }
    state.commit_deployment_release(payload, {"root": root, "certificate": certificate})


@pytest.mark.parametrize("mode", MODES)
def test_prepare_is_read_only_and_pins_first_envelope_without_root_occupancy(mode):
    state, root_request, root, request, _ = original(mode)
    before = snapshot(state)
    assert state.deployment_control(query(request)) is None
    prepared = state.prepare_deployment_control(request)
    assert prepared == {
        "request": {name: value for name, value in request.items() if name != "descendant"},
        "root": root,
        "submission": root_request["root_admission"]["submission"],
        "target_execution_epoch": "original-child-epoch",
    }
    prepared["root"]["scope"]["principal"] = "changed"
    prepared["submission"]["task_queue"] = "moved-alias-queue"
    assert snapshot(state) == before


@pytest.mark.parametrize("mode", MODES)
def test_only_verified_commit_records_one_command_and_separate_binding(mode):
    state, _, root, request, verification = original(mode)
    before_roots = copy.deepcopy(state.deployment.roots)
    before_submissions = copy.deepcopy(state.deployment.submissions)
    with pytest.raises(RalfError):
        state.reserve(request)
    assert len(state.deployment.commands) == 1
    receipt = state.commit_deployment_control(request, verification)
    base = {
        "command_id": request["command_id"],
        "target": request["target"],
        "record_state": "durably_recorded",
        "apply_state": "not_applied",
    }
    key = digest([SCOPE, request["command_id"]])
    assert receipt == {**base, "control_binding": verification}
    assert state.deployment.commands[key] == {
        "identity": {name: request[name] for name in ("kind", "target", "payload_digest")},
        "receipt": base,
    }
    assert state.deployment.control_bindings[key] == verification
    assert len(state.deployment.commands) == 2 and len(state.deployment.roots) == 1
    assert state.deployment.roots == before_roots
    assert state.deployment.submissions == before_submissions
    assert state.deployment_control(query(request)) == receipt
    receipt["control_binding"]["target_execution_epoch"] = "changed"
    verification["namespace"]["id"] = "changed"
    assert state.deployment_control(query(request))["control_binding"]["namespace"] == NAMESPACE
    assert state.deployment.roots[next(iter(before_roots))] == root


@pytest.mark.parametrize("mode", MODES)
def test_exact_duplicate_precedes_retirement_hints_capacity_and_verifier(mode):
    state, _, root, request, verification = original(mode, capacity=2)
    receipt = state.commit_deployment_control(request, verification)
    retire(state, root)
    assert not state.deployment.roots
    before = snapshot(state)
    for hint in (None, {}, {"root_command_id": "foreign", "execution_epoch": "reset"}):
        retry = {**request, "descendant": hint}
        assert state.prepare_deployment_control(retry) == {"receipt": receipt}
        assert state.commit_deployment_control(retry, {"caller": "forged"}) == receipt
        assert state.reserve(retry) == receipt
    without_hint = {k: v for k, v in request.items() if k != "descendant"}
    assert state.prepare_deployment_control(without_hint) == {"receipt": receipt}
    assert state.reserve(without_hint) == receipt
    assert state.deployment_control(query(request)) == receipt
    assert snapshot(state) == before


@pytest.mark.parametrize("mode", MODES)
def test_retirement_during_verification_rejects_fresh_commit_without_any_writes(mode):
    state, _, root, request, verification = original(mode)
    state.prepare_deployment_control(request)
    retire(state, root)
    before = snapshot(state)
    with pytest.raises(RalfError):
        state.commit_deployment_control(request, verification)
    assert snapshot(state) == before


@pytest.mark.parametrize("field", ["kind", "target", "payload_digest"])
def test_same_scoped_command_changed_identity_conflicts_before_hints(field):
    state, _, _, request, verification = original()
    state.commit_deployment_control(request, verification)
    changed = {
        **request,
        field: {"kind": "cancel", "target": "other", "payload_digest": "f" * 64}[field],
        "descendant": None,
    }
    before = snapshot(state)
    for operation in (
        lambda: state.prepare_deployment_control(changed),
        lambda: state.commit_deployment_control(changed, None),
        lambda: state.reserve(changed),
        lambda: state.deployment_control(query(changed)),
    ):
        with pytest.raises(RalfError) as error:
            operation()
        assert error.value.code == "idempotency_conflict"
    assert snapshot(state) == before


def test_submit_control_collision_never_uses_submission_receipt_as_control():
    state, _, _, request, verification = original()
    request["command_id"] = "one"
    before = snapshot(state)
    with pytest.raises(RalfError) as error:
        state.prepare_deployment_control(request)
    assert error.value.code == "idempotency_conflict"
    assert snapshot(state) == before


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "namespace",
        "target",
        "target_execution_epoch",
        "root_run_id",
        "root_execution_epoch",
        "version",
        "extra",
        "missing",
        "string_subclass",
    ],
)
def test_changed_or_caller_verification_rejects_atomically(field):
    state, _, _, request, verification = original()
    if field == "scope":
        verification[field]["principal"] = "foreign"
    elif field == "namespace":
        verification[field]["id"] = "22222222-2222-2222-2222-222222222222"
    elif field == "version":
        verification[field] = True
    elif field == "extra":
        verification["closed"] = True
    elif field == "missing":
        verification.pop("root_execution_epoch")
    elif field == "string_subclass":

        class Epoch(str):
            pass

        verification["target_execution_epoch"] = Epoch(verification["target_execution_epoch"])
    else:
        verification[field] = "changed"
    before = snapshot(state)
    with pytest.raises(RalfError):
        state.commit_deployment_control(request, verification)
    assert snapshot(state) == before


@pytest.mark.parametrize(
    "fault",
    [
        "no_hint",
        "hint_none",
        "hint_extra",
        "foreign_root",
        "root_target",
        "epoch_empty",
        "epoch_large",
        "command_large",
        "unbound",
        "namespace",
        "caller_proof",
    ],
)
def test_prepare_rejects_incomplete_hints_authority_and_original_root(fault):
    state, _, root, request, verification = original(bound=fault != "unbound")
    if fault == "no_hint":
        request.pop("descendant")
    elif fault == "hint_none":
        request["descendant"] = None
    elif fault == "hint_extra":
        request["descendant"]["proof"] = True
    elif fault == "foreign_root":
        request["descendant"]["root_command_id"] = "absent"
    elif fault == "root_target":
        request["target"] = root["run_id"]
    elif fault == "epoch_empty":
        request["descendant"]["execution_epoch"] = ""
    elif fault == "epoch_large":
        request["descendant"]["execution_epoch"] = "e" * 1025
    elif fault == "command_large":
        request["descendant"]["root_command_id"] = "r" * 1025
    elif fault == "namespace":
        request["namespace"]["id"] = "22222222-2222-2222-2222-222222222222"
    elif fault == "caller_proof":
        request["control_binding"] = verification
    before = snapshot(state)
    with pytest.raises(RalfError):
        state.prepare_deployment_control(request)
    assert snapshot(state) == before


@pytest.mark.parametrize("phase", ["prepare", "commit_after_await"])
def test_capacity_is_rechecked_before_both_writes(phase):
    state, _, root, request, verification = original(capacity=1 if phase == "prepare" else 2)
    if phase == "commit_after_await":
        state.prepare_deployment_control(request)
        state.reserve(
            {
                **{k: v for k, v in request.items() if k != "descendant"},
                "command_id": "root-drive",
                "kind": "drive",
                "target": root["run_id"],
            }
        )
    before = snapshot(state)
    with pytest.raises(RalfError):
        state.commit_deployment_control(request, verification)
    assert snapshot(state) == before


def test_read_only_query_is_scoped_and_does_not_create_any_record():
    state, _, _, request, verification = original()
    receipt = state.commit_deployment_control(request, verification)
    foreign = query(request)
    foreign["scope"]["principal"] = "other"
    before = snapshot(state)
    assert state.deployment_control(foreign) is None
    assert state.deployment_control(query(request)) == receipt
    assert snapshot(state) == before


@pytest.mark.parametrize(
    "fault",
    [
        "request",
        "manifest",
        "queue",
        "timeout",
        "version",
        "root_proof",
        "root_command",
        "submission_epoch",
    ],
)
def test_prepare_refuses_changed_first_acceptance_envelope_or_root(fault):
    state, _, _, request, _ = original()
    key = digest([SCOPE, "one"])
    record = state.deployment.submissions[key]
    if fault == "request":
        record["submission"]["request"]["input"] = "caller-replaced-task"
    elif fault == "manifest":
        record["submission"]["manifest"]["providers"] = {}
    elif fault == "queue":
        record["submission"]["task_queue"] = ""
    elif fault == "timeout":
        record["submission"]["activity_timeout"] = 0
    elif fault == "version":
        record["submission"]["version"] = True
    elif fault == "root_proof":
        state.deployment.roots[key]["proof_digest"] = "f" * 64
    elif fault == "root_command":
        state.deployment.commands[key]["identity"]["payload_digest"] = "f" * 64
    else:
        record["execution_epoch"] = "replacement-root"
    before = snapshot(state)
    with pytest.raises(RalfError):
        state.prepare_deployment_control(request)
    assert snapshot(state) == before


@pytest.mark.parametrize(
    "fault", ["extra", "missing", "query_kind", "control_kind", "digest", "namespace", "scope"]
)
def test_lookup_validates_exact_authority_before_returning_a_duplicate(fault):
    state, _, _, request, verification = original()
    state.commit_deployment_control(request, verification)
    payload = query(request)
    if fault == "extra":
        payload["control_binding"] = verification
    elif fault == "missing":
        payload.pop("command_kind")
    elif fault == "query_kind":
        payload["kind"] = "deployment_submission"
    elif fault == "control_kind":
        payload["command_kind"] = []
    elif fault == "digest":
        payload["payload_digest"] = "not-a-digest"
    elif fault == "namespace":
        payload["namespace"]["id"] = "22222222-2222-2222-2222-222222222222"
    else:
        payload["scope"]["principal"] = None
    before = snapshot(state)
    with pytest.raises(RalfError):
        state.deployment_control(payload)
    assert snapshot(state) == before


def test_concurrent_exact_commit_returns_saved_binding_before_new_verifier():
    state, _, _, request, verification = original()
    state.prepare_deployment_control(request)
    first = state.commit_deployment_control(request, verification)
    before = snapshot(state)
    assert state.commit_deployment_control(request, {"stale": "activity-reply"}) == first
    assert snapshot(state) == before


def test_pure_control_interfaces_do_not_import_optional_sdk():
    script = """
import importlib.abc
import sys
class NoSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'temporalio' or fullname.startswith('temporalio.'):
            raise AssertionError('Pure Registry imported optional SDK')
sys.meta_path.insert(0, NoSDK())
from tests.test_temporal_deployment_descendant_control_state import original, query
state, _, _, request, verification = original((3, 3))
assert state.deployment_control(query(request)) is None
assert 'root' in state.prepare_deployment_control(request)
receipt = state.commit_deployment_control(request, verification)
assert receipt['control_binding'] == verification
assert state.deployment_control(query(request)) == receipt
assert not any(name.startswith('temporalio') for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_original_root_fast_path_remains_four_fields_and_prepare_stays_read_only():
    state, _, root, request, _ = original()
    base = {k: v for k, v in request.items() if k != "descendant"}
    base["target"] = root["run_id"]
    before = snapshot(state)
    with pytest.raises(RalfError):
        state.prepare_deployment_control(base)
    assert snapshot(state) == before
    receipt = state.reserve(base)
    assert set(receipt) == {"command_id", "target", "record_state", "apply_state"}
    assert state.prepare_deployment_control(base) == {"receipt": receipt}
    assert state.deployment_control(query(base)) == receipt


@pytest.mark.parametrize("mode", ["private", "scoped"])
def test_new_control_delegates_refuse_private_and_default_modes(mode):
    state = (
        TemporalCommandRegistryState(scope=SCOPE)
        if mode == "scoped"
        else TemporalCommandRegistryState(admission_policy=POLICY.identity, namespace=NAMESPACE)
    )
    _, _, _, request, verification = original()
    for operation in (
        lambda: state.deployment_control(query(request)),
        lambda: state.prepare_deployment_control(request),
        lambda: state.commit_deployment_control(request, verification),
    ):
        with pytest.raises(RalfError):
            operation()
