"""Public SDK transport of first acceptance; original Registry History persists it."""

import json
from dataclasses import asdict
from uuid import uuid4

from .errors import DefinitionMismatch, ValidationError
from .governance import DeploymentAdmissionPolicy
from .temporal_deployment_admission import _namespace as validate_namespace
from .temporal_deployment_admission import registry_id, root_run_id
from .temporal_state import COMMAND_REGISTRY_NAME, WORKFLOW_NAME, detached, text
from .types import CommandReceipt, RunHandle, canonical, digest, submission_request

_RECORD_FIELDS = {"reservation", "submission", "run_receipt", "execution_epoch"}
_SUBMISSION_FIELDS = {"version", "request", "manifest", "activity_timeout", "task_queue"}
_RECEIPT_FIELDS = {"command_id", "run_id", "kind", "record_state", "apply_state", "outcome"}


def _reject():
    raise DefinitionMismatch("Original public deployment submission identity does not match")


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        _reject()


def _policy(engine):
    if engine._closed:
        raise ValidationError("TemporalEngine is closed")
    protocol = engine.release.get("deployment_admission_protocol")
    if (
        type(protocol) is not dict
        or type(protocol.get("version")) is not int
        or protocol["version"] not in (2, 3, 4)
    ):
        _reject()
    policy = DeploymentAdmissionPolicy.from_identity(protocol["policy"]).identity
    if protocol.get("registry_id") != registry_id(policy["deployment_id"]):
        _reject()
    return detached(policy)


def _check(engine, client, scope, namespace, policy):
    if (
        engine.client is not client
        or asdict(engine.scope) != scope
        or engine.namespace != namespace["name"]
        or client.namespace != namespace["name"]
        or _policy(engine) != policy
    ):
        _reject()


async def _namespace(engine, client, scope, policy):
    from .temporal_session_activities import namespace_id

    name = client.namespace
    if engine.namespace != name:
        _reject()
    value = validate_namespace({"name": name, "id": await namespace_id(client)})
    _check(engine, client, scope, value, policy)
    holder = vars(engine).setdefault("_deployment_namespace_binding", {"namespace": None})
    if type(holder) is not dict or set(holder) != {"namespace"}:
        _reject()
    if holder["namespace"] is None:
        holder["namespace"] = detached(value)
    elif holder["namespace"] != value:
        _reject()
    return value


async def _recheck(engine, client, scope, namespace, policy):
    _check(engine, client, scope, namespace, policy)
    if await _namespace(engine, client, scope, policy) != namespace:
        _reject()


def _raise_sdk(exc):
    from .temporal import _raise_code, _sdk

    sdk = _sdk()
    if isinstance(exc, sdk[1]) and isinstance(exc.cause, sdk[4]):
        _raise_code(exc.cause.type)
    raise exc


async def _query(handle, value):
    from .temporal import _raise_code

    result = await handle.query("view", value)
    if type(result) is dict and set(result) == {"error"}:
        _raise_code(result["error"])
    return detached(result)


async def _update(handle, name, value):
    try:
        if (
            name == "reserve"
            and value.get("kind")
            in {"submit", "approve", "cancel", "reconcile", "drive", "send_input", "patch"}
            and "descendant" not in value
            and "recovery" not in value
        ):
            from .temporal_reservation_transport import reserve

            return await reserve(handle, value)
        return detached(
            await handle.execute_update(
                name, value, id="ralf-deployment:" + name + ":" + digest(value)
            )
        )
    except Exception as exc:
        _raise_sdk(exc)


