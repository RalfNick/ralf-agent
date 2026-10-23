"""Bounded observations of original scoped Registry manual verification."""

from .errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict, ValidationError
from .temporal_deployment_admission import _exact, _sha, _text
from .types import canonical, digest


def _identity(owner, envelope, info):
    from .temporal_manual_recovery import manual_payload
    from .temporal_scoped_manual_recovery import FIELDS, configuration

    original = configuration(owner.commands, info)
    _exact(
        envelope, {"version", "scope", "namespace", "execution_epoch", "observation_id", "request"}
    )
    if envelope["scope"] != original["scope"]:
        raise AuthorizationDenied("Manual observation belongs to another Scope")
    if (
        type(envelope["version"]) is not int
        or envelope["version"] != 1
        or envelope["namespace"] != original["namespace"]
        or envelope["execution_epoch"] != original["registry_execution_epoch"]
        or len(canonical(envelope).encode()) > 2 * 1024 * 1024
    ):
        raise DefinitionMismatch("Manual observation requires original Registry History")
    request = envelope["request"]
    _exact(request, FIELDS | {"recovery"})
    if request["scope"] != original["scope"]:
        raise AuthorizationDenied("Manual request belongs to another Scope")
    _text(request["command_id"])
    _text(request["target"])
    _sha(request["payload_digest"])
    recovery = request["recovery"]
    _exact(recovery, {"version", "registry_execution_epoch", "namespace", "payload"})
    if (
        type(recovery["version"]) is not int
        or recovery["version"] != 1
        or recovery["namespace"] != original["namespace"]
        or recovery["registry_execution_epoch"] != original["registry_execution_epoch"]
        or request["kind"] != "reconcile"
        or digest(manual_payload(recovery["payload"], original["scope"]))
        != request["payload_digest"]
    ):
        raise DefinitionMismatch("Only original scoped manual requests use observations")
    key = envelope["observation_id"]
    if type(key) is not str or not key or len(key) > 128:
        raise ValidationError("Bounded manual observation identity required")
    request_digest = digest(request)
    previous = getattr(owner, "_manual_observations", {}).get(key)
    if previous is not None and previous["request_digest"] != request_digest:
        raise IdempotencyConflict("Manual observation already identifies another request")
    return key, request_digest, request, original


async def accept(owner, envelope, info):
    try:
        key, request_digest, request, _ = _identity(owner, envelope, info)
    except Exception:
        return
    cache = vars(owner).setdefault("_manual_observations", {})
    if key in cache:
        return
    if len(cache) >= 64:
        completed = next((k for k, v in cache.items() if v["result"] is not None), None)
        if completed is None:
            return
        del cache[completed]
    # Claim before the async original verifier. Pending work is never evicted.
    entry = {"request_digest": request_digest, "result": None}
    cache[key] = entry
    try:
        result = {"ok": True, "receipt": await owner.reserve(request)}
    except Exception as exc:
        result = {
            "ok": False,
            "error": getattr(exc, "code", None) or getattr(exc, "type", "validation_error"),
        }
    entry["result"] = result


def observe(owner, envelope, info):
    from .temporal_state import detached

    key, request_digest, _, original = _identity(owner, envelope, info)
    entry = getattr(owner, "_manual_observations", {}).get(key)
    return detached(
        {
            "version": 1,
            "scope": original["scope"],
            "namespace": original["namespace"],
            "execution_epoch": original["registry_execution_epoch"],
            "observation_id": key,
            "request_digest": request_digest,
            "result": None if entry is None else entry["result"],
        }
    )


async def execute(client, registry_id, request, *, original):
    import asyncio
    from uuid import uuid4

    from .task_controls import _binding
    from .temporal import _raise_code
    from .temporal_scoped_reservation import _receipt
    from .temporal_state import detached

    request, original = detached(request), detached(original)
    _exact(original, {"version", "scope", "namespace", "registry_execution_epoch"})
    namespace = client.namespace
    if (
        type(original["version"]) is not int
        or original["version"] != 1
        or original["scope"] != request["scope"]
        or original["namespace"] != namespace
        or registry_id != "ralf-temporal-commands-" + digest(request["scope"])
    ):
        raise DefinitionMismatch("Original manual Registry configuration changed")
    epoch = original["registry_execution_epoch"]
    _text(epoch)
    envelope = {
        "version": 1,
        "scope": request["scope"],
        "namespace": namespace,
        "execution_epoch": epoch,
        "observation_id": uuid4().hex,
        "request": request,
    }
    if len(canonical(envelope).encode()) > 2 * 1024 * 1024:
        raise ValidationError("Bounded manual request required")
    ports = [(client, "get_workflow_handle")]
    pins = tuple(_binding(getattr(o, n)) for o, n in ports)

    def check():
        if (
            client.namespace != namespace
            or tuple(_binding(getattr(o, n)) for o, n in ports) != pins
        ):
            raise DefinitionMismatch("Original manual Registry transport changed")

    async def query(handle):
        value = await handle.query(
            "view",
            {
                "kind": "scoped_manual_configuration",
                "scope": envelope["scope"],
                "manual_observation": detached(envelope),
            },
        )
        check()
        return detached(value)

    def observation(value):
        if type(value) is dict and set(value) == {"error"}:
            _raise_code(value["error"])
        if type(value) is not dict or set(value) != {"manual_observation"}:
            raise DefinitionMismatch("Original manual observation unavailable")
        value = value["manual_observation"]
        expected = {
            "version": 1,
            "scope": envelope["scope"],
            "namespace": namespace,
            "execution_epoch": epoch,
            "observation_id": envelope["observation_id"],
            "request_digest": digest(request),
        }
        if (
            type(value) is not dict
            or set(value) != {*expected, "result"}
            or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
        ):
            raise DefinitionMismatch("Original manual observation identity changed")
        return value

    async with asyncio.timeout(30):
        handle = client.get_workflow_handle(registry_id, run_id=epoch)
        check()
        for name in ("query", "signal", "execute_update"):
            ports.append((handle, name))
            pins += (_binding(getattr(handle, name)),)
        first = await query(handle)
        if type(first) is dict and digest(first) == digest(original):
            # Old manual-capable Workers ignore this optional probe field.
            if digest(await query(handle)) != digest(original):
                raise DefinitionMismatch("Original legacy manual Worker changed")
            result = await handle.execute_update("reserve", request)
            check()
            return detached(_receipt(result, request))
        observation(first)
        await handle.signal("reserve_scoped_manual", detached(envelope))
        check()
        while True:
            result = observation(await query(handle))["result"]
            if result is not None:
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise DefinitionMismatch("Invalid manual observation result")
                if result["ok"] and set(result) == {"ok", "receipt"}:
                    return detached(_receipt(result["receipt"], request))
                if result["ok"] is False and set(result) == {"ok", "error"}:
                    _raise_code(result["error"])
                raise DefinitionMismatch("Invalid manual observation fields")
            await asyncio.sleep(0.02)
