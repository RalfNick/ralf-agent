"""Original durable controls and host-owned recovery through existing JSON-RPC."""

import asyncio
import sqlite3
from contextlib import asynccontextmanager

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
from ralf_agent.a2a import A2AClient, A2ARemoteError
from ralf_agent.errors import AuthorizationDenied
from ralf_agent.handoff import SQLiteInbox
from ralf_agent.service_lifecycle import LocalA2AService
from ralf_agent.storage import SQLiteStore


class Provider:
    identity = {"kind": "http-control-write", "version": "1"}

    async def complete(self, messages, tools):
        if any(message["role"] == "tool" for message in messages):
            return ModelResponse(output="verified")
        return ModelResponse(tool_calls=(ToolCall("write", {}),))


@asynccontextmanager
async def hosted(tmp_path, *, uncertain=False, enabled=True, queryable=False):
    business = tmp_path / "business.sqlite"
    with sqlite3.connect(business) as db:
        db.execute("CREATE TABLE IF NOT EXISTS attempts (effect_key TEXT NOT NULL)")

    def write(args, context):
        with sqlite3.connect(business) as db:
            db.execute("INSERT INTO attempts VALUES (?)", (context.effect_key,))
        if uncertain:
            raise ConnectionError("Original response lost after commit")
        return {"changed": True}

    def query(args, context):
        with sqlite3.connect(business) as db:
            found = db.execute(
                "SELECT count(*) FROM attempts WHERE effect_key=?", (context.effect_key,)
            ).fetchone()[0]
        return {"changed": True} if found == 1 else None

    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "write",
            "Write once",
            {"type": "object"},
            effect="queryable_write" if queryable else "unqueryable_write",
            requires_approval=not uncertain,
        ),
        write,
        reconciler=query if queryable else None,
    )
    engine = LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"), providers={"default": Provider()}, tools=tools
    )
    inbox = SQLiteInbox(tmp_path / "inbox.sqlite", max_entries=1)

    async def auth(headers):
        if headers.get("authorization") != "Bearer owner":
            raise AuthorizationDenied("Rejected")
        return Scope()

    service = None
    try:
        service = LocalA2AService(
            engine=engine,
            inbox=inbox,
            spec=AgentSpec("writer", "Write once", ("write",)),
            authenticate=auth,
            url="http://test/rpc",
            enable_run_controls=enabled,
            enable_run_events=enabled,
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service)) as http:
            client = A2AClient(
                "http://test/rpc", client=http, headers={"Authorization": "Bearer owner"}
            )
            try:
                yield service, engine, client, http
            finally:
                await client.aclose()
    finally:
        if service is not None:
            await service.aclose()
        else:
            inbox.close()
            engine.close()


def writes(tmp_path):
    with sqlite3.connect(tmp_path / "business.sqlite") as db:
        return db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]


async def wait_state(client, task_id, expected):
    async with asyncio.timeout(3):
        while True:
            task = await client.get_task(task_id)
            if task["metadata"]["ralf"]["state"] == expected:
                return task
            await asyncio.sleep(0.01)


async def raw(http, method, params, *, authenticated=True):
    return await http.post(
        "http://test/rpc",
        headers={"Authorization": "Bearer owner"} if authenticated else {},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )


def test_http_approval_receipt_survives_completion_and_host_restart(tmp_path):
    async def run():
        async with hosted(tmp_path) as (_, _, client, _):
            task = await client.send_message("submit", "change")
            waiting = await wait_state(client, task["id"], "waiting_approval")
            target = waiting["metadata"]["ralf"]["pending"][0]
            assert writes(tmp_path) == 0
            receipts = await asyncio.gather(
                *[
                    client.approve_task(
                        task["id"], target["action_id"], target["digest"], command_id="approve"
                    )
                    for _ in range(2)
                ]
            )
            assert receipts[0] == receipts[1]
            receipt = receipts[0]
            assert receipt["receipt"]["command_id"] == "approve"
            assert receipt["receipt"]["record_state"] == "durably_recorded"
            await wait_state(client, task["id"], "succeeded")
            assert writes(tmp_path) == 1
        async with hosted(tmp_path) as (_, _, client, _):
            repeated = await client.approve_task(
                task["id"], target["action_id"], target["digest"], command_id="approve"
            )
            assert repeated == receipt
            assert writes(tmp_path) == 1
            with pytest.raises(A2ARemoteError) as conflict:
                await client.approve_task(
                    task["id"],
                    target["action_id"],
                    target["digest"],
                    command_id="approve",
                    approved=False,
                )
            assert conflict.value.rpc_code == -32602

    asyncio.run(run())


