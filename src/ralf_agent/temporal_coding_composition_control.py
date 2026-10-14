"""Original SDK composition transport and owned stop; no business authority."""

import uuid
from dataclasses import asdict
from types import SimpleNamespace

from .errors import CloseIncomplete, DefinitionMismatch
from .temporal_state import detached
from .types import Scope, canonical, digest

ACTIVITY = "ralf.temporal.coding-composition-admission.v1"


def selected(manifest):
    value = manifest.get("coding_composition_protocol")
    return (
        manifest.get("binding_protocol") == 13 and "coding_composition_protocol" in manifest
    ) or (
        manifest.get("binding_protocol") in (15, 17, 19, 21)
        and type(value) is dict
        and type(value.get("version")) is int
        and value["version"] == {15: 3, 17: 4, 19: 5, 21: 6}[manifest["binding_protocol"]]
    )


def _root_kind(manifest, kind):
    """Only the current publication admits the expanded original parent topology."""
    return kind in (
        {"graph", "team", "dynamic"}
        if manifest.get("binding_protocol") in (17, 19, 21)
        else {"graph"}
    )


def _registry(client, scope):
    return client.get_workflow_handle("ralf-temporal-commands-" + digest(scope))


def _actual(client, value, info):
    if (
        client is None
        or info is None
        or info.workflow_id != value["run_id"]
        or info.workflow_run_id != value["execution_epoch"]
        or info.workflow_namespace != client.namespace
        or not selected(value["runtime_manifest"])
    ):
        raise DefinitionMismatch("Composition lost its actual original SDK identity")


async def _namespace(client, expected=None):
    from .temporal_session_activities import namespace_id

    name = client.namespace
    value = {"name": name, "id": await namespace_id(client)}
    if client.namespace != name or (expected is not None and value != expected):
        raise DefinitionMismatch("Composition namespace resource changed")
    return value


def _validate_proof(value, *, scope, run_id, epoch, manifest, namespace, request=None):
    from .temporal_bindings import request_release_digest
    from .temporal_coding_composition_state import _view_fields

    try:
        if (
            type(value) is not dict
            or set(value) != _view_fields()
            or value["version"] != 1
            or type(value["version"]) is not int
            or value["scope"] != scope
            or value["run_id"] != run_id
            or value["execution_epoch"] != epoch
            or value["original_execution_epoch"] != epoch
            or value["namespace"] != namespace
            or canonical(value["manifest"]) != canonical(manifest)
            or value["request_digest"] != digest(value["request"])
            or value["release_digest"] != request_release_digest(value["request"], manifest)
            or (request is not None and canonical(value["request"]) != canonical(request))
            or type(value["revision"]) is not int
            or value["revision"] < 0
            or type(value["physical_stopped"]) is not bool
            or not isinstance(value["action_stops"], list)
            or value["proof_digest"]
            != digest({k: v for k, v in value.items() if k != "proof_digest"})
        ):
            raise DefinitionMismatch("Composition original History proof changed")
        return detached(value)
    except (KeyError, TypeError, ValueError):
        raise DefinitionMismatch("Composition original History proof unavailable") from None


async def _proof(
    client, scope, run_id, epoch, manifest, namespace, *, request=None, allow_unlinked=False
):
    handle = client.get_workflow_handle(run_id, run_id=epoch)
    value = await handle.query("view", {"scope": scope, "kind": "coding_composition_proof"})
    await _namespace(client, namespace)
    if (
        allow_unlinked
        and type(value) is dict
        and value.get("namespace") == {"name": namespace["name"], "id": None}
    ):
        partial = _validate_proof(
            value,
            scope=scope,
            run_id=run_id,
            epoch=epoch,
            manifest=manifest,
            namespace=value["namespace"],
            request=request,
        )
        if (
            partial["request"]["definition"]["kind"] not in {"agent", "sequence"}
            or "coding_parent" in partial["request"]
        ):
            raise DefinitionMismatch("Composition business requires original root admission")
        result = await handle.execute_update(
            "coding_composition_namespace",
            {
                "scope": scope,
                "run_id": run_id,
                "execution_epoch": epoch,
                "manifest_digest": digest(manifest),
                "namespace": namespace,
            },
            id="ralf-composition-namespace:" + digest([scope, run_id, epoch, namespace]),
        )
        if result != {"run_id": run_id, "recorded": True}:
            raise DefinitionMismatch("Standalone selected12 namespace binding unavailable")
        value = await handle.query("view", {"scope": scope, "kind": "coding_composition_proof"})
        await _namespace(client, namespace)
    return _validate_proof(
        value,
        scope=scope,
        run_id=run_id,
        epoch=epoch,
        manifest=manifest,
        namespace=namespace,
        request=request,
    )


