"""HTTP observation uses original durable events, never business execution."""

import asyncio
from contextlib import contextmanager

import httpx
import pytest

from ralf_agent import AgentSpec, EventCursor, LocalEngine, ModelResponse, Scope, ToolRegistry
from ralf_agent.a2a import A2AApplication, A2AClient, A2AError
from ralf_agent.errors import AuthorizationDenied
from ralf_agent.handoff import SQLiteInbox
from ralf_agent.storage import SQLiteStore
from tests.helpers import ScriptedProvider


class AsyncControls:
    """Native async control mode over a real local authority for transport checks."""

    def __init__(self, engine):
        self.engine, self.scope = engine, engine.scope

    async def submit(self, *args, **kwargs):
        return self.engine.submit(*args, **kwargs)

    async def status(self, *args, **kwargs):
        return self.engine.status(*args, **kwargs)

    async def cancel(self, *args, **kwargs):
        return self.engine.cancel(*args, **kwargs)

    async def events(self, *args, **kwargs):
        return self.engine.events(*args, **kwargs)


@contextmanager
def service(tmp_path, *, enabled=True, asynchronous=False, controls=None, response_limit=262144):
    engine = LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        providers={"default": ScriptedProvider([ModelResponse(output="done")])},
        tools=ToolRegistry(),
    )
    inbox = SQLiteInbox(tmp_path / "inbox.sqlite")

    async def auth(headers):
        if headers.get("authorization") != "Bearer owner":
            raise AuthorizationDenied("Rejected")
        return Scope()

    selected = controls(engine) if controls else AsyncControls(engine) if asynchronous else engine
    try:
        app = A2AApplication(
            engine_for_scope=lambda scope: selected,
            spec=AgentSpec("answer", "Answer"),
            inbox=inbox,
            authenticate=auth,
            url="http://test/rpc",
            enable_run_events=enabled,
            max_response_bytes=response_limit,
        )
        yield app, engine, selected
    finally:
        inbox.close()
        engine.close()


def client_for(http):
    return A2AClient("http://test/rpc", client=http, headers={"Authorization": "Bearer owner"})


