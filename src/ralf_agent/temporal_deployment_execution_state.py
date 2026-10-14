"""Pure original-History deployment admission and inherited child intent."""

import copy

from .errors import DefinitionMismatch, ValidationError
from .governance import TemporalExecutionPolicy
from .temporal_deployment_admission import (
    _exact,
    _namespace,
    _scope,
    _sha,
    _text,
    root_run_id,
)
from .temporal_deployment_protocol import selected, validate_protocol
from .types import canonical, digest

ACTIVITY = "ralf.temporal.deployment-admission.v1"

ROOT_FIELDS = {
    "version",
    "registry_id",
    "scope",
    "command_id",
    "run_id",
    "request_digest",
    "manifest_digest",
    "namespace",
    "proof_digest",
    "state",
    "execution_epoch",
}
LINK_FIELDS = {
    "parent_run_id",
    "parent_execution_epoch",
    "parent_request_digest",
    "parent_manifest_digest",
    "call_id",
    "child_run_id",
    "child_command_id",
    "child_request_digest",
}


def _detached(value):
    canonical(value)
    return copy.deepcopy(value)


def _epoch(value):
    _text(value)
    if len(value) > 1024:
        raise ValidationError("Original SDK execution epoch exceeds its allowance")


def _command(state):
    commands = [key for key, receipt in state.receipts.items() if receipt.get("kind") == "submit"]
    if len(commands) != 1:
        raise DefinitionMismatch("Original submission command is unavailable")
    _text(commands[0])
    return commands[0]


def _root(value, *, bound=False):
    _exact(value, ROOT_FIELDS)
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValidationError("Invalid original root version")
    for field in ("registry_id", "command_id", "run_id"):
        _text(value[field])
    for field in ("request_digest", "manifest_digest", "proof_digest"):
        _sha(value[field])
    _scope(value["scope"])
    _namespace(value["namespace"])
    proof = {
        k: v for k, v in value.items() if k not in {"proof_digest", "state", "execution_epoch"}
    }
    if value["proof_digest"] != digest(proof):
        raise DefinitionMismatch("Original Registry reservation digest changed")
    if bound:
        _epoch(value["execution_epoch"])
        if value["state"] != "held-bound":
            raise DefinitionMismatch("Original Registry root is not held-bound")
    elif value["state"] != "held-unbound" or value["execution_epoch"] is not None:
        raise DefinitionMismatch("Accepted original root must be held-unbound")


def _depth(state):
    return (
        TemporalExecutionPolicy.from_identity(state.manifest["execution_policy"]).max_depth
        if "execution_policy" in state.manifest
        else 8
    )