def _validate_admission(receipt, expected, epoch, namespace):
    if (
        type(receipt) is not dict
        or set(receipt)
        != set(expected) | {"close_requested", "admitted", "execution_epoch", "namespace"}
        or any(receipt.get(name) != item for name, item in expected.items())
        or type(receipt["close_requested"]) is not bool
        or type(receipt["admitted"]) is not bool
        or receipt["admitted"] != (not receipt["close_requested"])
        or receipt["execution_epoch"] != epoch
        or receipt["namespace"] != namespace
    ):
        raise DefinitionMismatch("Composition admission lost its original registry acceptance")


async def _bind_submission(client, scope, expected, epoch, namespace):
    payload = {"scope": scope, **expected, "execution_epoch": epoch, "namespace": namespace}
    receipt = await _registry(client, scope).execute_update(
        "admit_coding_composition_submission",
        payload,
        id="ralf-composition-admission:" + digest(payload),
    )
    await _namespace(client, namespace)
    _validate_admission(receipt, expected, epoch, namespace)
    return receipt


async def root_admission(runtime, client, value, info):
    _actual(client, value, info)
    runtime.validate_release(value["runtime_manifest"])
    if not _root_kind(value["runtime_manifest"], value["request"]["definition"]["kind"]) or (
        "coding_parent" in value["request"]
    ):
        raise DefinitionMismatch("Composition admission requires its original bounded parent")
    namespace = await _namespace(client)
    expected = {
        "command_id": value["command_id"],
        "run_id": value["run_id"],
        "request_digest": digest(value["request"]),
        "manifest_digest": digest(value["runtime_manifest"]),
    }
    await _bind_submission(client, value["scope"], expected, value["execution_epoch"], namespace)
    receipt = await _registry(client, value["scope"]).query(
        "view", {"scope": value["scope"], "kind": "coding_composition_admission", **expected}
    )
    _validate_admission(receipt, expected, value["execution_epoch"], namespace)
    await _namespace(client, namespace)
    _actual(client, value, info)
    runtime.validate_release(value["runtime_manifest"])
    return {
        "namespace": namespace,
        "admitted": receipt["admitted"],
        "execution_epoch": value["execution_epoch"],
    }


