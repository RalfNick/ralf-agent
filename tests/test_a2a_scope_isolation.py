"""Two valid identities routed serially through one original SQLite authority."""

import asyncio
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict

import httpx
import pytest

from ralf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    Scope,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from ralf_agent.a2a import A2AApplication, A2AClient
from ralf_agent.errors import AuthorizationDenied
from ralf_agent.handoff import SQLiteInbox
from ralf_agent.service_audit import ServiceAudit
from ralf_agent.storage import SQLiteStore
from ralf_agent.types import canonical

SCOPES = {name: Scope("shared-workspace", name) for name in ("alice", "bob")}


class Provider:
    identity = {"kind": "scope-isolation-write", "version": "1"}

    async def complete(self, messages, tools):
        if any(message["role"] == "tool" for message in messages):
            return ModelResponse(output="verified")
        return ModelResponse(tool_calls=(ToolCall("write", {}),))


@contextmanager
def hosted(tmp_path, *, uncertain=False, audit=None):
    business = tmp_path / "business.sqlite"
    authority = tmp_path / "runs.sqlite"
    with sqlite3.connect(business) as db:
        db.execute("CREATE TABLE attempts (effect_key TEXT NOT NULL)")

    def write(args, context):
        with sqlite3.connect(business) as db:
            db.execute("INSERT INTO attempts VALUES (?)", (context.effect_key,))
        if uncertain:
            raise ConnectionError("Original response lost after commit")
        return {"changed": True}

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
    current = None

    def engine_for_scope(scope):
        nonlocal current
        # SQLite permits one coordinator. This host switches Scope serially,
        # reopening the SAME authority so a foreign Run is present, not missing.
        # It does not model concurrent multi-tenant or Temporal host routing.
        if current is None or current.scope != scope:
            if current is not None:
                current.close()
            current = LocalEngine(
                SQLiteStore(authority),
                providers={"default": Provider()},
                tools=tools,
                scope=scope,
            )
        return current

    async def authenticate(headers):
        for name, scope in SCOPES.items():
            if headers.get("authorization") == "Bearer " + name:
                return scope
        raise AuthorizationDenied("private-credential-secret")

    async def recover(scope, run_id):
        await engine_for_scope(scope).drive(run_id)

    inbox = SQLiteInbox(tmp_path / "inbox.sqlite")
    try:
        app = A2AApplication(
            engine_for_scope=engine_for_scope,
            spec=AgentSpec("writer", "Write once", ("write",)),
            inbox=inbox,
            authenticate=authenticate,
            url="http://test/rpc",
            enable_run_events=True,
            enable_run_controls=True,
            recovery_wakeup=recover,
            audit=audit,
        )
        yield app, engine_for_scope
    finally:
        inbox.close()
        if current is not None:
            current.close()


def client_for(http, name):
    return A2AClient("http://test/rpc", client=http, headers={"Authorization": "Bearer " + name})


