"""Explicit maintenance under the original immutable deployment closure."""

import asyncio
from dataclasses import asdict

from .errors import DefinitionMismatch, ValidationError
from .postgres_effect_retention import binding, request
from .temporal_deployment_execution import _ancestry, _namespace, _policy, _proof
from .temporal_deployment_release import _tree
from .temporal_deployment_release_state import public


async def compact_effect_evidence(engine, run_id, *, runtime, limit=100, after_effect_key=None):
    request(engine.scope, run_id, limit, after_effect_key)
    client, namespace, scope, release = (
        engine.client,
        engine.namespace,
        asdict(engine.scope),
        engine.release,
    )
    journal = runtime.journal
    dataset = binding(journal)

    def verify():
        runtime.validate_release(release)
        current = binding(journal)
        if (
            engine._closed
            or engine.client is not client
            or engine.namespace != namespace
            or client.namespace != namespace
            or asdict(engine.scope) != scope
            or engine.release != release
            or runtime.journal is not journal
            or current[0] is not dataset[0]
            or current[1:] != dataset[1:]
        ):
            raise DefinitionMismatch("Original effect compaction authority or dataset changed")

    verify()
    policy = _policy(runtime, expected=release)
    if policy is None or not public(release):
        raise ValidationError("Effect compaction requires the selected original public deployment")
    snapshot = await engine.status(run_id)
    verify()
    if snapshot.state != "succeeded":
        raise ValidationError("Effect compaction requires a settled successful original Run")
    description = await client.get_workflow_handle(run_id).describe()
    verify()
    proof = await _proof(runtime, client, policy, scope, run_id, description.run_id, required=True)
    verify()
    root = await _ancestry(runtime, client, policy, proof, read_only=True)
    verify()
    certificate = await _tree(runtime, client, policy, root, seal=False)
    verify()
    if certificate["terminal_state"] != "succeeded":
        raise ValidationError("Effect compaction requires a successful sealed original tree")

    async def namespace_check():
        # Bound the original namespace RPC while holding the original target lock.
        # A mismatch/timeout before commit rolls this Action's deletion back.
        async with asyncio.timeout(10):
            await _namespace(client, proof["namespace"])
        verify()

    result = await journal._compact_adopted_evidence(
        engine.scope,
        run_id,
        limit=limit,
        after_effect_key=after_effect_key,
        verify=verify,
        namespace_check=namespace_check,
    )
    await namespace_check()
    return {
        "run_id": run_id,
        "execution_epoch": proof["execution_epoch"],
        "root_run_id": root["run_id"],
        "root_execution_epoch": root["execution_epoch"],
        "seal_digest": certificate["proof_digest"],
        **result,
    }
