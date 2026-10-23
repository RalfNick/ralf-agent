"""Actual original sealed Run/PG maintenance, effects and cold SDK replay."""

import asyncio
import json
import os
import uuid

import pytest

from relf_agent import AgentSpec, ToolExecutionOwner, ToolRegistry, ToolSpec, WorkflowSpec
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.temporal_journal import PostgresEffectJournal
from relf_agent.types import canonical
from tests.test_a2a_temporal_http_service import HTTPProvider
from tests.test_temporal_deployment_public_service import public_system

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires actual Temporal and PostgreSQL",
)


@pytest.mark.parametrize("kind", ["agent", "sequence"])
def test_actual_seal_gates_compaction_and_original_sdk_cold_receipts(tmp_path, kind):
    async def run():
        from psycopg import AsyncConnection, sql
        from psycopg.conninfo import make_conninfo

        schema = "ralf_retention_live_" + uuid.uuid4().hex
        owner = await AsyncConnection.connect(os.environ["RALF_TEST_POSTGRES_DSN"], autocommit=True)
        journal = business = None
        verified = False
        try:
            await owner.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            dsn = make_conninfo(
                os.environ["RALF_TEST_POSTGRES_DSN"], options="-csearch_path=" + schema
            )
            journal = await PostgresEffectJournal.connect(dsn, backend_id=schema)
            await journal.initialize()
            business = await AsyncConnection.connect(dsn, autocommit=True)
            await business.execute(
                "CREATE TABLE business (effect_key TEXT PRIMARY KEY,result TEXT NOT NULL,calls INT NOT NULL)"
            )

            async def write(arguments, context):
                result = {"effect_key": context.effect_key, "body": "receipt-你好" * 100}
                await business.execute(
                    "INSERT INTO business VALUES (%s,%s,1) ON CONFLICT(effect_key) DO UPDATE SET calls=business.calls+1",
                    (context.effect_key, canonical(result)),
                )
                if kind == "sequence":
                    raise ConnectionError("response lost after the original business commit")
                return result

            tools = ToolRegistry()
            tools.register(
                ToolSpec(
                    "write",
                    "Write once",
                    {"type": "object"},
                    effect="unqueryable_write",
                    requires_approval=True,
                ),
                write,
            )
            options = {
                "providers": {"default": HTTPProvider()},
                "tools": tools,
                "journal": journal,
                "tool_execution": ToolExecutionOwner(version="retention-tool-v1"),
            }
            async with public_system(tmp_path, options=options) as system:
                agent = AgentSpec("writer", "Write once", ("write",))
                spec = agent if kind == "agent" else WorkflowSpec("sequence", (agent, agent))
                controls = []
                async with system.worker():
                    handle = await system.engine.submit(
                        spec, "request", command_id="original", budget=64
                    )
                    system.targets.add(handle.run_id)
                    while True:
                        snapshot = await system.status(
                            handle.run_id,
                            {"waiting_approval", "waiting_reconciliation", "succeeded"},
                        )
                        if snapshot.state == "succeeded":
                            break
                        before = await (
                            await journal.connection.execute(
                                "SELECT * FROM ralf_temporal_effect_evidence ORDER BY effect_key"
                            )
                        ).fetchall()
                        with pytest.raises((DefinitionMismatch, ValidationError)):
                            await system.engine.compact_effect_evidence(
                                handle.run_id, runtime=system.runtime
                            )
                        assert (
                            await (
                                await journal.connection.execute(
                                    "SELECT * FROM ralf_temporal_effect_evidence ORDER BY effect_key"
                                )
                            ).fetchall()
                            == before
                        )
                        action = next(
                            a
                            for a in snapshot.actions
                            if a["kind"] == "tool"
                            and a["status"] in {"waiting_approval", "outcome_unknown"}
                        )
                        command_id = snapshot.state + ":" + action["id"]
                        if snapshot.state == "waiting_approval":
                            receipt = await system.engine.approve(
                                handle.run_id, action["id"], action["digest"], command_id=command_id
                            )
                            controls.append(("approve", action, None, receipt))
                        else:
                            row = await (
                                await business.execute(
                                    "SELECT result FROM business WHERE effect_key=%s",
                                    (action["effect_key"],),
                                )
                            ).fetchone()
                            result = json.loads(row[0])
                            receipt = await system.engine.reconcile(
                                handle.run_id, action["id"], result, command_id=command_id
                            )
                            controls.append(("reconcile", action, result, receipt))
                        await system.engine.drive(handle.run_id, wait_seconds=0)
                    await system.count(0)
                    await system.evidence(handle.run_id)
                    main = await (
                        await journal.connection.execute(
                            "SELECT * FROM ralf_temporal_effects ORDER BY effect_key"
                        )
                    ).fetchall()
                    history_before = (
                        await system.client.get_workflow_handle(handle.run_id).fetch_history()
                    ).to_json()
                    from relf_agent import temporal_session_activities

                    # Complete the real SQL DELETE, then observe the original
                    # actual namespace and inject an inconsistent UUID. The
                    # per-Action transaction must roll back before any commit.
                    evidence_before = await (
                        await journal.connection.execute(
                            "SELECT * FROM ralf_temporal_effect_evidence ORDER BY effect_key"
                        )
                    ).fetchall()
                    execute = journal._execute
                    namespace_id = temporal_session_activities.namespace_id
                    deleted = namespace_rechecked = False

                    async def observed_execute(statement, *args, **kwargs):
                        nonlocal deleted
                        value = await execute(statement, *args, **kwargs)
                        if "DELETE FROM ralf_temporal_effect_evidence" in str(statement):
                            deleted = True
                        return value

                    async def changed_namespace(client):
                        nonlocal namespace_rechecked
                        actual = await namespace_id(client)
                        if deleted:
                            namespace_rechecked = True
                            return str(uuid.uuid5(uuid.NAMESPACE_OID, actual))
                        return actual

                    with pytest.MonkeyPatch.context() as patch:
                        patch.setattr(journal, "_execute", observed_execute)
                        patch.setattr(
                            temporal_session_activities, "namespace_id", changed_namespace
                        )
                        with pytest.raises(DefinitionMismatch):
                            await system.engine.compact_effect_evidence(
                                handle.run_id, runtime=system.runtime
                            )
                    assert deleted and namespace_rechecked
                    assert (
                        await (
                            await journal.connection.execute(
                                "SELECT * FROM ralf_temporal_effect_evidence ORDER BY effect_key"
                            )
                        ).fetchall()
                        == evidence_before
                    )
                    cursor, removed, pages = None, 0, []
                    while True:
                        page = await system.engine.compact_effect_evidence(
                            handle.run_id, runtime=system.runtime, limit=1, after_effect_key=cursor
                        )
                        pages.append(page)
                        removed += page["removed_records"]
                        cursor = page["next_after_effect_key"]
                        if cursor is None:
                            break
                    expected = 1 if kind == "agent" else 2
                    assert removed == expected
                    assert (
                        await (
                            await journal.connection.execute(
                                "SELECT * FROM ralf_temporal_effect_evidence"
                            )
                        ).fetchall()
                        == []
                    )
                    assert (
                        await (
                            await journal.connection.execute(
                                "SELECT * FROM ralf_temporal_effects ORDER BY effect_key"
                            )
                        ).fetchall()
                        == main
                    )
                    assert (
                        await system.client.get_workflow_handle(handle.run_id).fetch_history()
                    ).to_json() == history_before
                    cold = system.facade()
                    assert (
                        await cold.submit(spec, "request", command_id="original", budget=64)
                    ).run_id == handle.run_id
                    for method, action, result, receipt in controls:
                        if method == "approve":
                            repeat = await cold.approve(
                                handle.run_id,
                                action["id"],
                                action["digest"],
                                command_id=receipt.command_id,
                            )
                        else:
                            repeat = await cold.reconcile(
                                handle.run_id, action["id"], result, command_id=receipt.command_id
                            )
                        assert repeat == receipt
                    assert (await cold.drive(handle.run_id)).state == "succeeded"
                    assert (
                        await cold.compact_effect_evidence(handle.run_id, runtime=system.runtime)
                    )["removed_records"] == 0
                    assert (
                        await (
                            await business.execute("SELECT calls FROM business ORDER BY effect_key")
                        ).fetchall()
                        == [(1,)] * expected
                    )
                    assert await system.evidence(handle.run_id) == 1
                    (tmp_path / "retention-result.json").write_text(
                        json.dumps(
                            {
                                "kind": kind,
                                "removed_records": removed,
                                "pages": pages,
                                "main_receipts_unchanged": True,
                                "history_unchanged_by_compaction": True,
                                "namespace_mismatch_before_commit_rolled_back": True,
                                "cold_receipts_replayed": True,
                                "calls_per_effect": 1,
                                "model_api_calls": 0,
                            }
                        )
                    )
            verified = True
        finally:
            if journal is not None:
                await journal.aclose()
            if business is not None:
                await business.close()
            if verified:
                await owner.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )
            await owner.close()
            (tmp_path / "retention-cleanup.json").write_text(
                json.dumps(
                    {
                        "owned_schema": schema,
                        "removed_after_original_proofs": verified,
                        "retained_on_failure": not verified,
                    }
                )
            )

    asyncio.run(asyncio.wait_for(run(), 180))