async def rpc(http, name, method, params, *, request_id=1):
    return await http.post(
        "http://test/rpc",
        headers={} if name is None else {"Authorization": "Bearer " + name},
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


def persisted(tmp_path):
    with sqlite3.connect(tmp_path / "runs.sqlite") as db:
        authority = {
            table: db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
            for table in ("runs", "events", "commands", "budgets", "reservations")
        }
    with sqlite3.connect(tmp_path / "business.sqlite") as db:
        return authority, db.execute("SELECT effect_key FROM attempts ORDER BY rowid").fetchall()


@pytest.mark.parametrize(
    "operation", ["get", "events", "cursor", "cancel", "approve", "reconcile", "resume"]
)
def test_valid_bob_cannot_read_or_control_alices_original_task(tmp_path, operation):
    async def run():
        uncertain = operation in {"reconcile", "resume"}
        with hosted(tmp_path, uncertain=uncertain) as (app, select):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                alice, bob = client_for(http, "alice"), client_for(http, "bob")
                original = await alice.send_message("same-message", "Alice private request")
                other = await bob.send_message("same-message", "Bob private request")
                assert other["id"] != original["id"]
                assert (await bob.get_task(other["id"]))["id"] == other["id"]
                assert (await bob.get_by_message("same-message"))["id"] == other["id"]
                assert (await alice.get_by_message("same-message"))["id"] == original["id"]
                engine = select(SCOPES["alice"])
                assert (await engine.drive(original["id"])).state == "waiting_approval"
                target = engine.status(original["id"]).pending[0]
                if uncertain:
                    await alice.approve_task(
                        original["id"], target["action_id"], target["digest"], command_id="allow"
                    )
                    assert (await engine.drive(original["id"])).state == "waiting_reconciliation"
                page = await alice.get_events(original["id"], limit=1)
                assert page["events"]
                method = "tasks/events" if operation == "cursor" else "tasks/" + operation
                params = {"id": original["id"]}
                if operation == "cursor":
                    params["afterCursor"] = page["cursor_token"]
                elif operation == "approve":
                    params.update(
                        actionId=target["action_id"],
                        targetDigest=target["digest"],
                        commandId="take",
                    )
                elif operation == "reconcile":
                    params.update(
                        actionId=target["action_id"], result={"changed": True}, commandId="take"
                    )
                before = persisted(tmp_path)
                denied = await rpc(http, "bob", method, params)
                assert denied.status_code == 401
                assert denied.json() == {"error": "unauthorized"}
                assert persisted(tmp_path) == before
                assert len(before[1]) == int(uncertain)

                # The identical request is valid for Alice, so malformed input,
                # unavailable controls or a missing Run cannot explain rejection.
                accepted = await rpc(http, "alice", method, params)
                assert accepted.status_code == 200 and "result" in accepted.json()
                if operation in {"approve", "reconcile"}:
                    assert (
                        await select(SCOPES["alice"]).drive(original["id"])
                    ).state == "succeeded"
                    assert len(persisted(tmp_path)[1]) == 1
                elif operation == "cancel":
                    assert select(SCOPES["alice"]).status(original["id"]).state == "cancelled"
                elif operation == "resume":
                    result = accepted.json()["result"]["metadata"]["ralf"]
                    assert result["recoveryHint"] == {"accepted": True, "durable": False}
                    assert result["state"] == "waiting_reconciliation"
                    assert len(persisted(tmp_path)[1]) == 1
                await alice.aclose()
                await bob.aclose()

    asyncio.run(run())


def test_authentication_and_forged_scope_cannot_select_another_valid_identity(tmp_path):
    async def run():
        with hosted(tmp_path) as (app, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                alice = client_for(http, "alice")
                original = await alice.send_message("original", "private")
                before = persisted(tmp_path)
                for name in (None, "invalid"):
                    denied = await rpc(http, name, "tasks/get", {"id": original["id"]})
                    assert denied.status_code == 401
                    assert denied.json() == {"error": "unauthorized"}
                forged = await rpc(
                    http,
                    "bob",
                    "tasks/get",
                    {
                        "id": original["id"],
                        "scope": {"workspace": "shared-workspace", "principal": "alice"},
                    },
                )
                assert forged.json()["error"]["code"] == -32602
                assert persisted(tmp_path) == before
                assert (await alice.get_task(original["id"]))["id"] == original["id"]
                await alice.aclose()

    asyncio.run(run())


def test_audit_correlates_foreign_denial_and_owner_recovery_without_secrets(tmp_path):
    async def run():
        audit = ServiceAudit()
        with hosted(tmp_path, uncertain=True, audit=audit) as (app, select):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                alice, bob = client_for(http, "alice"), client_for(http, "bob")
                original = await alice.send_message("alice-message-secret", "request-body-secret")
                other = await bob.send_message("bob-message-secret", "bob-request-secret")
                assert (await bob.get_task(other["id"]))["id"] == other["id"]
                engine = select(SCOPES["alice"])
                assert (await engine.drive(original["id"])).state == "waiting_approval"
                target = engine.status(original["id"]).pending[0]
                await alice.approve_task(
                    original["id"],
                    target["action_id"],
                    target["digest"],
                    command_id="approve-command-secret",
                )
                approval_record = audit.sink.records[-1]
                assert (await engine.drive(original["id"])).state == "waiting_reconciliation"
                params = {
                    "id": original["id"],
                    "actionId": target["action_id"],
                    "result": {"changed": True, "private": "reconcile-result-secret"},
                    "commandId": "reconcile-command-secret",
                }
                before = persisted(tmp_path)
                denied = await rpc(
                    http, "bob", "tasks/reconcile", params, request_id="denied-request-secret"
                )
                assert denied.status_code == 401
                assert persisted(tmp_path) == before and len(before[1]) == 1
                denied_record = audit.sink.records[-1]
                assert denied_record.operation == "tasks/reconcile"
                assert denied_record.outcome == "unauthorized"

                accepted = await rpc(
                    http, "alice", "tasks/reconcile", params, request_id="owner-request-secret"
                )
                assert accepted.status_code == 200
                assert accepted.json()["result"]["receipt"]["apply_state"] == "applied"
                owner_record = audit.sink.records[-1]
                assert owner_record.operation == "tasks/reconcile"
                assert owner_record.outcome == "rpc_ok"
                assert denied_record.scope_ref and owner_record.scope_ref
                assert denied_record.scope_ref != owner_record.scope_ref
                assert denied_record.task_ref == owner_record.task_ref == approval_record.task_ref
                assert owner_record.task_ref
                assert denied_record.command_ref == owner_record.command_ref
                assert (
                    owner_record.command_ref
                    and owner_record.command_ref != approval_record.command_ref
                )
                assert denied_record.request_ref != owner_record.request_ref
                repeated = await rpc(
                    http, "alice", "tasks/reconcile", params, request_id="repeat-request-secret"
                )
                assert repeated.json()["result"] == accepted.json()["result"]
                assert audit.sink.records[-1].command_ref == owner_record.command_ref
                assert (await select(SCOPES["alice"]).drive(original["id"])).state == "succeeded"
                assert len(persisted(tmp_path)[1]) == 1
                assert (await alice.get_task(original["id"]))["status"]["state"] == "completed"
                serialized = canonical([asdict(record) for record in audit.sink.records])
                for private in (
                    "secret",
                    "Bearer alice",
                    "Bearer bob",
                    "shared-workspace",
                    original["id"],
                    other["id"],
                    target["action_id"],
                    target["digest"],
                ):
                    assert private not in serialized
                assert audit.failures == 0 and audit.sink.dropped == 0
                await alice.aclose()
                await bob.aclose()

    asyncio.run(run())
