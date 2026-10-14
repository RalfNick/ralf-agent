"""SDK mechanics for original actual-call ownership and sealed root retirement."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

from . import temporal_deployment_execution as execution
from . import temporal_deployment_release_state as state
from .errors import DefinitionMismatch, RalfError
from .temporal_context_execution import ContextExecutionOwner, ContextExecutionRejected
from .temporal_deployment_admission import _exact, _sha, registry_id
from .temporal_state import detached
from .types import digest

RELEASE_ACTIVITY = "ralf.temporal.deployment-release.v2"
_RELEASE_MARKER = object()
_CONTEXT = ContextVar("ralf_original_deployment_activity", default=None)


def _reject():
    raise DefinitionMismatch("Original SDK deployment closure proof does not match")


def check_owner(runtime):
    runtime.validate_release()
    if not state.public(runtime.manifest):
        return None
    owner = getattr(runtime, "_deployment_execution_owner", None)
    if type(owner) is not ContextExecutionOwner or owner is not getattr(
        runtime, "_deployment_execution_owner_pin", None
    ):
        _reject()
    return owner


async def close_owner(runtime, *, wait_timeout=30):
    owner = check_owner(runtime)
    if owner is not None:
        await owner.aclose(wait_timeout=wait_timeout)


@contextmanager
def activity_context(runtime, client, proof, carrier):
    token = _CONTEXT.set((runtime, client, detached(proof), detached(carrier)))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _ack(identity, field, value):
    return {
        "activity_id": identity["activity_id"],
        "attempt": identity["attempt"],
        "invocation_id": identity["invocation_id"],
        field: value,
    }


def _definitive_refusal(exc):
    code = (
        exc.code
        if isinstance(exc, RalfError)
        else getattr(getattr(exc, "cause", None), "type", None)
    )
    return code in {"definition_mismatch", "validation_error", "authorization_denied"}


def wrap_activity(runtime, client, function):
    if not state.public(runtime.manifest):
        return function
    from temporalio import activity

    definition = activity._Definition.from_callable(function)
    if definition is None or definition.name in {RELEASE_ACTIVITY, execution.ACTIVITY}:
        _reject()

    @wraps(function)
    async def wrapped(request):
        owner = check_owner(runtime)
        context = _CONTEXT.get()
        if context is None or context[0] is not runtime or context[1] is not client:
            _reject()
        proof, carrier = context[2], context[3]
        info = activity.info()
        execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
        if info.activity_type != definition.name or execution._activity_body(carrier) != request:
            _reject()
        identity = {
            "version": 1,
            "scope": proof["scope"],
            "run_id": proof["run_id"],
            "execution_epoch": proof["execution_epoch"],
            "activity_id": info.activity_id,
            "activity_name": info.activity_type,
            "attempt": info.attempt,
            "invocation_id": uuid4().hex,
            "request_digest": digest(carrier),
            "manifest_digest": proof["manifest_digest"],
        }
        handle = client.get_workflow_handle(proof["run_id"], run_id=proof["execution_epoch"])
        owner_proof = {
            "scope": proof["scope"],
            "action_id": digest(
                [
                    proof["run_id"],
                    identity["activity_id"],
                    identity["attempt"],
                    identity["invocation_id"],
                ]
            ),
            "release_digest": proof["manifest_digest"],
            "request_digest": digest(carrier),
            "execution_epoch": proof["execution_epoch"],
        }
        lifecycle = {"requested": False, "allowed": None}

        async def begin():
            lifecycle["requested"] = True
            try:
                granted = await handle.execute_update(
                    "deployment_call_started",
                    identity,
                    id="ralf-deployment-call:" + digest(identity),
                )
            except Exception as exc:
                if _definitive_refusal(exc):
                    lifecycle["allowed"] = False
                raise
            if granted == _ack(identity, "allowed", False):
                lifecycle["allowed"] = False
                _reject()
            if granted != _ack(identity, "allowed", True):
                _reject()
            lifecycle["allowed"] = True

        async def ended(received):
            if received != owner_proof:
                _reject()
            execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
            if check_owner(runtime) is not owner:
                _reject()
            if not lifecycle["requested"]:
                return
            if lifecycle["allowed"] is None:
                try:
                    await begin()
                except Exception:
                    if lifecycle["allowed"] is not False:
                        raise
            if lifecycle["allowed"] is False:
                return
            result = await handle.execute_update(
                "deployment_call_ended", identity, id="ralf-deployment-call-end:" + digest(identity)
            )
            if result != _ack(identity, "recorded", True):
                _reject()
            execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
            check_owner(runtime)

        async def operation():
            if check_owner(runtime) is not owner:
                _reject()
            execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
            await begin()
            result = await function(detached(request))
            execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
            check_owner(runtime)
            return result

        try:
            return await owner.execute(operation, proof=owner_proof, on_end=ended)
        except ContextExecutionRejected as exc:
            if exc.handler_not_started:
                await ended(owner_proof)
            raise

    return wrapped


def _certificate(value, proof):
    _exact(value, state.CERTIFICATE_FIELDS)
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["terminal_state"] not in state.TERMINAL
        or type(value["children"]) is not list
    ):
        _reject()
    for name in (
        "request_digest",
        "manifest_digest",
        "admission_digest",
        "receipt_digest",
        "closure_digest",
        "proof_digest",
    ):
        _sha(value[name])
    if (
        any(
            value[name] != proof[name]
            for name in (
                "scope",
                "run_id",
                "command_id",
                "namespace",
                "execution_epoch",
                "original_execution_epoch",
                "request_digest",
                "manifest_digest",
            )
        )
        or value["admission_digest"] != digest(proof["admission"])
        or value["receipt_digest"] != digest(proof["admission_receipt"])
        or value["proof_digest"]
        != digest({name: item for name, item in value.items() if name != "proof_digest"})
    ):
        _reject()


def _child_entry(call, certificate):
    return {
        "call_id": call["id"],
        "run_id": call["run_id"],
        "command_id": call["command_id"],
        "execution_epoch": None if certificate is None else certificate["execution_epoch"],
        "request_digest": digest(call["request"]),
        "admission_digest": digest(call["deployment_admission"]),
        "seal_digest": None if certificate is None else certificate["proof_digest"],
    }


async def _closure(runtime, client, policy, proof):
    value = detached(
        await client.get_workflow_handle(proof["run_id"], run_id=proof["execution_epoch"]).query(
            "view", {"scope": proof["scope"], "kind": "deployment_closure"}
        )
    )
    _exact(value, {"version", "deployment", "ready", "reasons", "calls", "seal"})
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or type(value["ready"]) is not bool
        or type(value["reasons"]) is not list
        or type(value["calls"]) is not dict
    ):
        _reject()
    original = value["deployment"]
    _exact(original, execution._PROOF_FIELDS)
    execution._sealed(original)
    if any(
        original[name] != proof[name]
        for name in execution._PROOF_FIELDS - {"children", "proof_digest"}
    ):
        _reject()
    if not value["ready"] or value["reasons"]:
        _reject()
    for call in value["calls"].values():
        _exact(call, {"identity", "allowed", "stopped", "end_proof"})
        _exact(call["identity"], state.CALL_FIELDS)
        if (
            type(call["allowed"]) is not bool
            or type(call["stopped"]) is not bool
            or call["allowed"]
            and (call["stopped"] is not True or call["end_proof"] != call["identity"])
        ):
            _reject()
    runtime.validate_release(original["manifest"])
    await execution._namespace(client, proof["namespace"])
    return value


async def _tree(runtime, client, policy, proof, *, seal, seen=None):
    seen = set() if seen is None else seen
    if proof["run_id"] in seen:
        _reject()
    seen.add(proof["run_id"])
    closure = await _closure(runtime, client, policy, proof)
    proof = closure["deployment"]
    children = []
    for call in proof["children"]:
        if call.get("settled") is not True or call.get("uncertain") is True:
            _reject()
        if call.get("dispatch_started") is not True and call.get("started") is not True:
            if (
                call.get("deployment_execution_epoch") is not None
                or call.get("state") not in state.TERMINAL
            ):
                _reject()
            children.append(_child_entry(call, None))
            continue
        epoch = call.get("deployment_execution_epoch")
        if type(epoch) is not str or not epoch:
            _reject()
        child = await execution._proof(
            runtime, client, policy, proof["scope"], call["run_id"], epoch, required=True
        )
        if (
            child["request"] != call["request"]
            or child["command_id"] != call["command_id"]
            or child["admission"] != call["deployment_admission"]
        ):
            _reject()
        await execution._ancestry(runtime, client, policy, child)
        certificate = await _tree(runtime, client, policy, child, seal=seal, seen=seen)
        children.append(_child_entry(call, certificate))
    certificate = closure["seal"]
    if certificate is None:
        if not seal:
            _reject()
        payload = {"scope": proof["scope"], "children": children}
        certificate = await client.get_workflow_handle(
            proof["run_id"], run_id=proof["execution_epoch"]
        ).execute_update("deployment_seal", payload, id="ralf-deployment-seal:" + digest(payload))
    _certificate(certificate, proof)
    if certificate["children"] != children:
        _reject()
    current = await execution._proof(
        runtime,
        client,
        policy,
        proof["scope"],
        proof["run_id"],
        proof["execution_epoch"],
        required=True,
    )
    readback = await _closure(runtime, client, policy, current)
    if readback["seal"] != certificate:
        _reject()
    return detached(certificate)


def _binding(root, policy, certificate):
    return {
        "scope": root["scope"],
        "admission_policy": policy,
        "namespace": root["namespace"],
        **{
            name: root[name]
            for name in (
                "command_id",
                "run_id",
                "request_digest",
                "manifest_digest",
                "proof_digest",
                "execution_epoch",
            )
        },
        "certificate": certificate,
    }


async def _claim(client, policy, root, certificate):
    request = {
        "kind": "deployment_admission",
        "scope": root["scope"],
        "admission_policy": policy,
        "namespace": root["namespace"],
    }
    handle = client.get_workflow_handle(root["registry_id"])
    view = await handle.query("view", request)
    if (
        type(view) is not dict
        or view.get("registry_id") != root["registry_id"]
        or view.get("scope") != root["scope"]
        or view.get("policy") != policy
        or view.get("namespace") != root["namespace"]
        or type(view.get("held_roots")) is not list
    ):
        _reject()
    matches = [record for record in view["held_roots"] if record.get("run_id") == root["run_id"]]
    if matches:
        if matches != [root]:
            _reject()
        return
    retirement = await handle.query(
        "view", {"kind": "deployment_retirement", **_binding(root, policy, certificate)}
    )
    if retirement != {"root": root, "certificate": certificate, "released": True}:
        _reject()


async def execute(runtime, client, value, info):
    value = detached(value)
    policy = execution._policy(runtime)
    if policy is None or not state.public(runtime.manifest):
        _reject()
    mode = value.get("mode")
    if mode == "release":
        _exact(value, {"mode", "scope", "run_id", "execution_epoch"})
        execution._actual(client, info, run_id=value["run_id"], epoch=value["execution_epoch"])
        proof = await execution._proof(
            runtime,
            client,
            policy,
            value["scope"],
            value["run_id"],
            value["execution_epoch"],
            required=True,
        )
        if proof["admission"]["lineage"]:
            _reject()
        certificate = await _tree(runtime, client, policy, proof, seal=True)
        root = proof["admission_receipt"]["root"]
        result = await client.get_workflow_handle(root["registry_id"]).execute_update(
            "release_deployment_root",
            _binding(root, policy, certificate),
            id="ralf-deployment-release:" + digest(certificate),
        )
        execution._actual(client, info, run_id=proof["run_id"], epoch=proof["execution_epoch"])
    elif mode == "verify":
        _exact(
            value, {"mode", "scope", "root", "certificate", "manifest", "registry_execution_epoch"}
        )
        runtime.validate_release(value["manifest"])
        root = value["root"]
        execution._exact(root, execution._ROOT_FIELDS)
        registry = registry_id(policy["deployment_id"])
        execution._actual(client, info, run_id=registry, epoch=value["registry_execution_epoch"])
        if (
            root["registry_id"] != registry
            or root["scope"] != value["scope"]
            or root["state"] != "held-bound"
            or root["manifest_digest"] != digest(value["manifest"])
        ):
            _reject()
        handle = client.get_workflow_handle(registry, run_id=value["registry_execution_epoch"])
        description = await handle.describe()
        if (
            description.id != registry
            or description.run_id != value["registry_execution_epoch"]
            or description.namespace != client.namespace
            or getattr(getattr(description, "raw_info", None), "first_run_id", None)
            != value["registry_execution_epoch"]
            or description.parent_id is not None
        ):
            _reject()
        configuration = await handle.query(
            "view",
            {
                "kind": "deployment_configuration",
                "scope": value["scope"],
                "admission_policy": policy,
                "namespace": root["namespace"],
            },
        )
        if configuration != {
            "version": 2,
            "registry_id": registry,
            "policy": policy,
            "namespace": root["namespace"],
        }:
            _reject()
        proof = await execution._proof(
            runtime,
            client,
            policy,
            value["scope"],
            root["run_id"],
            root["execution_epoch"],
            required=True,
        )
        if proof["admission"]["lineage"] or proof["admission_receipt"]["root"] != root:
            _reject()
        certificate = await _tree(runtime, client, policy, proof, seal=False)
        if certificate != value["certificate"]:
            _reject()
        await _claim(client, policy, root, certificate)
        execution._actual(client, info, run_id=registry, epoch=value["registry_execution_epoch"])
        result = {"root": root, "certificate": certificate}
    else:
        _reject()
    await execution._namespace(client, proof["namespace"])
    execution._policy(runtime)
    runtime.validate_release(proof["manifest"])
    return detached(result)


def registered_activity(runtime, client):
    from temporalio import activity

    @activity.defn(name=RELEASE_ACTIVITY)
    async def release(value: dict) -> dict:
        try:
            return {"ok": True, "result": await execute(runtime, client, value, activity.info())}
        except Exception as exc:
            return {
                "ok": False,
                "code": exc.code if isinstance(exc, RalfError) else "deployment_release_failed",
            }

    release.__ralf_deployment_release__ = (_RELEASE_MARKER, runtime, client)
    return release


def is_registered_activity(runtime, client, function):
    from temporalio import activity

    definition = activity._Definition.from_callable(function)
    return (
        definition is not None
        and definition.name == RELEASE_ACTIVITY
        and getattr(function, "__ralf_deployment_release__", None)
        == (_RELEASE_MARKER, runtime, client)
    )
