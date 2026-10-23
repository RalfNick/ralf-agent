import asyncio
import json
from dataclasses import asdict

import httpx
import pytest

from relf_agent import AgentSpec, ServiceAudit
from relf_agent.a2a import A2AApplication
from relf_agent.errors import ValidationError

from .test_a2a import make_app


def application(tmp_path, audit):
    app, engine, inbox = make_app(tmp_path)
    return (
        A2AApplication(
            engine_for_scope=lambda scope: engine,
            spec=AgentSpec("agent", "Answer"),
            inbox=inbox,
            authenticate=app._authenticate,
            url="http://test/rpc",
            audit=audit,
        ),
        engine,
        inbox,
    )


def test_rpc_auth_retries_and_errors_are_redacted_and_correlated(tmp_path):
    async def check():
        audit = ServiceAudit(key=b"a" * 32)
        app, engine, inbox = application(tmp_path, audit)
        headers = {"Authorization": "Bearer trusted"}
        body = {
            "jsonrpc": "2.0",
            "id": "request-secret",
            "method": "message/send",
            "params": {
                "message": {
                    "kind": "message",
                    "role": "user",
                    "messageId": "message-secret",
                    "parts": [{"kind": "text", "text": "payload-private-secret"}],
                }
            },
        }
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as http:
                assert (await http.post("/rpc", json=body)).status_code == 401
                first = (await http.post("/rpc", json=body, headers=headers)).json()
                repeat = (await http.post("/rpc", json=body, headers=headers)).json()
                assert first == repeat and "result" in first
                task_id = first["result"]["id"]
                assert engine.status(task_id).state == "queued"
                assert (
                    await http.post(
                        "/rpc",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 4,
                            "method": "private-secret",
                            "params": {},
                        },
                    )
                ).json()["error"]["code"] == -32601
                assert (
                    await http.post("/rpc", headers=headers, content=b"secret-bad-json")
                ).json()["error"]["code"] == -32700
            records = [asdict(item) for item in audit.sink.records]
            assert [item["outcome"] for item in records] == [
                "unauthorized",
                "rpc_ok",
                "rpc_ok",
                "rpc_error",
                "invalid_request",
            ]
            assert records[0]["scope_ref"] is None and records[0]["request_ref"] is None
            for field in ("scope_ref", "request_ref", "message_ref", "task_ref"):
                assert records[1][field] == records[2][field] is not None
            assert "secret" not in json.dumps(records) and task_id not in json.dumps(records)
        finally:
            engine.close()
            inbox.close()

    asyncio.run(check())


def test_sink_failure_does_not_turn_accepted_submission_into_error(tmp_path):
    class Sink:
        def emit(self, record):
            raise RuntimeError("sink-private-secret")

    async def check():
        audit = ServiceAudit(Sink())
        app, engine, inbox = application(tmp_path, audit)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                response = await http.post(
                    "http://test/rpc",
                    headers={"Authorization": "Bearer trusted"},
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "message/send",
                        "params": {
                            "message": {
                                "kind": "message",
                                "role": "user",
                                "messageId": "stable",
                                "parts": [{"kind": "text", "text": "answer"}],
                            },
                        },
                    },
                )
            result = response.json()
            assert "result" in result and engine.status(result["result"]["id"]).state == "queued"
            assert audit.failures == 1
        finally:
            engine.close()
            inbox.close()

    asyncio.run(check())


@pytest.mark.parametrize("mode", ["disconnect", "cancel", "timeout"])
def test_interrupted_observation_records_without_business_cancel(tmp_path, mode):
    async def check():
        audit = ServiceAudit()
        app, engine, inbox = application(tmp_path, audit)
        messages = []
        entered = asyncio.Event()

        async def receive():
            entered.set()
            if mode == "disconnect":
                return {"type": "http.disconnect"}
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        if mode == "timeout":
            app._timeout = 0.01
        try:
            task = asyncio.create_task(
                app(
                    {
                        "type": "http",
                        "method": "POST",
                        "path": "/rpc",
                        "headers": [(b"authorization", b"Bearer trusted")],
                    },
                    receive,
                    send,
                )
            )
            await entered.wait()
            if mode == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
            assert [item.outcome for item in audit.sink.records] == [
                {
                    "disconnect": "disconnected",
                    "cancel": "cancelled",
                    "timeout": "timeout",
                }[mode]
            ]
            assert audit.failures == 0
        finally:
            engine.close()
            inbox.close()

    asyncio.run(check())


def test_invalid_audit_configuration_is_rejected(tmp_path):
    app, engine, inbox = make_app(tmp_path)
    try:
        with pytest.raises(ValidationError):
            A2AApplication(
                engine_for_scope=lambda scope: engine,
                spec=AgentSpec("a", "b"),
                inbox=inbox,
                authenticate=app._authenticate,
                url="http://test/rpc",
                audit=lambda value: None,
            )
    finally:
        engine.close()
        inbox.close()


@pytest.mark.parametrize("mode", ["cancel", "timeout"])
def test_interruption_after_acceptance_retains_original_run(tmp_path, mode):
    async def check():
        audit = ServiceAudit()
        app, engine, inbox = application(tmp_path, audit)
        accepted = asyncio.Event()
        original_rpc = app._rpc
        original_result = None

        async def blocked_reply(*args):
            nonlocal original_result
            original_result = await original_rpc(*args)
            accepted.set()
            await asyncio.Event().wait()

        app._rpc = blocked_reply
        if mode == "timeout":
            app._timeout = 0.05
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                task = asyncio.create_task(
                    http.post(
                        "http://test/rpc",
                        headers={"Authorization": "Bearer trusted"},
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "message/send",
                            "params": {
                                "message": {
                                    "kind": "message",
                                    "role": "user",
                                    "messageId": "original-message",
                                    "parts": [{"kind": "text", "text": "answer"}],
                                },
                            },
                        },
                    )
                )
                await accepted.wait()
                if mode == "cancel":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    assert (await task).json()["error"]["code"] == -32603
                run_id = original_result["id"]
                assert engine.status(run_id).state == "queued"
                app._rpc = original_rpc
                app._timeout = 10
                replay = await http.post(
                    "http://test/rpc",
                    headers={"Authorization": "Bearer trusted"},
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tasks/get",
                        "params": {
                            "id": run_id,
                            "metadata": {"ralfMessageId": "original-message"},
                        },
                    },
                )
                assert replay.json()["result"]["id"] == run_id
            assert (
                audit.sink.records[0].outcome == {"cancel": "cancelled", "timeout": "timeout"}[mode]
            )
            assert audit.sink.records[0].message_ref is not None
        finally:
            engine.close()
            inbox.close()

    asyncio.run(check())
