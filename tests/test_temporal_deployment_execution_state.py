"""Original History admission and immutable inherited child authority."""

import copy
import importlib
from types import SimpleNamespace

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.governance import TemporalExecutionPolicy
from ralf_agent.types import digest
from tests.test_temporal_deployment_protocol import POLICY, manifest

SCOPE = {"workspace": "workspace", "principal": "principal"}
NAMESPACE = {"name": "execution-state", "id": "12345678-1234-5678-1234-567812345678"}


@pytest.fixture
def api():
    name = "ralf_agent.temporal_deployment_execution_state"
    assert importlib.util.find_spec(name) is not None, "Original execution admission is missing"
    return importlib.import_module(name)


def state():
    return SimpleNamespace(
        scope=copy.deepcopy(SCOPE),
        run_id="ralf-temporal-" + digest([POLICY["deployment_id"], SCOPE, "root-command"]),
        epoch="root-epoch",
        request={"definition": {"kind": "agent"}, "input": "original"},
        manifest=manifest(),
        receipts={"root-command": {"kind": "submit"}},
    )


def metadata(current):
    proof = {
        "version": 1,
        "registry_id": current.manifest["deployment_admission_protocol"]["registry_id"],
        "scope": copy.deepcopy(SCOPE),
        "command_id": "root-command",
        "run_id": current.run_id,
        "request_digest": digest(current.request),
        "manifest_digest": digest(current.manifest),
        "namespace": copy.deepcopy(NAMESPACE),
    }
    return {
        "version": 1,
        "root": {
            **proof,
            "proof_digest": digest(proof),
            "state": "held-unbound",
            "execution_epoch": None,
        },
        "lineage": [],
    }


def initialize(api, current, value=None, **kwargs):
    api.initialize(
        current,
        metadata(current) if value is None else value,
        namespace=NAMESPACE["name"],
        epoch=current.epoch,
        original_epoch=current.epoch,
        parent=None,
        **kwargs,
    )


def response(current, value):
    root = {**copy.deepcopy(value["root"]), "state": "held-bound", "execution_epoch": "root-epoch"}
    proof = {
        "version": 1,
        "run_id": current.run_id,
        "execution_epoch": current.epoch,
        "root": root,
        "metadata_digest": digest(value),
    }
    return {**proof, "proof_digest": digest(proof)}


def test_default_metadata_is_harmless_but_unselected_presence_is_refused(api):
    current = state()
    value = metadata(current)
    current.manifest.pop("deployment_admission_protocol")
    before = copy.deepcopy(vars(current))
    api.initialize(
        current, None, namespace="default", epoch="epoch", original_epoch="epoch", parent=None
    )
    assert vars(current) == before
    assert api.admitted(current)
    with pytest.raises(DefinitionMismatch):
        api.initialize(
            current, value, namespace="default", epoch="epoch", original_epoch="epoch", parent=None
        )


def test_root_initialization_detaches_metadata_and_never_changes_request(api):
    assert getattr(api, "ACTIVITY", None) == "ralf.temporal.deployment-admission.v1"
    transport = importlib.import_module("ralf_agent.temporal_deployment_execution")
    assert api.ACTIVITY == transport.ACTIVITY
    current = state()
    value = metadata(current)
    request = copy.deepcopy(current.request)
    initialize(api, current, value)
    value["root"]["scope"]["workspace"] = "mutated"
    assert current.deployment_admission["root"]["scope"] == SCOPE
    assert current.request == request
    assert current.deployment_original_epoch == "root-epoch"
    assert current.deployment_namespace == NAMESPACE["name"]
    assert current.deployment_sdk_parent is None
    assert current.deployment_receipt is None
    assert not api.admitted(current)
    proof = api.view(current)
    assert set(proof) == {
        "version",
        "scope",
        "run_id",
        "command_id",
        "execution_epoch",
        "original_execution_epoch",
        "namespace",
        "request",
        "request_digest",
        "manifest",
        "manifest_digest",
        "admission",
        "admission_receipt",
        "children",
        "proof_digest",
    }
    assert proof["namespace"] == NAMESPACE
    assert proof["command_id"] == "root-command"
    assert proof["request_digest"] == digest(request)
    assert proof["proof_digest"] == digest({k: v for k, v in proof.items() if k != "proof_digest"})
    proof["request"]["input"] = "mutated"
    assert current.request == request
    activity = api.activity_request(current)
    assert set(activity) == {
        "scope",
        "run_id",
        "execution_epoch",
        "command_id",
        "request",
        "runtime_manifest",
        "deployment_admission",
    }
    assert activity["deployment_admission"] == current.deployment_admission


