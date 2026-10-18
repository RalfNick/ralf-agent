"""Bounded receipt/stop observations on the original Coding Run History."""

from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .types import canonical, digest

OPERATIONS = frozenset({"coding_receipt", "admit_coding_stop", "coding_owner_stopped"})


def workflow_source():
    """Worker-only fixed source inventory; never import optional SDK in pure rules."""
    import hashlib
    from pathlib import Path

    return hashlib.sha256(Path(__file__).with_name("temporal_workflow.py").read_bytes()).hexdigest()


def _identity(owner, envelope, info):
    from .temporal_coding_state import PROOF_FIELDS, enabled

    state = owner.state
    if not enabled(state.manifest):
        raise DefinitionMismatch("Original Coding History required")
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
        raise ValidationError("Complete original Coding observation required")
    state.authorize(envelope["scope"])
    proof = envelope["proof"]
    if (
        type(envelope["version"]) is not int
        or envelope["version"] != 1
        or envelope["operation"] not in OPERATIONS
        or envelope["run_id"] != state.run_id
        or info.workflow_id != state.run_id
        or envelope["namespace"] != info.namespace
        or type(state.epoch) is not str
        or not state.epoch
        or envelope["execution_epoch"] != state.epoch
        or any(
            getattr(info, n, None) != state.epoch
            for n in ("run_id", "first_execution_run_id", "original_execution_run_id")
        )
        or type(proof) is not dict
        or not PROOF_FIELDS.issubset(proof)
        or proof["run_id"] != state.run_id
        or proof["execution_epoch"] != state.epoch
        or proof["release_digest"] != state.release_digest
        or len(canonical(envelope).encode()) > 2 * 1024 * 1024
    ):
        raise DefinitionMismatch("Coding recovery requires original SDK History and proof")
    state.authorize(proof["scope"])
    key = envelope["observation_id"]
    if type(key) is not str or not key or len(key) > 128:
        raise ValidationError("Bounded original Coding observation required")
    proof_digest = digest([envelope["operation"], proof])
    previous = getattr(owner, "_coding_recovery_observations", {}).get(key)
    if previous is not None and previous["proof_digest"] != proof_digest:
        raise IdempotencyConflict("Coding observation already identifies another proof")
    return key, proof_digest, envelope["operation"], proof


async def accept(owner, envelope, info):
    try:
        key, proof_digest, operation, proof = _identity(owner, envelope, info)
    except Exception:
        return
    cache = vars(owner).setdefault("_coding_recovery_observations", {})
    if key in cache:
        return
    if len(cache) >= 64:
        completed = next((k for k, v in cache.items() if v["result"] is not None), None)
        if completed is None:
            return
        del cache[completed]
    entry = {"proof_digest": proof_digest, "result": None}
    cache[key] = entry
    try:
        # Whole original handlers retain request/claim/phase/stop checks and wake.
        result = {"ok": True, "receipt": await getattr(owner, operation)(proof)}
    except Exception as exc:
        result = {
            "ok": False,
            "error": getattr(exc, "code", None) or getattr(exc, "type", "validation_error"),
        }
    entry["result"] = result


def observe(owner, envelope, info):
    from .temporal_state import detached

    key, proof_digest, _, _ = _identity(owner, envelope, info)
    entry = getattr(owner, "_coding_recovery_observations", {}).get(key)
    return detached(
        {
            **{
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
            },
            "proof_digest": proof_digest,
            "result": None if entry is None else entry["result"],
        }
    )


def _receipt(operation, proof, value):
    expected = {"action_id": proof["action_id"], "recorded": True}
    if operation == "admit_coding_stop":
        if (
            type(value) is not dict
            or set(value)
            != {"action_id", "admitted", "original_invocation_id", "request", "runner"}
            or value["action_id"] != proof["action_id"]
            or value["admitted"] is not True
            or type(value["original_invocation_id"]) is not str
            or not value["original_invocation_id"]
            or type(value["request"]) is not dict
            or type(value["runner"]) is not dict
        ):
            raise DefinitionMismatch("Original Coding stop admission required")
    elif (
        type(value) is not dict
        or set(value) != set(expected)
        or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
    ):
        raise DefinitionMismatch("Original Coding receipt acknowledgement required")
    canonical(value)
    return value


async def execute(client, run_id, operation, proof, *, execution_epoch):
    import asyncio
    from uuid import uuid4

    from .task_controls import _binding
    from .temporal import _raise_code
    from .temporal_state import WORKFLOW_NAME, detached

    if type(operation) is not str or operation not in OPERATIONS or type(proof) is not dict:
        raise ValidationError("Only original Coding receipt and stop handlers use observations")
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
        raise ValidationError("Bounded original Coding proof required")
    ports = [(client, "get_workflow_handle")]
    pins = tuple(_binding(getattr(o, n)) for o, n in ports)

    def check():
        if (
            client.namespace != namespace
            or tuple(_binding(getattr(o, n)) for o, n in ports) != pins
        ):
            raise DefinitionMismatch("Original Coding observation ports changed")

    expected = {k: v for k, v in envelope.items() if k != "proof"} | {
        "proof_digest": digest([operation, proof])
    }

    async def query(handle):
        value = await handle.query(
            "view",
            {
                "kind": "status",
                "scope": proof["scope"],
                "coding_recovery_observation": detached(envelope),
            },
        )
        check()
        if type(value) is dict and set(value) == {"error"}:
            _raise_code(value["error"])
        if type(value) is not dict or set(value) != {"coding_recovery_observation"}:
            raise DefinitionMismatch(
                "Original Coding observation unavailable; matching SDK/Worker required"
            )
        value = value["coding_recovery_observation"]
        if (
            type(value) is not dict
            or set(value) != {*expected, "result"}
            or any(value[k] != v or type(value[k]) is not type(v) for k, v in expected.items())
        ):
            raise DefinitionMismatch("Original Coding observation identity changed")
        return value["result"]

    async with asyncio.timeout(30):
        handle = client.get_workflow_handle(run_id, run_id=execution_epoch)
        check()
        for name in ("query", "signal", "describe"):
            ports.append((handle, name))
            pins += (_binding(getattr(handle, name)),)
        description = await handle.describe()
        check()
        if (
            description.id != run_id
            or description.namespace != namespace
            or description.run_id != execution_epoch
            or description.raw_info.first_run_id != execution_epoch
            or description.workflow_type != WORKFLOW_NAME
        ):
            raise DefinitionMismatch("Original Coding SDK epoch required")
        await query(handle)
        await handle.signal("coding_recovery", detached(envelope))
        check()
        while True:
            result = await query(handle)
            if result is not None:
                if type(result) is not dict or type(result.get("ok")) is not bool:
                    raise DefinitionMismatch("Typed original Coding result required")
                if result["ok"] is False and set(result) == {"ok", "error"}:
                    _raise_code(result["error"])
                if result["ok"] is True and set(result) == {"ok", "receipt"}:
                    return detached(_receipt(operation, proof, result["receipt"]))
                raise DefinitionMismatch("Invalid original Coding result fields")
            await asyncio.sleep(0.02)