async def validate_activity(client, request, *, workflow_id):
    manifest = request["runtime_manifest"]
    if not selected(manifest):
        return
    if client is None or workflow_id != request.get("run_id"):
        raise DefinitionMismatch("Composition Activity requires its original Run")
    from temporalio import activity

    try:
        info = activity.info()
    except RuntimeError:
        info = None  # Direct original close callbacks already carry their fixed epoch.
    epoch = request.get("execution_epoch")
    if info is not None:
        if (
            info.workflow_id != workflow_id
            or info.workflow_namespace != client.namespace
            or (epoch is not None and epoch != info.workflow_run_id)
        ):
            raise DefinitionMismatch("Composition Activity changed its actual original SDK epoch")
        epoch = info.workflow_run_id
    if not epoch:
        raise DefinitionMismatch("Composition Activity requires actual or original recorded epoch")
    namespace = await _namespace(client)
    original = await _proof(
        client,
        request["scope"],
        workflow_id,
        epoch,
        manifest,
        namespace,
        allow_unlinked=True,
    )
    link = original["request"].get("coding_parent")
    if link is not None:
        if request.get("coding_parent", link) != link or link["namespace"] != namespace:
            raise DefinitionMismatch("Composition Activity changed its original parent link")
        parent = await _proof(
            client,
            request["scope"],
            link["parent_run_id"],
            link["parent_execution_epoch"],
            manifest,
            namespace,
        )
        if (
            parent["request_digest"] != link["parent_request_digest"]
            or parent["release_digest"] != link["parent_release_digest"]
        ):
            raise DefinitionMismatch("Composition Activity replaced its original parent")
        children = await _children(client, parent, namespace)
        call = next((item for item in children if item.get("run_id") == workflow_id), None)
        if call is None or call["request"] != original["request"]:
            raise DefinitionMismatch("Composition Activity lacks its original parent child intent")
        if parent["state"] in {"cancelling", "cancelled", "failed"}:
            await _command(client, original, "cancel", owner_id=parent["run_id"])
            original = await _proof(
                client,
                request["scope"],
                workflow_id,
                epoch,
                manifest,
                namespace,
            )
        actual_execution = {
            name: original[name]
            for name in ("namespace", "execution_epoch", "original_execution_epoch")
        }
        if call.get("child_execution") is None:
            await _adopt(client, parent, original, epoch=True)
            children = await _children(client, parent, namespace)
            call = next((item for item in children if item.get("run_id") == workflow_id), None)
        if call is None or call.get("child_execution") != actual_execution:
            raise DefinitionMismatch("Composition Activity changed original pinned child epoch")
    await _namespace(client, namespace)


async def _discover(client, scope, run_id, manifest, namespace, *, request=None, parent=None):
    # The unbound handle only discovers an epoch. No command, observation adoption,
    # or native permission uses it. Exact History proof is mandatory afterward.
    description = await client.get_workflow_handle(run_id).describe()
    await _namespace(client, namespace)
    epoch = description.run_id
    if parent is not None and (
        description.parent_id != parent["run_id"]
        or description.parent_run_id != parent["execution_epoch"]
    ):
        raise DefinitionMismatch("Composition discovery found a foreign actual SDK parent")
    return await _proof(client, scope, run_id, epoch, manifest, namespace, request=request)


async def _command(client, proof, kind, *, owner_id):
    command_id = (
        "ralf-parent-stop:" + digest([owner_id, proof["run_id"]])
        if kind == "cancel"
        else "ralf-parent-recover:" + digest([owner_id, proof["run_id"], proof["revision"]])
    )
    payload = {"kind": kind, "scope": proof["scope"]}
    await _namespace(client, proof["namespace"])
    result = await client.get_workflow_handle(
        proof["run_id"], run_id=proof["execution_epoch"]
    ).execute_update("command", {"command_id": command_id, "payload": payload}, id=command_id)
    await _namespace(client, proof["namespace"])
    return result


def _child_update(parent, child):
    return {
        "scope": parent["scope"],
        "run_id": parent["run_id"],
        "execution_epoch": parent["execution_epoch"],
        "request_digest": parent["request_digest"],
        "release_digest": parent["release_digest"],
        "child_run_id": child["run_id"],
        "evidence": child,
    }


async def _adopt(client, parent, child, *, epoch=False):
    name = "coding_composition_child_epoch" if epoch else "coding_composition_child_stopped"
    payload = _child_update(parent, child)
    await _namespace(client, parent["namespace"])
    result = await client.get_workflow_handle(
        parent["run_id"], run_id=parent["execution_epoch"]
    ).execute_update(name, payload, id="ralf-composition:" + name + ":" + digest(payload))
    await _namespace(client, parent["namespace"])
    if result != {"run_id": child["run_id"], "recorded": True}:
        raise DefinitionMismatch("Composition parent lacks original adoption acknowledgement")