def _metadata(state, metadata, namespace, epoch, original_epoch, parent):
    _exact(metadata, {"version", "root", "lineage"})
    if type(metadata["version"]) is not int or metadata["version"] != 1:
        raise ValidationError("Invalid original deployment metadata version")
    _root(metadata["root"])
    _epoch(epoch)
    _epoch(original_epoch)
    _text(namespace)
    if epoch != original_epoch or epoch != state.epoch:
        raise DefinitionMismatch("Original SDK execution cannot be replaced")
    root, lineage = metadata["root"], metadata["lineage"]
    publication = state.manifest["deployment_admission_protocol"]
    if (
        root["registry_id"] != publication["registry_id"]
        or root["scope"] != state.scope
        or root["namespace"]["name"] != namespace
        or root["manifest_digest"] != digest(state.manifest)
        or root["run_id"]
        != root_run_id(publication["policy"]["deployment_id"], root["scope"], root["command_id"])
    ):
        raise DefinitionMismatch("Original Registry reservation does not match the accepted Run")
    if type(lineage) is not list or len(lineage) >= _depth(state):
        raise ValidationError("Original deployment ancestry exceeds its bounded depth")
    previous_id, previous_request = root["run_id"], root["request_digest"]
    seen = {previous_id}
    for link in lineage:
        _exact(link, LINK_FIELDS)
        for field in ("parent_run_id", "call_id", "child_run_id", "child_command_id"):
            _text(link[field])
        _epoch(link["parent_execution_epoch"])
        for field in ("parent_request_digest", "parent_manifest_digest", "child_request_digest"):
            _sha(link[field])
        if (
            link["parent_run_id"] != previous_id
            or link["parent_request_digest"] != previous_request
            or link["parent_manifest_digest"] != root["manifest_digest"]
            or link["child_run_id"] in seen
        ):
            raise DefinitionMismatch("Original deployment ancestry is disconnected or cyclic")
        seen.add(link["child_run_id"])
        previous_id, previous_request = link["child_run_id"], link["child_request_digest"]
    command_id = lineage[-1]["child_command_id"] if lineage else root["command_id"]
    if (
        previous_id != state.run_id
        or previous_request != digest(state.request)
        or command_id != _command(state)
    ):
        raise DefinitionMismatch("Original deployment ancestry ends at another accepted Run")
    if lineage:
        _exact(parent, {"namespace", "workflow_id", "run_id"})
        expected = {
            "namespace": namespace,
            "workflow_id": lineage[-1]["parent_run_id"],
            "run_id": lineage[-1]["parent_execution_epoch"],
        }
        if parent != expected:
            raise DefinitionMismatch("Actual original SDK parent differs from accepted ancestry")
    elif parent is not None:
        raise DefinitionMismatch("Original deployment root cannot have an SDK parent")


def initialize(state, metadata=None, *, namespace, epoch, original_epoch, parent):
    if not selected(state.manifest):
        if metadata is not None:
            raise DefinitionMismatch("Unselected release cannot adopt deployment metadata")
        return
    validate_protocol(state.manifest)
    if metadata is None:
        raise DefinitionMismatch("Selected release requires original deployment metadata")
    if any(key in state.request for key in ("session_turn", "session_observer", "session_lineage")):
        raise DefinitionMismatch("Deployment Session coordinator admission is unavailable")
    _metadata(state, metadata, namespace, epoch, original_epoch, parent)
    values = {
        "deployment_admission": _detached(metadata),
        "deployment_original_epoch": original_epoch,
        "deployment_namespace": namespace,
        "deployment_sdk_parent": _detached(parent),
    }
    if hasattr(state, "deployment_admission"):
        if any(getattr(state, key) != value for key, value in values.items()):
            raise DefinitionMismatch("Original deployment execution admission cannot change")
        return
    for key, value in values.items():
        setattr(state, key, value)
    state.deployment_receipt = None


def _require(state):
    if not selected(state.manifest) or not hasattr(state, "deployment_admission"):
        raise DefinitionMismatch("Original deployment execution admission is unavailable")
    validate_protocol(state.manifest)
    _metadata(
        state,
        state.deployment_admission,
        state.deployment_namespace,
        state.epoch,
        state.deployment_original_epoch,
        state.deployment_sdk_parent,
    )


def view(state):
    _require(state)
    value = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "command_id": _command(state),
        "execution_epoch": state.epoch,
        "original_execution_epoch": state.deployment_original_epoch,
        "namespace": state.deployment_admission["root"]["namespace"],
        "request": state.request,
        "request_digest": digest(state.request),
        "manifest": state.manifest,
        "manifest_digest": digest(state.manifest),
        "admission": state.deployment_admission,
        "admission_receipt": state.deployment_receipt,
        "children": getattr(state, "children", []),
    }
    return _detached({**value, "proof_digest": digest(value)})


def activity_request(state):
    _require(state)
    return _detached(
        {
            "scope": state.scope,
            "run_id": state.run_id,
            "execution_epoch": state.epoch,
            "command_id": _command(state),
            "request": state.request,
            "runtime_manifest": state.manifest,
            "deployment_admission": state.deployment_admission,
        }
    )


