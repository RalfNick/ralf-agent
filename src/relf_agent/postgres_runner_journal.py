"""Shared finite native startup evidence on the original PostgreSQL effect journal.

This borrowed view records intent, one-time submission advances and receipts.
It does not authorize a native call, schedule work, establish native recovery,
or prove that cancellation stopped an execution. Initialize explicitly before
publishing its dataset identity. Closing the view never closes its effect owner.
"""

import json
import uuid
from contextlib import asynccontextmanager

from .errors import (
    DefinitionMismatch,
    MemoryBackendError,
    RalfError,
    RuntimeClosed,
    ValidationError,
)
from .executors import DispatchEnvelope
from .postgres import _advisory_key, _PostgresAdapter
from .postgres_coding_resources import new_resource, receive_resource, validate_resource
from .runner_journal_state import (
    _MAX_JSON,
    _MAX_RECORD,
    _json,
    _text,
    append_observation,
    cancel_record,
    new_record,
    receive_record,
    submit_record,
    validate_record,
)
from .temporal_journal import PostgresEffectJournal, _binding
from .types import InvocationContext, Scope, canonical

_METADATA = "ralf_temporal_runner_metadata"
_RECORDS = "ralf_temporal_runner_effects"
_RESOURCES = "ralf_temporal_coding_resources"
_TABLES = (
    _METADATA,
    _RECORDS,
    _RESOURCES,
    "ralf_temporal_effects",
    "ralf_temporal_effect_evidence",
)
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ralf_temporal_coding_resources (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, effect_key TEXT NOT NULL,
        record TEXT NOT NULL, PRIMARY KEY(workspace,principal,effect_key))""",
    """CREATE TABLE IF NOT EXISTS ralf_temporal_runner_metadata (
        singleton INTEGER PRIMARY KEY CHECK (singleton=1), value TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ralf_temporal_runner_effects (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, effect_key TEXT NOT NULL,
        record TEXT NOT NULL, PRIMARY KEY(workspace,principal,effect_key))""",
)


def _dispatch(envelope):
    if not isinstance(envelope, DispatchEnvelope):
        raise ValidationError("PostgreSQL Runner journal requires DispatchEnvelope")
    context = envelope.context
    return {
        "scope": {"workspace": context.scope.workspace, "principal": context.scope.principal},
        "run_id": context.run_id,
        "action_id": context.action_id,
        "attempt_id": context.attempt_id,
        "effect_key": context.effect_key,
        "execution_epoch": context.execution_epoch,
        "tool_manifest": envelope.tool_manifest,
        "arguments": envelope.arguments,
        "operation_digest": envelope.operation_digest,
    }


def _envelope(binding, key):
    value = binding.get("dispatch")
    if type(value) is not dict or set(value) != {
        "scope",
        "run_id",
        "action_id",
        "attempt_id",
        "effect_key",
        "execution_epoch",
        "tool_manifest",
        "arguments",
        "operation_digest",
    }:
        raise ValidationError("Runner binding requires the complete original dispatch")
    if (
        value["scope"] != {"workspace": key[0], "principal": key[1]}
        or value["effect_key"] != key[2]
    ):
        raise ValidationError("Runner dispatch differs from its original scoped effect")
    for name in (
        "run_id",
        "action_id",
        "attempt_id",
        "effect_key",
        "execution_epoch",
        "operation_digest",
    ):
        _text(value[name], "Runner dispatch " + name)
    envelope = DispatchEnvelope(
        InvocationContext(
            Scope(*key[:2]),
            *(
                value[name]
                for name in (
                    "run_id",
                    "action_id",
                    "attempt_id",
                    "effect_key",
                    "execution_epoch",
                )
            ),
        ),
        value["tool_manifest"],
        value["arguments"],
        value["operation_digest"],
    )
    effect = envelope.tool_manifest.get("effect")
    if type(effect) is not str or effect not in {
        "read_only",
        "idempotent_write",
        "queryable_write",
        "unqueryable_write",
    }:
        raise ValidationError("Runner dispatch requires its original effect classification")
    return envelope


class PostgresRunnerJournal:
    """Bounded shared stage CAS; original History retains all execution authority."""

    def __init__(self, effect_journal: PostgresEffectJournal, *, identity: dict, capacity=1000):
        if not isinstance(effect_journal, PostgresEffectJournal):
            raise ValidationError("Runner journal requires the original PostgreSQL effect journal")
        if type(capacity) is not int or not 1 <= capacity <= 1000000:
            raise ValidationError("Runner journal requires bounded positive capacity")
        self._dependencies = _json(identity, "Runner dependencies")
        self._effect = effect_journal
        self._effect_identity = _json(effect_journal.identity, "Effect journal identity")
        self._capacity = capacity
        self._closed = False
        self._metadata_json = self._identity_json = None
        self._routing = None

    def _ready(self, *, initialize=False):
        if self._closed:
            raise RuntimeClosed("PostgreSQL Runner journal view is closed")
        if self._effect._closed or canonical(self._effect.identity) != self._effect_identity:
            raise DefinitionMismatch("Original PostgreSQL effect journal is unavailable or changed")
        if not initialize and self._metadata_json is None:
            raise DefinitionMismatch("PostgreSQL Runner journal requires explicit initialization")
        if self._routing is not None and any(
            self._effect._table_schemas.get(table) != schema
            for table, schema in self._routing.items()
        ):
            raise DefinitionMismatch("Original PostgreSQL Runner journal schema routing changed")

    @property
    def identity(self):
        self._ready()
        return json.loads(self._identity_json)

    async def initialize(self):
        self._ready(initialize=True)
        # Initialization alone needs to publish routing after database commit
        # while the borrowed owner's mutex is still held. _transaction releases
        # that mutex on exit, so publishing after its exit would expose a race.
        async with self._effect._lock:
            self._ready(initialize=True)
            staging = _PostgresAdapter(self._effect.connection, backend_id=self._effect.backend_id)
            staging._table_schemas = dict(self._effect._table_schemas)
            try:
                async with self._effect.connection.transaction():
                    await staging._execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    await staging._execute(
                        "SELECT pg_advisory_xact_lock(%s)", (_advisory_key(("schema",)),)
                    )
                    metadata, routing = await self._initialize_staged(staging)
                    metadata_json = canonical(metadata)
                    identity_json = canonical(
                        {k: v for k, v in metadata.items() if k != "capacity"}
                    )
                # No await separates commit from publication. Errors or
                # cancellation before this point leave the owner untouched.
                self._effect._table_schemas.update(routing)
                self._metadata_json = metadata_json
                self._identity_json = identity_json
                self._routing = routing
            except RalfError:
                raise
            except Exception as exc:
                raise MemoryBackendError("PostgreSQL backend operation failed") from exc

    async def _initialize_staged(self, staging):
        for statement in _SCHEMA:
            await staging._execute(statement)
        routing = {}
        # Resolve every table once, including the borrowed v1 effect tables.
        # All SQL thereafter delegates through that owner's qualified routing.
        from psycopg import sql

        for table in _TABLES:
            schema = staging._table_schemas.get(table)
            reference = (
                table
                if schema is None
                else sql.Identifier(schema, table).as_string(self._effect.connection)
            )
            row = await staging._execute(
                "SELECT n.nspname FROM pg_class c JOIN pg_namespace n "
                "ON n.oid=c.relnamespace WHERE c.oid=to_regclass(%s)",
                (reference,),
                fetch="one",
            )
            if row is None:
                raise DefinitionMismatch(
                    "Original PostgreSQL effect and Runner tables are required"
                )
            routing[table] = row[0]
        staging._table_schemas.update(routing)
        row = await staging._execute(
            "SELECT value FROM ralf_temporal_runner_metadata WHERE singleton=1 FOR UPDATE",
            fetch="one",
        )
        if row is None:
            count = await staging._execute(
                "SELECT count(*) FROM ralf_temporal_runner_effects", fetch="one"
            )
            resource_count = await staging._execute(
                "SELECT count(*) FROM ralf_temporal_coding_resources", fetch="one"
            )
            if count[0] or resource_count[0] or self._metadata_json is not None:
                raise DefinitionMismatch("Original PostgreSQL Runner dataset metadata is missing")
            metadata = {
                "kind": "postgres-runner-journal",
                "version": "1",
                "dataset_uuid": uuid.uuid4().hex,
                "dependencies": json.loads(self._dependencies),
                "effect_journal": json.loads(self._effect_identity),
                "capacity": self._capacity,
            }
            encoded = _json(metadata, "Runner dataset metadata")
            await staging._execute(
                "INSERT INTO ralf_temporal_runner_metadata (singleton,value) VALUES (1,%s)",
                (encoded,),
            )
        else:
            encoded = row[0]
        metadata = self._validate_metadata(encoded)
        if self._metadata_json is not None and canonical(metadata) != self._metadata_json:
            raise DefinitionMismatch("Original PostgreSQL Runner dataset changed")
        return metadata, routing

    def _validate_metadata(self, encoded):
        try:
            if type(encoded) is not str or len(encoded.encode("utf-8")) > _MAX_JSON:
                raise ValueError
            metadata = json.loads(encoded)
            _json(metadata, "Saved Runner dataset metadata")
            if (
                set(metadata)
                != {"kind", "version", "dataset_uuid", "dependencies", "effect_journal", "capacity"}
                or metadata["kind"] != "postgres-runner-journal"
                or metadata["version"] != "1"
                or type(metadata["dataset_uuid"]) is not str
                or len(metadata["dataset_uuid"]) != 32
                or set(metadata["dataset_uuid"]) - set("0123456789abcdef")
                or canonical(metadata["dependencies"]) != self._dependencies
                or canonical(metadata["effect_journal"]) != self._effect_identity
                or type(metadata["capacity"]) is not int
                or metadata["capacity"] != self._capacity
            ):
                raise ValueError
            return metadata
        except (ValueError, TypeError, KeyError, RecursionError):
            raise DefinitionMismatch(
                "Original PostgreSQL Runner dataset or dependencies changed"
            ) from None

    async def _check(self, *, capacity_lock=False):
        self._ready()
        row = await self._effect._execute(
            "SELECT value FROM ralf_temporal_runner_metadata WHERE singleton=1"
            + (" FOR UPDATE" if capacity_lock else ""),
            fetch="one",
        )
        if row is None or canonical(self._validate_metadata(row[0])) != self._metadata_json:
            raise DefinitionMismatch("Original PostgreSQL Runner dataset changed")

    def _key(self, scope, effect_key, binding):
        self._ready()
        if not isinstance(scope, Scope):
            raise ValidationError("Runner journal requires Scope")
        key = (
            _text(scope.workspace, "Workspace"),
            _text(scope.principal, "Principal"),
            _text(effect_key, "Effect key"),
        )
        return key, _json(binding, "Runner binding")

    async def _record(self, key, binding_json):
        row = await self._effect._execute(
            "SELECT record FROM ralf_temporal_runner_effects WHERE workspace=%s AND principal=%s AND effect_key=%s",
            key,
            fetch="one",
        )
        return None if row is None else validate_record(row[0], key, binding_json)

    async def _validate_effect(self, key, record):
        envelope = _envelope(record["binding"], key)
        _, target = _binding(envelope)
        effect = await self._effect._record(key)
        if (
            effect is None
            or effect["attempt_id"] != envelope.context.attempt_id
            or effect["effect"] != envelope.tool_manifest["effect"]
        ):
            raise DefinitionMismatch("Original Runner dispatch intent or attempt changed")
        self._effect._validate_record(effect, envelope, target)
        return envelope, target

    @asynccontextmanager
    async def _record_transaction(self, key, binding_json, *, required=False):
        async with self._effect._transaction():
            await self._check()
            record = await self._record(key, binding_json)
            if record is None:
                if required:
                    raise ValidationError("No durable Runner startup intent for evidence")
                yield None
                return
            # Derive the advisory domain from the original saved dispatch, not
            # an Activity retry's attempt or a caller-supplied target digest.
            _, target = await self._validate_effect(key, record)
            await self._effect._execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (_advisory_key(("temporal-effects", *key[:2], target)),),
            )
            await self._check()
            record = await self._record(key, binding_json)
            if record is None:
                raise DefinitionMismatch("Original PostgreSQL Runner startup intent disappeared")
            await self._validate_effect(key, record)
            yield record

    async def lookup(self, scope: Scope, effect_key: str, *, binding: dict) -> dict | None:
        key, encoded = self._key(scope, effect_key, binding)
        async with self._record_transaction(key, encoded) as record:
            return record

    async def begin(
        self, scope: Scope, effect_key: str, binding: dict, *, envelope: DispatchEnvelope
    ) -> dict:
        key, binding_json = self._key(scope, effect_key, binding)
        fixed = json.loads(binding_json)
        original = _envelope(fixed, key)
        if canonical(_dispatch(envelope)) != canonical(_dispatch(original)):
            raise ValidationError("Runner binding differs from the complete original envelope")
        prefix, target = _binding(original)
        async with self._effect._transaction(("temporal-effects", *prefix[:2], target)):
            # This row lock bounds native capacity even across different target
            # advisory locks and independent connections. No RPC happens here.
            await self._check(capacity_lock=True)
            record = await self._record(key, binding_json)
            effect = await self._effect._record(key)
            if record is not None:
                await self._validate_effect(key, record)
                return {**record, "execute": False}
            resource = await self._resource(key)
            if resource is not None:
                await self._validate_resource_effect(key, resource)
                prepared = resource["prepared"]
                expected = {
                    **resource["namespace_binding"],
                    "environment": None
                    if prepared is None
                    else {k: prepared[k] for k in ("identity", "container_id", "generation")},
                }
                if (
                    prepared is None
                    or resource["stop"] is not None
                    or resource["unprepared"] is not None
                    or resource["namespace_absent"] is not None
                    or canonical(fixed) != canonical(expected)
                ):
                    raise DefinitionMismatch(
                        "Runner startup lacks its original prepared resource intent"
                    )
            elif effect is not None:
                raise DefinitionMismatch(
                    "Existing effect intent lacks original Runner startup evidence"
                )
            if resource is None and original.tool_manifest["effect"] != "read_only":
                prior = await self._effect._execute(
                    "SELECT run_id,action_id,effect_key FROM ralf_temporal_effects "
                    "WHERE workspace=%s AND principal=%s AND target_digest=%s "
                    "AND effect<>'read_only' AND state<>'adopted' ORDER BY effect_key LIMIT 1",
                    (*key[:2], target),
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
            count = await self._resource_capacity()
            if resource is None and count >= self._capacity:
                raise ValidationError("Runner journal effect capacity is full")
            context = original.context
            record = new_record(key, binding_json)
            if resource is None:
                await self._effect._execute(
                    "INSERT INTO ralf_temporal_effects "
                    "(workspace,principal,effect_key,run_id,action_id,attempt_id,operation_digest,target_digest,effect,state) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'dispatched')",
                    (
                        *key,
                        context.run_id,
                        context.action_id,
                        context.attempt_id,
                        original.operation_digest,
                        target,
                        original.tool_manifest["effect"],
                    ),
                )
            await self._effect._execute(
                "INSERT INTO ralf_temporal_runner_effects (workspace,principal,effect_key,record) VALUES (%s,%s,%s,%s)",
                (*key, _json(record, "Runner record", limit=_MAX_RECORD)),
            )
            return {**record, "execute": True}

    async def _resource(self, key, request=None):
        row = await self._effect._execute(
            "SELECT record FROM ralf_temporal_coding_resources WHERE workspace=%s AND principal=%s AND effect_key=%s",
            key,
            fetch="one",
        )
        return None if row is None else validate_resource(row[0], key, request)

    async def _validate_resource_effect(self, key, resource):
        envelope = _envelope(resource["namespace_binding"], key)
        _, target = _binding(envelope)
        effect = await self._effect._record(key)
        if (
            effect is None
            or effect["attempt_id"] != envelope.context.attempt_id
            or effect["effect"] != envelope.tool_manifest["effect"]
        ):
            raise DefinitionMismatch("Original resource effect intent changed")
        self._effect._validate_record(effect, envelope, target)
        return envelope, target

    async def _resource_capacity(self):
        row = await self._effect._execute(
            "SELECT (SELECT count(*) FROM ralf_temporal_coding_resources) + "
            "(SELECT count(*) FROM ralf_temporal_runner_effects r WHERE NOT EXISTS "
            "(SELECT 1 FROM ralf_temporal_coding_resources c WHERE c.workspace=r.workspace "
            "AND c.principal=r.principal AND c.effect_key=r.effect_key))",
            fetch="one",
        )
        return row[0]

    async def begin_resource(
        self, envelope, request, runner_identity, namespace_binding, *, owner_proof=None
    ):
        context = envelope.context if type(envelope) is DispatchEnvelope else None
        if context is None:
            raise ValidationError("Coding resource requires original DispatchEnvelope")
        key, _ = self._key(context.scope, context.effect_key, namespace_binding)
        resource = new_resource(
            key, request, runner_identity, namespace_binding, owner_proof=owner_proof
        )
        original = _envelope(resource["namespace_binding"], key)
        if canonical(_dispatch(original)) != canonical(_dispatch(envelope)):
            raise ValidationError("Resource request differs from original dispatch")
        prefix, target = _binding(original)
        async with self._effect._transaction(("temporal-effects", *prefix[:2], target)):
            await self._check(capacity_lock=True)
            prior = await self._resource(key, request)
            if prior is not None:
                await self._validate_resource_effect(key, prior)
                if (
                    prior["runner"] != resource["runner"]
                    or prior["namespace_binding"] != resource["namespace_binding"]
                    or prior["owner"] != resource["owner"]
                ):
                    from .errors import IdempotencyConflict

                    raise IdempotencyConflict("Original resource namespace or runner changed")
                return {"execute": False, "resource": prior}
            if (
                await self._effect._record(key) is not None
                or await self._record(key, canonical(namespace_binding)) is not None
            ):
                raise DefinitionMismatch("Existing effect lacks original resource intent")
            if original.tool_manifest["effect"] != "read_only":
                prior = await self._effect._execute(
                    "SELECT run_id,action_id,effect_key FROM ralf_temporal_effects "
                    "WHERE workspace=%s AND principal=%s AND target_digest=%s "
                    "AND effect<>'read_only' AND state<>'adopted' ORDER BY effect_key LIMIT 1",
                    (*key[:2], target),
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
            if await self._resource_capacity() >= self._capacity:
                raise ValidationError("Runner journal resource capacity is full")
            await self._effect._execute(
                "INSERT INTO ralf_temporal_effects "
                "(workspace,principal,effect_key,run_id,action_id,attempt_id,operation_digest,target_digest,effect,state) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'dispatched')",
                (
                    *key,
                    context.run_id,
                    context.action_id,
                    context.attempt_id,
                    original.operation_digest,
                    target,
                    original.tool_manifest["effect"],
                ),
            )
            await self._effect._execute(
                "INSERT INTO ralf_temporal_coding_resources (workspace,principal,effect_key,record) VALUES (%s,%s,%s,%s)",
                (*key, _json(resource, "Coding resource record", limit=_MAX_RECORD)),
            )
            return {"execute": True, "resource": resource}

    async def resource_state(self, scope, effect_key, request):
        key, _ = self._key(scope, effect_key, request)
        async with self._effect._transaction():
            await self._check()
            resource = await self._resource(key, request)
            if resource is not None:
                await self._validate_resource_effect(key, resource)
            return resource

    async def record_resource(self, scope, effect_key, request, *, kind, evidence):
        key, _ = self._key(scope, effect_key, request)
        async with self._effect._transaction():
            await self._check()
            resource = await self._resource(key, request)
            if resource is None:
                raise ValidationError("Resource receipt requires original durable intent")
            _, target = await self._validate_resource_effect(key, resource)
            await self._effect._execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (_advisory_key(("temporal-effects", *key[:2], target)),),
            )
            await self._check()
            resource = await self._resource(key, request)
            if resource is None:
                raise DefinitionMismatch("Original Coding resource intent disappeared")
            await self._validate_resource_effect(key, resource)
            updated = receive_resource(resource, kind, evidence)
            await self._effect._execute(
                "UPDATE ralf_temporal_coding_resources SET record=%s WHERE workspace=%s AND principal=%s AND effect_key=%s",
                (_json(updated, "Coding resource record", limit=_MAX_RECORD), *key),
            )
            return updated

    async def composition_resources(self, scope):
        """Read every original scoped native intent, including already fenced rows."""
        if type(scope) is not Scope:
            raise ValidationError("Composition resources require original Scope")
        self._ready()
        prefix = (_text(scope.workspace, "Workspace"), _text(scope.principal, "Principal"))
        async with self._effect._transaction():
            await self._check()
            rows = await self._effect._execute(
                "SELECT effect_key,record FROM ralf_temporal_coding_resources "
                "WHERE workspace=%s AND principal=%s ORDER BY effect_key LIMIT %s",
                (*prefix, self._capacity + 1),
                fetch="all",
            )
            if len(rows) > self._capacity:
                raise DefinitionMismatch("Original Coding resource capacity changed")
            records = []
            for effect_key, encoded in rows:
                key = (*prefix, effect_key)
                resource = validate_resource(encoded, key)
                await self._validate_resource_effect(key, resource)
                records.append(resource)
            return tuple(records)

    async def pending_resources(self, scope):
        if type(scope) is not Scope:
            raise ValidationError("Pending Coding resources require original Scope")
        self._ready()
        prefix = (_text(scope.workspace, "Workspace"), _text(scope.principal, "Principal"))
        async with self._effect._transaction():
            await self._check()
            rows = await self._effect._execute(
                "SELECT effect_key,record FROM ralf_temporal_coding_resources "
                "WHERE workspace=%s AND principal=%s ORDER BY effect_key LIMIT %s",
                (*prefix, self._capacity + 1),
                fetch="all",
            )
            if len(rows) > self._capacity:
                raise DefinitionMismatch("Original Coding resource capacity changed")
            pending = []
            for effect_key, encoded in rows:
                key = (*prefix, effect_key)
                resource = validate_resource(encoded, key)
                await self._validate_resource_effect(key, resource)
                if resource["pending_stop"]:
                    pending.append(resource)
            return tuple(pending)

    async def _save(self, key, record, before):
        encoded = _json(record, "Runner record", limit=_MAX_RECORD)
        if encoded != before:
            await self._effect._execute(
                "UPDATE ralf_temporal_runner_effects SET record=%s WHERE workspace=%s AND principal=%s AND effect_key=%s",
                (encoded, *key),
            )
        return json.loads(encoded)

    async def _submit(self, scope, effect_key, binding, previous, stage):
        key, encoded = self._key(scope, effect_key, binding)
        async with self._record_transaction(key, encoded, required=True) as record:
            before = canonical(record)
            record, execute = submit_record(record, previous, stage)
            return {**await self._save(key, record, before), "execute": execute}

    async def mark_thread_submitted(self, scope: Scope, effect_key: str, *, binding: dict) -> dict:
        return await self._submit(scope, effect_key, binding, "intent", "thread_submitted")

    async def mark_turn_submitted(self, scope: Scope, effect_key: str, *, binding: dict) -> dict:
        return await self._submit(scope, effect_key, binding, "thread_confirmed", "turn_submitted")

    async def _receipt(self, scope, effect_key, binding, native, previous, stage):
        key, encoded = self._key(scope, effect_key, binding)
        async with self._record_transaction(key, encoded, required=True) as record:
            before = canonical(record)
            return await self._save(key, receive_record(record, native, previous, stage), before)

    async def record_thread(
        self, scope: Scope, effect_key: str, *, binding: dict, thread_id: str, process_epoch: str
    ) -> dict:
        native = {
            "thread_id": _text(thread_id, "Thread ID"),
            "process_epoch": _text(process_epoch, "Process epoch"),
        }
        return await self._receipt(
            scope, effect_key, binding, native, "thread_submitted", "thread_confirmed"
        )

    async def record_turn(
        self, scope: Scope, effect_key: str, *, binding: dict, turn_id: str
    ) -> dict:
        return await self._receipt(
            scope,
            effect_key,
            binding,
            {"turn_id": _text(turn_id, "Turn ID")},
            "turn_submitted",
            "turn_confirmed",
        )

    async def record_observation(
        self, scope: Scope, effect_key: str, *, binding: dict, observation: dict
    ) -> dict:
        key, encoded = self._key(scope, effect_key, binding)
        observation_json = _json(observation, "Runner observation")
        async with self._record_transaction(key, encoded, required=True) as record:
            before = canonical(record)
            return await self._save(key, append_observation(record, observation_json), before)

    async def request_cancel(self, scope: Scope, effect_key: str, *, binding: dict) -> dict:
        key, encoded = self._key(scope, effect_key, binding)
        async with self._record_transaction(key, encoded, required=True) as record:
            before = canonical(record)
            return await self._save(key, cancel_record(record), before)

    async def aclose(self):
        # Share the owner's transaction mutex so a running mutation finishes
        # before this view is disabled. Never close or disable the borrowed owner.
        async with self._effect._lock:
            self._closed = True
