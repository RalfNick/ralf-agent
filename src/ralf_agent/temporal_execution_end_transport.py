"""Original Run observations for four fixed physical-execution end handlers."""

from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .types import canonical, digest

OPERATIONS = frozenset(
    {
        "tool_execution_ended",
        "context_execution_ended",
        "session_execution_ended",
        "deployment_call_ended",
    }
)


def _identity(owner, envelope, info):
    from .temporal_deployment_protocol import public_selected, selected

    state = owner.state
    if selected(state.manifest) and not public_selected(state.manifest):
        raise DefinitionMismatch("Private deployment keeps original end Updates")
    if type(envelope) is not dict or set(envelope) != {
        "version",
        "scope",
        "run_id",
        "namespace",
        "execution_epoch",
        "observation_id",
        "operation",
        "proof",
    }:
        raise ValidationError("Complete original end observation required")
    state.authorize(envelope["scope"])
    if (
        type(envelope["version"]) is not int
        or envelope["version"] != 1
        or envelope["operation"] not in OPERATIONS
        or envelope["run_id"] != state.run_id
        or info.workflow_id != state.run_id
        or info.namespace != envelope["namespace"]
        or type(state.epoch) is not str
        or not state.epoch
        or any(
            getattr(info, n, None) != state.epoch
            for n in ("run_id", "first_execution_run_id", "original_execution_run_id")
        )
        or envelope["execution_epoch"] != state.epoch
        or len(canonical(envelope).encode()) > 2 * 1024 * 1024
    ):
        raise DefinitionMismatch("Execution end requires original SDK History")
    proof = envelope["proof"]
    if type(proof) is not dict:
        raise ValidationError("Original complete end proof required")
    state.authorize(proof.get("scope"))
    if (
        envelope["operation"] != "session_execution_ended"
        and proof.get("execution_epoch") != state.epoch
    ):
        raise DefinitionMismatch("End proof belongs to another original execution")
    key = envelope["observation_id"]
    if type(key) is not str or not key or len(key) > 128:
        raise ValidationError("Bounded execution-end observation required")
    proof_digest = digest(proof)
    previous = getattr(owner, "_execution_end_observations", {}).get(key)
    if previous is not None and (
        previous["proof_digest"] != proof_digest or previous["operation"] != envelope["operation"]
    ):
        raise IdempotencyConflict("End observation already identifies another proof")
    return key, proof_digest, envelope["operation"], proof


async def accept(owner, envelope, info):
    try:
        key, proof_digest, operation, proof = _identity(owner, envelope, info)
    except Exception:
        return
    cache = vars(owner).setdefault("_execution_end_observations", {})
    if key in cache:
        return
    try:
        # These fixed handlers complete without suspending; dynamic dispatch
        # preserves Parent retirement, Session retry and original wake rules.
        result = {"ok": True, "receipt": await getattr(owner, operation)(proof)}
    except Exception as exc:
        result = {
            "ok": False,
            "error": getattr(exc, "code", None) or getattr(exc, "type", "validation_error"),
        }
    if len(cache) >= 64:
        del cache[next(iter(cache))]
    cache[key] = {"proof_digest": proof_digest, "operation": operation, "result": result}


def observe(owner, envelope, info):
    from .temporal_state import detached

    key, proof_digest, operation, _ = _identity(owner, envelope, info)
    entry = getattr(owner, "_execution_end_observations", {}).get(key)
    return detached(
        {
            "version": 1,
            "scope": owner.state.scope,
            "run_id": owner.state.run_id,
            "namespace": info.namespace,
            "execution_epoch": info.run_id,
            "observation_id": key,
            "operation": operation,
            "proof_digest": proof_digest,
            "result": None if entry is None else entry["result"],
        }
    )


def _receipt(operation, proof, value):
    if operation == "deployment_call_ended":
        expected = {k: proof[k] for k in ("activity_id", "attempt", "invocation_id")} | {
            "recorded": True
        }
        if type(expected["attempt"]) is not int or expected["attempt"] < 1:
            raise DefinitionMismatch("Original actual-call attempt required")
    else:
        expected = {
            "action_id": proof["action_id"],
            "execution_stopped" if operation == "session_execution_ended" else "recorded": True,
        }
    if (
        type(value) is not dict
        or set(value) != set(expected)
        or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
    ):
        raise DefinitionMismatch("Original completed execution-end acknowledgement required")
    canonical(value)
    return value


