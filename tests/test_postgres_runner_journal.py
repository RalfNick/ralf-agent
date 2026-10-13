"""Native startup boundary tests and opt-in actual PostgreSQL transactions.

Set RALF_TEST_POSTGRES_DSN to run the database cases. Skipped integration tests
provide no evidence of PostgreSQL concurrency, rollback, or durable startup.
"""

import asyncio
import copy
import importlib
import importlib.util
import json
import os
import uuid
from contextlib import asynccontextmanager

import pytest

from ralf_agent.errors import (
    DefinitionMismatch,
    IdempotencyConflict,
    MemoryBackendError,
    RuntimeClosed,
    ValidationError,
)
from ralf_agent.executors import DispatchEnvelope
from ralf_agent.temporal_journal import PostgresEffectJournal
from ralf_agent.types import InvocationContext, Scope

DEPENDENCIES = {"adapter": "codex-test", "environment": {"generation": "original"}}
SCOPE = Scope("runner-pg", "principal")


def adapter():
    name = "ralf_agent.postgres_runner_journal"
    assert importlib.util.find_spec(name) is not None, "Missing shared PostgreSQL Runner journal"
    return importlib.import_module(name).PostgresRunnerJournal


def envelope(
    *, scope=SCOPE, run="run", key="effect", arguments=None, attempt="attempt", epoch="epoch"
):
    return DispatchEnvelope(
        InvocationContext(scope, run, "action", attempt, key, epoch),
        {"name": "coding", "effect": "queryable_write"},
        {"task": "bounded"} if arguments is None else arguments,
        "operation",
    )


def binding(value):
    context = value.context
    return {
        "environment": {"generation": "original"},
        "dispatch": {
            "scope": {"workspace": context.scope.workspace, "principal": context.scope.principal},
            "run_id": context.run_id,
            "action_id": context.action_id,
            "attempt_id": context.attempt_id,
            "effect_key": context.effect_key,
            "execution_epoch": context.execution_epoch,
            "tool_manifest": value.tool_manifest,
            "arguments": value.arguments,
            "operation_digest": value.operation_digest,
        },
    }


class BoundaryConnection:
    """Constructor/lifetime checks only; no simulated SQL state or transactions."""

    autocommit = True

    def __init__(self):
        self.closed = False

    def cursor(self, **kwargs):
        raise AssertionError("Boundary validation must precede PostgreSQL I/O")

    def transaction(self):
        raise AssertionError("Boundary validation must precede PostgreSQL I/O")

    async def close(self):
        self.closed = True


def unopened(**kwargs):
    connection = BoundaryConnection()
    effect = PostgresEffectJournal(connection, backend_id="borrowed-effect")
    return adapter()(effect, identity=DEPENDENCIES, **kwargs), effect, connection


@pytest.mark.parametrize("effect", [None, object(), {"identity": "not an adapter"}])
def test_only_actual_effect_journal_can_supply_shared_transactions(effect):
    with pytest.raises(ValidationError):
        adapter()(effect, identity=DEPENDENCIES)


@pytest.mark.parametrize("capacity", [True, False, 0, -1, 1.5, 1000001])
def test_capacity_validation_precedes_database_io(capacity):
    with pytest.raises(ValidationError):
        unopened(capacity=capacity)


@pytest.mark.parametrize("identity", [None, {}, [], {"bad": float("nan")}, {"bad": 2**63}])
def test_dependencies_are_strict_bounded_json_before_io(identity):
    effect = PostgresEffectJournal(BoundaryConnection(), backend_id="borrowed-effect")
    with pytest.raises(ValidationError):
        adapter()(effect, identity=identity)


def test_uninitialized_view_cannot_expose_identity_or_start_and_close_preserves_borrow():
    async def scenario():
        journal, effect, connection = unopened()
        with pytest.raises(DefinitionMismatch):
            _ = journal.identity
        value = envelope()
        with pytest.raises(DefinitionMismatch):
            await journal.begin(SCOPE, "effect", binding(value), envelope=value)
        await journal.aclose()
        await journal.aclose()
        assert not connection.closed and not effect._closed
        with pytest.raises(RuntimeClosed):
            await journal.lookup(SCOPE, "effect", binding=binding(value))
        with pytest.raises(RuntimeClosed):
            await journal.initialize()

    asyncio.run(scenario())


@pytest.fixture
def postgres_dsn():
    dsn = os.environ.get("RALF_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Set RALF_TEST_POSTGRES_DSN for actual PostgreSQL Runner journal cases")
    pytest.importorskip("psycopg")
    return dsn


