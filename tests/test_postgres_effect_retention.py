"""Actual PostgreSQL duplicate-receipt compaction; no SQL state simulator."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import pytest

from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.executors import DispatchEnvelope, EffectObservation
from relf_agent.postgres import _advisory_key
from relf_agent.temporal_journal import PostgresEffectJournal
from relf_agent.types import InvocationContext, Scope, canonical, digest

SCOPE = Scope("effect-retention", "alice")
TABLES = ("ralf_temporal_effects", "ralf_temporal_effect_evidence")


@pytest.fixture
def postgres_dsn():
    dsn = os.getenv("RALF_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("requires actual PostgreSQL via RALF_TEST_POSTGRES_DSN")
    pytest.importorskip("psycopg")
    return dsn


@asynccontextmanager
async def journals(dsn):
    from psycopg import AsyncConnection, sql

    schema = "ralf_effect_retention_" + uuid.uuid4().hex
    connections, effects = [], []
    owner = await AsyncConnection.connect(dsn, autocommit=True)
    try:
        await owner.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for _ in range(2):
            connection = await AsyncConnection.connect(dsn, autocommit=True)
            connections.append(connection)
            await connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
            )
            effect = PostgresEffectJournal(connection, backend_id=schema)
            effects.append(effect)
            await effect.initialize()
        yield effects, connections, owner, schema
    finally:
        for effect in effects:
            await effect.aclose()
        for connection in connections:
            await connection.close()
        # Only this UUID schema's synthetic Journal rows exist here: no actual
        # Workflow, business handler, quota or recovery obligations are created.
        await owner.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )
        await owner.close()


def envelope(key="a", *, scope=SCOPE, run_id="original-run"):
    return DispatchEnvelope(
        InvocationContext(scope, run_id, "action:" + key, "attempt:" + key, key, "original-epoch"),
        {"name": "write", "effect": "unqueryable_write"},
        {"target": key},
        "operation:" + key,
    )


async def seed(journal, value, *, state="adopted"):
    observation = EffectObservation(
        {"private": "receipt-secret-你好", "key": value.context.effect_key}
    )
    assert await journal.begin(value) == {"execute": True}
    if state != "dispatched":
        await journal.received(value, observation)
    if state == "adopted":
        await journal.acknowledge(value, observation)
    return observation


async def rows(connection, schema, table):
    from psycopg import sql

    return await (
        await connection.execute(
            sql.SQL("SELECT * FROM {}.{} ORDER BY workspace,principal,effect_key").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        )
    ).fetchall()


def verify():
    return None


async def compact(journal, **kwargs):
    return await journal._compact_adopted_evidence(SCOPE, "original-run", verify=verify, **kwargs)


def test_real_pg_removes_only_duplicate_payload_and_original_receipt_still_replays(postgres_dsn):
    async def run():
        async with journals(postgres_dsn) as (effects, connections, _, schema):
            first, replacement = effects
            value = envelope()
            observation = await seed(first, value)
            main = await rows(connections[0], schema, TABLES[0])
            result = await compact(first)
            assert result == {
                "scanned_records": 1,
                "removed_records": 1,
                "removed_payload_bytes": len(canonical(observation.result).encode("utf-8")),
                "next_after_effect_key": None,
            }
            assert await rows(connections[0], schema, TABLES[0]) == main
            assert await rows(connections[0], schema, TABLES[1]) == []
            replay = await replacement.begin(value)
            assert replay["execute"] is False
            assert replay["observation"].result == observation.result
            assert replay["observation"].source == observation.source
            assert (await replacement.observation(value)).result == observation.result
            # A late original ACK may recreate the same redundant copy; it must
            # neither redispatch nor erase the immutable adopted primary row.
            await replacement.acknowledge(value, observation)
            assert len(await rows(connections[0], schema, TABLES[1])) == 1
            assert (await compact(first))["removed_records"] == 1
            assert await rows(connections[0], schema, TABLES[0]) == main
            assert (await replacement.begin(value))["execute"] is False

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        "dispatched",
        "received",
        "bad-main-digest",
        "bad-evidence-digest",
        "different-source",
        "different-result",
        "different-bytes",
    ],
)
def test_real_pg_unadopted_or_nonidentical_evidence_is_retained(postgres_dsn, fault):
    async def run():
        async with journals(postgres_dsn) as (effects, connections, _, schema):
            journal = effects[0]
            observation = await seed(
                journal,
                envelope(),
                state=fault if fault in {"dispatched", "received"} else "adopted",
            )
            if fault == "bad-main-digest":
                await connections[0].execute(
                    "UPDATE ralf_temporal_effects SET adopted_result_digest=%s", ("0" * 64,)
                )
            elif fault == "bad-evidence-digest":
                await connections[0].execute(
                    "UPDATE ralf_temporal_effect_evidence SET evidence_digest=%s", ("0" * 64,)
                )
            elif fault == "different-source":
                await connections[0].execute(
                    "UPDATE ralf_temporal_effect_evidence SET source=%s,evidence_digest=%s",
                    ("another-source", digest(["another-source", observation.result])),
                )
            elif fault == "different-result":
                changed = {"private": "conflicting-real-result"}
                await connections[0].execute(
                    "UPDATE ralf_temporal_effect_evidence SET result=%s,evidence_digest=%s",
                    (canonical(changed), digest([observation.source, changed])),
                )
            elif fault == "different-bytes":
                await connections[0].execute(
                    "UPDATE ralf_temporal_effect_evidence SET result=%s",
                    (" " + canonical(observation.result),),
                )
            before = [await rows(connections[0], schema, table) for table in TABLES]
            result = await compact(journal, limit=1)
            assert result["removed_records"] == result["removed_payload_bytes"] == 0
            assert result["scanned_records"] == (0 if fault in {"dispatched", "received"} else 1)
            if result["next_after_effect_key"] is not None:
                assert result["next_after_effect_key"] == "a"
                assert (await compact(journal, after_effect_key="a"))["scanned_records"] == 0
            assert [await rows(connections[0], schema, table) for table in TABLES] == before

    asyncio.run(run())


def test_real_pg_conflict_and_other_scope_and_run_survive_bounded_pages(postgres_dsn):
    async def run():
        async with journals(postgres_dsn) as (effects, connections, _, schema):
            journal = effects[0]
            for key in ("c", "a", "b"):
                await seed(journal, envelope(key))
            foreign_scope = envelope("a", scope=Scope(SCOPE.workspace, "bob"))
            foreign_run = envelope("z", run_id="another-run")
            await seed(journal, foreign_scope)
            await seed(journal, foreign_run)
            await journal.received(envelope("a"), EffectObservation({"conflict": True}))
            await journal.received(envelope("b"), EffectObservation({"key": "b"}, "another-source"))
            main = await rows(connections[0], schema, TABLES[0])
            before = await rows(connections[0], schema, TABLES[1])
            cursor, scanned, removed, visited = None, 0, 0, []
            for _ in range(4):
                page = await compact(journal, limit=1, after_effect_key=cursor)
                assert 0 <= page["scanned_records"] <= 1
                scanned += page["scanned_records"]
                removed += page["removed_records"]
                following = page["next_after_effect_key"]
                if following is None:
                    break
                assert cursor is None or following > cursor
                visited.append(following)
                cursor = following
            else:
                pytest.fail("bounded three-row scan did not terminate")
            assert scanned == removed == 3
            assert visited[:2] == ["a", "b"]
            assert await rows(connections[0], schema, TABLES[0]) == main
            remaining = await rows(connections[0], schema, TABLES[1])
            assert len(remaining) == 4
            assert all(row in before for row in remaining)
            assert {row[:3] for row in remaining} == {
                (SCOPE.workspace, "bob", "a"),
                (SCOPE.workspace, SCOPE.principal, "z"),
                (SCOPE.workspace, SCOPE.principal, "a"),
                (SCOPE.workspace, SCOPE.principal, "b"),
            }
            assert (await compact(journal))["removed_records"] == 0

    asyncio.run(run())


def test_real_pg_original_schema_is_fixed_despite_search_path_change(postgres_dsn):
    async def run():
        from psycopg import sql

        async with journals(postgres_dsn) as (effects, connections, owner, schema):
            original = effects[0]
            await seed(original, envelope())
            decoy_schema = "ralf_effect_decoy_" + uuid.uuid4().hex
            await owner.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(decoy_schema)))
            try:
                await connections[1].execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(decoy_schema))
                )
                decoy = PostgresEffectJournal(connections[1], backend_id="decoy")
                await decoy.initialize()
                await seed(decoy, envelope())
                await connections[0].execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(decoy_schema))
                )
                main = await rows(owner, schema, TABLES[0])
                untouched = [await rows(owner, decoy_schema, table) for table in TABLES]
                assert (await compact(original))["removed_records"] == 1
                assert await rows(owner, schema, TABLES[1]) == []
                assert await rows(owner, schema, TABLES[0]) == main
                assert [await rows(owner, decoy_schema, table) for table in TABLES] == untouched
                assert (await original.begin(envelope()))["execute"] is False
                await decoy.aclose()
            finally:
                await owner.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(decoy_schema))
                )

    asyncio.run(run())


def test_real_pg_verify_failure_after_actual_delete_rolls_back(postgres_dsn, monkeypatch):
    async def run():
        async with journals(postgres_dsn) as (effects, connections, _, schema):
            journal = effects[0]
            await seed(journal, envelope())
            before = [await rows(connections[1], schema, table) for table in TABLES]
            execute, deleted = journal._execute, False

            async def observed_execute(statement, *args, **kwargs):
                nonlocal deleted
                result = await execute(statement, *args, **kwargs)
                if "DELETE FROM ralf_temporal_effect_evidence" in str(statement):
                    deleted = True
                return result

            def recheck():
                if deleted:
                    raise DefinitionMismatch("original binding changed before commit")

            # Observe completed real I/O without replacing SQL, results or transactions.
            monkeypatch.setattr(journal, "_execute", observed_execute)
            with pytest.raises(DefinitionMismatch):
                await journal._compact_adopted_evidence(SCOPE, "original-run", verify=recheck)
            assert [await rows(connections[1], schema, table) for table in TABLES] == before

    asyncio.run(run())


def test_real_pg_async_namespace_failure_before_commit_rolls_back(postgres_dsn):
    async def run():
        async with journals(postgres_dsn) as (effects, connections, _, schema):
            journal = effects[0]
            await seed(journal, envelope())
            before = [await rows(connections[1], schema, table) for table in TABLES]
            checked = False

            async def namespace_check():
                nonlocal checked
                # The actual DELETE is visible inside this uncommitted transaction.
                assert await rows(connections[0], schema, TABLES[1]) == []
                checked = True
                raise DefinitionMismatch("namespace UUID changed before commit")

            with pytest.raises(DefinitionMismatch):
                await compact(journal, namespace_check=namespace_check)
            assert checked
            assert [await rows(connections[1], schema, table) for table in TABLES] == before

    asyncio.run(run())


async def waiting_on_advisory(owner, connection):
    async with asyncio.timeout(3):
        while True:
            waiting = await (
                await owner.execute(
                    "SELECT 1 FROM pg_locks WHERE pid=%s AND locktype='advisory' AND NOT granted",
                    (connection.info.backend_pid,),
                )
            ).fetchone()
            if waiting:
                return
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("drift", [False, True], ids=["serialized", "verify-drift"])
def test_real_pg_original_target_lock_serializes_independent_journals(postgres_dsn, drift):
    async def run():
        async with journals(postgres_dsn) as (effects, connections, owner, schema):
            await seed(effects[0], envelope())
            before = [await rows(owner, schema, table) for table in TABLES]
            changed = False

            def recheck():
                if changed:
                    raise DefinitionMismatch("binding drift while awaiting original target lock")

            target = digest({"tool": "write", "arguments": {"target": "a"}})
            task = None
            try:
                async with connections[0].transaction():
                    await connections[0].execute(
                        "SELECT pg_advisory_xact_lock(%s)",
                        (
                            _advisory_key(
                                ("temporal-effects", SCOPE.workspace, SCOPE.principal, target)
                            ),
                        ),
                    )
                    task = asyncio.create_task(
                        effects[1]._compact_adopted_evidence(
                            SCOPE,
                            "original-run",
                            verify=recheck,
                        )
                    )
                    await waiting_on_advisory(owner, connections[1])
                    assert [await rows(owner, schema, table) for table in TABLES] == before
                    changed = drift
                if drift:
                    with pytest.raises(DefinitionMismatch):
                        await task
                    assert [await rows(owner, schema, table) for table in TABLES] == before
                else:
                    assert (await task)["removed_records"] == 1
                    assert await rows(owner, schema, TABLES[0]) == before[0]
                    assert await rows(owner, schema, TABLES[1]) == []
            finally:
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("limit", [0, -1, True, 1001])
def test_real_pg_invalid_limit_preserves_original_rows(postgres_dsn, limit):
    async def run():
        async with journals(postgres_dsn) as (effects, connections, _, schema):
            await seed(effects[0], envelope())
            before = [await rows(connections[0], schema, table) for table in TABLES]
            with pytest.raises(ValidationError):
                await compact(effects[0], limit=limit)
            assert [await rows(connections[0], schema, table) for table in TABLES] == before

    asyncio.run(run())


@pytest.mark.parametrize("unavailable", ["uninitialized", "closed"])
def test_real_pg_unbound_or_closed_journal_cannot_delete(postgres_dsn, unavailable):
    async def run():
        async with journals(postgres_dsn) as (effects, connections, owner, schema):
            await seed(effects[0], envelope())
            before = [await rows(owner, schema, table) for table in TABLES]
            if unavailable == "uninitialized":
                selected = PostgresEffectJournal(connections[0], backend_id=schema)
            else:
                selected = effects[0]
                await selected.aclose()
            with pytest.raises(ValidationError):
                await compact(selected)
            assert [await rows(owner, schema, table) for table in TABLES] == before

    asyncio.run(run())
