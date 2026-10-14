"""Actual SDK proof transport for original deployment History admission.

The Worker guards mechanical calls; Registry and original Run/Parent Histories
remain the only owners of root acceptance and descendant intent respectively.
"""

import re
from functools import wraps

from .errors import DefinitionMismatch, RalfError, ValidationError
from .governance import DeploymentAdmissionPolicy, TemporalExecutionPolicy
from .temporal_deployment_admission import registry_id, root_run_id
from .temporal_state import detached
from .types import digest

ACTIVITY = "ralf.temporal.deployment-admission.v1"
_ADMISSION_MARKER = object()
_PROOF_FIELDS = frozenset(
    {
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
)
_ROOT_FIELDS = frozenset(
    {
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
)
_LINK_FIELDS = frozenset(
    {
        "parent_run_id",
        "parent_execution_epoch",
        "parent_request_digest",
        "parent_manifest_digest",
        "call_id",
        "child_run_id",
        "child_command_id",
        "child_request_digest",
    }
)
_VALUE_FIELDS = frozenset(
    {
        "scope",
        "run_id",
        "execution_epoch",
        "command_id",
        "request",
        "runtime_manifest",
        "deployment_admission",
    }
)


def _reject():
    raise DefinitionMismatch("Original SDK deployment admission proof does not match")


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        _reject()


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 1024:
        _reject()


def _sha(value):
    if type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None:
        _reject()


def _sealed(value):
    if value.get("proof_digest") != digest({k: v for k, v in value.items() if k != "proof_digest"}):
        _reject()


def _policy(runtime):
    runtime.validate_release()
    pin = getattr(runtime, "_deployment_admission_policy_pin", None)
    if pin is None:
        return None
    if (
        type(pin) is not DeploymentAdmissionPolicy
        or getattr(runtime, "_deployment_admission_policy", None) is not pin
        or getattr(runtime, "_deployment_admission_identity", None) != pin.identity
    ):
        _reject()
    runtime.validate_release()
    return detached(pin.identity)


def _actual(client, info, *, run_id, epoch):
    if (
        client is None
        or info is None
        or info.workflow_id != run_id
        or info.workflow_run_id != epoch
        or info.workflow_namespace != client.namespace
    ):
        _reject()
    _text(run_id)
    _text(epoch)


async def _namespace(client, expected):
    from .temporal_deployment_admission import _namespace as validate_namespace
    from .temporal_session_activities import namespace_id

    name = client.namespace
    try:
        current = validate_namespace({"name": name, "id": await namespace_id(client)})
    except ValidationError:
        _reject()
    if client.namespace != name or current != expected:
        _reject()
    return current


def _metadata(
    value, policy, *, scope, run_id, command_id, request_digest, manifest_digest, manifest
):
    _exact(value, {"version", "root", "lineage"})
    if type(value["version"]) is not int or value["version"] != 1:
        _reject()
    root, links = value["root"], value["lineage"]
    _exact(root, _ROOT_FIELDS)
    from .temporal_deployment_admission import _namespace as validate_namespace

    try:
        validate_namespace(root["namespace"])
    except ValidationError:
        _reject()
    for field in ("request_digest", "manifest_digest", "proof_digest"):
        _sha(root[field])
    root_proof = {
        k: v for k, v in root.items() if k not in {"state", "execution_epoch", "proof_digest"}
    }
    if (
        type(root["version"]) is not int
        or root["version"] != 1
        or root["registry_id"] != registry_id(policy["deployment_id"])
        or root["scope"] != scope
        or root["proof_digest"] != digest(root_proof)
        or root["run_id"] != root_run_id(policy["deployment_id"], scope, root["command_id"])
        or root["state"] != "held-unbound"
        or root["execution_epoch"] is not None
        or type(links) is not list
    ):
        _reject()
    depth = (
        TemporalExecutionPolicy.from_identity(manifest["execution_policy"]).max_depth
        if "execution_policy" in manifest
        else 8
    )
    if len(links) >= min(depth, 8):
        _reject()
    previous, seen = root["run_id"], {root["run_id"]}
    for link in links:
        _exact(link, _LINK_FIELDS)
        for field in (
            "parent_run_id",
            "parent_execution_epoch",
            "call_id",
            "child_run_id",
            "child_command_id",
        ):
            _text(link[field])
        for field in ("parent_request_digest", "parent_manifest_digest", "child_request_digest"):
            _sha(link[field])
        if link["parent_run_id"] != previous or link["child_run_id"] in seen:
            _reject()
        seen.add(link["child_run_id"])
        previous = link["child_run_id"]
    if previous != run_id or root["manifest_digest"] != manifest_digest:
        _reject()
    if links:
        if (
            links[-1]["child_command_id"] != command_id
            or links[-1]["child_request_digest"] != request_digest
        ):
            _reject()
    elif root["command_id"] != command_id or root["request_digest"] != request_digest:
        _reject()


def _receipt(proof, *, required):
    value = proof["admission_receipt"]
    if value is None:
        if required:
            _reject()
        return
    _exact(
        value, {"version", "run_id", "execution_epoch", "root", "metadata_digest", "proof_digest"}
    )
    _sealed(value)
    root = proof["admission"]["root"]
    _exact(value["root"], _ROOT_FIELDS)
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["run_id"] != proof["run_id"]
        or value["execution_epoch"] != proof["execution_epoch"]
        or value["metadata_digest"] != digest(proof["admission"])
        or value["root"]["state"] != "held-bound"
        or any(value["root"][k] != root[k] for k in root if k not in {"state", "execution_epoch"})
    ):
        _reject()
    _text(value["root"]["execution_epoch"])


async def _proof(runtime, client, policy, scope, run_id, epoch, *, required=False):
    handle = client.get_workflow_handle(run_id, run_id=epoch)
    description = await handle.describe()
    if (
        description.id != run_id
        or description.run_id != epoch
        or description.namespace != client.namespace
    ):
        _reject()
    value = detached(await handle.query("view", {"scope": scope, "kind": "deployment_admission"}))
    _exact(value, _PROOF_FIELDS)
    _sealed(value)
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["scope"] != scope
        or value["run_id"] != run_id
        or value["execution_epoch"] != epoch
        or value["original_execution_epoch"] != epoch
        or type(value["request"]) is not dict
        or type(value["manifest"]) is not dict
        or value["request_digest"] != digest(value["request"])
        or value["manifest_digest"] != digest(value["manifest"])
        or type(value["children"]) is not list
        or len(value["children"]) > 4096
    ):
        _reject()
    runtime.validate_release(value["manifest"])
    protocol = value["manifest"].get("deployment_admission_protocol", {})
    if protocol.get("policy") != policy or protocol.get("registry_id") != registry_id(
        policy["deployment_id"]
    ):
        _reject()
    _metadata(
        value["admission"],
        policy,
        scope=scope,
        run_id=run_id,
        command_id=value["command_id"],
        request_digest=value["request_digest"],
        manifest_digest=value["manifest_digest"],
        manifest=value["manifest"],
    )
    if (
        value["namespace"] != value["admission"]["root"]["namespace"]
        or value["namespace"]["name"] != client.namespace
    ):
        _reject()
    links = value["admission"]["lineage"]
    expected_parent = (
        (links[-1]["parent_run_id"], links[-1]["parent_execution_epoch"]) if links else (None, None)
    )
    if (description.parent_id, description.parent_run_id) != expected_parent:
        _reject()
    _receipt(value, required=required)
    await _namespace(client, value["admission"]["root"]["namespace"])
    from .temporal_deployment_protocol import public_selected

    if public_selected(value["manifest"]):
        await _public_start_binding(client, policy, value, description)
    return value