async def _registry(engine, client, scope, namespace, policy, *, start=True):
    from .temporal import _sdk

    sdk = _sdk()
    identity = registry_id(policy["deployment_id"])
    publication = engine.release["deployment_admission_protocol"]["version"]
    registry_protocol = getattr(engine, "_deployment_registry_protocol", publication)
    if (
        type(registry_protocol) is not int
        or registry_protocol not in (2, 3, 4)
        or publication == 3
        and registry_protocol not in (3, 4)
        or publication == 4
        and registry_protocol != 4
    ):
        _reject()
    if start:
        try:
            await client.start_workflow(
                COMMAND_REGISTRY_NAME,
                {
                    "deployment_admission": {
                        "version": registry_protocol,
                        "policy": policy,
                        "namespace": namespace,
                    }
                },
                id=identity,
                task_queue=engine.task_queue,
                id_reuse_policy=sdk[3].REJECT_DUPLICATE,
                id_conflict_policy=sdk[2].FAIL,
                retry_policy=None,
            )
        except sdk[5]:
            pass
    await _recheck(engine, client, scope, namespace, policy)
    handle = client.get_workflow_handle(identity)
    description = await handle.describe()
    if (
        description.id != identity
        or description.namespace != namespace["name"]
        or description.workflow_type != COMMAND_REGISTRY_NAME
        or type(description.run_id) is not str
        or not description.run_id
        or description.run_id
        != getattr(getattr(description, "raw_info", None), "first_run_id", None)
    ):
        _reject()
    handle = client.get_workflow_handle(identity, run_id=description.run_id)
    await _recheck(engine, client, scope, namespace, policy)
    configuration = await _query(
        handle,
        {
            "kind": "deployment_configuration",
            "scope": scope,
            "admission_policy": policy,
            "namespace": namespace,
        },
    )
    if type(configuration) is not dict or type(configuration.get("version")) is not int:
        _reject()
    if configuration["version"] not in (
        {2, 3, 4} if publication == 2 else {3, 4} if publication == 3 else {4}
    ):
        _reject()
    if configuration != {
        "version": configuration["version"],
        "registry_id": identity,
        "policy": policy,
        "namespace": namespace,
    }:
        _reject()
    await _recheck(engine, client, scope, namespace, policy)
    return handle


def _receipt(value, *, command_id, run_id):
    _exact(value, _RECEIPT_FIELDS)
    if (
        value["command_id"] != command_id
        or value["run_id"] != run_id
        or value["kind"] != "submit"
        or value["record_state"] != "durably_recorded"
        or value["apply_state"] != "applied"
        or type(value["outcome"]) is not dict
    ):
        _reject()
    return CommandReceipt(**detached(value))


def _record(value, *, request, command_id, scope, namespace, policy):
    from .temporal_deployment_execution_state import _root
    from .temporal_startup_options import validate_seconds

    _exact(value, _RECORD_FIELDS)
    submission, reservation = value["submission"], value["reservation"]
    _exact(submission, _SUBMISSION_FIELDS)
    _exact(reservation, {"command_id", "target", "record_state", "apply_state", "root_admission"})
    root = reservation["root_admission"]
    _root(root)
    identity = root_run_id(policy["deployment_id"], scope, command_id)
    if (
        type(submission["version"]) is not int
        or submission["version"] != 1
        or submission["request"] != request
        or type(submission["manifest"]) is not dict
        or reservation["command_id"] != command_id
        or reservation["target"] != identity
        or reservation["record_state"] != "durably_recorded"
        or reservation["apply_state"] != "not_applied"
        or root["scope"] != scope
        or root["command_id"] != command_id
        or root["run_id"] != identity
        or root["namespace"] != namespace
        or root["registry_id"] != registry_id(policy["deployment_id"])
        or root["request_digest"] != digest(request)
        or root["manifest_digest"] != digest(submission["manifest"])
    ):
        _reject()
    protocol = submission["manifest"].get("deployment_admission_protocol", {})
    if (
        protocol.get("version") not in (2, 3, 4)
        or protocol.get("policy") != policy
        or protocol.get("registry_id") != root["registry_id"]
    ):
        _reject()
    validate_seconds(submission["activity_timeout"])
    text(submission["task_queue"], "Original Temporal task queue")
    if value["execution_epoch"] is not None:
        text(value["execution_epoch"], "Original SDK execution epoch")
        if len(value["execution_epoch"]) > 1024:
            _reject()
    if value["run_receipt"] is not None:
        if value["execution_epoch"] is None:
            _reject()
        _receipt(value["run_receipt"], command_id=command_id, run_id=identity)
    return detached(value)


async def _lookup(handle, scope, command_id, request, namespace, policy):
    return await _query(
        handle,
        {
            "kind": "deployment_submission",
            "scope": scope,
            "command_id": command_id,
            "payload_digest": digest(request),
            "admission_policy": policy,
            "namespace": namespace,
        },
    )