async def execute(client, run_id, operation, proof, *, execution_epoch, legacy_update_id):
    import asyncio
    from uuid import uuid4

    from .task_controls import _binding
    from .temporal import _raise_code
    from .temporal_command_transport import _legacy_snapshot
    from .temporal_parent_state import PARENT_WORKFLOW_NAME
    from .temporal_state import WORKFLOW_NAME, detached, text

    if type(operation) is not str or operation not in OPERATIONS or type(proof) is not dict:
        raise ValidationError("Only original fixed end handlers use this transport")
    text(run_id, "Run ID")
    text(execution_epoch, "Original SDK epoch")
    text(legacy_update_id, "Original end Update ID")
    proof = detached(proof)
    namespace = client.namespace
    envelope = {
        "version": 1,
        "scope": proof["scope"],
        "run_id": run_id,
        "namespace": namespace,
        "execution_epoch": execution_epoch,
        "observation_id": uuid4().hex,
        "operation": operation,
        "proof": proof,
    }
    if len(canonical(envelope).encode()) > 2 * 1024 * 1024:
        raise ValidationError("Bounded original end proof required")
    ports = [(client, "get_workflow_handle")]
    pins = tuple(_binding(getattr(o, n)) for o, n in ports)

    def check():
        if (
            client.namespace != namespace
            or tuple(_binding(getattr(o, n)) for o, n in ports) != pins
        ):
            raise DefinitionMismatch("Original execution-end transport changed")

    async def query(handle):
        value = await handle.query(
            "view",
            {
                "kind": "status",
                "scope": envelope["scope"],
                "execution_end_observation": detached(envelope),
            },
        )
        check()
        return detached(value)

    def observation(value):
        if type(value) is dict and set(value) == {"error"}:
            _raise_code(value["error"])
        if type(value) is not dict or set(value) != {"execution_end_observation"}:
            raise DefinitionMismatch("Original execution-end observation unavailable")
        value = value["execution_end_observation"]
        expected = {
            k: envelope[k]
            for k in (
                "version",
                "scope",
                "run_id",
                "namespace",
                "execution_epoch",
                "observation_id",
                "operation",
            )
        } | {"proof_digest": digest(proof)}
        if (
            type(value) is not dict
            or set(value) != {*expected, "result"}
            or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
        ):
            raise DefinitionMismatch("Original execution-end observation identity changed")
        return value

    async with asyncio.timeout(30):
        handle = client.get_workflow_handle(run_id, run_id=execution_epoch)
        check()
        for name in ("query", "signal", "execute_update", "describe"):
            ports.append((handle, name))
            pins += (_binding(getattr(handle, name)),)
        first = await query(handle)
        if _legacy_snapshot(first, run_id):
            description = await handle.describe()
            check()
            if (
                description.id != run_id
                or description.namespace != namespace
                or description.run_id != execution_epoch
                or description.raw_info.first_run_id != execution_epoch
                or description.workflow_type not in {WORKFLOW_NAME, PARENT_WORKFLOW_NAME}
            ):
                raise DefinitionMismatch("Original legacy end SDK identity changed")
            if not _legacy_snapshot(await query(handle), run_id):
                raise DefinitionMismatch("Original legacy end Worker changed")
            result = await handle.execute_update(operation, proof, id=legacy_update_id)
            check()
            return detached(_receipt(operation, proof, result))
        observation(first)
        await handle.signal("execution_ended", detached(envelope))
        check()
        while True:
            result = observation(await query(handle))["result"]
            if result is not None:
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise DefinitionMismatch("Invalid original end observation result")
                if result["ok"] and set(result) == {"ok", "receipt"}:
                    return detached(_receipt(operation, proof, result["receipt"]))
                if result["ok"] is False and set(result) == {"ok", "error"}:
                    _raise_code(result["error"])
                raise DefinitionMismatch("Invalid original end observation fields")
            await asyncio.sleep(0.02)