async def _public_start_binding(client, policy, proof, description):
    root = proof["admission"]["root"]
    response = detached(
        await client.get_workflow_handle(root["registry_id"]).query(
            "view",
            {
                "kind": "deployment_submission",
                "scope": root["scope"],
                "command_id": root["command_id"],
                "payload_digest": root["request_digest"],
                "admission_policy": policy,
                "namespace": root["namespace"],
            },
        )
    )
    _exact(response, {"reservation", "submission", "run_receipt", "execution_epoch"})
    envelope = response["submission"]
    _exact(envelope, {"version", "request", "manifest", "activity_timeout", "task_queue"})
    if (
        response["reservation"].get("root_admission") != root
        or digest(envelope["request"]) != root["request_digest"]
        or envelope["manifest"] != proof["manifest"]
        or description.task_queue != envelope["task_queue"]
    ):
        _reject()
    started = await client.get_workflow_handle(
        proof["run_id"], run_id=proof["execution_epoch"]
    ).query(
        "view",
        {"kind": "deployment_start", "scope": proof["scope"]},
    )
    expected = {
        "scope": proof["scope"],
        "run_id": proof["run_id"],
        "execution_epoch": proof["execution_epoch"],
        "activity_timeout": envelope["activity_timeout"],
        "task_queue": envelope["task_queue"],
        "request_digest": proof["request_digest"],
        "manifest_digest": proof["manifest_digest"],
    }
    if started != expected:
        _reject()
    await _namespace(client, root["namespace"])