async def _child_proof(client, parent, call, manifest, namespace):
    from .temporal_coding_composition_state import _link

    request = call["request"]
    link = _link(request)
    if (
        type(link) is not dict
        or link["parent_run_id"] != parent["run_id"]
        or link["parent_execution_epoch"] != parent["execution_epoch"]
        or link["parent_request_digest"] != parent["request_digest"]
        or link["parent_release_digest"] != parent["release_digest"]
        or link["child_run_id"] != call["run_id"]
        or link["cap"] != call["cap"]
        or link["namespace"] != namespace
        or manifest.get("binding_protocol") in (17, 19, 21)
        and (
            link["scope"] != parent["scope"]
            or link["call_id"] != call.get("id")
            or link["member"] != call.get("member")
            or link["command_id"] != call.get("command_id")
            or link["planning_revision"] != call.get("planning_revision")
            or call.get("child_request_digest") != digest(request)
        )
    ):
        raise DefinitionMismatch("Composition child original ownership changed")
    execution = call.get("child_execution")
    if execution is None:
        result = await _discover(
            client,
            parent["scope"],
            call["run_id"],
            manifest,
            namespace,
            request=request,
            parent=parent,
        )
    else:
        if (
            execution["namespace"] != namespace
            or execution["execution_epoch"] != execution["original_execution_epoch"]
        ):
            raise DefinitionMismatch("Composition original child execution changed")
        result = await _proof(
            client,
            parent["scope"],
            call["run_id"],
            execution["execution_epoch"],
            manifest,
            namespace,
            request=request,
        )
    return result


async def _children(client, parent, namespace):
    value = await client.get_workflow_handle(
        parent["run_id"], run_id=parent["execution_epoch"]
    ).query("view", {"scope": parent["scope"], "kind": "coding_composition_children"})
    await _namespace(client, namespace)
    if (
        type(value) is not list
        or len(value) > 4096
        or any(type(item) is not dict for item in value)
    ):
        raise DefinitionMismatch("Composition original child obligations unavailable")
    if len({item.get("run_id") for item in value}) != len(value):
        raise DefinitionMismatch("Composition original child obligations are duplicated")
    return detached(value)


async def control(runtime, client, value, info=None):
    runtime.validate_release(value["runtime_manifest"])
    actual = {
        **value,
        "run_id": value["parent_id"],
        "execution_epoch": value["parent_execution_epoch"],
    }
    _actual(client, actual, info)
    namespace = await _namespace(client, value["namespace"])
    parent = await _proof(
        client,
        value["scope"],
        value["parent_id"],
        value["parent_execution_epoch"],
        value["runtime_manifest"],
        namespace,
    )
    if (
        parent["request_digest"] != value["parent_request_digest"]
        or parent["release_digest"] != value["parent_release_digest"]
    ):
        raise DefinitionMismatch("Composition control changed its original parent request/release")
    supplied = value["child"]
    call = next(
        (
            item
            for item in await _children(client, parent, namespace)
            if item.get("run_id") == supplied.get("run_id")
        ),
        None,
    )
    identity = (
        "id",
        "call_id",
        "member",
        "input",
        "command_id",
        "run_id",
        "request",
        "cap",
        "depth",
        "child_request_digest",
    )
    if call is None or any(call.get(name) != supplied.get(name) for name in identity):
        raise DefinitionMismatch("Composition control lost its original child intent")
    mode = value["mode"]
    if mode == "register" and parent["state"] in {"cancelling", "cancelled", "failed", "succeeded"}:
        raise DefinitionMismatch("Stopped original parent cannot register child business")
    if mode == "register":
        from .temporal import TemporalEngine
        from .temporal_state import validate_request

        validate_request(call["request"], value["runtime_manifest"])
        engine = TemporalEngine(
            client,
            task_queue=value["task_queue"],
            release=value["runtime_manifest"],
            scope=Scope(**value["scope"]),
        )
        await engine._guard("submit", call["command_id"], call["run_id"], call["request"])
        result = {"run_id": call["run_id"], "registered": True}
    else:
        child = await _child_proof(client, parent, call, value["runtime_manifest"], namespace)
        if mode == "recover" and parent["state"] in {"cancelling", "cancelled", "failed"}:
            await _command(client, child, "cancel", owner_id=parent["run_id"])
        if mode in {"cancel", "recover"}:
            await _command(
                client, child, "cancel" if mode == "cancel" else "drive", owner_id=parent["run_id"]
            )
            result = (
                {"run_id": child["run_id"], "recovery_requested": True}
                if mode == "recover"
                else {"run_id": child["run_id"], "cancel_requested": True}
            )
        elif mode == "observe":
            handle = client.get_workflow_handle(child["run_id"], run_id=child["execution_epoch"])
            result = {
                **await handle.query("view", {"scope": value["scope"], "kind": "diagnostics"}),
                "scope": value["scope"],
                "coding_composition_proof": child,
            }
        else:
            raise DefinitionMismatch("Unknown original composition control")
        result["coding_composition_proof"] = child
    await _namespace(client, namespace)
    _actual(client, actual, info)
    runtime.validate_release(value["runtime_manifest"])
    return detached(result)


