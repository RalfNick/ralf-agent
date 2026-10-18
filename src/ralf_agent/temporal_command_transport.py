"""Bounded observations of necessary controls in the original Run History."""

from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .types import canonical, digest


def supports(payload):
    return payload.get("kind") in {"cancel", "drive"} or (
        payload.get("kind") == "reconcile" and payload.get("query") is False
    )


def _identity(owner, envelope, info, *, signal=False):
    from .temporal_deployment_protocol import public_selected, selected
    from .temporal_state import text

    state = owner.state
    if selected(state.manifest) and not public_selected(state.manifest):
        raise DefinitionMismatch("Private deployment retains its original command transport")
    if type(envelope) is not dict or set(envelope) != {
        "version",
        "scope",
        "run_id",
        "namespace",
        "execution_epoch",
        "observation_id",
        "request",
    }:
        raise ValidationError("Complete Run command observation required")
    state.authorize(envelope["scope"])
    if (
        type(envelope["version"]) is not int
        or envelope["version"] != 1
        or envelope["run_id"] != state.run_id
        or info.workflow_id != state.run_id
        or info.namespace != envelope["namespace"]
        or any(
            getattr(info, n, None) != state.epoch
            for n in ("run_id", "first_execution_run_id", "original_execution_run_id")
        )
        or envelope["execution_epoch"] not in ((state.epoch,) if signal else (None, state.epoch))
    ):
        raise DefinitionMismatch("Run control requires its original SDK History")
    request = envelope["request"]
    if (
        type(request) is not dict
        or set(request) != {"command_id", "payload"}
        or type(request["payload"]) is not dict
        or not supports(request["payload"])
        or len(canonical(envelope).encode()) > 2 * 1024 * 1024
    ):
        raise ValidationError("Only original necessary Run commands are supported")
    state.authorize(request["payload"].get("scope"))
    text(request["command_id"], "Command ID")
    key = envelope["observation_id"]
    if type(key) is not str or not key or len(key) > 128:
        raise ValidationError("Bounded Run observation identity required")
    request_digest = digest(request)
    previous = getattr(owner, "_command_observations", {}).get(key)
    if previous is not None and previous["request_digest"] != request_digest:
        raise IdempotencyConflict("Run observation already identifies another request")
    return key, request_digest, request


async def accept(owner, envelope, info):
    try:
        key, request_digest, request = _identity(owner, envelope, info, signal=True)
    except Exception:
        return
    cache = vars(owner).setdefault("_command_observations", {})
    if key in cache:
        return
    try:
        # Keep the full handler's retry/notification/Parent wake semantics.
        result = {"ok": True, "receipt": await owner.command(request)}
    except Exception as exc:
        result = {
            "ok": False,
            "error": getattr(exc, "code", None) or getattr(exc, "type", "validation_error"),
        }
    if len(cache) >= 64:
        del cache[next(iter(cache))]
    cache[key] = {"request_digest": request_digest, "result": result}


def observe(owner, envelope, info):
    from .temporal_state import detached

    key, request_digest, _ = _identity(owner, envelope, info)
    previous = getattr(owner, "_command_observations", {}).get(key)
    return detached(
        {
            "version": 1,
            "scope": owner.state.scope,
            "run_id": owner.state.run_id,
            "namespace": info.namespace,
            "execution_epoch": info.run_id,
            "observation_id": key,
            "request_digest": request_digest,
            "result": None if previous is None else previous["result"],
        }
    )


def _legacy_snapshot(value, run_id):
    return (
        type(value) is dict
        and set(value)
        == {
            "run_id",
            "state",
            "state_revision",
            "result",
            "error",
            "pending",
            "actions",
            "consistency",
        }
        and value["run_id"] == run_id
        and value["consistency"] == "authoritative"
        and type(value["state_revision"]) is int
        and value["state_revision"] >= 0
        and value["state"]
        in {
            "queued",
            "running",
            "waiting_approval",
            "waiting_reconciliation",
            "outcome_unknown",
            "waiting_input",
            "cancelling",
            "cancelled",
            "failed",
            "succeeded",
        }
        and type(value["pending"]) is list
        and type(value["actions"]) is list
    )