def _child(parent, child_id):
    matching = [c for c in parent["children"] if type(c) is dict and c.get("run_id") == child_id]
    if len(matching) != 1:
        _reject()
    return matching[0]


async def _pin(client, parent, child, call):
    previous = call.get("deployment_execution_epoch")
    if previous not in (None, child["execution_epoch"]):
        _reject()
    if previous is None:
        payload = {
            "scope": parent["scope"],
            "parent_run_id": parent["run_id"],
            "parent_execution_epoch": parent["execution_epoch"],
            "child_run_id": child["run_id"],
            "child_execution_epoch": child["execution_epoch"],
            "child_request_digest": child["request_digest"],
            "metadata_digest": digest(child["admission"]),
        }
        result = await client.get_workflow_handle(
            parent["run_id"], run_id=parent["execution_epoch"]
        ).execute_update(
            "deployment_child_epoch", payload, id="ralf-deployment-child:" + digest(payload)
        )
        if result != {"run_id": child["run_id"], "recorded": True}:
            _reject()


async def _ancestry(runtime, client, policy, original):
    current = original
    for index in range(len(original["admission"]["lineage"]) - 1, -1, -1):
        link = original["admission"]["lineage"][index]
        parent = await _proof(
            runtime,
            client,
            policy,
            original["scope"],
            link["parent_run_id"],
            link["parent_execution_epoch"],
            required=True,
        )
        if (
            parent["request_digest"] != link["parent_request_digest"]
            or parent["manifest_digest"] != link["parent_manifest_digest"]
            or parent["admission"]
            != {**original["admission"], "lineage": original["admission"]["lineage"][:index]}
        ):
            _reject()
        call = _child(parent, current["run_id"])
        if (
            call.get("id") != link["call_id"]
            or call.get("command_id") != current["command_id"]
            or call.get("request") != current["request"]
            or call.get("deployment_admission") != current["admission"]
            or call.get("dispatch_started") is not True
        ):
            _reject()
        await _pin(client, parent, current, call)
        refreshed = await _proof(
            runtime,
            client,
            policy,
            parent["scope"],
            parent["run_id"],
            parent["execution_epoch"],
            required=True,
        )
        pinned = _child(refreshed, current["run_id"])
        if (
            pinned.get("deployment_execution_epoch") != current["execution_epoch"]
            or pinned.get("request") != current["request"]
            or pinned.get("deployment_admission") != current["admission"]
        ):
            _reject()
        current = refreshed
    return current


