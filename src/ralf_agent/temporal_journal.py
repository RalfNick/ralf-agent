"""PostgreSQL effect evidence, never an execution state store.

Rows hold dispatch intent and observed receipts for stable effect keys. An
advisory transaction lock prevents a different Run dispatching the same scoped
write while prior evidence has not been adopted by Workflow History.
"""

import json

from .errors import IdempotencyConflict, ValidationError
from .executors import DispatchEnvelope, EffectObservation
from .postgres import _connect, _PostgresAdapter
from .types import canonical, digest

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ralf_temporal_effects (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, effect_key TEXT NOT NULL,
        run_id TEXT NOT NULL, action_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
        operation_digest TEXT NOT NULL, target_digest TEXT NOT NULL, effect TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('dispatched','received','adopted')),
        result TEXT, source TEXT, adopted_result_digest TEXT,
        PRIMARY KEY (workspace,principal,effect_key))""",
    """CREATE INDEX IF NOT EXISTS ralf_temporal_unresolved_targets
        ON ralf_temporal_effects (workspace,principal,target_digest,state)""",
    """CREATE TABLE IF NOT EXISTS ralf_temporal_effect_evidence (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, effect_key TEXT NOT NULL,
        evidence_digest TEXT NOT NULL, result TEXT NOT NULL, source TEXT NOT NULL,
        PRIMARY KEY (workspace,principal,effect_key,evidence_digest))""",
)


def _binding(envelope):
    if not isinstance(envelope, DispatchEnvelope):
        raise ValidationError("EffectJournal requires a DispatchEnvelope")
    context = envelope.context
    target = digest({"tool": envelope.tool_name, "arguments": envelope.arguments})
    return (context.scope.workspace, context.scope.principal, context.effect_key), target


class PostgresEffectJournal(_PostgresAdapter):
    """Durable receipt query and conservative cross-Run write exclusion.

    ``received`` alone does not clear a write exclusion. Only an explicit
    acknowledgement scheduled *after* History adoption changes it to adopted.
    Borrowed autocommit connections remain owned by their caller.
    """

    def __init__(self, connection, *, backend_id="ralf-temporal-effects-v1", owns_connection=False):
        super().__init__(connection, backend_id=backend_id, owns_connection=owns_connection)

    @classmethod
    async def connect(cls, dsn, *, backend_id="ralf-temporal-effects-v1"):
        return cls(await _connect(dsn), backend_id=backend_id, owns_connection=True)

    @property
    def identity(self):
        return {"kind": "postgres-effect-journal", "version": "1", "backend_id": self.backend_id}

    async def initialize(self):
        from .postgres_effect_retention import TABLES

        await self._initialize(_SCHEMA, tables=TABLES)

    async def _compact_adopted_evidence(
        self, scope, run_id, *, limit=100, after_effect_key=None, verify, namespace_check=None
    ):
        from .postgres_effect_retention import compact

        return await compact(
            self,
            scope,
            run_id,
            limit=limit,
            after_effect_key=after_effect_key,
            verify=verify,
            namespace_check=namespace_check,
        )

    async def _record(self, prefix):
        row = await self._execute(
            "SELECT run_id,action_id,attempt_id,operation_digest,target_digest,effect,state,result,source,adopted_result_digest "
            "FROM ralf_temporal_effects WHERE workspace=%s AND principal=%s AND effect_key=%s",
            prefix,
            fetch="one",
        )
        if row is None:
            return None
        return dict(
            zip(
                (
                    "run_id",
                    "action_id",
                    "attempt_id",
                    "operation_digest",
                    "target_digest",
                    "effect",
                    "state",
                    "result",
                    "source",
                    "adopted_result_digest",
                ),
                row,
                strict=True,
            )
        )

    @staticmethod
    def _validate_record(record, envelope, target):
        context = envelope.context
        if (
            record["run_id"] != context.run_id
            or record["action_id"] != context.action_id
            or record["operation_digest"] != envelope.operation_digest
            or record["target_digest"] != target
        ):
            raise IdempotencyConflict("Effect key already identifies a different operation")

    async def begin(self, envelope):
        prefix, target = _binding(envelope)
        async with self._transaction(("temporal-effects", *prefix[:2], target)):
            record = await self._record(prefix)
            if record is not None:
                self._validate_record(record, envelope, target)
                observation = (
                    None
                    if record["result"] is None
                    else EffectObservation(json.loads(record["result"]), record["source"])
                )
                return {"execute": False, "observation": observation}
            if envelope.tool_manifest["effect"] != "read_only":
                prior = await self._execute(
                    "SELECT run_id,action_id,effect_key FROM ralf_temporal_effects "
                    "WHERE workspace=%s AND principal=%s AND target_digest=%s "
                    "AND effect<>'read_only' AND state<>'adopted' ORDER BY effect_key LIMIT 1",
                    (*prefix[:2], target),
                    fetch="one",
                )
                if prior is not None:
                    return {
                        "execute": False,
                        "blocked": True,
                        "prior": dict(
                            zip(("run_id", "action_id", "effect_key"), prior, strict=True)
                        ),
                    }
            context = envelope.context
            await self._execute(
                "INSERT INTO ralf_temporal_effects "
                "(workspace,principal,effect_key,run_id,action_id,attempt_id,operation_digest,target_digest,effect,state) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'dispatched')",
                (
                    *prefix,
                    context.run_id,
                    context.action_id,
                    context.attempt_id,
                    envelope.operation_digest,
                    target,
                    envelope.tool_manifest["effect"],
                ),
            )
            return {"execute": True}

    async def received(self, envelope, observation):
        if not isinstance(observation, EffectObservation):
            raise ValidationError("EffectJournal requires EffectObservation")
        prefix, target = _binding(envelope)
        result = canonical(observation.result)
        async with self._transaction(("temporal-effects", *prefix[:2], target)):
            record = await self._record(prefix)
            if record is None:
                raise ValidationError("No durable dispatch intent for observed effect")
            self._validate_record(record, envelope, target)
            await self._execute(
                "INSERT INTO ralf_temporal_effect_evidence "
                "(workspace,principal,effect_key,evidence_digest,result,source) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (
                    *prefix,
                    digest([observation.source, observation.result]),
                    result,
                    observation.source,
                ),
            )
            if record["result"] is None:
                await self._execute(
                    "UPDATE ralf_temporal_effects SET result=%s,source=%s,state=CASE WHEN state='adopted' THEN state ELSE 'received' END "
                    "WHERE workspace=%s AND principal=%s AND effect_key=%s",
                    (result, observation.source, *prefix),
                )
            # A first receipt is immutable. Later, even conflicting, evidence is
            # retained separately and can never overwrite adopted Run output.

    async def observation(self, envelope):
        prefix, target = _binding(envelope)
        async with self._transaction(("temporal-effects", *prefix[:2], target)):
            record = await self._record(prefix)
            if record is None:
                return None
            self._validate_record(record, envelope, target)
            return (
                None
                if record["result"] is None
                else EffectObservation(json.loads(record["result"]), record["source"])
            )

    async def acknowledge(self, envelope, observation):
        if not isinstance(observation, EffectObservation):
            raise ValidationError("EffectJournal requires EffectObservation")
        prefix, target = _binding(envelope)
        async with self._transaction(("temporal-effects", *prefix[:2], target)):
            record = await self._record(prefix)
            if record is None:
                # A blocked, never-dispatched Action cannot manufacture an
                # acknowledgement and clear another Run's unresolved intent.
                raise ValidationError("No durable dispatch intent to acknowledge")
            self._validate_record(record, envelope, target)
            identity = digest(observation.result)
            if (
                record["adopted_result_digest"] is not None
                and record["adopted_result_digest"] != identity
            ):
                raise IdempotencyConflict("Adopted effect evidence is immutable")
            await self._execute(
                "INSERT INTO ralf_temporal_effect_evidence "
                "(workspace,principal,effect_key,evidence_digest,result,source) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    *prefix,
                    digest([observation.source, observation.result]),
                    canonical(observation.result),
                    observation.source,
                ),
            )
            await self._execute(
                "UPDATE ralf_temporal_effects SET state='adopted',adopted_result_digest=%s,"
                "result=COALESCE(result,%s),source=COALESCE(source,%s) "
                "WHERE workspace=%s AND principal=%s AND effect_key=%s",
                (identity, canonical(observation.result), observation.source, *prefix),
            )

    async def aclose(self):
        await super().aclose()
