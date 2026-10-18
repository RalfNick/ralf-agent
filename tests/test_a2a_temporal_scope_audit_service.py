"""Actual HTTP/Temporal/PG two-identity recovery, original proofs and audit."""

import asyncio
import json
import os
import signal
import socket
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from ralf_agent import Scope, ToolExecutionOwner, ToolRegistry, ToolSpec
from ralf_agent.a2a import A2AClient
from ralf_agent.temporal import replay_temporal_history
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_journal import PostgresEffectJournal
from ralf_agent.types import canonical
from tests.test_a2a_temporal_http_service import HTTPProvider, wait_task
from tests.test_temporal_deployment_public_service import public_system

pytestmark = pytest.mark.skipif(
    not (os.getenv("RALF_TEST_TEMPORAL_ADDRESS") and os.getenv("RALF_TEST_POSTGRES_DSN")),
    reason="requires actual Temporal and PostgreSQL",
)


@asynccontextmanager
async def http_host(directory):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/rpc"
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "TMPDIR", "RALF_TEST_TEMPORAL_ADDRESS")
        if key in os.environ
    }
    with (directory / f"scope-http-{listener.getsockname()[1]}.log").open("w") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(Path(__file__).with_name("a2a_temporal_scope_audit_http_fixture.py")),
            str(directory),
            str(listener.fileno()),
            pass_fds=(listener.fileno(),),
            env=environment,
            stdout=log,
            stderr=log,
        )
        try:
            async with httpx.AsyncClient(trust_env=False) as readiness:
                async with asyncio.timeout(15):
                    while process.returncode is None:
                        try:
                            response = await readiness.get(
                                url.removesuffix("rpc") + ".well-known/agent-card.json", timeout=0.2
                            )
                            if response.status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        await asyncio.sleep(0.02)
                    else:
                        pytest.fail("owned two-Scope HTTP host startup failed; see local log")
            async with httpx.AsyncClient(trust_env=False) as http:
                clients = {
                    name: A2AClient(url, client=http, headers={"Authorization": "Bearer " + name})
                    for name in ("alice", "bob")
                }
                try:
                    yield clients, http, url, process
                finally:
                    for client in clients.values():
                        await client.aclose()
        finally:
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                process.kill()
                await process.wait()
            listener.close()
        assert process.returncode in (0, -signal.SIGTERM)
        closed = json.loads((directory / f"scope-host-closed-{process.pid}.json").read_text())
        assert closed["engines_closed"] and closed["inbox_closed"]
        assert closed["failures"] == closed["dropped"] == 0


async def effect_rows(journal, business):
    return {
        "effects": await (
            await journal.connection.execute(
                "SELECT * FROM ralf_temporal_effects ORDER BY workspace,principal,effect_key"
            )
        ).fetchall(),
        "evidence": await (
            await journal.connection.execute(
                "SELECT * FROM ralf_temporal_effect_evidence ORDER BY workspace,principal,effect_key,evidence_digest"
            )
        ).fetchall(),
        "business": await (
            await business.execute("SELECT * FROM business ORDER BY effect_key")
        ).fetchall(),
    }


async def finish(client, engine, business, run_id, waiting, *, uncertain):
    if uncertain:
        action = next(a for a in (await engine.status(run_id)).actions if a["kind"] == "tool")
        result = json.loads(
            (
                await (
                    await business.execute(
                        "SELECT result FROM business WHERE effect_key=%s", (action["effect_key"],)
                    )
                ).fetchone()
            )[0]
        )
        receipt = await client.reconcile_task(
            run_id, action["id"], result, command_id="owner-control-secret"
        )
        repeat = await client.reconcile_task(
            run_id, action["id"], result, command_id="owner-control-secret"
        )
    else:
        target = waiting["metadata"]["ralf"]["pending"][0]
        receipt = await client.approve_task(
            run_id, target["action_id"], target["digest"], command_id="owner-control-secret"
        )
        repeat = await client.approve_task(
            run_id, target["action_id"], target["digest"], command_id="owner-control-secret"
        )
    assert receipt == repeat and receipt["receipt"]["apply_state"] == "applied"
    await client.resume_task(run_id)
    await wait_task(client, run_id, "succeeded")
    return receipt


async def save_evidence(system, engine, run_id):
    # Same original public root proof as public_system.evidence, for either Scope.
    view = await engine._view(run_id, "deployment_closure")
    assert view["ready"] and view["seal"] is not None
    proof, certificate = view["deployment"], view["seal"]
    assert proof["scope"] == certificate["scope"] == asdict(engine.scope)
    assert certificate["children"] == []
    assert certificate["request_digest"] == proof["request_digest"]
    assert certificate["manifest_digest"] == proof["manifest_digest"]
    handle = system.client.get_workflow_handle(run_id, run_id=certificate["execution_epoch"])
    assert (await handle.describe()).run_id == certificate["original_execution_epoch"]
    history = await handle.fetch_history()
    await replay_temporal_history(history, namespace=system.namespace["name"])
    (system.directory / (run_id + ".json")).write_text(history.to_json())
    (system.directory / (run_id + "-closure.json")).write_text(json.dumps(view))