def test_http_unknown_effect_resume_and_manual_confirmation_never_repeat_write(tmp_path):
    async def run():
        async with hosted(tmp_path, uncertain=True) as (service, engine, client, _):
            task = await client.send_message("submit", "change")
            await wait_state(client, task["id"], "waiting_reconciliation")
            action = next(a for a in engine.status(task["id"]).actions if a["kind"] == "tool")
            assert writes(tmp_path) == 1
            resumed = await client.resume_task(task["id"])
            assert resumed["id"] == task["id"]
            assert resumed["metadata"]["ralf"]["recoveryHint"] == {
                "accepted": True,
                "durable": False,
            }
            async with asyncio.timeout(3):
                while service._active:
                    await asyncio.gather(*tuple(service._active.values()))
            assert engine.status(task["id"]).state == "waiting_reconciliation"
            assert writes(tmp_path) == 1
        async with hosted(tmp_path, uncertain=True) as (_, _, client, _):
            receipt = await client.reconcile_task(
                task["id"], action["id"], {"changed": True}, command_id="confirm"
            )
            await wait_state(client, task["id"], "succeeded")
            assert (
                await client.reconcile_task(
                    task["id"], action["id"], {"changed": True}, command_id="confirm"
                )
                == receipt
            )
            assert writes(tmp_path) == 1

    asyncio.run(run())


@pytest.mark.parametrize("method", ["tasks/approve", "tasks/reconcile", "tasks/resume"])
def test_legacy_server_does_not_expose_run_controls(tmp_path, method):
    async def run():
        async with hosted(tmp_path, enabled=False) as (_, _, client, http):
            assert all(
                e["uri"] != "urn:ralf:a2a:run-controls:v1"
                for e in (await client.discover())["capabilities"]["extensions"]
            )
            response = await raw(http, method, {"id": "missing"})
            assert response.json()["error"]["code"] == -32601
            assert writes(tmp_path) == 0

    asyncio.run(run())


def test_control_authentication_and_exact_request_precede_business_change(tmp_path):
    async def run():
        async with hosted(tmp_path) as (_, engine, client, http):
            task = await client.send_message("submit", "change")
            waiting = await wait_state(client, task["id"], "waiting_approval")
            target = waiting["metadata"]["ralf"]["pending"][0]
            params = {
                "id": task["id"],
                "actionId": target["action_id"],
                "targetDigest": target["digest"],
                "commandId": "approve",
            }
            assert (
                await raw(http, "tasks/approve", params, authenticated=False)
            ).status_code == 401
            for invalid in [
                {**params, "approved": 1},
                {**params, "scope": {"principal": "admin"}},
                {**params, "targetDigest": "wrong"},
            ]:
                assert (await raw(http, "tasks/approve", invalid)).json()["error"]["code"] == -32602
            assert engine.status(task["id"]).state == "waiting_approval"
            assert writes(tmp_path) == 0

    asyncio.run(run())


def test_recovery_hints_refused_after_host_closing(tmp_path):
    async def run():
        async with hosted(tmp_path) as (service, _, _, http):
            await service.aclose()
            assert (await raw(http, "tasks/resume", {"id": "missing"})).status_code == 503

    asyncio.run(run())


def test_lost_reply_after_control_acceptance_replays_original_receipt(tmp_path):
    async def run():
        async with hosted(tmp_path) as (service, engine, client, _):
            task = await client.send_message("submit", "change")
            target = (await wait_state(client, task["id"], "waiting_approval"))["metadata"]["ralf"][
                "pending"
            ][0]
            original_wakeup = service.application._wakeup
            fail = True

            async def lose_reply(scope, run_id):
                nonlocal fail
                await original_wakeup(scope, run_id)
                if fail:
                    fail = False
                    raise ConnectionError("Lost reply after original acceptance")

            service.application._wakeup = lose_reply
            with pytest.raises(A2ARemoteError) as lost:
                await client.approve_task(
                    task["id"], target["action_id"], target["digest"], command_id="original-approve"
                )
            assert lost.value.rpc_code == -32603
            receipt = await client.approve_task(
                task["id"], target["action_id"], target["digest"], command_id="original-approve"
            )
            assert receipt["receipt"]["command_id"] == "original-approve"
            await wait_state(client, task["id"], "succeeded")
            assert writes(tmp_path) == 1
            assert sum(e.kind == "approval_applied" for e in engine.events(task["id"])) == 1

    asyncio.run(run())