async def rpc(http, params, *, authorized=True):
    return await http.post(
        "http://test/rpc",
        headers={"Authorization": "Bearer owner"} if authorized else {},
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/events", "params": params},
    )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_http_event_cursor_replays_and_resumes_after_authority_restart(tmp_path, asynchronous):
    async def run():
        with service(tmp_path, asynchronous=asynchronous) as (app, engine, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = client_for(http)
                card = await client.discover()
                assert any(
                    ext["uri"] == "urn:ralf:a2a:run-events:v1"
                    for ext in card["capabilities"]["extensions"]
                )
                task = await client.send_message("submit", "question")
                first = await client.get_events(task["id"], limit=1)
                assert [r["event"]["seq"] for r in first["events"]] == [1]
                assert engine.status(task["id"]).state == "queued"
                assert first == await client.get_events(task["id"], limit=1)
                token = first["cursor_token"]
                assert EventCursor.from_token(token).after == 1
                assert (await engine.drive(task["id"])).state == "succeeded"
                expected = engine.events(task["id"], after=1)
                before = engine.store.run(task["id"])
                page = await client.get_events(task["id"], cursor=token, limit=100)
                assert [r["event"]["kind"] for r in page["events"]] == [e.kind for e in expected]
                assert [r["event"]["seq"] for r in page["events"]] == [e.seq for e in expected]
                assert engine.store.run(task["id"]) == before
                saved = page["cursor_token"]
                await client.aclose()
        with service(tmp_path, asynchronous=asynchronous) as (app, engine, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = client_for(http)
                assert await client.get_events(task["id"], cursor=token, limit=100) == page
                empty = await client.get_events(task["id"], cursor=saved)
                assert empty["events"] == [] and empty["cursor_token"] == saved
                assert engine.status(task["id"]).result == "done"
                await client.aclose()

    asyncio.run(run())


def test_disabled_events_preserve_legacy_discovery_and_refuse_route(tmp_path):
    async def run():
        with service(tmp_path, enabled=False) as (app, _, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                card = await client_for(http).discover()
                assert all(
                    ext["uri"] != "urn:ralf:a2a:run-events:v1"
                    for ext in card["capabilities"]["extensions"]
                )
                assert (await rpc(http, {"id": "missing"})).json()["error"]["code"] == -32601

    asyncio.run(run())


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": True}, {"limit": 1001}, {"afterCursor": "invalid!"}, {"extra": True}],
)
def test_http_events_reject_invalid_request_without_changing_run(tmp_path, params):
    async def run():
        with service(tmp_path) as (app, engine, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                task = await client_for(http).send_message("submit", "question")
                before = engine.store.run(task["id"])
                response = await rpc(http, {"id": task["id"], **params})
                assert response.json()["error"]["code"] == -32602
                assert engine.store.run(task["id"]) == before

    asyncio.run(run())


def test_http_event_cursor_is_not_authorization_or_a_foreign_run_selector(tmp_path):
    async def run():
        with service(tmp_path) as (app, engine, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                task = await client_for(http).send_message("submit", "question")
                for cursor in [
                    EventCursor(Scope("foreign", "owner"), task["id"]),
                    EventCursor(Scope(), "other"),
                ]:
                    assert (
                        await rpc(http, {"id": task["id"], "afterCursor": cursor.token})
                    ).status_code == 401
                assert (await rpc(http, {"id": task["id"]}, authorized=False)).status_code == 401
                assert (await rpc(http, {"id": "missing"})).json()["error"]["code"] == -32001
                assert engine.status(task["id"]).state == "queued"

    asyncio.run(run())


def test_canceling_http_event_read_ends_observation_without_canceling_business(tmp_path):
    async def run():
        started, ended = asyncio.Event(), asyncio.Event()

        class Held(AsyncControls):
            async def events(self, *args, **kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    ended.set()

        with service(tmp_path, controls=Held) as (app, engine, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = client_for(http)
                task = await client.send_message("submit", "question")
                before = engine.store.run(task["id"])
                read = asyncio.create_task(client.get_events(task["id"]))
                try:
                    await asyncio.wait_for(started.wait(), 1)
                    read.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await read
                    assert ended.is_set()
                    assert engine.store.run(task["id"]) == before
                finally:
                    read.cancel()
                    await asyncio.gather(read, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize(
    "corrupt", ["gap", "foreign_task", "wrong_cursor", "extra_field", "empty_jump"]
)
def test_client_rejects_remote_event_page_without_adopting_invalid_cursor(corrupt):
    from ralf_agent import EventEnvelope, RunEvent

    async def run():
        start = EventCursor(Scope(), "task")
        event = {"run_id": "task", "seq": 1, "kind": "created", "data": {}}
        record = EventEnvelope(Scope(), RunEvent(**event)).to_dict()
        page = {
            "kind": "ralf.event-page",
            "taskId": "task",
            "events": [record],
            "cursor_token": record["cursor_token"],
        }
        if corrupt == "gap":
            page["events"][0]["event"]["seq"] = 2
        elif corrupt == "foreign_task":
            page["taskId"] = "other"
        elif corrupt == "wrong_cursor":
            page["cursor_token"] = EventCursor(Scope("foreign", "owner"), "task", 1).token
        elif corrupt == "extra_field":
            page["events"][0]["event"]["unexpected"] = True
        else:
            page["events"] = []

        async def handler(request):
            import json

            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": json.loads(request.content)["id"], "result": page},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(A2AError, match="invalid event page"):
                await client_for(http).get_events("task", cursor=start.token)
            assert start.after == 0

    asyncio.run(run())


@pytest.mark.parametrize("drift", ["scope", "method"])
def test_async_event_binding_drift_cannot_publish_page(tmp_path, drift):
    class Changing(AsyncControls):
        async def events(self, *args, **kwargs):
            result = self.engine.events(*args, **kwargs)
            await asyncio.sleep(0)
            if drift == "scope":
                self.scope = Scope("other", "owner")
            else:
                self.events = AsyncControls(self.engine).events
            return result

    async def run():
        with service(tmp_path, controls=Changing) as (app, engine, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                task = await client_for(http).send_message("submit", "question")
                response = await rpc(http, {"id": task["id"]})
                assert "result" not in response.json()
                assert engine.status(task["id"]).state == "queued"

    asyncio.run(run())


def test_byte_limited_pages_resume_at_last_returned_event(tmp_path):
    async def run():
        with service(tmp_path, response_limit=4096) as (app, engine, _):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = client_for(http)
                task = await client.send_message("submit", "question")
                start = EventCursor(Scope(), task["id"], engine.events(task["id"])[-1].seq)
                for i in range(3):
                    engine.store.emit(task["id"], "large", {"value": "x" * 1200, "index": i})
                page = await client.get_events(task["id"], cursor=start.token, limit=100)
                assert 0 < len(page["events"]) < 3
                rest = await client.get_events(task["id"], cursor=page["cursor_token"], limit=100)
                records = [*page["events"], *rest["events"]]
                assert [r["event"]["data"]["index"] for r in records] == [0, 1, 2]
                assert [r["event"]["seq"] for r in records] == [
                    start.after + 1,
                    start.after + 2,
                    start.after + 3,
                ]
                engine.store.emit(task["id"], "too_large", {"value": "x" * 5000})
                from ralf_agent.a2a import A2ARemoteError

                with pytest.raises(A2ARemoteError) as large:
                    await client.get_events(task["id"], cursor=rest["cursor_token"])
                assert large.value.rpc_code == -32603
                assert engine.status(task["id"]).state == "queued"

    asyncio.run(run())