def _fresh(request, manifest, scope):
    from .spec_codec import agent_steps
    from .temporal_bindings import validate_bindings
    from .temporal_managed_context import check_scope
    from .temporal_session_tree import require_tree_admission
    from .temporal_state import validate_request, validate_schema_references

    check_scope(manifest, scope)
    for step in agent_steps(request["definition"]):
        validate_schema_references(step["output_schema"])
    validate_request(request, manifest)
    validate_bindings(request, manifest, scope)
    require_tree_admission(request, manifest)


async def _actual_submission(engine, client, record, scope, command_id, namespace, policy):
    from .temporal import _sdk
    from .temporal_parent_state import PARENT_WORKFLOW_NAME

    sdk = _sdk()
    submission, root = record["submission"], record["reservation"]["root_admission"]
    request = submission["request"]
    workflow = (
        PARENT_WORKFLOW_NAME
        if request["definition"]["kind"] in {"graph", "team", "dynamic"}
        else WORKFLOW_NAME
    )
    handle = client.get_workflow_handle(
        root["run_id"],
        **({"run_id": record["execution_epoch"]} if record["execution_epoch"] else {}),
    )
    try:
        description = await handle.describe()
    except sdk[6] as exc:
        if exc.status != sdk[7].NOT_FOUND or record["execution_epoch"] is not None:
            raise
        await _recheck(engine, client, scope, namespace, policy)
        accepted = {
            "scope": scope,
            "command_id": command_id,
            "request": request,
            "manifest": submission["manifest"],
            "activity_timeout": submission["activity_timeout"],
            "deployment_admission": {"version": 1, "root": root, "lineage": []},
        }
        try:
            await client.start_workflow(
                workflow,
                accepted,
                id=root["run_id"],
                task_queue=submission["task_queue"],
                id_reuse_policy=sdk[3].REJECT_DUPLICATE,
                id_conflict_policy=sdk[2].FAIL,
                retry_policy=None,
            )
        except sdk[5]:
            pass
        await _recheck(engine, client, scope, namespace, policy)
        description = await handle.describe()
    await _recheck(engine, client, scope, namespace, policy)
    if (
        description.id != root["run_id"]
        or description.namespace != namespace["name"]
        or description.workflow_type != workflow
        or description.task_queue != submission["task_queue"]
        or description.parent_id is not None
        or description.parent_run_id is not None
        or record["execution_epoch"] not in (None, description.run_id)
    ):
        _reject()
    text(description.run_id, "Original SDK execution epoch")
    epoch = description.run_id
    handle = client.get_workflow_handle(root["run_id"], run_id=epoch)
    proof = await _query(handle, {"scope": scope, "kind": "deployment_admission"})
    from .temporal_deployment_execution import _PROOF_FIELDS

    await _recheck(engine, client, scope, namespace, policy)
    _exact(proof, _PROOF_FIELDS)
    if (
        type(proof["version"]) is not int
        or proof["version"] != 1
        or proof["scope"] != scope
        or proof["run_id"] != root["run_id"]
        or proof["command_id"] != command_id
        or proof["execution_epoch"] != epoch
        or proof["original_execution_epoch"] != epoch
        or proof["namespace"] != namespace
        or proof["request"] != request
        or proof["request_digest"] != digest(request)
        or proof["manifest"] != submission["manifest"]
        or proof["manifest_digest"] != digest(submission["manifest"])
        or proof["admission"] != {"version": 1, "root": root, "lineage": []}
        or proof["proof_digest"] != digest({k: v for k, v in proof.items() if k != "proof_digest"})
    ):
        _reject()
    start = await _query(handle, {"scope": scope, "kind": "deployment_start"})
    await _recheck(engine, client, scope, namespace, policy)
    if start != {
        "scope": scope,
        "run_id": root["run_id"],
        "execution_epoch": epoch,
        "activity_timeout": submission["activity_timeout"],
        "task_queue": submission["task_queue"],
        "request_digest": digest(request),
        "manifest_digest": digest(submission["manifest"]),
    }:
        _reject()
    receipt = await _query(
        handle, {"scope": scope, "kind": "submission", "command_id": command_id, "request": request}
    )
    await _recheck(engine, client, scope, namespace, policy)
    _receipt(receipt, command_id=command_id, run_id=root["run_id"])
    return epoch, receipt


