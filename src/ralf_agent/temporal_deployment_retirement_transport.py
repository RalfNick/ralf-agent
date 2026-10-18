"""Bounded observations of the original public Registry retirement handler."""

from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .temporal_deployment_admission import _BIND_FIELDS, _exact, _text
from .types import canonical, digest


def _identity(owner, envelope, info):
    owner._check_deployment_registry_epoch()
    registry = owner.commands.deployment
    if registry is None or owner.commands.admission_protocol not in (2, 3, 4):
        raise DefinitionMismatch("Original public Registry required for retirement")
    _exact(
        envelope,
        {
            "version",
            "scope",
            "namespace",
            "registry_id",
            "execution_epoch",
            "observation_id",
            "request",
        },
    )
    request = envelope["request"]
    _exact(request, _BIND_FIELDS | {"certificate"})
    scope = registry._authority(request)
    if (
        type(envelope["version"]) is not int
        or envelope["version"] != 1
        or envelope["scope"] != scope
        or envelope["namespace"] != registry.namespace
        or envelope["registry_id"] != registry.registry_id
        or info.workflow_id != registry.registry_id
        or info.namespace != registry.namespace["name"]
        or type(envelope["execution_epoch"]) is not str
        or not envelope["execution_epoch"]
        or any(
            getattr(info, name, None) != envelope["execution_epoch"]
            for name in ("run_id", "first_execution_run_id", "original_execution_run_id")
        )
        or len(canonical(envelope).encode()) > 2 * 1024 * 1024
    ):
        raise DefinitionMismatch("Retirement observation requires original Registry History")
    # Pure validation only. Quota is freed exclusively by the complete handler.
    owner.commands.prepare_deployment_release(request)
    observation_id = envelope["observation_id"]
    if type(observation_id) is not str or not observation_id or len(observation_id) > 128:
        raise ValidationError("Bounded retirement observation required")
    key, request_digest = digest([scope, observation_id]), digest(request)
    previous = getattr(owner, "_retirement_observations", {}).get(key)
    if previous is not None and previous["request_digest"] != request_digest:
        raise IdempotencyConflict("Retirement observation already identifies another proof")
    return key, request_digest, request


async def accept(owner, envelope, info):
    try:
        key, request_digest, request = _identity(owner, envelope, info)
    except Exception:
        return
    cache = vars(owner).setdefault("_retirement_observations", {})
    if key in cache:
        return
    if len(cache) >= 64:
        completed = next((k for k, v in cache.items() if v["result"] is not None), None)
        if completed is None:
            return
        del cache[completed]
    entry = {"request_digest": request_digest, "result": None}
    cache[key] = entry
    try:
        result = {"ok": True, "receipt": await owner.release_deployment_root(request)}
    except Exception as exc:
        result = {
            "ok": False,
            "error": getattr(exc, "code", None)
            or getattr(exc, "type", "deployment_release_failed"),
        }
    entry["result"] = result


def observe(owner, envelope, info):
    from .temporal_state import detached

    key, request_digest, _ = _identity(owner, envelope, info)
    entry = getattr(owner, "_retirement_observations", {}).get(key)
    return detached(
        {
            **{
                name: envelope[name]
                for name in (
                    "version",
                    "scope",
                    "namespace",
                    "registry_id",
                    "execution_epoch",
                    "observation_id",
                )
            },
            "request_digest": request_digest,
            "result": None if entry is None else entry["result"],
        }
    )


async def execute(client, root, request):
    import asyncio
    from uuid import uuid4

    from .task_controls import _binding
    from .temporal import _raise_code
    from .temporal_deployment_execution_state import _root
    from .temporal_state import COMMAND_REGISTRY_NAME, detached

    root, request = detached(root), detached(request)
    _root(root, bound=True)
    _exact(request, _BIND_FIELDS | {"certificate"})
    namespace, target = client.namespace, root["registry_id"]
    if (
        request["scope"] != root["scope"]
        or request["namespace"] != root["namespace"]
        or root["namespace"]["name"] != namespace
    ):
        raise DefinitionMismatch("Retirement requires original root namespace and Scope")
    ports = [(client, "get_workflow_handle")]
    pins = tuple(_binding(getattr(o, n)) for o, n in ports)

    def check():
        if (
            client.namespace != namespace
            or tuple(_binding(getattr(o, n)) for o, n in ports) != pins
        ):
            raise DefinitionMismatch("Original Registry retirement transport changed")

    async with asyncio.timeout(30):
        handle = client.get_workflow_handle(target)
        check()
        ports.append((handle, "describe"))
        pins += (_binding(handle.describe),)
        description = await handle.describe()
        check()
        epoch = description.run_id
        _text(epoch)
        if (
            description.id != target
            or description.namespace != namespace
            or description.raw_info.first_run_id != epoch
            or description.workflow_type != COMMAND_REGISTRY_NAME
            or description.parent_id is not None
            or description.parent_run_id is not None
        ):
            raise DefinitionMismatch("Original standalone Registry SDK identity required")
        handle = client.get_workflow_handle(target, run_id=epoch)
        check()
        for name in ("query", "signal"):
            ports.append((handle, name))
            pins += (_binding(getattr(handle, name)),)
        envelope = dict(
            version=1,
            scope=root["scope"],
            namespace=root["namespace"],
            registry_id=target,
            execution_epoch=epoch,
            observation_id=uuid4().hex,
            request=request,
        )
        if len(canonical(envelope).encode()) > 2 * 1024 * 1024:
            raise ValidationError("Bounded original retirement proof required")
        expected = {name: value for name, value in envelope.items() if name != "request"} | {
            "request_digest": digest(request)
        }

        async def query():
            result = await handle.query(
                "view",
                {
                    "kind": "deployment_retirement_observation",
                    "scope": root["scope"],
                    "retirement_observation": detached(envelope),
                },
            )
            check()
            if type(result) is dict and set(result) == {"error"}:
                _raise_code(result["error"])
            if (
                type(result) is not dict
                or set(result) != {*expected, "result"}
                or any(
                    result[k] != v or type(result[k]) is not type(v) for k, v in expected.items()
                )
            ):
                raise DefinitionMismatch("Original retirement observation identity changed")
            return result["result"]

        # Unsupported historical selected Workers must use their matching SDK.
        # A malformed/failed probe never authorizes an Update fallback.
        await query()
        await handle.signal("retire_deployment_root", detached(envelope))
        check()
        while True:
            result = await query()
            if result is not None:
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise DefinitionMismatch("Typed original retirement result required")
                if result["ok"] is False and set(result) == {"ok", "error"}:
                    _raise_code(result["error"])
                if result["ok"] is True and set(result) == {"ok", "receipt"}:
                    receipt = result["receipt"]
                    if (
                        type(receipt) is dict
                        and set(receipt) == {"root", "certificate", "released"}
                        and receipt["root"] == root
                        and receipt["certificate"] == request["certificate"]
                        and receipt["released"] is True
                    ):
                        return detached(receipt)
                raise DefinitionMismatch("Original retirement certificate or receipt changed")
            await asyncio.sleep(0.02)