@asynccontextmanager
async def journals(dsn, *, capacity=1000):
    import psycopg
    from psycopg import sql

    schema = "ralf_runner_test_" + uuid.uuid4().hex
    connections = []
    try:
        for _ in range(2):
            connections.append(await psycopg.AsyncConnection.connect(dsn, autocommit=True))
        await connections[0].execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        effects, views = [], []
        for connection in connections:
            await connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
            )
            effect = PostgresEffectJournal(connection, backend_id="shared-effect-test")
            await effect.initialize()
            view = adapter()(effect, identity=DEPENDENCIES, capacity=capacity)
            await view.initialize()
            effects.append(effect)
            views.append(view)
        yield views, effects, connections, schema
    finally:
        if connections:
            await connections[0].execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )
        for connection in connections:
            await connection.close()


def test_real_pg_original_intent_and_phase_permissions_survive_new_worker(postgres_dsn):
    async def scenario():
        async with journals(postgres_dsn) as (views, effects, _, _):
            first, other = views
            value = envelope()
            original = binding(value)
            assert (await first.begin(SCOPE, "effect", original, envelope=value))["execute"] is True
            assert (await other.begin(SCOPE, "effect", original, envelope=value))[
                "execute"
            ] is False
            assert (await effects[0].begin(value))["execute"] is False
            results = await asyncio.gather(
                *[
                    views[n % 2].mark_thread_submitted(SCOPE, "effect", binding=original)
                    for n in range(16)
                ]
            )
            assert sum(item["execute"] for item in results) == 1
            await other.record_thread(
                SCOPE, "effect", binding=original, thread_id="thread", process_epoch="process"
            )
            results = await asyncio.gather(
                *[
                    views[n % 2].mark_turn_submitted(SCOPE, "effect", binding=original)
                    for n in range(16)
                ]
            )
            assert sum(item["execute"] for item in results) == 1
            await first.request_cancel(SCOPE, "effect", binding=original)
            saved = await other.record_turn(SCOPE, "effect", binding=original, turn_id="turn")
            assert saved["stage"] == "turn_confirmed" and saved["cancel_requested"] is True
            await first.aclose()
            assert (await other.lookup(SCOPE, "effect", binding=original))["turn_id"] == "turn"
            assert (await effects[0].begin(value))["execute"] is False
            assert (await other.mark_turn_submitted(SCOPE, "effect", binding=original))[
                "execute"
            ] is False

    asyncio.run(scenario())


def test_real_pg_unresolved_target_blocks_without_native_intent(postgres_dsn):
    async def scenario():
        async with journals(postgres_dsn) as (views, _, _, _):
            first = envelope()
            await views[0].begin(SCOPE, "effect", binding(first), envelope=first)
            second = envelope(run="other-run", key="other-effect")
            result = await views[1].begin(SCOPE, "other-effect", binding(second), envelope=second)
            assert result == {
                "execute": False,
                "blocked": True,
                "prior": {"run_id": "run", "action_id": "action", "effect_key": "effect"},
            }
            assert await views[1].lookup(SCOPE, "other-effect", binding=binding(second)) is None

    asyncio.run(scenario())


def test_real_pg_existing_effect_without_native_record_cannot_be_restarted(postgres_dsn):
    async def scenario():
        async with journals(postgres_dsn) as (views, effects, _, _):
            value = envelope()
            await effects[0].begin(value)
            with pytest.raises(DefinitionMismatch):
                await views[0].begin(SCOPE, "effect", binding(value), envelope=value)
            assert await views[0].lookup(SCOPE, "effect", binding=binding(value)) is None

    asyncio.run(scenario())


def test_real_pg_capacity_is_atomic_across_distinct_target_locks(postgres_dsn):
    async def scenario():
        async with journals(postgres_dsn, capacity=1) as (views, effects, _, _):
            values = [envelope(key=f"effect-{n}", arguments={"task": n}) for n in range(2)]
            results = await asyncio.gather(
                *[
                    views[n].begin(SCOPE, value.context.effect_key, binding(value), envelope=value)
                    for n, value in enumerate(values)
                ],
                return_exceptions=True,
            )
            assert sum(isinstance(result, ValidationError) for result in results) == 1
            assert sum(isinstance(result, dict) and result["execute"] for result in results) == 1
            for n, result in enumerate(results):
                if isinstance(result, ValidationError):
                    value = values[n]
                    assert (
                        await views[n].lookup(
                            SCOPE, value.context.effect_key, binding=binding(value)
                        )
                        is None
                    )
                    assert (
                        await effects[n]._record(
                            (SCOPE.workspace, SCOPE.principal, value.context.effect_key)
                        )
                        is None
                    )

    asyncio.run(scenario())