async def submit(engine, spec, input, *, command_id, budget=32, session_id=None):
    from .temporal_bindings import normalize_request

    text(command_id, "Command ID")
    # SDK JSON payloads turn tuple arrays into lists. Keep the logical request
    # in that same representation before comparing original History envelopes.
    if engine.release.get("deployment_admission_protocol", {}).get("version") == 3:
        from .temporal_deployment_coding_bridge import logical_request

        request = logical_request(spec, input, budget=budget, session_id=session_id)
    else:
        request = json.loads(
            canonical(
                normalize_request(
                    submission_request(spec, input, budget=budget, session_id=session_id), None
                )
            )
        )
    if session_id is not None:
        raise ValidationError("Temporal shared sessions are not supported")
    policy, client, scope = _policy(engine), engine.client, asdict(engine.scope)
    manifest = detached(engine.release)
    timeout, queue = engine.activity_timeout, engine.task_queue
    namespace = await _namespace(engine, client, scope, policy)
    handle = await _registry(engine, client, scope, namespace, policy)
    previous = await _lookup(handle, scope, command_id, request, namespace, policy)
    await _recheck(engine, client, scope, namespace, policy)
    if previous is None:
        _fresh(request, manifest, scope)
        payload = {
            "scope": scope,
            "command_id": command_id,
            "kind": "submit",
            "target": root_run_id(policy["deployment_id"], scope, command_id),
            "payload_digest": digest(request),
            "admission_policy": policy,
            "namespace": namespace,
            "root_admission": {
                "version": 2,
                "manifest_digest": digest(manifest),
                "submission": {
                    "version": 1,
                    "request": request,
                    "manifest": manifest,
                    "activity_timeout": timeout,
                    "task_queue": queue,
                },
            },
        }
        reservation = await _update(handle, "reserve", payload)
        _exact(
            reservation,
            {"command_id", "target", "record_state", "apply_state", "root_admission", "submission"},
        )
        previous = {
            "reservation": {k: v for k, v in reservation.items() if k != "submission"},
            "submission": reservation["submission"],
            "run_receipt": None,
            "execution_epoch": None,
        }
    record = _record(
        previous,
        request=request,
        command_id=command_id,
        scope=scope,
        namespace=namespace,
        policy=policy,
    )
    await _recheck(engine, client, scope, namespace, policy)
    root = record["reservation"]["root_admission"]
    if record["run_receipt"] is not None:
        return RunHandle(
            root["run_id"],
            _receipt(record["run_receipt"], command_id=command_id, run_id=root["run_id"]),
        )
    epoch, receipt = await _actual_submission(
        engine, client, record, scope, command_id, namespace, policy
    )
    await _recheck(engine, client, scope, namespace, policy)
    payload = {
        "scope": scope,
        "admission_policy": policy,
        "namespace": namespace,
        **{
            k: root[k]
            for k in ("command_id", "run_id", "request_digest", "manifest_digest", "proof_digest")
        },
        "execution_epoch": epoch,
        "receipt": receipt,
    }
    result = _record(
        await _update(handle, "record_deployment_submission", payload),
        request=request,
        command_id=command_id,
        scope=scope,
        namespace=namespace,
        policy=policy,
    )
    if (
        result["submission"] != record["submission"]
        or result["reservation"] != record["reservation"]
        or result["execution_epoch"] != epoch
        or result["run_receipt"] != receipt
    ):
        _reject()
    await _recheck(engine, client, scope, namespace, policy)
    observed = _record(
        await _lookup(handle, scope, command_id, request, namespace, policy),
        request=request,
        command_id=command_id,
        scope=scope,
        namespace=namespace,
        policy=policy,
    )
    if observed != result:
        _reject()
    await _recheck(engine, client, scope, namespace, policy)
    return RunHandle(
        root["run_id"], _receipt(receipt, command_id=command_id, run_id=root["run_id"])
    )