@pytest.mark.parametrize(
    "change",
    [
        lambda v: v.update(version=True),
        lambda v: v.update(extra="foreign"),
        lambda v: v["root"].update(extra="foreign"),
        lambda v: v["root"].update(state="held-bound"),
        lambda v: v["root"].update(execution_epoch="root-epoch"),
        lambda v: v["root"].update(proof_digest="a" * 64),
        lambda v: v["root"].update(request_digest="a" * 64),
        lambda v: v["root"].update(manifest_digest="a" * 64),
        lambda v: v["root"].update(registry_id="foreign"),
        lambda v: v["root"]["scope"].update(principal="foreign"),
        lambda v: v["root"]["namespace"].update(id="bad-uuid"),
        lambda v: v.update(lineage={}),
    ],
)
def test_invalid_original_metadata_is_refused_without_partial_adoption(api, change):
    current = state()
    before = copy.deepcopy(vars(current))
    value = metadata(current)
    change(value)
    with pytest.raises((DefinitionMismatch, ValidationError)):
        initialize(api, current, value)
    assert vars(current) == before


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "namespace": "foreign",
            "epoch": "root-epoch",
            "original_epoch": "root-epoch",
            "parent": None,
        },
        {
            "namespace": NAMESPACE["name"],
            "epoch": "replacement",
            "original_epoch": "root-epoch",
            "parent": None,
        },
        {
            "namespace": NAMESPACE["name"],
            "epoch": "root-epoch",
            "original_epoch": "root-epoch",
            "parent": {
                "namespace": NAMESPACE["name"],
                "workflow_id": "foreign",
                "run_id": "foreign",
            },
        },
    ],
)
def test_root_requires_actual_original_sdk_tuple(api, kwargs):
    current = state()
    with pytest.raises((DefinitionMismatch, ValidationError)):
        api.initialize(current, metadata(current), **kwargs)


def test_selected_metadata_is_required_and_session_coordinator_turn_is_refused(api):
    current = state()
    with pytest.raises(DefinitionMismatch):
        api.initialize(
            current,
            None,
            namespace=NAMESPACE["name"],
            epoch=current.epoch,
            original_epoch=current.epoch,
            parent=None,
        )
    current.request["session_turn"] = {"turn_id": "coordinator"}
    with pytest.raises(DefinitionMismatch):
        initialize(api, current)


def test_adoption_requires_exact_sha_bound_root_and_is_idempotent(api):
    current = state()
    value = metadata(current)
    initialize(api, current, value)
    good = response(current, value)
    for change in (
        lambda v: v.update(admitted=True),
        lambda v: v.update(version=True),
        lambda v: v.update(metadata_digest="b" * 64),
        lambda v: v.update(execution_epoch="replacement"),
        lambda v: v["root"].update(execution_epoch="replacement"),
        lambda v: v["root"].update(state="held-unbound"),
        lambda v: v.update(proof_digest="b" * 64),
    ):
        bad = copy.deepcopy(good)
        change(bad)
        with pytest.raises((DefinitionMismatch, ValidationError)):
            api.adopt(current, bad)
        assert not api.admitted(current)
    api.adopt(current, good)
    assert api.admitted(current)
    api.adopt(current, copy.deepcopy(good))
    good["root"]["scope"]["principal"] = "mutated"
    assert current.deployment_receipt["root"]["scope"] == SCOPE


