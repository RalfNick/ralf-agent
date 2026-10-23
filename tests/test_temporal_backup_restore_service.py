"""Opt-in real offline Temporal/PG backup to new directories and empty databases."""

import asyncio
import copy
import json
import os
import uuid
from dataclasses import asdict
from datetime import timedelta

import pytest

from relf_agent import (
    AgentSpec,
    ModelResponse,
    Scope,
    ToolCall,
    ToolExecutionOwner,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.governance import DeploymentAdmissionPolicy
from relf_agent.temporal import TemporalEngine, build_temporal_worker, replay_temporal_history
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_deployment_admission import registry_id
from relf_agent.temporal_deployment_release import check_owner, close_owner
from relf_agent.temporal_journal import PostgresEffectJournal
from relf_agent.types import canonical, digest
from tests.temporal_backup_restore_fixture import OwnedServices, write_private

pytestmark = pytest.mark.skipif(
    os.getenv("RALF_TEST_BACKUP_OWNED_SERVICES") != "1",
    reason="requires explicit ownership of new real Temporal and PG backup services",
)


class Provider:
    identity = {"kind": "backup-restore-offline-provider", "version": "1"}

    async def complete(self, messages, tools):
        if messages[-1]["role"] == "tool":
            return ModelResponse(output=json.loads(messages[-1]["content"]))
        return ModelResponse(tool_calls=(ToolCall("write", {}, "original-write"),))


class Business:
    """Owned fixture business only; production external effects must not roll back."""

    def __init__(self, connection):
        self.connection = connection

    async def write(self, arguments, context):
        result = {"changed": True, "effect_key": context.effect_key, "business_id": "original"}
        await self.connection.execute(
            "INSERT INTO business_store.effects VALUES (%s,%s,1) ON CONFLICT(effect_key) "
            "DO UPDATE SET calls=business_store.effects.calls+1",
            (context.effect_key, canonical(result)),
        )
        raise ConnectionError("genuine committed owned business response loss")

    async def rows(self):
        return await (
            await self.connection.execute(
                "SELECT * FROM business_store.effects ORDER BY effect_key"
            )
        ).fetchall()


class Stage:
    def __init__(self):
        self.worker = self.engine = self.runtime = self.journal = self.business = (
            self.tool_owner
        ) = None
        self.entered_worker = False
        self.directory = None
        self.database = None

    async def open(self, services, database, policy, scope, queue, *, initialize=False):
        from psycopg import AsyncConnection
        from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
        from temporalio.client import Client

        self.directory, self.database = services.directory, database
        self.client = await Client.connect(services.address)
        response = await self.client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace="default")
        )
        self.namespace = {"name": "default", "id": response.namespace_info.id}
        connection = await AsyncConnection.connect(services.dsn(database), autocommit=True)
        self.business = Business(connection)
        if initialize:
            await connection.execute("CREATE SCHEMA effect_store")
            await connection.execute("CREATE SCHEMA business_store")
            await connection.execute(
                "CREATE TABLE business_store.effects(effect_key TEXT PRIMARY KEY,result TEXT NOT NULL,calls INT NOT NULL)"
            )
        self.journal = await PostgresEffectJournal.connect(
            services.dsn(database, schema="effect_store"),
            backend_id=policy.deployment_id + "-effects",
        )
        await self.journal.initialize()
        if initialize:
            # Nondefault owner ACLs survive pg_dump normalization. These revoke
            # rights only; the owned test superuser can still initialize and run.
            await connection.execute("GRANT USAGE ON SCHEMA effect_store,business_store TO ralf")
            await connection.execute(
                "GRANT SELECT ON business_store.effects,effect_store.ralf_temporal_effects,"
                "effect_store.ralf_temporal_effect_evidence TO ralf"
            )
            await connection.execute(
                "REVOKE CREATE ON SCHEMA effect_store,business_store FROM ralf"
            )
            await connection.execute(
                "REVOKE TRUNCATE ON business_store.effects,effect_store.ralf_temporal_effects,"
                "effect_store.ralf_temporal_effect_evidence FROM ralf"
            )
        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "write",
                "One owned business write",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            self.business.write,
        )
        self.tool_owner = ToolExecutionOwner(version="backup-original-1")
        self.runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=tools,
            journal=self.journal,
            tool_execution=self.tool_owner,
            admission_policy=policy,
        )
        self.engine = TemporalEngine(
            self.client,
            task_queue=queue,
            release=self.runtime.orchestration_release,
            scope=scope,
            activity_timeout=5,
            drive_timeout=30,
        )
        self.worker = build_temporal_worker(
            self.client,
            task_queue=queue,
            runtime=self.runtime,
            release=self.runtime.orchestration_release,
            graceful_shutdown_timeout=timedelta(seconds=1),
            max_concurrent_activities=16,
        )
        await self.worker.__aenter__()
        self.entered_worker = True
        return self

    async def close(self):
        errors = []
        deployment_drained = tool_drained = False
        try:
            if self.runtime is not None:
                owner = check_owner(self.runtime)
                deployment_drained = owner is not None and await owner.wait(wait_timeout=20)
                assert deployment_drained
            if self.tool_owner is not None:
                tool_drained = await self.tool_owner.wait(wait_timeout=20)
                assert tool_drained
        except BaseException as exc:
            errors.append(exc)
        try:
            if self.entered_worker:
                await self.worker.__aexit__(None, None, None)
                self.entered_worker = False
        except BaseException as exc:
            errors.append(exc)
        operations = []
        if self.runtime is not None and deployment_drained:
            operations.append(lambda: close_owner(self.runtime, wait_timeout=20))
        if self.tool_owner is not None:
            operations.append(self.tool_owner.aclose)
        if self.engine is not None:
            operations.append(self.engine.aclose)
        if self.journal is not None:
            operations.append(self.journal.aclose)
        if self.business is not None:
            operations.append(self.business.connection.close)
        for operation in operations:
            try:
                await operation()
            except BaseException as exc:
                errors.append(exc)
        worker_shutdown = (
            self.worker is not None and self.worker.is_shutdown and not self.worker.is_running
        )
        if self.directory is not None:
            write_private(
                self.directory / (self.database + "-worker-closed.json"),
                json.dumps(
                    {
                        "actual_deployment_calls_drained": deployment_drained,
                        "actual_tool_calls_drained": tool_drained,
                        "worker_shutdown": worker_shutdown,
                        "engine_closed": self.engine is not None and self.engine._closed,
                        "journal_closed": self.journal is not None and self.journal._closed,
                        "business_connection_closed": self.business is not None
                        and self.business.connection.closed,
                        "errors": [type(error).__name__ for error in errors],
                    }
                ),
            )
        if errors:
            raise BaseExceptionGroup("Owned backup Worker cleanup failed", errors)
        assert worker_shutdown