async def recover_retirement(engine, run_id, closure):
    """Wake original sealed root History; Registry alone can retire occupancy."""
    from .temporal_deployment_execution import _PROOF_FIELDS
    from .temporal_deployment_release import _binding, _certificate

    closure = detached(closure)
    text(run_id, "Original deployment root Run ID")
    _exact(closure, {"version", "deployment", "ready", "reasons", "calls", "seal"})
    if (
        type(closure["version"]) is not int
        or closure["version"] != 1
        or closure["ready"] is not True
        or closure["reasons"] != []
        or type(closure["calls"]) is not dict
    ):
        _reject()
    proof, certificate = closure["deployment"], closure["seal"]
    _exact(proof, _PROOF_FIELDS)
    policy, client, scope = _policy(engine), engine.client, asdict(engine.scope)
    if (
        type(proof["version"]) is not int
        or proof["version"] != 1
        or proof["scope"] != scope
        or proof["run_id"] != run_id
        or proof["request_digest"] != digest(proof["request"])
        or proof["manifest_digest"] != digest(proof["manifest"])
        or proof["proof_digest"] != digest({k: v for k, v in proof.items() if k != "proof_digest"})
    ):
        _reject()
    _certificate(certificate, proof)
    namespace = await _namespace(engine, client, scope, policy)
    if proof["namespace"] != namespace:
        _reject()
    registry = await _registry(engine, client, scope, namespace, policy, start=False)
    command_id, request = proof["command_id"], proof["request"]
    record = _record(
        await _lookup(registry, scope, command_id, request, namespace, policy),
        request=request,
        command_id=command_id,
        scope=scope,
        namespace=namespace,
        policy=policy,
    )
    await _recheck(engine, client, scope, namespace, policy)
    root, submission, epoch = (
        record["reservation"]["root_admission"],
        record["submission"],
        record["execution_epoch"],
    )
    if (
        epoch is None
        or record["run_receipt"] is None
        or root["run_id"] != run_id
        or proof["execution_epoch"] != epoch
        or proof["original_execution_epoch"] != epoch
        or proof["manifest"] != submission["manifest"]
    ):
        _reject()
    session = "session_origin" in proof["admission"]
    validation = None
    if session:
        from types import SimpleNamespace

        from .temporal_session_deployment_control import _business_identity
        from .temporal_session_deployment_verification import SessionControlValidation
        from .temporal_state import validate_manifest

        origin = proof["admission"]["session_origin"]
        if (
            submission["manifest"].get("deployment_admission_protocol", {}).get("version") != 4
            or submission["manifest"].get("session_deployment_protocol") != 1
            or proof["admission"]
            != {"version": 2, "root": root, "lineage": [], "session_origin": origin}
        ):
            _reject()
        saved = await _query(
            registry,
            {
                "kind": "deployment_session_root",
                "scope": scope,
                "admission_policy": policy,
                "namespace": namespace,
                "command_id": command_id,
                "payload_digest": digest(request),
            },
        )
        await _recheck(engine, client, scope, namespace, policy)
        _exact(saved, _RECORD_FIELDS | {"intent", "session_origin"})
        if {k: saved[k] for k in _RECORD_FIELDS} != record or saved["session_origin"] != origin:
            _reject()
        intent, original_manifest = saved["intent"], detached(submission["manifest"])
        manifest_digest = digest(original_manifest)
        if (
            intent["run_id"] != run_id
            or intent["run_command_id"] != command_id
            or intent["submission"] != submission
        ):
            _reject()

        def validate_original_release(expected):
            # A facade retains no provider Runtime. This adapter only pins the
            # original Registry envelope and caller's existing SDK resources.
            _check(engine, client, scope, namespace, policy)
            if digest(original_manifest) != manifest_digest or expected != original_manifest:
                _reject()
            validate_manifest(original_manifest)

        validation = SessionControlValidation(
            SimpleNamespace(validate_release=validate_original_release),
            client,
            {
                "version": 1,
                "mode": "observe",
                "intent": intent,
                **{
                    k: intent[k]
                    for k in ("scope", "namespace", "coordinator_id", "coordinator_execution_epoch")
                },
            },
            None,
            deployment_id=policy["deployment_id"],
            _coordinator_activity=False,
        )
        if (await validation.validate())["session_origin"] != origin:
            _reject()
        await _recheck(engine, client, scope, namespace, policy)
    elif proof["admission"] != {"version": 1, "root": root, "lineage": []}:
        _reject()
    bound_root = {**root, "state": "held-bound", "execution_epoch": epoch}
    retirement = await _query(
        registry, {"kind": "deployment_retirement", **_binding(bound_root, policy, certificate)}
    )
    await _recheck(engine, client, scope, namespace, policy)
    if retirement is not None:
        if retirement != {"root": bound_root, "certificate": certificate, "released": True}:
            _reject()
        return detached(certificate)
    if session:
        original_run = await _business_identity(
            validation, epoch, reservation=record["reservation"]
        )
        receipt = await _query(
            original_run,
            {"kind": "submission", "scope": scope, "command_id": command_id, "request": request},
        )
        await validation.validate()
        await _recheck(engine, client, scope, namespace, policy)
        _receipt(receipt, command_id=command_id, run_id=run_id)
        actual_epoch = epoch
    else:
        actual_epoch, receipt = await _actual_submission(
            engine, client, record, scope, command_id, namespace, policy
        )
    if actual_epoch != epoch or receipt != record["run_receipt"]:
        _reject()
    handle = client.get_workflow_handle(run_id, run_id=epoch)
    original = await _query(handle, {"kind": "deployment_closure", "scope": scope})
    await _recheck(engine, client, scope, namespace, policy)
    if original != closure:
        _reject()
    if validation is not None:
        await validation.validate()
        await _recheck(engine, client, scope, namespace, policy)
    # A fresh SDK Update executes the existing idempotent seal handler and its
    # wake. Reusing the first seal Update ID would only replay its old reply.
    try:
        result = detached(
            await handle.execute_update(
                "deployment_seal",
                {"scope": scope, "children": certificate["children"]},
                id="ralf-deployment-recover:" + uuid4().hex,
            )
        )
    except Exception as exc:
        _raise_sdk(exc)
    if validation is not None:
        await _business_identity(validation, epoch, reservation=record["reservation"])
        await validation.validate()
    _certificate(result, proof)
    if result != certificate:
        _reject()
    await _recheck(engine, client, scope, namespace, policy)
    return detached(certificate)