async def _initialize_root(client, scope, candidate, manifest, namespace):
    epoch = candidate.get("execution_epoch")
    if epoch is None:
        description = await client.get_workflow_handle(candidate["run_id"]).describe()
        if description.parent_id is not None or description.parent_run_id is not None:
            raise DefinitionMismatch("Composition root discovery found an actual SDK parent")
        epoch = description.run_id
    elif candidate.get("namespace") != namespace:
        raise DefinitionMismatch("Composition root admission namespace changed")
    await _namespace(client, namespace)
    handle = client.get_workflow_handle(candidate["run_id"], run_id=epoch)
    raw = await handle.query("view", {"scope": scope, "kind": "coding_composition_proof"})
    partial = raw.get("namespace") if type(raw) is dict else None
    if partial not in (namespace, {"name": namespace["name"], "id": None}):
        raise DefinitionMismatch("Composition original root namespace changed")
    root = _validate_proof(
        raw,
        scope=scope,
        run_id=candidate["run_id"],
        epoch=epoch,
        manifest=manifest,
        namespace=partial,
    )
    if (
        "coding_parent" in root["request"]
        or not _root_kind(manifest, root["request"]["definition"]["kind"])
        or candidate["request_digest"] != digest(root["request"])
    ):
        raise DefinitionMismatch("Composition root lost original submission acceptance")
    expected = {
        name: candidate[name]
        for name in ("command_id", "run_id", "request_digest", "manifest_digest")
    }
    await _bind_submission(client, scope, expected, epoch, namespace)
    if partial != namespace:
        await handle.execute_update(
            "coding_composition_namespace",
            {
                "scope": scope,
                "run_id": candidate["run_id"],
                "execution_epoch": epoch,
                "manifest_digest": digest(manifest),
                "namespace": namespace,
            },
            id="ralf-composition-namespace:"
            + digest([scope, candidate["run_id"], epoch, namespace]),
        )
    return await _proof(
        client, scope, candidate["run_id"], epoch, manifest, namespace, request=root["request"]
    )


async def _leaf_requests(runtime, client, leaf, namespace):
    handle = client.get_workflow_handle(leaf["run_id"], run_id=leaf["execution_epoch"])
    requests = await handle.query("view", {"scope": leaf["scope"], "kind": "coding_requests"})
    await _namespace(client, namespace)
    if type(requests) is not list or len(requests) > 10000:
        raise CloseIncomplete({"coding_composition": "original native requests unavailable"})
    for request in requests:
        if (
            type(request) is not dict
            or request.get("scope") != leaf["scope"]
            or request.get("run_id") != leaf["run_id"]
            or request.get("execution_epoch") != leaf["execution_epoch"]
            or request.get("runtime_manifest") != leaf["manifest"]
        ):
            raise DefinitionMismatch("Composition native request replaced original leaf")
        runtime.validate_release(request["runtime_manifest"])
    return detached(requests)