async def wait_state(engine, run_id, state):
    async with asyncio.timeout(40):
        while True:
            snapshot = await engine.status(run_id)
            if snapshot.state == state:
                return snapshot
            await asyncio.sleep(0.05)


async def frozen(stage, run_id):
    schema_privileges = await (
        await stage.business.connection.execute(
            "SELECT nspname,pg_get_userbyid(nspowner),nspacl::text FROM pg_namespace "
            "WHERE nspname IN ('effect_store','business_store') ORDER BY nspname"
        )
    ).fetchall()
    table_privileges = await (
        await stage.business.connection.execute(
            "SELECT n.nspname,c.relname,pg_get_userbyid(c.relowner),c.relacl::text "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('effect_store','business_store') AND c.relkind IN ('r','p') "
            "ORDER BY n.nspname,c.relname"
        )
    ).fetchall()
    assert len(schema_privileges) == 2 and all(
        row[1] == "ralf" and row[2] for row in schema_privileges
    )
    assert len(table_privileges) == 3 and all(
        row[2] == "ralf" and row[3] for row in table_privileges
    )
    return {
        "schema_owner_acl": schema_privileges,
        "table_owner_acl": table_privileges,
        "status": asdict(await stage.engine.status(run_id)),
        "events": [asdict(event) for event in await stage.engine.events(run_id)],
        "business": await stage.business.rows(),
        "effects": await (
            await stage.journal.connection.execute(
                "SELECT * FROM effect_store.ralf_temporal_effects ORDER BY effect_key"
            )
        ).fetchall(),
        "effect_evidence": await (
            await stage.journal.connection.execute(
                "SELECT * FROM effect_store.ralf_temporal_effect_evidence ORDER BY effect_key,evidence_digest"
            )
        ).fetchall(),
    }