def child_intent(parent):
    return {
        "id": "0:child",
        "call_id": "child",
        "run_id": "child-run",
        "command_id": "child-command",
        "request": {"definition": {"kind": "agent"}, "input": "child"},
        "started": False,
        "dispatch_started": False,
    }


def prepared_parent(api):
    parent = state()
    parent.request["definition"]["kind"] = "graph"
    parent.children = []
    value = metadata(parent)
    initialize(api, parent, value)
    call = child_intent(parent)
    parent.children.append(call)
    return parent, call, value


def test_child_projection_requires_original_admitted_intent_and_preserves_requests(api):
    parent, call, value = prepared_parent(api)
    original = copy.deepcopy(call["request"])
    with pytest.raises(DefinitionMismatch):
        api.project_child(parent, call)
    api.adopt(parent, response(parent, value))
    projected = api.project_child(parent, copy.deepcopy(call))
    assert projected["root"] == value["root"]
    assert projected["lineage"] == [
        {
            "parent_run_id": parent.run_id,
            "parent_execution_epoch": parent.epoch,
            "parent_request_digest": digest(parent.request),
            "parent_manifest_digest": digest(parent.manifest),
            "call_id": "0:child",
            "child_run_id": "child-run",
            "child_command_id": "child-command",
            "child_request_digest": digest(original),
        }
    ]
    assert call["request"] == original
    bad = copy.deepcopy(call)
    bad["request"]["input"] = "forged"
    with pytest.raises(DefinitionMismatch):
        api.project_child(parent, bad)


def test_child_initialization_requires_connected_path_and_exact_sdk_parent(api):
    parent, call, value = prepared_parent(api)
    api.adopt(parent, response(parent, value))
    projected = api.project_child(parent, call)
    child = SimpleNamespace(
        run_id=call["run_id"],
        epoch="child-epoch",
        scope=copy.deepcopy(SCOPE),
        request=copy.deepcopy(call["request"]),
        manifest=copy.deepcopy(parent.manifest),
        receipts={"child-command": {"kind": "submit"}},
    )
    kwargs = {
        "namespace": NAMESPACE["name"],
        "epoch": "child-epoch",
        "original_epoch": "child-epoch",
        "parent": {
            "namespace": NAMESPACE["name"],
            "workflow_id": parent.run_id,
            "run_id": parent.epoch,
        },
    }
    api.initialize(child, projected, **kwargs)
    api.adopt(child, response(child, projected))
    assert api.admitted(child)
    for field in (
        "parent_run_id",
        "child_run_id",
        "child_command_id",
        "child_request_digest",
        "parent_manifest_digest",
    ):
        changed = copy.deepcopy(projected)
        changed["lineage"][0][field] = "b" * 64 if "digest" in field else "foreign"
        with pytest.raises((DefinitionMismatch, ValidationError)):
            api.initialize(child, changed, **kwargs)
    kwargs["parent"]["run_id"] = "replacement"
    with pytest.raises(DefinitionMismatch):
        api.initialize(child, projected, **kwargs)


def test_depth_cycle_and_extra_link_fields_cannot_authorize_child(api):
    parent = state()
    parent.request["definition"]["kind"] = "graph"
    parent.children = []
    parent.manifest["execution_policy"] = TemporalExecutionPolicy(max_depth=1).identity
    value = metadata(parent)
    initialize(api, parent, value)
    api.adopt(parent, response(parent, value))
    call = child_intent(parent)
    parent.children.append(call)
    with pytest.raises(ValidationError):
        api.project_child(parent, call)
    parent, call, value = prepared_parent(api)
    api.adopt(parent, response(parent, value))
    call["run_id"] = parent.run_id
    with pytest.raises((DefinitionMismatch, ValidationError)):
        api.project_child(parent, call)


