"""Selected3 control carriers; original Histories still validate and adopt evidence."""

from types import SimpleNamespace

from .errors import DefinitionMismatch
from .temporal_state import detached
from .types import canonical, digest

REQUEST_FIELDS = {
    "version",
    "mode",
    "scope",
    "parent_run_id",
    "parent_execution_epoch",
    "child_run_id",
    "child_execution_epoch",
    "parent_request_digest",
    "manifest_digest",
    "child_intent_digest",
}
BINDING_FIELDS = {
    "scope",
    "namespace",
    "parent_run_id",
    "parent_execution_epoch",
    "child_run_id",
    "child_execution_epoch",
    "manifest_digest",
    "request_digest",
    "child_intent_digest",
}
FLAGS = {
    "quiescent",
    "remote_stop_confirmed",
    "unknown_remote_execution",
    "evidence_ack_pending",
    "reconciliation_pending",
}
EXTRA_OBSERVATIONS = {
    "parent_notification_ack",
    "input_requests",
    "planning_input_sources",
    "native_history_bundle",
    "native_history_episodes",
}


def _reject():
    raise DefinitionMismatch("Original compact control identity or evidence changed")


def _selected(manifest):
    from .temporal_deployment_coding_state import selected

    if not selected(manifest):
        _reject()


def _child_digest(call):
    from .temporal_deployment_control_projection import child_identity

    return child_identity(call)


def request(state, call, mode):
    _selected(state.manifest)
    if mode not in {"register", "observe", "cancel", "recover"}:
        _reject()
    return detached(
        {
            "version": 1,
            "mode": mode,
            "scope": state.scope,
            "parent_run_id": state.run_id,
            "parent_execution_epoch": state.epoch,
            "child_run_id": call["run_id"],
            "child_execution_epoch": call.get("deployment_execution_epoch"),
            "parent_request_digest": digest(state.request),
            "manifest_digest": digest(state.manifest),
            "child_intent_digest": _child_digest(call),
        }
    )


def _binding(state, call, proof):
    expected_epoch = call.get("deployment_execution_epoch")
    namespace = getattr(state, "composition_namespace", None)
    if (
        namespace is None
        or proof.get("namespace") != namespace
        or proof.get("scope") != state.scope
        or proof.get("run_id") != call["run_id"]
        or proof.get("execution_epoch") != proof.get("original_execution_epoch")
        or not proof.get("execution_epoch")
        or expected_epoch is not None
        and proof["execution_epoch"] != expected_epoch
        or canonical(proof.get("manifest")) != canonical(state.manifest)
        or canonical(proof.get("request")) != canonical(call["request"])
        or proof.get("request_digest") != digest(call["request"])
        or proof.get("proof_digest")
        != digest({k: v for k, v in proof.items() if k != "proof_digest"})
    ):
        _reject()
    return detached(
        {
            "scope": state.scope,
            "namespace": namespace,
            "parent_run_id": state.run_id,
            "parent_execution_epoch": state.epoch,
            "child_run_id": call["run_id"],
            "child_execution_epoch": proof["execution_epoch"],
            "manifest_digest": digest(state.manifest),
            "request_digest": digest(call["request"]),
            "child_intent_digest": _child_digest(call),
        }
    )


def _snapshot_references(snapshot, manifest):
    """Only this native protocol field is referenced; business dictionaries stay literal."""
    _snapshot_shape(snapshot)
    references = []
    for index, action in enumerate(snapshot.get("actions", [])):
        native = action.get("delegated_execution")
        if type(native) is not dict or type(native.get("tool_request")) is not dict:
            continue
        tool_request = native["tool_request"]
        if type(tool_request.get("runtime_manifest")) is dict and (
            canonical(tool_request["runtime_manifest"]) == canonical(manifest)
        ):
            tool_request["runtime_manifest"] = None
            references.append(
                {
                    "path": [
                        "actions",
                        index,
                        "delegated_execution",
                        "tool_request",
                        "runtime_manifest",
                    ],
                    "digest": digest(manifest),
                }
            )
    return references