@pytest.mark.parametrize("uncertain", [False, True], ids=["approval", "unknown-write"])
def test_actual_temporal_http_scopes_reject_foreign_controls_and_preserve_audited_recovery(
    tmp_path, uncertain
):
    async def run():
        from psycopg import AsyncConnection, sql
        from psycopg.conninfo import make_conninfo

        schema = "ralf_scope_http_" + uuid.uuid4().hex
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
                "CREATE TABLE business(effect_key TEXT PRIMARY KEY,result TEXT NOT NULL,calls INT NOT NULL)"
            )

            async def write(arguments, context):
                result = {
                    "changed": True,
                    "effect_key": context.effect_key,
                    "private": "effect-result-secret",
                }
                await business.execute(
                    "INSERT INTO business VALUES (%s,%s,1) ON CONFLICT(effect_key) DO UPDATE SET calls=business.calls+1",
                    (context.effect_key, canonical(result)),
                )
                if uncertain:
                    raise ConnectionError("genuine commit before response-secret loss")
                return result

            tools = ToolRegistry()
            tools.register(
                ToolSpec(
                    "write",
                    "Write once",
                    {"type": "object"},
                    effect="unqueryable_write",
                    requires_approval=not uncertain,
                ),
                write,
            )
            options = {
                "providers": {"default": HTTPProvider()},
                "tools": tools,
                "journal": journal,
                "tool_execution": ToolExecutionOwner(version="scope-http-temporal-1"),
            }
            async with public_system(tmp_path, options=options) as system:
                scopes = {
                    "alice": system.scope,
                    "bob": Scope(system.scope.workspace, system.scope.principal + "-bob"),
                }
                facades = {"alice": system.engine, "bob": system.facade(scope=scopes["bob"])}
                ids = {
                    name: root_run_id(
                        system.policy.deployment_id, asdict(scope), "original-message-secret"
                    )
                    for name, scope in scopes.items()
                }
                system.targets.update(ids.values())
                (tmp_path / "scope-host.json").write_text(
                    json.dumps(
                        {
                            "scopes": {name: asdict(scope) for name, scope in scopes.items()},
                            "namespace": system.namespace["name"],
                            "queue": system.queue,
                            "release": system.runtime.orchestration_release,
                        }
                    )
                )
                state = "waiting_reconciliation" if uncertain else "waiting_approval"
                async with system.worker():
                    async with http_host(tmp_path) as (clients, http, url, first):
                        # Keep the original one-root capacity: Bob finishes before Alice starts.
                        bob_task = await clients["bob"].send_message(
                            "original-message-secret", "request-body-secret"
                        )
                        assert bob_task["id"] == ids["bob"]
                        bob_waiting = await wait_task(clients["bob"], ids["bob"], state)
                        assert (await clients["bob"].get_task(ids["bob"]))["id"] == ids["bob"]
                        bob_receipt = await finish(
                            clients["bob"],
                            facades["bob"],
                            business,
                            ids["bob"],
                            bob_waiting,
                            uncertain=uncertain,
                        )
                        await system.count(0)
                        await save_evidence(system, facades["bob"], ids["bob"])
                        original = await clients["alice"].send_message(
                            "original-message-secret", "request-body-secret"
                        )
                        assert original["id"] == ids["alice"]
                        waiting = await wait_task(clients["alice"], ids["alice"], state)
                        page = await clients["alice"].get_events(ids["alice"], limit=1)
                        assert page["events"]
                        action = next(
                            a
                            for a in (await system.engine.status(ids["alice"])).actions
                            if a["kind"] == "tool"
                        )
                        before = {
                            "status": asdict(await system.engine.status(ids["alice"])),
                            "events": [asdict(e) for e in await system.engine.events(ids["alice"])],
                            "pg": await effect_rows(journal, business),
                        }
                        requests = [
                            ("tasks/get", {"id": ids["alice"]}),
                            ("tasks/events", {"id": ids["alice"]}),
                            (
                                "tasks/events",
                                {"id": ids["alice"], "afterCursor": page["cursor_token"]},
                            ),
                            (
                                "tasks/cancel",
                                {
                                    "id": ids["alice"],
                                    "metadata": {"ralfCommandId": "foreign-control-secret"},
                                },
                            ),
                            (
                                "tasks/approve",
                                {
                                    "id": ids["alice"],
                                    "actionId": action["id"],
                                    "targetDigest": action["digest"],
                                    "commandId": "foreign-control-secret",
                                },
                            ),
                            (
                                "tasks/reconcile",
                                {
                                    "id": ids["alice"],
                                    "actionId": action["id"],
                                    "result": {"private": "foreign-result-secret"},
                                    "commandId": "foreign-control-secret",
                                },
                            ),
                            ("tasks/resume", {"id": ids["alice"]}),
                        ]
                        for method, params in requests:
                            denied = await http.post(
                                url,
                                headers={"Authorization": "Bearer bob"},
                                json={
                                    "jsonrpc": "2.0",
                                    "id": "foreign-request-secret",
                                    "method": method,
                                    "params": params,
                                },
                            )
                            assert denied.status_code == 401 and denied.json() == {
                                "error": "unauthorized"
                            }
                        assert {
                            "status": asdict(await system.engine.status(ids["alice"])),
                            "events": [asdict(e) for e in await system.engine.events(ids["alice"])],
                            "pg": await effect_rows(journal, business),
                        } == before
                        denied = await http.post(
                            url,
                            json={
                                "jsonrpc": "2.0",
                                "id": "auth-secret",
                                "method": "tasks/get",
                                "params": {"id": ids["alice"]},
                            },
                        )
                        assert denied.status_code == 401
                    async with http_host(tmp_path) as (clients, _, _, second):
                        assert (
                            await finish(
                                clients["bob"],
                                facades["bob"],
                                business,
                                ids["bob"],
                                bob_waiting,
                                uncertain=uncertain,
                            )
                            == bob_receipt
                        )
                        await save_evidence(system, facades["bob"], ids["bob"])
                        assert (
                            await clients["alice"].send_message(
                                "original-message-secret", "request-body-secret"
                            )
                        )["id"] == ids["alice"]
                        assert (await clients["bob"].get_by_message("original-message-secret"))[
                            "id"
                        ] == ids["bob"]
                        assert (await clients["alice"].get_by_message("original-message-secret"))[
                            "id"
                        ] == ids["alice"]
                        assert (await clients["alice"].resume_task(ids["alice"]))["metadata"][
                            "ralf"
                        ]["recoveryHint"]["durable"] is False
                        receipt = await finish(
                            clients["alice"],
                            system.engine,
                            business,
                            ids["alice"],
                            waiting,
                            uncertain=uncertain,
                        )
                        await system.count(0)
                        await save_evidence(system, system.engine, ids["alice"])
                    assert await (
                        await business.execute("SELECT calls FROM business ORDER BY effect_key")
                    ).fetchall() == [(1,), (1,)]
                    assert await (
                        await journal.connection.execute(
                            "SELECT state FROM ralf_temporal_effects ORDER BY effect_key"
                        )
                    ).fetchall() == [("adopted",), ("adopted",)]
                    records = []
                    for process in (first, second):
                        records.extend(
                            json.loads(
                                (tmp_path / f"scope-host-closed-{process.pid}.json").read_text()
                            )["records"]
                        )
                    foreign = [
                        r for r in records if r["outcome"] == "unauthorized" and r["scope_ref"]
                    ]
                    assert len(foreign) == 7
                    assert {r["operation"] for r in foreign} == {
                        "tasks/get",
                        "tasks/events",
                        "tasks/cancel",
                        "tasks/approve",
                        "tasks/reconcile",
                        "tasks/resume",
                    }
                    operation = "tasks/reconcile" if uncertain else "tasks/approve"
                    owner_controls = [
                        r
                        for r in records
                        if r["operation"] == operation
                        and r["outcome"] == "rpc_ok"
                        and r["task_ref"] == foreign[0]["task_ref"]
                    ]
                    assert len(owner_controls) == 2
                    assert (
                        owner_controls[0]["command_ref"]
                        and owner_controls[0]["command_ref"] == owner_controls[1]["command_ref"]
                    )
                    assert all(r["task_ref"] == owner_controls[0]["task_ref"] for r in foreign)
                    assert all(r["scope_ref"] != owner_controls[0]["scope_ref"] for r in foreign)
                    serialized = canonical(records)
                    for private in (
                        "secret",
                        "Bearer alice",
                        "Bearer bob",
                        ids["alice"],
                        ids["bob"],
                        scopes["alice"].workspace,
                        scopes["alice"].principal,
                        scopes["bob"].principal,
                        action["id"],
                        action["digest"],
                    ):
                        assert private not in serialized
                    (tmp_path / "scope-http-result.json").write_text(
                        json.dumps(
                            {
                                "mode": "unknown-write" if uncertain else "approval",
                                "actual_http_hosts": 2,
                                "valid_authenticated_scopes": 2,
                                "foreign_requests_rejected": 7,
                                "original_state_unchanged": True,
                                "writes_per_original_effect": 1,
                                "original_control_receipt": receipt,
                                "both_roots_retired": True,
                                "histories_replayed": True,
                                "audit_redacted": True,
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
            (tmp_path / "scope-postgres-cleanup.json").write_text(
                json.dumps(
                    {
                        "owned_schema": schema,
                        "removed_after_verified_retirement": verified,
                        "retained_on_incomplete": not verified,
                    }
                )
            )

    asyncio.run(asyncio.wait_for(run(), 180))