def test_child_epoch_pin_requires_dispatch_and_metadata_then_is_immutable(api):
    parent, call, value = prepared_parent(api)
    api.adopt(parent, response(parent, value))
    call["deployment_admission"] = api.project_child(parent, call)
    payload = {
        "scope": copy.deepcopy(SCOPE),
        "parent_run_id": parent.run_id,
        "parent_execution_epoch": parent.epoch,
        "child_run_id": call["run_id"],
        "child_execution_epoch": "child-epoch",
        "child_request_digest": digest(call["request"]),
        "metadata_digest": digest(call["deployment_admission"]),
    }
    with pytest.raises(DefinitionMismatch):
        api.pin_child(parent, payload)
    call["dispatch_started"] = True
    assert api.pin_child(parent, payload) == {"run_id": "child-run", "recorded": True}
    assert api.pin_child(parent, payload) == {"run_id": "child-run", "recorded": True}
    assert call["deployment_execution_epoch"] == "child-epoch"
    for field in (
        "parent_run_id",
        "parent_execution_epoch",
        "child_run_id",
        "child_execution_epoch",
        "child_request_digest",
        "metadata_digest",
    ):
        bad = copy.deepcopy(payload)
        bad[field] = "foreign"
        with pytest.raises((DefinitionMismatch, ValidationError)):
            api.pin_child(parent, bad)
    assert call["deployment_execution_epoch"] == "child-epoch"
    proof = api.view(parent)
    assert proof["children"][0]["deployment_execution_epoch"] == "child-epoch"
    proof["children"][0]["deployment_execution_epoch"] = "mutated"
    assert call["deployment_execution_epoch"] == "child-epoch"


def test_initialize_retry_preserves_receipt_and_refuses_metadata_replacement(api):
    current = state()
    value = metadata(current)
    initialize(api, current, value)
    accepted = response(current, value)
    api.adopt(current, accepted)
    initialize(api, current, copy.deepcopy(value))
    assert current.deployment_receipt == accepted
    forged = copy.deepcopy(value)
    forged["root"]["namespace"]["id"] = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    proof = {
        k: v
        for k, v in forged["root"].items()
        if k not in {"state", "execution_epoch", "proof_digest"}
    }
    forged["root"]["proof_digest"] = digest(proof)
    with pytest.raises(DefinitionMismatch):
        initialize(api, current, forged)
    assert current.deployment_receipt == accepted


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["lineage"][0].update(extra="foreign"),
        lambda value: value["lineage"][0].update(parent_execution_epoch=""),
        lambda value: value["lineage"][0].update(child_run_id=value["root"]["run_id"]),
        lambda value: value["lineage"][0].update(parent_request_digest="a" * 64),
        lambda value: value.update(lineage=value["lineage"] * 8),
    ],
)
def test_malformed_bounded_ancestry_refuses_before_state_write(api, change):
    parent, call, value = prepared_parent(api)
    api.adopt(parent, response(parent, value))
    projected = api.project_child(parent, call)
    child = SimpleNamespace(
        run_id=call["run_id"],
        epoch="child-epoch",
        scope=copy.deepcopy(SCOPE),
        request=copy.deepcopy(call["request"]),
        manifest=copy.deepcopy(parent.manifest),
        receipts={"child-command": {"kind": "submit"}},
    )
    before = copy.deepcopy(vars(child))
    change(projected)
    with pytest.raises((DefinitionMismatch, ValidationError)):
        api.initialize(
            child,
            projected,
            namespace=NAMESPACE["name"],
            epoch=child.epoch,
            original_epoch=child.epoch,
            parent={
                "namespace": NAMESPACE["name"],
                "workflow_id": parent.run_id,
                "run_id": parent.epoch,
            },
        )
    assert vars(child) == before
