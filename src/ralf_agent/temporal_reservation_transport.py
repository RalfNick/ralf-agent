"""Bounded observation of synchronous reservations in the original public Registry."""

from .errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict, ValidationError
from .types import canonical, digest


def _identity(owner, envelope):
    owner._check_deployment_registry_epoch()
    if owner.commands.deployment is None or owner.commands.admission_protocol not in (2, 3, 4):
        raise DefinitionMismatch("Public original Registry required")
    if type(envelope) is not dict or set(envelope) != {
        "kind",
        "scope",
        "observation_id",
        "request",
    }:
        raise DefinitionMismatch("Complete original reservation observation required")
    request = envelope["request"]
    if (
        envelope["kind"] != "deployment_reserve_receipt"
        or type(request) is not dict
        or "descendant" in request
        or request.get("kind")
        not in {"submit", "approve", "cancel", "reconcile", "drive", "send_input", "patch"}
    ):
        raise DefinitionMismatch("Only original synchronous public reservations are supported")
    scope = owner.commands.deployment._authority(request)
    if envelope["scope"] != scope:
        raise AuthorizationDenied("Reservation observation belongs to another Scope")
    identity = envelope["observation_id"]
    if type(identity) is not str or not identity or len(identity) > 128:
        raise ValidationError("Reservation observation requires a bounded identity")
    if len(canonical(envelope).encode()) > 2 * 1024 * 1024:
        raise ValidationError("Reservation observation exceeds its allowance")
    key, request_digest = digest([scope, identity]), digest(request)
    previous = getattr(owner, "_reserve_observations", {}).get(key)
    if previous is not None and previous["request_digest"] != request_digest:
        raise IdempotencyConflict("Reservation observation already identifies another request")
    return key, request_digest, request


def accept(owner, envelope):
    # An invalid Signal must neither poison the Workflow nor create observations.
    try:
        key, request_digest, request = _identity(owner, envelope)
    except Exception:
        return
    cache = vars(owner).setdefault("_reserve_observations", {})
    if key in cache:
        return
    try:
        result = {"ok": True, "receipt": owner.commands.reserve(request)}
    except Exception as exc:
        result = {"ok": False, "error": getattr(exc, "code", "validation_error")}
    if len(cache) >= 64:
        del cache[next(iter(cache))]
    cache[key] = {"request_digest": request_digest, "result": result}


def observe(owner, envelope):
    from .temporal_state import detached

    key, request_digest, _ = _identity(owner, envelope)
    previous = getattr(owner, "_reserve_observations", {}).get(key)
    return {
        "version": 1,
        "observation_id": envelope["observation_id"],
        "request_digest": request_digest,
        "result": None if previous is None else detached(previous["result"]),
    }


async def reserve(handle, request):
    import asyncio
    from uuid import uuid4

    from .temporal import _raise_code
    from .temporal_state import detached

    envelope = {
        "kind": "deployment_reserve_receipt",
        "scope": request["scope"],
        "observation_id": str(uuid4()),
        "request": detached(request),
    }
    expected = {
        "version": 1,
        "observation_id": envelope["observation_id"],
        "request_digest": digest(request),
    }

    async def query():
        value = await handle.query("view", envelope)
        if (
            type(value) is not dict
            or set(value) != {*expected, "result"}
            or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
        ):
            raise DefinitionMismatch("Original Registry reservation observation is unavailable")
        return value["result"]

    async with asyncio.timeout(30):
        # Capability/refusal is established before sending an irreversible Signal.
        await query()
        await handle.signal("reserve_command", envelope)
        while True:
            result = await query()
            if result is not None:
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise DefinitionMismatch("Invalid original reservation result")
                if result["ok"] is True and set(result) == {"ok", "receipt"}:
                    return detached(result["receipt"])
                if result["ok"] is False and set(result) == {"ok", "error"}:
                    _raise_code(result["error"])
                raise DefinitionMismatch("Invalid original reservation result")
            # Evicted/unprocessed results remain unknown. Never generate a new
            # business ID, release a root or fall back to an SDK Update.
            await asyncio.sleep(0.02)