def _resource_request(runtime, leaf, resource, requests):
    from .delegated_coding import registered_coding_tool
    from .temporal_bindings import selected_runtime

    native = resource["request"]
    dispatch = native["dispatch"]
    if (
        resource["scope"] != leaf["scope"]
        or dispatch["scope"] != leaf["scope"]
        or dispatch["run_id"] != leaf["run_id"]
        or dispatch["execution_epoch"] != leaf["execution_epoch"]
        or resource["effect_key"] != dispatch["effect_key"]
    ):
        raise DefinitionMismatch("Composition resource replaced original leaf dispatch")
    matching = [
        request
        for request in requests
        if request.get("action_id") == dispatch["action_id"]
        and request.get("coding_request") == native
    ]
    if len(matching) != 1:
        raise DefinitionMismatch("Composition resource lacks its exact original History request")
    request = matching[0]
    runtime.validate_release(request["runtime_manifest"])
    selected_host = selected_runtime(runtime, request)
    handler = registered_coding_tool(selected_host.tools.get(request["tool"]))
    if handler is None or handler.identity != resource["runner"]:
        raise DefinitionMismatch("Composition resource changed its original History Runner")
    return request


async def _fence_leaf(runtime, client, leaf, namespace):
    from .temporal_bindings import selected_runtime
    from .temporal_coding_runtime import callbacks, stop

    for request in await _leaf_requests(runtime, client, leaf, namespace):
        info = SimpleNamespace(
            workflow_id=leaf["run_id"],
            workflow_run_id=leaf["execution_epoch"],
            workflow_namespace=namespace["name"],
        )
        await stop(
            selected_runtime(runtime, request), request, callbacks(client, request, info, runtime)
        )
        await _namespace(client, namespace)
        runtime.validate_release(request["runtime_manifest"])


async def _close_child(runtime, client, root, call, manifest, namespace):
    leaf = await _child_proof(client, root, call, manifest, namespace)
    await _adopt(client, root, leaf, epoch=True)
    await _command(client, leaf, "cancel", owner_id=root["run_id"])
    leaf = await _proof(
        client,
        root["scope"],
        leaf["run_id"],
        leaf["execution_epoch"],
        manifest,
        namespace,
        request=call["request"],
    )
    if leaf["state"] not in {"cancelling", "cancelled", "failed", "succeeded"}:
        raise DefinitionMismatch("Original leaf stop recovery requires business closure")
    if not leaf["physical_stopped"]:
        parent = await _proof(
            client,
            root["scope"],
            root["run_id"],
            root["execution_epoch"],
            manifest,
            namespace,
            request=root["request"],
        )
        if parent["state"] not in {"cancelling", "cancelled", "failed", "succeeded"}:
            raise DefinitionMismatch("Original child stop recovery requires its closed parent")
        await _command(client, leaf, "drive", owner_id=root["run_id"])
    await _fence_leaf(runtime, client, leaf, namespace)
    leaf = await _proof(
        client,
        root["scope"],
        leaf["run_id"],
        leaf["execution_epoch"],
        manifest,
        namespace,
        request=call["request"],
    )
    await _adopt(client, root, leaf)
    if not leaf["physical_stopped"]:
        raise CloseIncomplete({"coding_composition": "original leaf owner closure remains pending"})


def _is_notfound(exc):
    from temporalio.service import RPCError, RPCStatusCode

    return isinstance(exc, RPCError) and exc.status == RPCStatusCode.NOT_FOUND


async def _resources(runtime, scope):
    from .delegated_coding import registered_coding_tool

    runners = {}
    for name in runtime.tools._tools:
        handler = registered_coding_tool(runtime.tools.get(name))
        if handler is not None:
            runners[digest(handler.identity)] = handler.runner
    resources = []
    for journal in {id(runner._journal): runner._journal for runner in runners.values()}.values():
        resources.extend(await journal.composition_resources(scope))
    return runners, tuple(resources)