def _control_result(value, command_id, target, scope, namespace, *, expected=None, manual=False):
    fields = {"command_id", "target", "record_state", "apply_state"}
    if type(value) is not dict or set(value) not in (fields, fields | {"control_binding"}):
        _reject()
    if {name: value[name] for name in fields} != {
        "command_id": command_id,
        "target": target,
        "record_state": "durably_recorded",
        "apply_state": "not_applied",
    }:
        _reject()
    if "control_binding" not in value:
        if expected is not None:
            _reject()
        return None
    binding = value["control_binding"]
    _exact(
        binding,
        {
            "version",
            "scope",
            "namespace",
            "target",
            "target_execution_epoch",
            "root_run_id",
            "root_execution_epoch",
        },
    )
    if (
        type(binding["version"]) is not int
        or binding["version"] not in ((1, 2) if manual else (1,))
        or binding["scope"] != scope
        or binding["namespace"] != namespace
        or binding["target"] != target
        or (binding["root_run_id"] == target) != (binding["version"] == 2)
        or binding["version"] == 2
        and binding["root_execution_epoch"] != binding["target_execution_epoch"]
    ):
        _reject()
    from .temporal_deployment_execution import _text

    for name in ("target", "target_execution_epoch", "root_run_id", "root_execution_epoch"):
        _text(binding[name])
    if expected is not None and any(binding[name] != item for name, item in expected.items()):
        _reject()
    return detached(binding)


