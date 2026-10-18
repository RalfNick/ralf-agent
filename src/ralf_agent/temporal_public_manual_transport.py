"""Bounded strong-manual proof on the original public Registry authority."""

from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .temporal_deployment_admission import _REQUEST_FIELDS, _exact, _text, registry_id, root_run_id
from .types import canonical, digest


def _identity(owner, envelope, info):
    owner._check_deployment_registry_epoch()
    registry = owner.commands.deployment
    if registry is None or owner.commands.admission_protocol not in (2, 3, 4):
        raise DefinitionMismatch("Original public Registry required for manual proof")
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
    _exact(request, _REQUEST_FIELDS | {"recovery"})
    scope = registry._authority(request)
    if (
        type(envelope["version"]) is not int
        or envelope["version"] != 1
        or request["kind"] != "reconcile"
        or envelope["scope"] != scope
        or envelope["namespace"] != registry.namespace
        or envelope["registry_id"] != registry.registry_id
        or info.workflow_id != registry.registry_id
        or info.namespace != registry.namespace["name"]
        or type(envelope["execution_epoch"]) is not str
        or not envelope["execution_epoch"]
        or any(
            getattr(info, k, None) != envelope["execution_epoch"]
            for k in ("run_id", "first_execution_run_id", "original_execution_run_id")
        )
        or len(canonical(envelope).encode()) > 2 * 1024 * 1024
    ):
        raise DefinitionMismatch("Manual proof requires original Registry identity")
    # This pure probe grants nothing. The complete original async verifier commits.
    owner.commands.prepare_deployment_control(request)
    observation_id = envelope["observation_id"]
    if type(observation_id) is not str or not observation_id or len(observation_id) > 128:
        raise ValidationError("Bounded public manual observation required")
    key, request_digest = digest([scope, observation_id]), digest(request)
    previous = getattr(owner, "_public_manual_observations", {}).get(key)
    if previous is not None and previous["request_digest"] != request_digest:
        raise IdempotencyConflict("Manual observation already identifies another request")
    return key, request_digest, request


async def accept(owner, envelope, info):
    try:
        key, request_digest, request = _identity(owner, envelope, info)
    except Exception:
        return
    cache = vars(owner).setdefault("_public_manual_observations", {})
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
        result = {"ok": True, "receipt": await owner.reserve(request)}
    except Exception as exc:
        result = {
            "ok": False,
            "error": getattr(exc, "code", None) or getattr(exc, "type", "validation_error"),
        }
    entry["result"] = result


def observe(owner, envelope, info):
    from .temporal_state import detached

    key, request_digest, _ = _identity(owner, envelope, info)
    entry = getattr(owner, "_public_manual_observations", {}).get(key)
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


async def reserve(handle, request):
    import asyncio
    from uuid import uuid4

    from .task_controls import _binding
    from .temporal import _raise_code
    from .temporal_deployment_submissions import _control_result
    from .temporal_manual_recovery import manual_payload
    from .temporal_state import COMMAND_REGISTRY_NAME, detached

    request = detached(request)
    _exact(request, _REQUEST_FIELDS | {"recovery"})
    _exact(request["recovery"], {"root_command_id", "execution_epoch", "payload"})
    payload = manual_payload(request["recovery"]["payload"], request["scope"])
    if request["kind"] != "reconcile" or request["payload_digest"] != digest(payload):
        raise DefinitionMismatch("Only original strong manual requests use observations")
    target = registry_id(request["admission_policy"]["deployment_id"])
    epoch = handle.run_id
    _text(epoch)
    pins = tuple(_binding(getattr(handle, name)) for name in ("query", "signal", "describe"))

    def check():
        if (
            handle.id != target
            or handle.run_id != epoch
            or tuple(_binding(getattr(handle, name)) for name in ("query", "signal", "describe"))
            != pins
        ):
            raise DefinitionMismatch("Original public manual transport changed")

    envelope = dict(
        version=1,
        scope=request["scope"],
        namespace=request["namespace"],
        registry_id=target,
        execution_epoch=epoch,
        observation_id=uuid4().hex,
        request=request,
    )
    if len(canonical(envelope).encode()) > 2 * 1024 * 1024:
        raise ValidationError("Bounded original manual proof required")
    expected = {k: v for k, v in envelope.items() if k != "request"} | {
        "request_digest": digest(request)
    }

    async def query():
        value = await handle.query(
            "view",
            {
                "kind": "deployment_manual_observation",
                "scope": request["scope"],
                "manual_observation": detached(envelope),
            },
        )
        check()
        if type(value) is dict and set(value) == {"error"}:
            _raise_code(value["error"])
        if (
            type(value) is not dict
            or set(value) != {*expected, "result"}
            or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
        ):
            raise DefinitionMismatch("Original manual observation identity changed")
        return value["result"]

    async with asyncio.timeout(30):
        check()
        description = await handle.describe()
        check()
        if (
            description.id != target
            or description.run_id != epoch
            or description.namespace != request["namespace"]["name"]
            or description.raw_info.first_run_id != epoch
            or description.workflow_type != COMMAND_REGISTRY_NAME
            or description.parent_id is not None
            or description.parent_run_id is not None
        ):
            raise DefinitionMismatch("Original standalone Registry SDK epoch required")
        # Unsupported historical selected Workers require their matching SDK.
        # No generic failure or unknown delivery permits an Update fallback.
        await query()
        await handle.signal("reserve_public_manual", detached(envelope))
        check()
        while True:
            result = await query()
            if result is not None:
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise DefinitionMismatch("Typed original manual result required")
                if result["ok"] is False and set(result) == {"ok", "error"}:
                    _raise_code(result["error"])
                if result["ok"] is True and set(result) == {"ok", "receipt"}:
                    _control_result(
                        result["receipt"],
                        request["command_id"],
                        request["target"],
                        request["scope"],
                        request["namespace"],
                        expected={
                            "target_execution_epoch": request["recovery"]["execution_epoch"],
                            "root_run_id": root_run_id(
                                request["admission_policy"]["deployment_id"],
                                request["scope"],
                                request["recovery"]["root_command_id"],
                            ),
                        },
                        manual=True,
                    )
                    return detached(result["receipt"])
                raise DefinitionMismatch("Invalid original manual result fields")
            await asyncio.sleep(0.02)