async def close(runtime, *, client, scope):
    manifest, scoped = runtime.orchestration_release, asdict(scope)
    runtime._tool_execution_closing = True
    runtime.validate_release(manifest)
    if client is None:
        raise CloseIncomplete({"coding_composition": "original client unavailable"})
    namespace = await _namespace(client)
    try:
        receipt = await _registry(client, scoped).execute_update(
            "close_coding_composition_submissions",
            {"scope": scoped, "manifest_digest": digest(manifest)},
            id="ralf-composition-close:" + digest([scoped, manifest, uuid.uuid4().hex]),
        )
    except Exception as exc:
        if not _is_notfound(exc):
            raise
        _, records = await _resources(runtime, scope)
        if records:
            raise CloseIncomplete(
                {"coding_composition": "original records lack original root registry"}
            ) from None
        runtime.validate_release(manifest)
        await _namespace(client, namespace)
        return  # Owned submissions drained; no acceptance or native rows exist.
    if (
        type(receipt) is not dict
        or receipt.get("manifest_digest") != digest(manifest)
        or receipt.get("close_requested") is not True
        or type(receipt.get("candidates")) is not list
    ):
        raise DefinitionMismatch("Composition original admission close unavailable")
    await _namespace(client, namespace)
    roots = {}
    obligations = []
    for candidate in receipt["candidates"]:
        try:
            if (
                candidate.get("manifest_digest") != digest(manifest)
                or candidate.get("close_requested") is not True
            ):
                raise DefinitionMismatch("Composition close replaced original admission")
            root = await _initialize_root(client, scoped, candidate, manifest, namespace)
        except Exception as exc:
            if _is_notfound(exc):
                continue  # Admission is durably closed; never create an absent root.
            obligations.append(
                {"root": candidate.get("run_id"), "code": getattr(exc, "code", "root_unavailable")}
            )
            continue
        roots[root["run_id"]] = root
        try:
            await _command(client, root, "cancel", owner_id=root["run_id"])
        except Exception as exc:
            obligations.append(
                {"root": root["run_id"], "code": getattr(exc, "code", "cancel_unavailable")}
            )
    standalone = {}
    try:
        runners, records = await _resources(runtime, scope)
    except Exception as exc:
        obligations.append(
            {"resources": "original", "code": getattr(exc, "code", "resources_unavailable")}
        )
        records = ()
    for resource in records:
        try:
            if digest(resource["runner"]) not in runners:
                raise DefinitionMismatch("Composition close changed original Runner")
            dispatch = resource["request"]["dispatch"]
            leaf = await _proof(
                client, scoped, dispatch["run_id"], dispatch["execution_epoch"], manifest, namespace
            )
            requests = await _leaf_requests(runtime, client, leaf, namespace)
            _resource_request(runtime, leaf, resource, requests)
            link = leaf["request"].get("coding_parent")
            if link is not None and link["parent_run_id"] not in roots:
                raise CloseIncomplete(
                    {"coding_composition": "original resource ancestor acceptance unavailable"}
                )
            if link is None:
                if leaf["request"]["definition"]["kind"] not in {"agent", "sequence"}:
                    raise DefinitionMismatch(
                        "Unlinked original resource requires a standalone Agent"
                    )
                standalone[leaf["run_id"]] = leaf
        except Exception as exc:
            obligations.append(
                {
                    "resource": resource.get("effect_key"),
                    "code": getattr(exc, "code", "resource_unavailable"),
                }
            )
    for leaf in standalone.values():
        try:
            await _command(client, leaf, "cancel", owner_id=leaf["run_id"])
            leaf = await _proof(
                client,
                scoped,
                leaf["run_id"],
                leaf["execution_epoch"],
                manifest,
                namespace,
                request=leaf["request"],
            )
            if leaf["state"] not in {"cancelling", "cancelled", "failed", "succeeded"}:
                raise DefinitionMismatch(
                    "Original standalone stop recovery requires business closure"
                )
            if not leaf["physical_stopped"]:
                await _command(client, leaf, "drive", owner_id=leaf["run_id"])
            await _fence_leaf(runtime, client, leaf, namespace)
            refreshed = await _proof(
                client,
                scoped,
                leaf["run_id"],
                leaf["execution_epoch"],
                manifest,
                namespace,
                request=leaf["request"],
            )
            if not refreshed["physical_stopped"]:
                raise CloseIncomplete(
                    {"coding_composition": "original standalone owner closure remains pending"}
                )
        except Exception as exc:
            obligations.append(
                {"leaf": leaf["run_id"], "code": getattr(exc, "code", "stop_unavailable")}
            )
    for root in roots.values():
        try:
            children = await _children(client, root, namespace)
        except Exception as exc:
            obligations.append(
                {"root": root["run_id"], "code": getattr(exc, "code", "children_unavailable")}
            )
            continue
        for call in children:
            if not call.get("dispatch_started"):
                continue
            try:
                await _close_child(runtime, client, root, call, manifest, namespace)
            except Exception as exc:
                obligations.append(
                    {"child": call.get("run_id"), "code": getattr(exc, "code", "stop_unavailable")}
                )
        try:
            refreshed = await _proof(
                client,
                scoped,
                root["run_id"],
                root["execution_epoch"],
                manifest,
                namespace,
                request=root["request"],
            )
            if not refreshed["physical_stopped"]:
                raise CloseIncomplete(
                    {"coding_composition": "original parent closure remains pending"}
                )
        except Exception as exc:
            obligations.append(
                {"root": root["run_id"], "code": getattr(exc, "code", "proof_unavailable")}
            )
    try:
        runners, records = await _resources(runtime, scope)
        for resource in records:
            try:
                if digest(resource["runner"]) not in runners:
                    raise DefinitionMismatch("Composition close changed original Runner")
                dispatch = resource["request"]["dispatch"]
                leaf = await _proof(
                    client,
                    scoped,
                    dispatch["run_id"],
                    dispatch["execution_epoch"],
                    manifest,
                    namespace,
                )
                _resource_request(
                    runtime, leaf, resource, await _leaf_requests(runtime, client, leaf, namespace)
                )
                if resource["pending_stop"] is not False:
                    raise CloseIncomplete(
                        {"coding_composition": "original native intent remains active"}
                    )
                if not leaf["physical_stopped"]:
                    raise CloseIncomplete(
                        {"coding_composition": "original resource owner closure remains pending"}
                    )
                link = leaf["request"].get("coding_parent")
                if link is None:
                    if leaf["request"]["definition"]["kind"] not in {"agent", "sequence"}:
                        raise DefinitionMismatch(
                            "Unlinked original resource requires a standalone Agent"
                        )
                else:
                    root = roots.get(link["parent_run_id"])
                    if root is None:
                        raise CloseIncomplete(
                            {
                                "coding_composition": "original resource ancestor acceptance unavailable"
                            }
                        )
                    call = next(
                        (
                            call
                            for call in await _children(client, root, namespace)
                            if call["run_id"] == leaf["run_id"]
                        ),
                        None,
                    )
                    if call is None:
                        raise DefinitionMismatch(
                            "Original resource lacks its ancestor child intent"
                        )
                    original = await _child_proof(client, root, call, manifest, namespace)
                    if (
                        original["execution_epoch"] != leaf["execution_epoch"]
                        or original["request"] != leaf["request"]
                        or not original["physical_stopped"]
                    ):
                        raise DefinitionMismatch(
                            "Original resource replaced its physically closed child"
                        )
                    await _adopt(client, root, original, epoch=True)
                    await _adopt(client, root, original)
                    refreshed = await _proof(
                        client,
                        scoped,
                        root["run_id"],
                        root["execution_epoch"],
                        manifest,
                        namespace,
                        request=root["request"],
                    )
                    if not refreshed["physical_stopped"]:
                        raise CloseIncomplete(
                            {
                                "coding_composition": "original resource ancestor closure remains pending"
                            }
                        )
            except Exception as exc:
                obligations.append(
                    {
                        "resource": resource.get("effect_key"),
                        "code": getattr(exc, "code", "resource_unavailable"),
                    }
                )
    except Exception as exc:
        obligations.append(
            {"resources": "original", "code": getattr(exc, "code", "resources_unavailable")}
        )
    runtime.validate_release(manifest)
    await _namespace(client, namespace)
    if obligations:
        raise CloseIncomplete({"coding_composition": obligations})