async def _held(client, policy, root_proof, *, bind):
    root = root_proof["admission"]["root"]
    handle = client.get_workflow_handle(root["registry_id"])
    expected = {**root, "state": "held-bound", "execution_epoch": root_proof["execution_epoch"]}
    if bind:
        payload = {
            "scope": root["scope"],
            "admission_policy": policy,
            "namespace": root["namespace"],
            **{
                k: root[k]
                for k in (
                    "command_id",
                    "run_id",
                    "request_digest",
                    "manifest_digest",
                    "proof_digest",
                )
            },
            "execution_epoch": root_proof["execution_epoch"],
        }
        result = await handle.execute_update(
            "bind_deployment_root", payload, id="ralf-deployment-bind:" + digest(payload)
        )
        if result != expected:
            _reject()
    response = await handle.query(
        "view",
        {
            "kind": "deployment_admission",
            "scope": root["scope"],
            "admission_policy": policy,
            "namespace": root["namespace"],
        },
    )
    if (
        type(response) is not dict
        or response.get("version") != 1
        or response.get("registry_id") != root["registry_id"]
        or response.get("scope") != root["scope"]
        or response.get("namespace") != root["namespace"]
        or response.get("policy") != policy
        or type(response.get("held_roots")) is not list
    ):
        _reject()
    roots = [
        r for r in response["held_roots"] if type(r) is dict and r.get("run_id") == root["run_id"]
    ]
    if len(roots) != 1 or roots[0] != expected:
        _reject()
    _receipt(root_proof, required=False)
    if (
        root_proof["admission_receipt"] is not None
        and root_proof["admission_receipt"]["root"] != expected
    ):
        _reject()
    await _namespace(client, root["namespace"])
    return detached(expected)


async def admit(runtime, client, value, info):
    value = detached(value)
    _exact(value, _VALUE_FIELDS)
    policy = _policy(runtime)
    if policy is None:
        _reject()
    _actual(client, info, run_id=value["run_id"], epoch=value["execution_epoch"])
    runtime.validate_release(value["runtime_manifest"])
    proof = await _proof(
        runtime, client, policy, value["scope"], value["run_id"], value["execution_epoch"]
    )
    if any(
        proof[k] != value[v]
        for k, v in (
            ("command_id", "command_id"),
            ("request", "request"),
            ("manifest", "runtime_manifest"),
            ("admission", "deployment_admission"),
        )
    ):
        _reject()
    root_proof = await _ancestry(runtime, client, policy, proof)
    held = await _held(client, policy, root_proof, bind=True)
    _actual(client, info, run_id=value["run_id"], epoch=value["execution_epoch"])
    _policy(runtime)
    runtime.validate_release(value["runtime_manifest"])
    result = {
        "version": 1,
        "run_id": proof["run_id"],
        "execution_epoch": proof["execution_epoch"],
        "root": held,
        "metadata_digest": digest(proof["admission"]),
    }
    return detached({**result, "proof_digest": digest(result)})


def _activity_body(request):
    if type(request) is not dict:
        _reject()
    if "_deployment_activity_request" not in request:
        return request
    _exact(request, {"scope", "_deployment_activity_request"})
    body = request["_deployment_activity_request"]
    if type(body) is not dict or "_deployment_activity_request" in body:
        _reject()
    return body


async def validate_activity(runtime, client, request, info):
    request = detached(request)
    policy = _policy(runtime)
    if policy is None:
        return None
    body = _activity_body(request)
    original = body.get("original_request", body)
    if type(original) is not dict or "_deployment_activity_request" in original:
        _reject()
    scope = request.get("scope", body.get("scope", original.get("scope")))
    if type(scope) is not dict or info is None:
        _reject()
    _actual(client, info, run_id=info.workflow_id, epoch=info.workflow_run_id)
    for payload in (request, body, original):
        if "scope" in payload and payload["scope"] != scope:
            _reject()
        if any(
            payload.get(k, expected) != expected
            for k, expected in (
                ("run_id", info.workflow_id),
                ("execution_epoch", info.workflow_run_id),
            )
        ):
            _reject()
        if "runtime_manifest" in payload:
            runtime.validate_release(payload["runtime_manifest"])
    proof = await _proof(
        runtime, client, policy, scope, info.workflow_id, info.workflow_run_id, required=True
    )
    for payload in (request, body, original):
        if (
            "deployment_admission" in payload
            and payload["deployment_admission"] != proof["admission"]
        ):
            _reject()
    root = await _ancestry(runtime, client, policy, proof)
    held = await _held(client, policy, root, bind=False)
    if proof["admission_receipt"]["root"] != held:
        _reject()
    _actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
    _policy(runtime)
    return detached(proof)