def _receipt(value, request, run_id):
    if (
        type(value) is not dict
        or set(value) != {"command_id", "run_id", "kind", "record_state", "apply_state", "outcome"}
        or value["command_id"] != request["command_id"]
        or value["run_id"] != run_id
        or value["kind"] != request["payload"]["kind"]
        or value["record_state"] != "durably_recorded"
        or value["apply_state"] not in {"applied", "rejected"}
        or type(value["outcome"]) is not dict
    ):
        raise DefinitionMismatch("Original Run command receipt changed")
    canonical(value)
    return value


async def execute(client, run_id, request, *, execution_epoch=None):
    import asyncio
    from uuid import uuid4

    from .task_controls import _binding
    from .temporal import _raise_code
    from .temporal_state import detached

    request = detached(request)
    namespace = client.namespace
    envelope = {
        "version": 1,
        "scope": request["payload"]["scope"],
        "run_id": run_id,
        "namespace": namespace,
        "execution_epoch": execution_epoch,
        "observation_id": uuid4().hex,
        "request": request,
    }
    if not supports(request["payload"]) or len(canonical(envelope).encode()) > 2 * 1024 * 1024:
        raise ValidationError("Only bounded necessary controls use Run observations")
    ports = [(client, "get_workflow_handle")]
    pins = tuple(_binding(getattr(o, n)) for o, n in ports)

    def check():
        if (
            client.namespace != namespace
            or tuple(_binding(getattr(o, n)) for o, n in ports) != pins
        ):
            raise DefinitionMismatch("Original Run command transport changed")

    def handle(epoch):
        nonlocal pins
        check()
        h = client.get_workflow_handle(run_id, **({"run_id": epoch} if epoch is not None else {}))
        check()
        for n in ("query", "signal", "execute_update", "describe"):
            ports.append((h, n))
            pins += (_binding(getattr(h, n)),)
        return h

    async def query(h):
        value = await h.query(
            "view",
            {
                "kind": "status",
                "scope": envelope["scope"],
                "command_observation": detached(envelope),
            },
        )
        check()
        return detached(value)

    def observation(value):
        if type(value) is dict and set(value) == {"error"}:
            _raise_code(value["error"])
        if type(value) is not dict or set(value) != {"command_observation"}:
            raise DefinitionMismatch("Original Run observation unavailable")
        value = value["command_observation"]
        expected = {
            "version": 1,
            "scope": envelope["scope"],
            "run_id": run_id,
            "namespace": namespace,
            "observation_id": envelope["observation_id"],
            "request_digest": digest(request),
        }
        if (
            type(value) is not dict
            or set(value) != {*expected, "execution_epoch", "result"}
            or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
            or type(value["execution_epoch"]) is not str
            or not value["execution_epoch"]
            or envelope["execution_epoch"] not in (None, value["execution_epoch"])
        ):
            raise DefinitionMismatch("Original Run observation identity changed")
        return value

    async with asyncio.timeout(30):
        h = handle(execution_epoch)
        first = await query(h)
        if _legacy_snapshot(first, run_id):
            # A complete old status-kind reply positively identifies old behavior;
            # an unknown-kind validation_error alone never authorizes an Update.
            from .temporal_parent_state import PARENT_WORKFLOW_NAME
            from .temporal_state import WORKFLOW_NAME

            d = await h.describe()
            check()
            if (
                d.id != run_id
                or d.namespace != namespace
                or d.raw_info.first_run_id != d.run_id
                or d.workflow_type not in {WORKFLOW_NAME, PARENT_WORKFLOW_NAME}
                or type(d.run_id) is not str
                or not d.run_id
                or execution_epoch not in (None, d.run_id)
            ):
                raise DefinitionMismatch("Original legacy Run SDK identity changed")
            pinned = handle(d.run_id)
            if not _legacy_snapshot(await query(pinned), run_id):
                raise DefinitionMismatch("Original legacy Worker changed during discovery")
            result = await pinned.execute_update("command", request)
            check()
            return detached(_receipt(result, request, run_id))
        first = observation(first)
        envelope["execution_epoch"] = first["execution_epoch"]
        pinned = handle(first["execution_epoch"])
        await pinned.signal("control_command", detached(envelope))
        check()
        while True:
            result = observation(await query(pinned))["result"]
            if result is not None:
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise DefinitionMismatch("Invalid original Run observation result")
                if result["ok"] and set(result) == {"ok", "receipt"}:
                    return detached(_receipt(result["receipt"], request, run_id))
                if result["ok"] is False and set(result) == {"ok", "error"}:
                    _raise_code(result["error"])
                raise DefinitionMismatch("Invalid original Run observation fields")
            await asyncio.sleep(0.02)