def adopt(state, result):
    _require(state)
    _exact(
        result, {"version", "run_id", "execution_epoch", "root", "metadata_digest", "proof_digest"}
    )
    _root(result["root"], bound=True)
    _sha(result["metadata_digest"])
    _sha(result["proof_digest"])
    metadata = state.deployment_admission
    expected_epoch = (
        metadata["lineage"][0]["parent_execution_epoch"] if metadata["lineage"] else state.epoch
    )
    expected_root = {**metadata["root"], "state": "held-bound", "execution_epoch": expected_epoch}
    if (
        type(result["version"]) is not int
        or result["version"] != 1
        or result["run_id"] != state.run_id
        or result["execution_epoch"] != state.epoch
        or result["root"] != expected_root
        or result["metadata_digest"] != digest(metadata)
        or result["proof_digest"]
        != digest({k: v for k, v in result.items() if k != "proof_digest"})
    ):
        raise DefinitionMismatch("Original deployment admission response changed")
    previous = state.deployment_receipt
    if previous is not None and previous != result:
        raise DefinitionMismatch("Original deployment admission cannot be replaced")
    if previous is None:
        state.deployment_receipt = _detached(result)


def admitted(state):
    if not selected(state.manifest):
        return True
    _require(state)
    return state.deployment_receipt is not None


def _parent(state):
    _require(state)
    if (
        not admitted(state)
        or not hasattr(state, "children")
        or state.request["definition"]["kind"] not in {"graph", "team", "dynamic"}
    ):
        raise DefinitionMismatch("Original admitted Parent authority is required")


def _call(state, run_id):
    matches = [call for call in state.children if call["run_id"] == run_id]
    if len(matches) != 1:
        raise DefinitionMismatch("Original child intent is unavailable")
    return matches[0]


def project_child(state, call):
    _parent(state)
    original = _call(state, call.get("run_id"))
    for key in ("id", "run_id", "command_id", "request"):
        if original[key] != call.get(key):
            raise DefinitionMismatch("Original recorded child intent changed")
    metadata = state.deployment_admission
    if len(metadata["lineage"]) + 1 >= _depth(state):
        raise ValidationError("Original deployment child depth exhausted")
    if call["run_id"] in {
        metadata["root"]["run_id"],
        *(link["child_run_id"] for link in metadata["lineage"]),
    }:
        raise DefinitionMismatch("Original deployment child ancestry is cyclic")
    link = {
        "parent_run_id": state.run_id,
        "parent_execution_epoch": state.epoch,
        "parent_request_digest": digest(state.request),
        "parent_manifest_digest": digest(state.manifest),
        "call_id": call["id"],
        "child_run_id": call["run_id"],
        "child_command_id": call["command_id"],
        "child_request_digest": digest(call["request"]),
    }
    return _detached(
        {"version": 1, "root": metadata["root"], "lineage": [*metadata["lineage"], link]}
    )


def pin_child(state, payload):
    _parent(state)
    _exact(
        payload,
        {
            "scope",
            "parent_run_id",
            "parent_execution_epoch",
            "child_run_id",
            "child_execution_epoch",
            "child_request_digest",
            "metadata_digest",
        },
    )
    _epoch(payload["child_execution_epoch"])
    _sha(payload["child_request_digest"])
    _sha(payload["metadata_digest"])
    call = _call(state, payload["child_run_id"])
    expected_metadata = project_child(state, call)
    if (
        payload["scope"] != state.scope
        or payload["parent_run_id"] != state.run_id
        or payload["parent_execution_epoch"] != state.epoch
        or payload["child_request_digest"] != digest(call["request"])
        or payload["metadata_digest"] != digest(expected_metadata)
        or call.get("deployment_admission") != expected_metadata
        or call.get("dispatch_started") is not True
    ):
        raise DefinitionMismatch("Child SDK pin differs from original dispatched intent")
    previous = call.get("deployment_execution_epoch")
    if previous is not None and previous != payload["child_execution_epoch"]:
        raise DefinitionMismatch("Original child SDK execution cannot be replaced")
    call["deployment_execution_epoch"] = payload["child_execution_epoch"]
    return {"run_id": call["run_id"], "recorded": True}