async def guard(engine, kind, command_id, target, payload):
    from . import temporal_deployment_execution as execution

    payload = detached(payload)
    manual = kind == "reconcile" and payload.get("query") is False
    payload_digest = digest(payload)
    policy, client, scope = _policy(engine), engine.client, asdict(engine.scope)
    namespace = await _namespace(engine, client, scope, policy)
    handle = await _registry(engine, client, scope, namespace, policy, start=False)
    request = {
        "scope": scope,
        "command_id": command_id,
        "kind": kind,
        "target": target,
        "payload_digest": payload_digest,
        "admission_policy": policy,
        "namespace": namespace,
    }
    previous = await _query(
        handle,
        {
            **request,
            "kind": "deployment_control",
            "command_kind": kind,
        },
    )
    await _recheck(engine, client, scope, namespace, policy)
    if previous is not None:
        return _control_result(previous, command_id, target, scope, namespace, manual=manual)
    description = await client.get_workflow_handle(target).describe()
    epoch = description.run_id
    execution._text(epoch)
    if (
        description.id != target
        or description.namespace != namespace["name"]
        or getattr(getattr(description, "raw_info", None), "first_run_id", None) != epoch
    ):
        _reject()
    await _recheck(engine, client, scope, namespace, policy)
    proof = await _query(
        client.get_workflow_handle(target, run_id=epoch),
        {
            "scope": scope,
            "kind": "deployment_admission",
        },
    )
    execution._exact(proof, execution._PROOF_FIELDS)
    execution._sealed(proof)
    if (
        type(proof["version"]) is not int
        or proof["version"] != 1
        or proof["scope"] != scope
        or proof["run_id"] != target
        or proof["execution_epoch"] != epoch
        or proof["original_execution_epoch"] != epoch
        or proof["namespace"] != namespace
        or proof["request_digest"] != digest(proof["request"])
        or proof["manifest_digest"] != digest(proof["manifest"])
    ):
        _reject()
    execution._metadata(
        proof["admission"],
        policy,
        scope=scope,
        run_id=target,
        command_id=proof["command_id"],
        request_digest=proof["request_digest"],
        manifest_digest=proof["manifest_digest"],
        manifest=proof["manifest"],
    )
    expected = None
    if proof["admission"]["lineage"]:
        request["descendant"] = {
            "root_command_id": proof["admission"]["root"]["command_id"],
            "execution_epoch": epoch,
        }
        expected = {
            "target_execution_epoch": epoch,
            "root_run_id": proof["admission"]["root"]["run_id"],
            "root_execution_epoch": proof["admission"]["lineage"][0]["parent_execution_epoch"],
        }
    await _recheck(engine, client, scope, namespace, policy)
    try:
        result = await _update(handle, "reserve", request)
    except ValidationError:
        if not manual:
            raise
        # Ordinary admission remains unchanged. Only a definitive refusal can
        # request this stronger original-Action proof, never a transport timeout.
        from .temporal_manual_recovery import manual_payload

        manual_payload(payload, scope)
        request.pop("descendant", None)
        request["recovery"] = {
            "root_command_id": proof["admission"]["root"]["command_id"],
            "execution_epoch": epoch,
            "payload": payload,
        }
        expected = {
            "target_execution_epoch": epoch,
            "root_run_id": proof["admission"]["root"]["run_id"],
            "root_execution_epoch": (
                proof["admission"]["lineage"][0]["parent_execution_epoch"]
                if proof["admission"]["lineage"]
                else epoch
            ),
        }
        await _recheck(engine, client, scope, namespace, policy)
        from .temporal_public_manual_transport import reserve as reserve_manual

        result = await reserve_manual(handle, request)
    await _recheck(engine, client, scope, namespace, policy)
    return _control_result(
        result, command_id, target, scope, namespace, expected=expected, manual=manual
    )


async def diagnostics(engine):
    policy, client, scope = _policy(engine), engine.client, asdict(engine.scope)
    namespace = await _namespace(engine, client, scope, policy)
    handle = await _registry(engine, client, scope, namespace, policy, start=False)
    result = await _query(
        handle,
        {
            "kind": "deployment_admission",
            "scope": scope,
            "admission_policy": policy,
            "namespace": namespace,
        },
    )
    if (
        type(result) is not dict
        or result.get("registry_id") != registry_id(policy["deployment_id"])
        or result.get("policy") != policy
        or result.get("namespace") != namespace
        or result.get("scope") != scope
    ):
        _reject()
    await _recheck(engine, client, scope, namespace, policy)
    return result