@pytest.mark.parametrize("uncertain", [False, True])
def test_native_async_ports_forward_original_control_receipts(tmp_path, uncertain):
    from ralf_agent.a2a import A2AApplication
    from tests.test_a2a_events import AsyncControls

    class Native(AsyncControls):
        async def approve(self, *args, **kwargs):
            await asyncio.sleep(0)
            return self.engine.approve(*args, **kwargs)

        async def reconcile(self, *args, **kwargs):
            await asyncio.sleep(0)
            return self.engine.reconcile(*args, **kwargs)

    async def run():
        async with hosted(tmp_path, uncertain=uncertain) as (service, engine, initial, _):
            task = await initial.send_message("submit", "change")
            state = "waiting_reconciliation" if uncertain else "waiting_approval"
            waiting = await wait_state(initial, task["id"], state)
            native = Native(engine)
            app = A2AApplication(
                engine_for_scope=lambda scope: native,
                inbox=service._inbox,
                spec=AgentSpec("writer", "Write once", ("write",)),
                authenticate=service.application._authenticate,
                url="http://test/rpc",
                wakeup=service.wakeup,
                recovery_wakeup=service.recovery_wakeup,
                enable_run_controls=True,
            )
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = A2AClient(
                    "http://test/rpc", client=http, headers={"Authorization": "Bearer owner"}
                )
                if uncertain:
                    action = next(
                        a for a in engine.status(task["id"]).actions if a["kind"] == "tool"
                    )
                    result = await client.reconcile_task(
                        task["id"], action["id"], {"changed": True}, command_id="async-control"
                    )
                else:
                    action = waiting["metadata"]["ralf"]["pending"][0]
                    result = await client.approve_task(
                        task["id"],
                        action["action_id"],
                        action["digest"],
                        command_id="async-control",
                    )
                assert result["receipt"]["run_id"] == task["id"]
                assert result["receipt"]["record_state"] == "durably_recorded"
                await wait_state(client, task["id"], "succeeded")
                assert writes(tmp_path) == 1
                await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [("run_id", "foreign"), ("command_id", "wrong"), ("record_state", "not_recorded")],
)
def test_client_refuses_foreign_or_nondurable_control_receipts(field, value):
    import json

    from ralf_agent.a2a import A2AError

    receipt = {
        "run_id": "task",
        "command_id": "approve",
        "kind": "approve",
        "record_state": "durably_recorded",
        "apply_state": "applied",
        "outcome": {},
    }
    receipt[field] = value

    async def handler(request):
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": json.loads(request.content)["id"],
                "result": {"kind": "ralf.control-receipt", "taskId": "task", "receipt": receipt},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = A2AClient("http://test/rpc", client=http)
            with pytest.raises(A2AError, match="invalid Run control receipt"):
                await client.approve_task("task", "action", "target", command_id="approve")
            await client.aclose()

    asyncio.run(run())


def test_recovery_hint_queries_original_effect_without_dispatching_another_attempt(tmp_path):
    async def run():
        async with hosted(tmp_path, uncertain=True, queryable=True) as (_, engine, client, _):
            task = await client.send_message("original", "change")
            await wait_state(client, task["id"], "waiting_reconciliation")
            assert writes(tmp_path) == 1
            await client.resume_task(task["id"])
            await wait_state(client, task["id"], "succeeded")
            action = next(a for a in engine.status(task["id"]).actions if a["kind"] == "tool")
            assert action["status"] == "completed" and len(action["attempts"]) == 1
            assert writes(tmp_path) == 1
            assert not any(e.kind == "effect_reconciled" for e in engine.events(task["id"]))

    asyncio.run(run())
