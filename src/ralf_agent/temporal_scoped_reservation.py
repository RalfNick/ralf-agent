"""Bounded synchronous reservations in the original default scoped Registry."""

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .types import canonical, digest

KINDS = {"submit", "approve", "cancel", "reconcile", "drive", "send_input", "patch"}


def _identity(host, envelope, info, *, signal=False):
    if host.commands.deployment is not None:
        raise DefinitionMismatch("Original scoped Registry required")
    if type(envelope) is not dict or set(envelope) != {
        "kind",
        "scope",
        "namespace",
        "execution_epoch",
        "observation_id",
        "request",
    }:
        raise ValidationError("Complete scoped reservation observation required")
    scope = host.commands.scope
    if envelope["scope"] != scope:
        raise AuthorizationDenied("Scoped observation belongs to another Scope")
    epoch = info.run_id
    if (
        info.workflow_id != "ralf-temporal-commands-" + digest(scope)
        or info.namespace != envelope["namespace"]
        or any(
            getattr(info, name, None) != epoch
            for name in ("first_execution_run_id", "original_execution_run_id")
        )
        or type(epoch) is not str
        or not epoch
        or envelope["execution_epoch"] not in ((epoch,) if signal else (None, epoch))
    ):
        raise DefinitionMismatch("Scoped reservation requires its original SDK History")
    request = envelope["request"]
    if (
        envelope["kind"] != "scoped_reserve_receipt"
        or type(request) is not dict
        or request.get("scope") != scope
        or request.get("kind") not in KINDS
        or type(envelope["observation_id"]) is not str
        or not envelope["observation_id"]
        or len(envelope["observation_id"]) > 128
        or len(canonical(envelope).encode()) > 2 * 1024 * 1024
    ):
        raise ValidationError("Invalid synchronous scoped reservation")
    key, request_digest = envelope["observation_id"], digest(request)
    previous = getattr(host, "_scoped_reserve_observations", {}).get(key)
    if previous is not None and previous["request_digest"] != request_digest:
        from .errors import IdempotencyConflict

        raise IdempotencyConflict("Scoped observation already identifies another request")
    return key, request_digest, request, epoch


def accept(host, envelope, info):
    try:
        key, request_digest, request, _ = _identity(host, envelope, info, signal=True)
    except Exception:
        return
    cache = vars(host).setdefault("_scoped_reserve_observations", {})
    if key in cache:
        return
    try:
        result = {"ok": True, "receipt": host.commands.reserve(request)}
    except Exception as exc:
        result = {"ok": False, "error": getattr(exc, "code", "validation_error")}
    if len(cache) >= 64:
        del cache[next(iter(cache))]
    cache[key] = {"request_digest": request_digest, "result": result}


def observe(host, envelope, info):
    from .temporal_state import detached

    key, request_digest, _, epoch = _identity(host, envelope, info)
    previous = getattr(host, "_scoped_reserve_observations", {}).get(key)
    return {
        "version": 1,
        "scope": detached(host.commands.scope),
        "namespace": info.namespace,
        "execution_epoch": epoch,
        "observation_id": key,
        "request_digest": request_digest,
        "result": None if previous is None else detached(previous["result"]),
    }


def _receipt(value, request):
    expected = {
        "command_id": request["command_id"],
        "target": request["target"],
        "record_state": "durably_recorded",
        "apply_state": "not_applied",
    }
    if type(value) is not dict or value != expected:
        raise DefinitionMismatch("Original scoped reservation receipt changed")
    return value


async def reserve(handle, request, *, namespace):
    import asyncio
    from uuid import uuid4

    from .temporal import _raise_code
    from .temporal_state import detached

    envelope = {
        "kind": "scoped_reserve_receipt",
        "scope": request["scope"],
        "namespace": namespace,
        "execution_epoch": None,
        "observation_id": uuid4().hex,
        "request": detached(request),
    }
    expected = {
        "version": 1,
        "scope": request["scope"],
        "namespace": namespace,
        "observation_id": envelope["observation_id"],
        "request_digest": digest(request),
    }

    def observation(value):
        if type(value) is dict and set(value) == {"error"}:
            _raise_code(value["error"])
        if (
            type(value) is not dict
            or set(value) != {*expected, "execution_epoch", "result"}
            or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
            or type(value["execution_epoch"]) is not str
            or not value["execution_epoch"]
            or envelope["execution_epoch"] not in (None, value["execution_epoch"])
        ):
            raise DefinitionMismatch("Original scoped reservation observation unavailable")
        return value

    async with asyncio.timeout(30):
        first = await handle.query("view", envelope)
        # Old default Workers answer unknown views with this exact scoped
        # configuration. Identify them before any Signal; never guess on errors.
        if (
            type(first) is dict
            and set(first) == {"scope", "capacity", "accepted_commands"}
            and first["scope"] == request["scope"]
            and type(first["capacity"]) is int
            and 1 <= first["capacity"] <= 4096
            and type(first["accepted_commands"]) is int
            and 0 <= first["accepted_commands"] <= first["capacity"]
        ):
            return _receipt(await handle.execute_update("reserve", request), request)
        first = observation(first)
        envelope["execution_epoch"] = first["execution_epoch"]
        await handle.signal("reserve_scoped_command", envelope)
        while True:
            result = observation(await handle.query("view", envelope))["result"]
            if result is not None:
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise DefinitionMismatch("Invalid scoped reservation observation result")
                if result["ok"]:
                    if set(result) != {"ok", "receipt"}:
                        raise DefinitionMismatch("Invalid scoped acceptance fields")
                    return detached(_receipt(result["receipt"], request))
                if set(result) != {"ok", "error"}:
                    raise DefinitionMismatch("Invalid scoped refusal fields")
                _raise_code(result["error"])
            await asyncio.sleep(0.02)