def test_real_pg_native_insert_failure_rolls_back_original_dispatch_intent(postgres_dsn):
    async def scenario():
        async with journals(postgres_dsn) as (views, effects, _, _):
            value = envelope()
            original_execute = effects[0]._execute

            async def fail_native_insert(statement, parameters=(), **kwargs):
                if statement.startswith("INSERT INTO ralf_temporal_runner_effects "):
                    raise RuntimeError("injected write failure")
                return await original_execute(statement, parameters, **kwargs)

            effects[0]._execute = fail_native_insert
            try:
                with pytest.raises(MemoryBackendError):
                    await views[0].begin(SCOPE, "effect", binding(value), envelope=value)
            finally:
                effects[0]._execute = original_execute
            assert await views[1].lookup(SCOPE, "effect", binding=binding(value)) is None
            assert await effects[1]._record((SCOPE.workspace, SCOPE.principal, "effect")) is None
            assert (await views[1].begin(SCOPE, "effect", binding(value), envelope=value))[
                "execute"
            ] is True

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field", ["attempt_id", "execution_epoch", "arguments", "operation_digest"]
)
def test_real_pg_full_original_dispatch_is_immutable(postgres_dsn, field):
    async def scenario():
        async with journals(postgres_dsn) as (views, _, _, _):
            value = envelope()
            original = binding(value)
            await views[0].begin(SCOPE, "effect", original, envelope=value)
            changed = copy.deepcopy(original)
            changed["dispatch"][field] = {"changed": True} if field == "arguments" else "changed"
            with pytest.raises(IdempotencyConflict):
                await views[1].lookup(SCOPE, "effect", binding=changed)
            with pytest.raises(ValidationError):
                await views[1].begin(SCOPE, "effect", changed, envelope=value)
            assert (await views[0].lookup(SCOPE, "effect", binding=original))["stage"] == "intent"

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["attempt", "epoch"])
def test_real_pg_blank_original_attempt_or_epoch_cannot_start(postgres_dsn, field):
    async def scenario():
        async with journals(postgres_dsn) as (views, _, _, _):
            value = envelope(**{field: " "})
            with pytest.raises(ValidationError):
                await views[0].begin(SCOPE, "effect", binding(value), envelope=value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "effect", ["read_only", "idempotent_write", "queryable_write", "unqueryable_write"]
)
def test_original_tool_effect_categories_can_bind_without_dispatch_coercion(effect):
    from ralf_agent.postgres_runner_journal import _envelope

    value = envelope()
    original = binding(value)
    original["dispatch"]["tool_manifest"]["effect"] = effect
    fixed = _envelope(original, (SCOPE.workspace, SCOPE.principal, "effect"))
    assert fixed.tool_manifest["effect"] == effect


def test_real_pg_receipts_and_observations_do_not_create_stages_or_stop_proof(postgres_dsn):
    async def scenario():
        async with journals(postgres_dsn) as (views, _, _, _):
            journal = views[0]
            value = envelope()
            original = binding(value)
            await journal.begin(SCOPE, "effect", original, envelope=value)
            with pytest.raises(ValidationError):
                await journal.record_turn(SCOPE, "effect", binding=original, turn_id="turn")
            with pytest.raises(ValidationError):
                await journal.record_thread(
                    SCOPE, "effect", binding=original, thread_id="thread", process_epoch="process"
                )
            record = await journal.record_observation(
                SCOPE, "effect", binding=original, observation={"kind": "cancel_ack"}
            )
            assert record["stage"] == "intent" and "stopped" not in record
            assert (
                len(
                    (
                        await journal.record_observation(
                            SCOPE, "effect", binding=original, observation={"kind": "cancel_ack"}
                        )
                    )["observations"]
                )
                == 1
            )
            await journal.request_cancel(SCOPE, "effect", binding=original)
            with pytest.raises(ValidationError):
                await views[1].mark_thread_submitted(SCOPE, "effect", binding=original)

    asyncio.run(scenario())


def test_real_pg_metadata_and_routing_are_pinned_and_identity_is_detached(postgres_dsn):
    async def scenario():
        from psycopg import sql

        async with journals(postgres_dsn) as (views, effects, connections, schema):
            journal = views[0]
            identity = journal.identity
            assert identity["kind"] == "postgres-runner-journal" and identity["version"] == "1"
            assert len(identity["dataset_uuid"]) == 32
            identity["dependencies"]["environment"]["generation"] = "changed"
            assert journal.identity["dependencies"] == DEPENDENCIES
            await connections[0].execute("SET search_path TO public")
            value = envelope()
            await journal.begin(SCOPE, "effect", binding(value), envelope=value)
            assert (await effects[0].begin(value))["execute"] is False
            changed = adapter()(effects[0], identity={"adapter": "different"})
            with pytest.raises(DefinitionMismatch):
                await changed.initialize()
            wrong_capacity = adapter()(effects[0], identity=DEPENDENCIES, capacity=1)
            with pytest.raises(DefinitionMismatch):
                await wrong_capacity.initialize()
            await connections[1].execute(
                sql.SQL("UPDATE {}.ralf_temporal_runner_metadata SET value=%s").format(
                    sql.Identifier(schema)
                ),
                (json.dumps({"changed": True}),),
            )
            with pytest.raises(DefinitionMismatch):
                await journal.mark_thread_submitted(SCOPE, "effect", binding=binding(value))

    asyncio.run(scenario())


