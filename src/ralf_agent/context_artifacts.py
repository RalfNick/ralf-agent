"""Artifact intent and independent receipts in the original Run authority."""

import asyncio
import copy
from dataclasses import asdict

from .artifacts import ArtifactReference
from .data_context import ManagedDataContext
from .errors import AuthorizationDenied, DefinitionMismatch, NotFound, ValidationError
from .memory import memory_call
from .ports import _invoke_sync_none
from .types import digest


def admit(engine, manifest):
    from .binding_manifests import all_step_manifests

    for step in all_step_manifests(manifest):
        policy = step.get("managed_context", {}).get("policy", {})
        if policy.get("kind") != "managed-data-context":
            continue
        if policy["scope"] != asdict(engine.scope):
            raise AuthorizationDenied("Data context belongs to another Scope")
        if (
            type(getattr(engine.store, "data_context_stage_version", None)) is not int
            or engine.store.data_context_stage_version != 1
        ):
            raise ValidationError("Data context requires its atomic Store extension")
        _invoke_sync_none(
            getattr(engine.store, "prepare_data_context_stages", None), "Data context activation"
        )


def validate_journal(engine, run):
    records = run.get("context_artifacts", {})
    intents = run.get("context_artifact_intents", {})
    receipts = run.get("context_artifact_receipts", {})
    dispatches = run.get("context_artifact_dispatches", {})
    try:
        if (
            any(type(v) is not dict for v in (records, intents, receipts, dispatches))
            or set(records) != set(intents)
            or set(receipts) - set(records)
            or set(dispatches) - set(records)
        ):
            raise ValueError("incomplete journal")
        for key, record in records.items():
            intent = record["intent"]
            reference = ArtifactReference.from_dict(intent["reference"])
            policy = engine._step_manifest(run, intent["node"])["managed_context"]["policy"]
            if (
                key != reference.artifact_id
                or intents[key] != digest(intent)
                or intent["run_id"] != run["id"]
                or intent["release_digest"] != run["release_digest"]
                or intent["scope"] != run["scope"]
                or intent["policy"] != policy
                or (reference.workspace, reference.principal)
                != (run["scope"]["workspace"], run["scope"]["principal"])
                or reference.backend_id != policy["artifacts"]["backend_id"]
                or reference.namespace != policy["namespace"]
                or reference.expires_at is not None
                or digest(record["value"]) != reference.content_digest
                or record["status"] not in {"prepared", "writing", "verified"}
                or type(record["dispatched"]) is not bool
                or record["dispatched"] != (key in dispatches)
                or (key in dispatches and dispatches[key] != digest(intent))
                or (record["status"] == "prepared" and record["dispatched"])
                or (record["status"] == "writing" and not record["dispatched"])
                or (record["status"] == "verified") != (key in receipts)
                or (key in receipts and receipts[key] != _receipt(record))
            ):
                raise ValueError("changed evidence")
        for action in run["actions"]:
            for projected in action.get("context_manifest", {}).get("artifact_projection", []):
                reference = ArtifactReference.from_dict(projected["reference"])
                record = records[reference.artifact_id]
                if (
                    record["status"] != "verified"
                    or record["intent"]["reference"] != reference.to_dict()
                ):
                    raise ValueError("model snapshot lacks receipt")
    except Exception as exc:
        raise DefinitionMismatch("Context artifact journal is invalid") from exc


def _receipt(record):
    return digest(
        {
            "reference": record["intent"]["reference"],
            "intent_digest": digest(record["intent"]),
            "dispatched": record["dispatched"],
        }
    )


def _actual(engine, run_id, context):
    context.check()
    run = engine._authorized(run_id)
    engine._check_release(run)
    if engine._components(run).context is not context:
        raise DefinitionMismatch("Actual data context changed during artifact I/O")
    return run


async def _read(context, reference):
    value = await asyncio.wait_for(
        memory_call(context.artifacts.get, context.scope, reference), context.timeout
    )
    from .types import canonical

    if (
        digest(value) != reference.content_digest
        or len(canonical(value).encode("utf-8")) != reference.byte_length
    ):
        raise DefinitionMismatch("Artifact payload differs from its fixed reference")
    return value


async def prepare(engine, run_id, context):
    if not isinstance(context, ManagedDataContext):
        return True
    run = _actual(engine, run_id, context)
    for projected in context.offloads(run["messages"]):
        reference = ArtifactReference.from_dict(projected["reference"])
        key = reference.artifact_id
        current = _actual(engine, run_id, context)
        record = current.get("context_artifacts", {}).get(key)
        if current["state"] in {"succeeded", "failed", "cancelled", "cancelling"}:
            return False
        if record is None:
            intent = {
                "run_id": run_id,
                "release_digest": current["release_digest"],
                "scope": current["scope"],
                "node": current["node"],
                "reference": reference.to_dict(),
                "policy": context.identity,
            }
            record = {
                "intent": intent,
                "value": projected["value"],
                "status": "prepared",
                "dispatched": False,
            }
            with engine.store.transaction():
                latest = _actual(engine, run_id, context)
                latest.setdefault("context_artifacts", {})[key] = copy.deepcopy(record)
                latest.setdefault("context_artifact_intents", {})[key] = digest(intent)
                engine._commit(latest, "context_artifact_intent", {"artifact_id": key})
        try:
            await _read(context, reference)
        except NotFound:
            if record["status"] != "prepared":
                raise DefinitionMismatch(
                    "Previously dispatched context artifact is unavailable"
                ) from None
            with engine.store.transaction():
                latest = _actual(engine, run_id, context)
                if latest["state"] in {"succeeded", "failed", "cancelled", "cancelling"}:
                    return False
                record["status"], record["dispatched"] = "writing", True
                latest["context_artifacts"][key] = copy.deepcopy(record)
                latest.setdefault("context_artifact_dispatches", {})[key] = digest(record["intent"])
                engine._commit(latest, "context_artifact_dispatched", {"artifact_id": key})
            put_error = None
            try:
                received = await asyncio.wait_for(
                    memory_call(
                        context.artifacts.put,
                        context.scope,
                        context.namespace,
                        copy.deepcopy(record["value"]),
                    ),
                    context.timeout,
                )
                if type(received) is not ArtifactReference or received != reference:
                    raise DefinitionMismatch("Artifact put returned a different reference")
            except DefinitionMismatch:
                raise
            except Exception as exc:
                put_error = exc
            _actual(engine, run_id, context)
            try:
                await _read(context, reference)
            except NotFound:
                if put_error is not None:
                    raise put_error from None
                raise DefinitionMismatch("Artifact write has no verifiable receipt") from None
        latest = _actual(engine, run_id, context)
        if latest["state"] in {"succeeded", "failed", "cancelled", "cancelling"}:
            return False
        if record["status"] != "verified":
            with engine.store.transaction():
                latest["context_artifacts"][key]["status"] = "verified"
                latest.setdefault("context_artifact_receipts", {})[key] = _receipt(record)
                engine._commit(latest, "context_artifact_verified", {"artifact_id": key})
    return True


async def validate_snapshot(engine, run_id, action):
    projections = action.get("context_manifest", {}).get("artifact_projection", [])
    if not projections:
        return
    context = engine._components(engine._authorized(run_id)).context
    if not isinstance(context, ManagedDataContext):
        raise DefinitionMismatch("Artifact snapshot lost its data context")
    for projection in projections:
        _actual(engine, run_id, context)
        await _read(context, ArtifactReference.from_dict(projection["reference"]))
        _actual(engine, run_id, context)