def _snapshot_shape(snapshot):
    if type(snapshot) is not dict or type(snapshot.get("actions")) is not list:
        _reject()
    for action in snapshot["actions"]:
        if type(action) is not dict:
            _reject()
        native = action.get("delegated_execution")
        if native is not None and type(native) is not dict:
            _reject()
        if (
            type(native) is dict
            and "tool_request" in native
            and type(native["tool_request"]) is not dict
        ):
            _reject()


def pack_response(state, call, value):
    _selected(state.manifest)
    value = detached(value)
    if "parent_notification_ack" in value:
        ack = value["parent_notification_ack"]
        if type(ack) is not str or len(ack) != 64 or any(c not in "0123456789abcdef" for c in ack):
            _reject()
    proof = value["coding_composition_proof"]
    binding = _binding(state, call, proof)
    if value.get("scope") != state.scope or canonical(value.get("manifest")) != canonical(
        state.manifest
    ):
        _reject()
    workflow = value["workflow"]
    if any(type(workflow.get(name, False)) is not bool for name in FLAGS):
        _reject()
    flow = {name: workflow.get(name, False) for name in FLAGS}
    for name in ("backend", "planning_revision"):
        if name in workflow:
            flow[name] = workflow[name]
    snapshot = value["snapshot"]
    _snapshot_shape(snapshot)
    if snapshot.get("run_id") != call["run_id"]:
        _reject()
    observation = {
        "snapshot": snapshot,
        "budget": value["budget"],
        "release_digest": value["release_digest"],
        "workflow": flow,
        "snapshot_manifest_refs": _snapshot_references(snapshot, state.manifest),
        **{name: value[name] for name in EXTRA_OBSERVATIONS if name in value},
    }
    physical = {k: v for k, v in proof.items() if k not in {"manifest", "request"}}
    physical.update(manifest_ref=digest(state.manifest), request_ref=digest(call["request"]))
    return detached(
        {"version": 1, "binding": binding, "observation": observation, "physical_proof": physical}
    )


def expand_response(state, call, response):
    response = detached(response)
    if type(response) is not dict:
        _reject()
    if response.get("ok") is not True or type(response.get("result")) is not dict:
        return response
    value = response["result"]
    if "version" not in value:
        return response  # register/cancel/recover original receipts are unchanged.
    _selected(state.manifest)
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or set(value) != {"version", "binding", "observation", "physical_proof"}
    ):
        _reject()
    binding, physical, observation = value["binding"], value["physical_proof"], value["observation"]
    if type(observation) is dict and "parent_notification_ack" in observation:
        ack = observation["parent_notification_ack"]
        if type(ack) is not str or len(ack) != 64 or any(c not in "0123456789abcdef" for c in ack):
            _reject()
    if type(binding) is not dict or set(binding) != BINDING_FIELDS or type(physical) is not dict:
        _reject()
    from .temporal_coding_composition_state import _view_fields

    if set(physical) != (_view_fields() - {"manifest", "request"}) | {
        "manifest_ref",
        "request_ref",
    }:
        _reject()
    if physical.pop("manifest_ref") != digest(state.manifest) or physical.pop(
        "request_ref"
    ) != digest(call["request"]):
        _reject()
    physical.update(manifest=detached(state.manifest), request=detached(call["request"]))
    if binding != _binding(state, call, physical):
        _reject()
    if (
        type(observation) is not dict
        or not {"snapshot", "budget", "release_digest", "workflow", "snapshot_manifest_refs"}
        <= set(observation)
        or set(observation)
        - {"snapshot", "budget", "release_digest", "workflow", "snapshot_manifest_refs"}
        - EXTRA_OBSERVATIONS
    ):
        _reject()
    references = observation.pop("snapshot_manifest_refs")
    snapshot = observation["snapshot"]
    _snapshot_shape(snapshot)
    if type(references) is not list or len(references) > 4096 or type(snapshot) is not dict:
        _reject()
    seen = set()
    for reference in references:
        if type(reference) is not dict or set(reference) != {"path", "digest"}:
            _reject()
        path = reference["path"]
        if (
            type(path) is not list
            or len(path) != 5
            or path[0] != "actions"
            or type(path[1]) is not int
            or path[1] < 0
            or path[2:] != ["delegated_execution", "tool_request", "runtime_manifest"]
            or path[1] in seen
            or reference["digest"] != digest(state.manifest)
        ):
            _reject()
        try:
            target = snapshot["actions"][path[1]]["delegated_execution"]["tool_request"]
            if target["runtime_manifest"] is not None:
                _reject()
            target["runtime_manifest"] = detached(state.manifest)
        except (KeyError, IndexError, TypeError):
            _reject()
        seen.add(path[1])
    for action in snapshot.get("actions", []):
        native = action.get("delegated_execution")
        if (
            type(native) is dict
            and type(native.get("tool_request")) is dict
            and native["tool_request"].get("runtime_manifest") is None
        ):
            _reject()
    return {
        "ok": True,
        "result": detached(
            {
                **observation,
                "scope": state.scope,
                "manifest": state.manifest,
                "coding_composition_proof": physical,
            }
        ),
    }


