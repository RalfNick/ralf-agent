"""Compact original-History identity and fresh control facts; no SDK or mutation."""

from types import SimpleNamespace

from .errors import DefinitionMismatch, ValidationError
from .temporal_deployment_admission import _detached, _exact, _namespace, _scope, _sha, _text
from .types import digest

NODE_QUERY = "deployment_coding_validation"
NODE_REQUEST_FIELDS = {"kind", "scope", "run_id", "execution_epoch", "child_call_id"}
NODE_FIELDS = {
    "version",
    "scope",
    "namespace",
    "run_id",
    "execution_epoch",
    "original_execution_epoch",
    "identity_digest",
    "revision",
    "state",
    "stop_requested",
    "sealed",
    "edge",
    "proof_digest",
}
EDGE_FIELDS = {
    "call_id",
    "child_run_id",
    "child_execution_epoch",
    "identity_digest",
    "dispatch_started",
    "owned",
}
REGISTRY_REQUEST_FIELDS = {
    "kind",
    "scope",
    "admission_policy",
    "namespace",
    "command_id",
    "run_id",
    "execution_epoch",
    "request_digest",
    "manifest_digest",
}
REGISTRY_FIELDS = {
    "version",
    "registry_id",
    "registry_execution_epoch",
    "configuration_version",
    "policy",
    "scope",
    "namespace",
    "root_identity_digest",
    "submission_digest",
    "held",
    "retired",
    "close_requested",
    "admitted",
    "proof_digest",
}
_START_FIELDS = {
    "scope",
    "run_id",
    "execution_epoch",
    "activity_timeout",
    "task_queue",
    "request_digest",
    "manifest_digest",
}
_STATES = {
    "queued",
    "running",
    "waiting_approval",
    "waiting_input",
    "waiting_reconciliation",
    "outcome_unknown",
    "cancelling",
    "cancelled",
    "failed",
    "succeeded",
}


def _epoch(value):
    _text(value)
    if len(value) > 1024:
        raise ValidationError("Original SDK epoch exceeds its allowance")


def _selected(manifest):
    from .temporal_deployment_coding_state import selected
    from .temporal_deployment_protocol import validate_protocol

    if not selected(manifest):
        raise DefinitionMismatch("Compact validation requires publication3")
    validate_protocol(manifest)


def _start(state):
    return {
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "request_digest": digest(state.request),
        "manifest_digest": digest(state.manifest),
        "activity_timeout": state.deployment_activity_timeout,
        "task_queue": state.deployment_task_queue,
    }


def _receipt(proof):
    from .temporal_deployment_execution_state import _root

    receipt = proof["admission_receipt"]
    _exact(
        receipt, {"version", "run_id", "execution_epoch", "root", "metadata_digest", "proof_digest"}
    )
    _root(receipt["root"], bound=True)
    metadata = proof["admission"]
    epoch = (
        metadata["lineage"][0]["parent_execution_epoch"]
        if metadata["lineage"]
        else proof["execution_epoch"]
    )
    expected = {
        "version": 1,
        "run_id": proof["run_id"],
        "execution_epoch": proof["execution_epoch"],
        "root": {**metadata["root"], "state": "held-bound", "execution_epoch": epoch},
        "metadata_digest": digest(metadata),
    }
    if type(receipt["version"]) is not int or receipt != {
        **expected,
        "proof_digest": digest(expected),
    }:
        raise DefinitionMismatch("Original admitted receipt changed")