def test_real_pg_missing_metadata_cannot_reidentify_existing_native_dataset(postgres_dsn):
    async def scenario():
        async with journals(postgres_dsn) as (views, effects, connections, _):
            value = envelope()
            await views[0].begin(SCOPE, "effect", binding(value), envelope=value)
            await connections[0].execute("DELETE FROM ralf_temporal_runner_metadata")
            replacement = adapter()(effects[1], identity=DEPENDENCIES)
            with pytest.raises(DefinitionMismatch):
                await replacement.initialize()
            with pytest.raises(DefinitionMismatch):
                await views[0].mark_thread_submitted(SCOPE, "effect", binding=binding(value))

    asyncio.run(scenario())


def test_metadata_bytes_are_bounded_before_json_decoding():
    journal, _, _ = unopened()
    metadata = {
        "kind": "postgres-runner-journal",
        "version": "1",
        "dataset_uuid": "a" * 32,
        "dependencies": DEPENDENCIES,
        "effect_journal": {
            "kind": "postgres-effect-journal",
            "version": "1",
            "backend_id": "borrowed-effect",
        },
        "capacity": 1000,
    }
    with pytest.raises(DefinitionMismatch):
        journal._validate_metadata(" " * 65536 + json.dumps(metadata))


@pytest.mark.parametrize("effect", [[], {}])
def test_malformed_effect_category_is_rejected_with_typed_validation(effect):
    from ralf_agent.postgres_runner_journal import _envelope

    original = binding(envelope())
    original["dispatch"]["tool_manifest"]["effect"] = effect
    with pytest.raises(ValidationError):
        _envelope(original, (SCOPE.workspace, SCOPE.principal, "effect"))


@pytest.mark.parametrize("failure", ["metadata", "cancel"])
def test_real_pg_failed_initialization_cannot_redirect_original_effect_owner(
    postgres_dsn, monkeypatch, failure
):
    async def scenario():
        import psycopg
        from psycopg import sql

        connection = await psycopg.AsyncConnection.connect(postgres_dsn, autocommit=True)
        schemas = ["ralf_runner_route_" + uuid.uuid4().hex for _ in range(2)]
        try:
            for schema in schemas:
                await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            await connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schemas[0]))
            )
            owner = PostgresEffectJournal(connection, backend_id="original-effect")
            await owner.initialize()
            value = envelope()
            assert (await owner.begin(value))["execute"] is True
            original_routing = dict(owner._table_schemas)
            await connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schemas[1]))
            )
            alternate = PostgresEffectJournal(connection, backend_id="original-effect")
            await alternate.initialize()
            await connection.execute(
                "CREATE TABLE ralf_temporal_runner_metadata(singleton INTEGER PRIMARY KEY CHECK(singleton=1),value TEXT NOT NULL)"
            )
            await connection.execute("INSERT INTO ralf_temporal_runner_metadata VALUES(1,'{}')")
            view = adapter()(owner, identity=DEPENDENCIES)
            with monkeypatch.context() as patch:
                if failure == "cancel":
                    from ralf_agent.postgres import _PostgresAdapter

                    original_execute = _PostgresAdapter._execute

                    async def cancelled_metadata_read(self, statement, parameters=(), **kwargs):
                        if statement.startswith("SELECT value FROM ralf_temporal_runner_metadata"):
                            raise asyncio.CancelledError
                        return await original_execute(self, statement, parameters, **kwargs)

                    patch.setattr(_PostgresAdapter, "_execute", cancelled_metadata_read)
                expected = asyncio.CancelledError if failure == "cancel" else DefinitionMismatch
                with pytest.raises(expected):
                    await view.initialize()
            await connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schemas[0]))
            )
            assert (await owner.begin(value))["execute"] is False
            assert owner._table_schemas == original_routing
            with pytest.raises(DefinitionMismatch):
                _ = view.identity
        finally:
            for schema in schemas:
                await connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
            await connection.close()

    asyncio.run(scenario())


def test_real_pg_original_effect_classification_cannot_drift(postgres_dsn):
    async def scenario():
        async with journals(postgres_dsn) as (views, _, connections, _):
            value = envelope()
            original = binding(value)
            await views[0].begin(SCOPE, "effect", original, envelope=value)
            await connections[0].execute("UPDATE ralf_temporal_effects SET effect='read_only'")
            with pytest.raises(DefinitionMismatch):
                await views[1].mark_thread_submitted(SCOPE, "effect", binding=original)

    asyncio.run(scenario())