async def control(runtime, client, value, info):
    value = detached(value)
    proof = await validate_activity(runtime, client, value, info)
    if proof is None or value.get("parent_id") != proof["run_id"]:
        _reject()
    runtime.validate_release(value["runtime_manifest"])
    supplied = value["child"]
    call = _child(proof, supplied.get("run_id"))
    for field in ("id", "command_id", "run_id", "request", "deployment_admission"):
        if call.get(field) != supplied.get(field):
            _reject()
    mode = value.get("mode")
    if mode == "register":
        diagnostics = await client.get_workflow_handle(
            proof["run_id"], run_id=proof["execution_epoch"]
        ).query("view", {"scope": proof["scope"], "kind": "diagnostics"})
        if diagnostics.get("snapshot", {}).get("state") in {
            "cancelled",
            "failed",
            "succeeded",
            "cancelling",
        }:
            _reject()
        result = {"run_id": call["run_id"], "registered": True}
    else:
        epoch = call.get("deployment_execution_epoch")
        if epoch is None:
            description = await client.get_workflow_handle(call["run_id"]).describe()
            epoch = description.run_id
        child = await _proof(
            runtime, client, _policy(runtime), proof["scope"], call["run_id"], epoch
        )
        if (
            child["request"] != call["request"]
            or child["admission"] != call["deployment_admission"]
        ):
            _reject()
        await _ancestry(runtime, client, _policy(runtime), child)
        handle = client.get_workflow_handle(call["run_id"], run_id=epoch)
        if mode == "observe":
            result = {
                **await handle.query("view", {"scope": proof["scope"], "kind": "diagnostics"}),
                "scope": proof["scope"],
            }
        elif mode in {"cancel", "recover"}:
            kind = "drive" if mode == "recover" else "cancel"
            command = "ralf-deployment-control:" + digest(
                [proof["run_id"], proof["execution_epoch"], child["run_id"], epoch, kind]
            )
            receipt = await handle.execute_update(
                "command",
                {"command_id": command, "payload": {"kind": kind, "scope": proof["scope"]}},
                id=command,
            )
            result = (
                {"run_id": child["run_id"], "recovery_requested": True}
                if mode == "recover"
                else receipt
            )
        else:
            _reject()
    await _namespace(client, proof["admission"]["root"]["namespace"])
    _actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
    _policy(runtime)
    runtime.validate_release(value["runtime_manifest"])
    return detached(result)


def registered_activity(runtime, client):
    from temporalio import activity

    @activity.defn(name=ACTIVITY)
    async def admission(value: dict) -> dict:
        try:
            return {"ok": True, "result": await admit(runtime, client, value, activity.info())}
        except Exception as exc:
            return {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "deployment_admission_failed",
            }

    admission.__ralf_deployment_admission__ = (_ADMISSION_MARKER, runtime, client)
    return admission


def wrap_activities(runtime, client, activities):
    from temporalio import activity

    def wrap(function):
        definition = activity._Definition.from_callable(function)
        if definition is None:
            _reject()
        from .temporal_deployment_protocol import public_selected
        from .temporal_deployment_release import RELEASE_ACTIVITY, is_registered_activity

        if definition.name == RELEASE_ACTIVITY:
            if not public_selected(runtime.manifest) or not is_registered_activity(
                runtime, client, function
            ):
                _reject()
            return function
        if definition.name == ACTIVITY:
            if getattr(function, "__ralf_deployment_admission__", None) != (
                _ADMISSION_MARKER,
                runtime,
                client,
            ):
                _reject()
            return function

        @wraps(function)
        async def wrapped(request):
            request = detached(request)
            info = activity.info()
            proof = await validate_activity(runtime, client, request, info)
            body = _activity_body(request) if proof is not None else request
            if proof is not None and public_selected(proof["manifest"]):
                from .temporal_deployment_release import activity_context, wrap_activity

                with activity_context(runtime, client, proof, request):
                    result = await wrap_activity(runtime, client, function)(body)
            else:
                result = await function(body)
            if proof is not None:
                _actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
                await _namespace(client, proof["admission"]["root"]["namespace"])
                runtime.validate_release(proof["manifest"])
            _policy(runtime)
            return result

        return wrapped

    return [wrap(function) for function in activities]