async def execute(runtime, client, value, info):
    from . import temporal_coding_composition_control as composition
    from . import temporal_deployment_coding_bridge as bridge
    from . import temporal_deployment_execution as execution
    from .temporal_bindings import request_release_digest
    from .temporal_deployment_coding_bridge import control
    from .temporal_deployment_coding_validation import CodingValidation, _ObservationValidation
    from .temporal_parent_state import CONTROL_ACTIVITY

    value = detached(value)
    if (
        set(value) != REQUEST_FIELDS
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["mode"] not in {"register", "observe", "cancel", "recover"}
    ):
        _reject()
    proof = await execution.validate_activity(runtime, client, value, info)
    if proof is None:
        _reject()
    _selected(proof["manifest"])
    if (
        proof["scope"] != value["scope"]
        or proof["run_id"] != value["parent_run_id"]
        or proof["execution_epoch"] != value["parent_execution_epoch"]
        or proof["request_digest"] != value["parent_request_digest"]
        or proof["manifest_digest"] != value["manifest_digest"]
    ):
        _reject()
    call = execution._child(proof, value["child_run_id"])
    if _child_digest(call) != value["child_intent_digest"] or value[
        "child_execution_epoch"
    ] not in (None, call.get("deployment_execution_epoch")):
        _reject()
    protocol = proof["manifest"]["deployment_admission_protocol"]
    epoch = call.get("deployment_execution_epoch")
    describe_readset = (
        value["mode"] == "observe"
        and epoch is not None
        and type(protocol.get("version")) is int
        and protocol["version"] == 4
    )
    pinned_observation = (
        describe_readset
        and type(epoch) is str
        and bool(epoch)
        and call.get("child_execution")
        == {
            "namespace": proof["namespace"],
            "execution_epoch": epoch,
            "original_execution_epoch": epoch,
        }
    )
    validator_type = (
        _ObservationValidation
        if pinned_observation and getattr(info, "activity_type", None) == CONTROL_ACTIVITY
        else CodingValidation
    )
    validator = validator_type(
        runtime,
        client,
        {
            "scope": proof["scope"],
            "run_id": proof["run_id"],
            "execution_epoch": proof["execution_epoch"],
            "runtime_manifest": proof["manifest"],
            **(
                {"coding_parent": proof["request"]["coding_parent"]}
                if "coding_parent" in proof["request"]
                else {}
            ),
        },
        info,
    )
    closed_reading = type(validator) is _ObservationValidation
    discard = validator._discard_reading if closed_reading else None
    try:
        if closed_reading:
            validator._open_reading(proof)
        reading_client = validator._read_client() if closed_reading else client
        # The preceding full Activity validation permits only this read. Finish the
        # adjacent descriptor read before bootstrap/fresh; control still follows a
        # complete validation, and the independent post-control validation remains.
        if value["mode"] == "register":
            # permission() includes the same complete identity read set and
            # full exit check as validate(); keep one fresh check on each side.
            if not await validator.permission():
                _reject()
        elif not describe_readset:
            await validator.validate()

        def child_description(epoch):
            from .temporal_parent_state import PARENT_WORKFLOW_NAME
            from .temporal_state import WORKFLOW_NAME

            return {
                "id": call["run_id"],
                "run_id": epoch,
                "namespace": proof["namespace"]["name"],
                "task_queue": info.task_queue,
                "parent_id": proof["run_id"],
                "parent_run_id": proof["execution_epoch"],
                "workflow_type": PARENT_WORKFLOW_NAME
                if call["request"]["definition"]["kind"] in {"graph", "team", "dynamic"}
                else WORKFLOW_NAME,
            }

        if value["mode"] != "register" and call.get("deployment_execution_epoch") is not None:
            validator._description(
                await reading_client.get_workflow_handle(call["run_id"]).describe(),
                child_description(call["deployment_execution_epoch"]),
            )
            await validator.validate()
        full = {
            "mode": value["mode"],
            "scope": proof["scope"],
            "child": detached(call),
            "parent_id": proof["run_id"],
            "parent_execution_epoch": proof["execution_epoch"],
            "parent_request_digest": proof["request_digest"],
            "parent_release_digest": request_release_digest(proof["request"], proof["manifest"]),
            "runtime_manifest": proof["manifest"],
            "namespace": proof["namespace"],
            "task_queue": info.task_queue,
        }
        if pinned_observation:
            # The complete original Activity proof and Coding read set above cover
            # this read-only collection. Keep composition's own identity checks and
            # the independent complete exit below; do not repeat the bridge's
            # same-parent Activity verification. Unexpected cold writes still fail.
            result = await composition.control(
                runtime, bridge._ReadOnlyClient(reading_client), full, info
            )
        else:
            result = await control(runtime, client, full, info)
        if closed_reading:
            if execution._policy(runtime) != validator._policy:
                _reject()
            current = await validator._read_observation_node(
                proof["run_id"], proof["execution_epoch"]
            )
        else:
            current = await execution._proof(
                runtime,
                client,
                execution._policy(runtime),
                proof["scope"],
                proof["run_id"],
                proof["execution_epoch"],
                required=True,
            )
        current_call = execution._child(current, call["run_id"])
        if (
            current["scope"] != proof["scope"]
            or current["run_id"] != proof["run_id"]
            or current["execution_epoch"] != proof["execution_epoch"]
            or current["namespace"] != proof["namespace"]
            or current["request_digest"] != proof["request_digest"]
            or current["manifest_digest"] != proof["manifest_digest"]
            or _child_digest(current_call) != _child_digest(call)
        ):
            _reject()
        if value["mode"] != "register":
            child_proof = result.get("coding_composition_proof")
            if type(child_proof) is not dict:
                _reject()
            expected_epoch = child_proof["execution_epoch"]
            if (
                current_call.get("deployment_execution_epoch") != expected_epoch
                or call.get("deployment_execution_epoch") not in (None, expected_epoch)
                or current_call.get("child_execution")
                != {
                    "namespace": proof["namespace"],
                    "execution_epoch": expected_epoch,
                    "original_execution_epoch": expected_epoch,
                }
            ):
                _reject()
            validator._description(
                await reading_client.get_workflow_handle(call["run_id"]).describe(),
                child_description(expected_epoch),
            )
        if value["mode"] == "register":
            if not await validator.permission():
                _reject()
        else:
            await validator.validate()
        execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
        await execution._namespace(reading_client, proof["namespace"])
        if closed_reading:
            await validator._finish_reading()
        runtime.validate_release(proof["manifest"])
        if value["mode"] != "observe":
            return detached(result)
        state = SimpleNamespace(
            scope=proof["scope"],
            run_id=proof["run_id"],
            epoch=proof["execution_epoch"],
            manifest=proof["manifest"],
            composition_namespace=proof["namespace"],
        )
        return pack_response(state, current_call, result)
    finally:
        if discard is not None:
            discard()