async def same_identity(stage, original, run_id, expected):
    assert stage.namespace == original["namespace"]
    assert stage.engine.scope == Scope(**original["scope"])
    assert stage.engine.task_queue == original["queue"]
    assert canonical(stage.engine.release) == canonical(original["release"])
    assert (await stage.client.get_workflow_handle(run_id).describe()).run_id == original["epoch"]
    assert await frozen(stage, run_id) == expected
    assert (await stage.engine.deployment_diagnostics())["counts"]["held_root_runs"] == 1


def test_real_owned_temporal_and_pg_restore_approval_then_unknown_without_repeat_effect(tmp_path):
    async def run():
        services = OwnedServices(tmp_path)
        stage = None
        verified = False
        receipts = {}
        queue = "backup-restore-" + uuid.uuid4().hex
        policy = DeploymentAdmissionPolicy(queue, max_active_root_runs=1)
        scope = Scope("backup-owned", queue)
        spec, request = AgentSpec("writer", "Write once", ("write",)), {"business_id": "original"}
        try:
            await services.start_pg()
            await services.start_temporal("stage0")
            stage = Stage()
            await stage.open(services, "stage0", policy, scope, queue, initialize=True)
            handle = await stage.engine.submit(
                spec, request, command_id="original-submit", budget=32
            )
            run_id = handle.run_id
            waiting = await wait_state(stage.engine, run_id, "waiting_approval")
            assert await stage.business.rows() == []
            target = waiting.pending[0]
            original = {
                "namespace": stage.namespace,
                "scope": asdict(scope),
                "queue": queue,
                "policy": policy.identity,
                "release": stage.engine.release,
                "epoch": (await stage.client.get_workflow_handle(run_id).describe()).run_id,
                "run_id": run_id,
                "submit_receipt": asdict(handle.receipt),
            }
            assert await check_owner(stage.runtime).wait(wait_timeout=20)
            assert await stage.tool_owner.wait(wait_timeout=20)
            expected = await frozen(stage, run_id)
            write_private(tmp_path / "original-identity.json", json.dumps(original))
            write_private(tmp_path / "approval-before.json", json.dumps(expected))
            await stage.close()
            stage = None
            first_backup = await services.backup("stage0", "approval-backup")
            await services.restore_pg(first_backup, "stage1")
            await services.start_temporal("stage1", restore=first_backup)
            stage = Stage()
            await stage.open(services, "stage1", policy, scope, queue)
            await same_identity(stage, original, run_id, expected)
            assert (
                await stage.engine.submit(spec, request, command_id="original-submit", budget=32)
                == handle
            )

            # A mismatched deployment policy is a real recovery call against the
            # restored authority, not an incompatible Worker executing business.
            bad_release = copy.deepcopy(stage.engine.release)
            bad_release["deployment_admission_protocol"]["policy"] = DeploymentAdmissionPolicy(
                queue, max_active_root_runs=2
            ).identity
            with pytest.raises(DefinitionMismatch):
                build_temporal_worker(
                    stage.client, task_queue=queue, runtime=stage.runtime, release=bad_release
                )
            wrong = TemporalEngine(stage.client, task_queue=queue, release=bad_release, scope=scope)
            history_before = (
                await stage.client.get_workflow_handle(run_id).fetch_history()
            ).to_json()
            try:
                with pytest.raises((DefinitionMismatch, ValidationError)):
                    await wrong.drive(run_id, wait_seconds=0)
            finally:
                await wrong.aclose()
            assert await frozen(stage, run_id) == expected
            assert (
                await stage.client.get_workflow_handle(run_id).fetch_history()
            ).to_json() == history_before
            write_private(
                tmp_path / "upgrade-refusal.json",
                json.dumps(
                    {
                        "worker_constructor_refused": True,
                        "restored_original_run_refused_wrong_policy": True,
                        "original_run_history_unchanged": True,
                        "business_writes": 0,
                        "rollback": "original immutable release and one-root policy",
                    }
                ),
            )
            approval = await stage.engine.approve(
                run_id, target["action_id"], target["digest"], command_id="original-approve"
            )
            assert (
                await stage.engine.approve(
                    run_id, target["action_id"], target["digest"], command_id="original-approve"
                )
                == approval
            )
            unknown = await wait_state(stage.engine, run_id, "waiting_reconciliation")
            rows = await stage.business.rows()
            assert len(rows) == 1 and rows[0][2] == 1
            action = next(item for item in unknown.actions if item["kind"] == "tool")
            assert action["status"] == "outcome_unknown"
            assert (await stage.engine.deployment_diagnostics())["counts"]["held_root_runs"] == 1
            assert await check_owner(stage.runtime).wait(wait_timeout=20)
            assert await stage.tool_owner.wait(wait_timeout=20)
            expected_unknown = await frozen(stage, run_id)
            write_private(tmp_path / "unknown-before.json", json.dumps(expected_unknown))
            receipts["approve"] = asdict(approval)
            await stage.close()
            stage = None
            second_backup = await services.backup("stage1", "unknown-backup")
            await services.restore_pg(second_backup, "stage2")
            await services.start_temporal("stage2", restore=second_backup)
            stage = Stage()
            await stage.open(services, "stage2", policy, scope, queue)
            await same_identity(stage, original, run_id, expected_unknown)
            assert (
                await stage.engine.submit(spec, request, command_id="original-submit", budget=32)
                == handle
            )
            assert (
                await stage.engine.approve(
                    run_id, target["action_id"], target["digest"], command_id="original-approve"
                )
                == approval
            )
            await stage.engine.drive(run_id, wait_seconds=0)
            assert (await stage.engine.status(run_id)).state == "waiting_reconciliation"
            assert await stage.business.rows() == rows
            genuine = json.loads(rows[0][1])
            assert genuine["effect_key"] == action["effect_key"]
            receipt = await stage.engine.reconcile(
                run_id, action["id"], genuine, command_id="original-reconcile"
            )
            assert (
                await stage.engine.reconcile(
                    run_id, action["id"], genuine, command_id="original-reconcile"
                )
                == receipt
            )
            receipts["reconcile"] = asdict(receipt)
            await wait_state(stage.engine, run_id, "succeeded")
            async with asyncio.timeout(40):
                while (await stage.engine.deployment_diagnostics())["counts"]["held_root_runs"]:  # noqa: ASYNC110 -- original remote Registry has no local completion Event
                    await asyncio.sleep(0.05)
            assert await stage.business.rows() == rows
            adopted = await (
                await stage.journal.connection.execute(
                    "SELECT state,adopted_result_digest FROM effect_store.ralf_temporal_effects"
                )
            ).fetchall()
            assert adopted == [("adopted", digest(genuine))]
            closure = await stage.engine._view(run_id, "deployment_closure")
            assert closure["ready"] and closure["seal"] is not None
            assert closure["seal"]["children"] == []
            assert closure["seal"]["scope"] == asdict(scope)
            assert closure["seal"]["execution_epoch"] == original["epoch"]
            for identity, name in (
                (run_id, "original-run"),
                (registry_id(queue), "original-registry"),
            ):
                history = await stage.client.get_workflow_handle(identity).fetch_history()
                await replay_temporal_history(history, namespace=stage.namespace["name"])
                write_private(tmp_path / (name + "-history.json"), history.to_json())
            write_private(
                tmp_path / "restore-result.json",
                json.dumps(
                    {
                        "restores_to_new_database_and_directory": 2,
                        "original_namespace_uuid_and_epoch_retained": True,
                        "approval_and_unknown_restored": True,
                        "unknown_root_held_until_adoption": True,
                        "business_calls": 1,
                        "effect_adopted": True,
                        "root_retired": True,
                        "seal": closure["seal"],
                        "receipts": receipts,
                        "histories_replayed": True,
                        "external_business_rollback_supported": False,
                        "model_api_calls": 0,
                    }
                ),
            )
            await stage.close()
            stage = None
            verified = True
        finally:
            try:
                if stage is not None:
                    await stage.close()
            finally:
                await services.finish(verified=verified)

    asyncio.run(asyncio.wait_for(run(), 300))