def node_identity_digest(deployment_proof, start, composition_proof=None):
    """Derive immutable identity from already SDK-verified full bootstrap objects."""
    from .temporal_bindings import request_release_digest
    from .temporal_coding_composition_state import _link, _view_fields, enabled
    from .temporal_deployment_execution_state import _metadata
    from .temporal_startup_options import validate_seconds

    try:
        proof = deployment_proof
        _selected(proof["manifest"])
        _scope(proof["scope"])
        _namespace(proof["namespace"])
        for field in ("run_id", "command_id"):
            _text(proof[field])
        for field in ("execution_epoch", "original_execution_epoch"):
            _epoch(proof[field])
        if (
            proof["execution_epoch"] != proof["original_execution_epoch"]
            or proof["request_digest"] != digest(proof["request"])
            or proof["manifest_digest"] != digest(proof["manifest"])
        ):
            raise DefinitionMismatch("Original node identity changed")
        metadata = proof["admission"]
        parent = (
            None
            if not metadata["lineage"]
            else {
                "namespace": proof["namespace"]["name"],
                "workflow_id": metadata["lineage"][-1]["parent_run_id"],
                "run_id": metadata["lineage"][-1]["parent_execution_epoch"],
            }
        )
        shadow = SimpleNamespace(
            scope=proof["scope"],
            run_id=proof["run_id"],
            epoch=proof["execution_epoch"],
            manifest=proof["manifest"],
            request=proof["request"],
            receipts={proof["command_id"]: {"kind": "submit"}},
        )
        _metadata(
            shadow,
            metadata,
            proof["namespace"]["name"],
            proof["execution_epoch"],
            proof["original_execution_epoch"],
            parent,
        )
        _receipt(proof)
        _exact(start, _START_FIELDS)
        for field in ("scope", "run_id", "execution_epoch", "request_digest", "manifest_digest"):
            if start[field] != proof[field]:
                raise DefinitionMismatch("Original start identity changed")
        validate_seconds(start["activity_timeout"], strict=True)
        _text(start["task_queue"])
        release_digest = request_release_digest(proof["request"], proof["manifest"])
        link = _link(proof["request"]) if "coding_parent" in proof["request"] else None
        if enabled(proof["manifest"]):
            _exact(composition_proof, _view_fields())
            if (
                any(
                    composition_proof[field] != proof[field]
                    for field in (
                        "scope",
                        "namespace",
                        "run_id",
                        "execution_epoch",
                        "original_execution_epoch",
                        "request",
                        "manifest",
                        "request_digest",
                    )
                )
                or composition_proof["release_digest"] != release_digest
            ):
                raise DefinitionMismatch("Original Coding/deployment identities diverged")
        elif composition_proof is not None or link is not None:
            raise DefinitionMismatch("Native node cannot acquire a composition identity")
        return digest(
            {
                "version": 1,
                "scope": proof["scope"],
                "namespace": proof["namespace"],
                "run_id": proof["run_id"],
                "command_id": proof["command_id"],
                "execution_epoch": proof["execution_epoch"],
                "original_execution_epoch": proof["original_execution_epoch"],
                "request_digest": proof["request_digest"],
                "manifest_digest": proof["manifest_digest"],
                "release_digest": release_digest,
                "admission_digest": digest(metadata),
                "receipt_digest": digest(proof["admission_receipt"]),
                "start": start,
                "coding_parent": link,
            }
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise DefinitionMismatch("Original compact node identity unavailable") from exc


def _child_identity(call):
    from .temporal_coding_composition_state import _link
    from .temporal_deployment_execution_state import LINK_FIELDS, _root

    if type(call) is not dict:
        raise ValidationError("Original child intent requires plain fields")
    try:
        for field in ("id", "call_id", "member", "command_id", "run_id"):
            _text(call[field])
        for field in ("cap", "depth", "planning_revision"):
            if type(call[field]) is not int or call[field] < (1 if field == "depth" else 0):
                raise ValidationError("Original child intent bounds changed")
        link = _link(call["request"])
        if call["child_request_digest"] != digest(call["request"]):
            raise DefinitionMismatch("Original child request digest changed")
        metadata = call["deployment_admission"]
        _exact(metadata, {"version", "root", "lineage"})
        if type(metadata["version"]) is not int or metadata["version"] != 1:
            raise ValidationError("Original child metadata version changed")
        _root(metadata["root"])
        lineage = metadata["lineage"]
        if type(lineage) is not list or not lineage or len(lineage) > 8:
            raise DefinitionMismatch("Original child deployment lineage unavailable")
        previous_id, previous_request = (
            metadata["root"]["run_id"],
            metadata["root"]["request_digest"],
        )
        seen = {previous_id}
        for edge in lineage:
            _exact(edge, LINK_FIELDS)
            for field in ("parent_run_id", "call_id", "child_run_id", "child_command_id"):
                _text(edge[field])
            _epoch(edge["parent_execution_epoch"])
            for field in (
                "parent_request_digest",
                "parent_manifest_digest",
                "child_request_digest",
            ):
                _sha(edge[field])
            if (
                edge["parent_run_id"] != previous_id
                or edge["parent_request_digest"] != previous_request
                or edge["parent_manifest_digest"] != metadata["root"]["manifest_digest"]
                or edge["child_run_id"] in seen
            ):
                raise DefinitionMismatch("Original child lineage is disconnected")
            seen.add(edge["child_run_id"])
            previous_id, previous_request = edge["child_run_id"], edge["child_request_digest"]
        last = lineage[-1]
        if (
            previous_id != call["run_id"]
            or previous_request != digest(call["request"])
            or call["request"]["input"] != call["input"]
            or call["depth"] != len(lineage)
            or metadata["root"]["scope"] != link["scope"]
            or metadata["root"]["namespace"] != link["namespace"]
            or last["parent_run_id"] != link["parent_run_id"]
            or last["parent_execution_epoch"] != link["parent_execution_epoch"]
            or last["parent_request_digest"] != link["parent_request_digest"]
            or last["child_command_id"] != call["command_id"]
            or last["call_id"] != call["id"]
            or any(
                link[name] != call[name]
                for name in ("cap", "depth", "planning_revision", "member", "command_id")
            )
            or link["child_run_id"] != call["run_id"]
            or link["call_id"] != call["id"]
        ):
            raise DefinitionMismatch("Original child immutable identities diverged")
        return {
            "id": call["id"],
            "call_id": call["call_id"],
            "member": call["member"],
            "input_digest": digest(call["input"]),
            "command_id": call["command_id"],
            "run_id": call["run_id"],
            "request_digest": digest(call["request"]),
            "cap": call["cap"],
            "depth": call["depth"],
            "planning_revision": call["planning_revision"],
            "deployment_metadata_digest": digest(call["deployment_admission"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise DefinitionMismatch("Original child identity unavailable") from exc


def child_identity(call):
    """CONTROL operation identity; excludes every mutable observation and epoch pin."""
    return digest(_child_identity(call))


def edge_identity_digest(call):
    """SDK edge identity also names its original complete Coding parent link."""
    return digest(
        {**_child_identity(call), "coding_parent_digest": digest(call["request"]["coding_parent"])}
    )


def root_identity_digest(bound_root):
    from .temporal_deployment_execution_state import _root

    _root(bound_root, bound=True)
    return digest({key: value for key, value in bound_root.items() if key != "state"})


def submission_identity_digest(envelope):
    from .temporal_startup_options import validate_seconds

    _exact(envelope, {"version", "request", "manifest", "activity_timeout", "task_queue"})
    if type(envelope["version"]) is not int or envelope["version"] != 1:
        raise ValidationError("Original envelope version changed")
    _selected(envelope["manifest"])
    validate_seconds(envelope["activity_timeout"], strict=True)
    _text(envelope["task_queue"])
    return digest(envelope)


def node(state, request):
    from .temporal_bindings import request_release_digest
    from .temporal_coding_composition_state import _link, enabled, physical_stop_view
    from .temporal_deployment_execution_state import _command, _require, project_child

    _exact(request, NODE_REQUEST_FIELDS)
    _scope(request["scope"])
    _text(request["run_id"])
    _epoch(request["execution_epoch"])
    if request["kind"] != NODE_QUERY or (
        request["scope"],
        request["run_id"],
        request["execution_epoch"],
    ) != (state.scope, state.run_id, state.epoch):
        raise DefinitionMismatch("Original compact query address changed")
    _selected(state.manifest)
    _require(state)
    try:
        composition = enabled(state.manifest)
        start = _start(state)
        if state.release_digest != request_release_digest(state.request, state.manifest):
            raise DefinitionMismatch("Original release digest changed")
        proof = {
            "scope": state.scope,
            "namespace": state.deployment_admission["root"]["namespace"],
            "run_id": state.run_id,
            "command_id": _command(state),
            "execution_epoch": state.epoch,
            "original_execution_epoch": state.deployment_original_epoch,
            "request": state.request,
            "manifest": state.manifest,
            "request_digest": digest(state.request),
            "manifest_digest": digest(state.manifest),
            "admission": state.deployment_admission,
            "admission_receipt": state.deployment_receipt,
        }
        physical = physical_stop_view(state) if composition else None
        identity = node_identity_digest(proof, start, physical)
        edge = None
        if request["child_call_id"] is not None:
            _text(request["child_call_id"])
            matches = [
                call
                for call in getattr(state, "children", [])
                if call.get("id") == request["child_call_id"]
            ]
            if not composition or len(matches) != 1:
                raise DefinitionMismatch("Original child intent is unavailable or ambiguous")
            call = matches[0]
            link = _link(call["request"])
            expected = {
                "scope": state.scope,
                "namespace": proof["namespace"],
                "parent_run_id": state.run_id,
                "parent_execution_epoch": state.epoch,
                "parent_request_digest": proof["request_digest"],
                "parent_release_digest": state.release_digest,
                "call_id": call["id"],
                "command_id": call["command_id"],
                "member": call["member"],
                "planning_revision": call["planning_revision"],
                "child_run_id": call["run_id"],
                "cap": call["cap"],
                "depth": call["depth"],
            }
            if any(link[name] != value for name, value in expected.items()):
                raise DefinitionMismatch("Original Coding child link changed")
            if call["deployment_admission"] != project_child(state, call):
                raise DefinitionMismatch("Original deployment child metadata changed")
            epoch = call["deployment_execution_epoch"]
            _epoch(epoch)
            execution = call["child_execution"]
            _exact(execution, {"namespace", "execution_epoch", "original_execution_epoch"})
            if execution != {
                "namespace": proof["namespace"],
                "execution_epoch": epoch,
                "original_execution_epoch": epoch,
            }:
                raise DefinitionMismatch("Original child epoch pins diverged")
            if type(call["dispatch_started"]) is not bool:
                raise ValidationError("Original child dispatch fact changed")
            edge = {
                "call_id": call["id"],
                "child_run_id": call["run_id"],
                "child_execution_epoch": epoch,
                "identity_digest": edge_identity_digest(call),
                "dispatch_started": call["dispatch_started"],
                "owned": True,
            }
        if type(state.revision) is not int or state.revision < 0 or state.state not in _STATES:
            raise ValidationError("Original state/revision changed")
        stop = (
            state.state in {"cancelling", "cancelled", "failed", "succeeded"}
            or getattr(state, "composition_stop_intent", None) is not None
        )
        for action in getattr(state, "actions", []):
            native = action.get("delegated_execution")
            if native is not None:
                for name in ("pending_stop", "stop_needed", "stop_active"):
                    if type(native.get(name)) is not bool:
                        raise ValidationError("Original native stop fact changed")
                # Every normal grant opens pending_stop resource debt. Only a
                # stop intent denies new phases; closure still requires that debt to end.
                stop = stop or "cancel" in native or native["stop_needed"] or native["stop_active"]
        value = {
            "version": 1,
            "scope": state.scope,
            "namespace": proof["namespace"],
            "run_id": state.run_id,
            "execution_epoch": state.epoch,
            "original_execution_epoch": state.deployment_original_epoch,
            "identity_digest": identity,
            "revision": state.revision,
            "state": state.state,
            "stop_requested": stop,
            "sealed": getattr(state, "deployment_seal", None) is not None,
            "edge": edge,
        }
        return _detached({**value, "proof_digest": digest(value)})
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise DefinitionMismatch("Original compact query facts unavailable") from exc


def registry(state, request):
    _exact(request, REGISTRY_REQUEST_FIELDS)
    if request["kind"] != NODE_QUERY or not hasattr(state, "coding_index"):
        raise DefinitionMismatch("Original Registry3 validation is unavailable")
    scope = state._authority(request)
    for field in ("command_id", "run_id"):
        _text(request[field])
    _epoch(request["execution_epoch"])
    for field in ("request_digest", "manifest_digest"):
        _sha(request[field])
    try:
        _epoch(state.deployment_registry_execution_epoch)
        key = digest([scope, request["command_id"]])
        held_root, retired = state.roots.get(key), state.retirements.get(key)
        if (held_root is None) == (retired is None):
            raise DefinitionMismatch("Original held or positively retired root required")
        root = held_root if held_root is not None else retired["root"]
        root_digest = root_identity_digest(root)
        if (
            root["scope"] != scope
            or root["namespace"] != state.namespace
            or root["registry_id"] != state.registry_id
            or any(
                root[name] != request[name]
                for name in (
                    "command_id",
                    "run_id",
                    "execution_epoch",
                    "request_digest",
                    "manifest_digest",
                )
            )
        ):
            raise DefinitionMismatch("Original held root address changed")
        index = state.coding_index[key]
        _exact(index, {"close_requested"})
        if type(index["close_requested"]) is not bool:
            raise ValidationError("Original Coding close fact changed")
        record = state.submissions[key]
        _exact(record, {"reservation", "submission", "run_receipt", "execution_epoch"})
        reservation = {
            "command_id": root["command_id"],
            "target": root["run_id"],
            "record_state": "durably_recorded",
            "apply_state": "not_applied",
            "root_admission": {**root, "state": "held-unbound", "execution_epoch": None},
        }
        if (
            record["reservation"] != reservation
            or state.commands[key]
            != {
                "identity": {
                    "kind": "submit",
                    "target": root["run_id"],
                    "payload_digest": root["request_digest"],
                },
                "receipt": reservation,
            }
            or record["execution_epoch"] not in (None, root["execution_epoch"])
        ):
            raise DefinitionMismatch("Original first acceptance changed")
        envelope = state._submission(
            {
                "scope": scope,
                "admission_policy": state.policy,
                "namespace": state.namespace,
                "payload_digest": root["request_digest"],
                "root_admission": {
                    "version": 2,
                    "manifest_digest": root["manifest_digest"],
                    "submission": record["submission"],
                },
            }
        )
        envelope_digest = submission_identity_digest(envelope)
        if retired is not None:
            _exact(retired, {"root", "certificate", "released"})
            if retired["released"] is not True:
                raise DefinitionMismatch("Original retirement is not positively verified")
            state.prepare_deployment_release(
                {
                    **{
                        name: root[name]
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
                    "admission_policy": state.policy,
                    "certificate": retired["certificate"],
                }
            )
        closed = (
            index["close_requested"]
            or digest([scope, root["manifest_digest"]]) in state.coding_closed
        )
        value = {
            "version": 1,
            "registry_id": state.registry_id,
            "registry_execution_epoch": state.deployment_registry_execution_epoch,
            "configuration_version": 3,
            "policy": state.policy,
            "scope": scope,
            "namespace": state.namespace,
            "root_identity_digest": root_digest,
            "submission_digest": envelope_digest,
            "held": held_root is not None,
            "retired": retired is not None,
            "close_requested": closed,
            "admitted": held_root is not None and retired is None and not closed,
        }
        return _detached({**value, "proof_digest": digest(value)})
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise DefinitionMismatch("Original compact Registry facts unavailable") from exc
