import asyncio

import httpx
import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, ToolRegistry
from relf_agent.errors import AuthorizationDenied
from relf_agent.storage import SQLiteStore

from .helpers import ScriptedProvider


def make_app(tmp_path, responses=(), *, wakeup=None, inbox_factory=None, max_response_bytes=262144):
    from relf_agent.a2a import A2AApplication
    from relf_agent.handoff import SQLiteInbox

    runtime = LocalEngine(
        SQLiteStore(tmp_path / "runs.db"),
        providers={"default": ScriptedProvider(responses)},
        tools=ToolRegistry(),
    )
    inbox = (inbox_factory or SQLiteInbox)(tmp_path / "inbox.db")

    async def auth(headers):
        if headers.get("authorization") != "Bearer trusted":
            raise AuthorizationDenied("private-credential-secret")
        return Scope()

    app = A2AApplication(
        engine_for_scope=lambda scope: runtime,
        spec=AgentSpec("agent", "Answer"),
        inbox=inbox,
        authenticate=auth,
        url="http://test/rpc",
        wakeup=wakeup,
        max_response_bytes=max_response_bytes,
    )
    return app, runtime, inbox


@pytest.mark.parametrize("request_id", ["x" * 4000, "界" * 1000], ids=["ascii", "utf8"])
def test_oversized_rpc_id_is_bounded_and_rejected_before_submission(tmp_path, request_id):
    async def run():
        app, engine, inbox = make_app(tmp_path, max_response_bytes=1024)
        try:
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "message/send",
                "params": {
                    "message": {
                        "kind": "message",
                        "role": "user",
                        "messageId": "bounded-message",
                        "parts": [{"kind": "data", "data": {"question": "q"}}],
                    }
                },
            }
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                response = await http.post(
                    "http://test/rpc", json=request, headers={"Authorization": "Bearer trusted"}
                )
                assert len(response.content) <= 1024
                assert response.json()["id"] is None
                assert response.json()["error"]["code"] == -32600
                assert inbox.pending(Scope()) == []
                assert engine.providers["default"].calls == 0
                request["id"] = 7
                accepted = await http.post(
                    "http://test/rpc", json=request, headers={"Authorization": "Bearer trusted"}
                )
                assert accepted.json()["id"] == 7
                assert accepted.json()["result"]["status"]["state"] == "submitted"
        finally:
            engine.close()
            inbox.close()

    asyncio.run(run())


def test_oversized_result_keeps_small_rpc_id_in_bounded_error(tmp_path):
    async def run():
        app, engine, inbox = make_app(
            tmp_path, [ModelResponse(output="x" * 3000)], max_response_bytes=1024
        )
        try:
            handle = engine.submit(AgentSpec("agent", "Answer"), "q", command_id="s")
            assert (await engine.drive(handle.run_id)).state == "succeeded"
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                response = await http.post(
                    "http://test/rpc",
                    headers={"Authorization": "Bearer trusted"},
                    json={
                        "jsonrpc": "2.0",
                        "id": "original",
                        "method": "tasks/get",
                        "params": {"id": handle.run_id},
                    },
                )
                assert len(response.content) <= 1024
                assert response.json()["id"] == "original"
                assert response.json()["error"]["code"] == -32603
        finally:
            engine.close()
            inbox.close()

    asyncio.run(run())


def test_native_run_send_get_cancel_and_authenticated_scope(tmp_path):
    from relf_agent.a2a import A2AClient, A2ARemoteError

    async def check():
        app, runtime, inbox = make_app(tmp_path, [ModelResponse(output={"answer": 42})])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
            client = A2AClient(
                "http://test/rpc", client=http, headers={"Authorization": "Bearer trusted"}
            )
            card = await client.discover()
            assert card["protocolVersion"] == "0.3.0"
            assert card["capabilities"]["streaming"] is False
            assert card["capabilities"]["pushNotifications"] is False
            first = await client.send_message("stable", {"question": "x"})
            assert first["status"]["state"] == "submitted"
            assert runtime.status(first["id"]).state == "queued"
            assert (await client.send_message("stable", {"question": "x"}))["id"] == first["id"]
            with pytest.raises(A2ARemoteError) as conflict:
                await client.send_message("stable", {"changed": True})
            assert conflict.value.rpc_code == -32602
            await runtime.drive(first["id"])
            completed = await client.get_task(first["id"])
            assert completed["status"]["state"] == "completed"
            assert completed["artifacts"][0]["parts"][0]["data"] == {"result": {"answer": 42}}
            assert (await client.get_by_message("stable"))["id"] == first["id"]
            with pytest.raises(A2ARemoteError) as late:
                await client.cancel_task(first["id"], command_id="late")
            assert late.value.rpc_code == -32002
            second = await client.send_message("second", {})
            assert (await client.cancel_task(second["id"], command_id="cancel"))["status"][
                "state"
            ] == "canceled"
            with pytest.raises(A2ARemoteError) as missing:
                await client.get_task("missing")
            assert missing.value.rpc_code == -32001
            denied = await http.post(
                "http://test/rpc",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tasks/get",
                    "params": {"id": first["id"]},
                },
            )
            assert denied.status_code == 401 and "secret" not in denied.text
            forged = await http.post(
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
                            "messageId": "forged",
                            "parts": [{"kind": "data", "data": {}}],
                            "scope": {"principal": "admin"},
                        }
                    },
                },
            )
            assert forged.json()["error"]["code"] == -32602
            revive = await http.post(
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
                            "messageId": "revive",
                            "taskId": first["id"],
                            "parts": [{"kind": "text", "text": "again"}],
                        }
                    },
                },
            )
            assert revive.json()["error"]["code"] == -32004
            assert runtime.status(first["id"]).state == "succeeded"
            await client.aclose()
            assert not http.is_closed
        inbox.close()
        runtime.close()

    asyncio.run(check())


@pytest.mark.parametrize(
    "response",
    [
        {"jsonrpc": "2.0", "id": "wrong", "result": {}},
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "kind": "task",
                "id": "r",
                "contextId": "c",
                "status": {"state": "invented"},
            },
        },
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "credential-secret"}},
        {"bad": float("nan")},
    ],
)
def test_malformed_remote_responses_are_safe(response):
    from relf_agent.a2a import A2AClient, A2AError

    async def check():
        async def handle(request):
            if response == {"bad": float("nan")}:
                return httpx.Response(200, content=b'{"bad":NaN}')
            return httpx.Response(200, json=response)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            client = A2AClient("http://test/rpc", client=http)
            with pytest.raises(A2AError) as error:
                await client.get_task("r")
            assert "secret" not in str(error.value)

    asyncio.run(check())


def test_submit_timeout_is_not_retried_and_response_is_bounded():
    from relf_agent.a2a import A2AClient, A2AError

    async def check():
        calls = []

        async def handle(request):
            calls.append(request)
            raise httpx.ReadTimeout("credential-secret")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            client = A2AClient("http://test/rpc", client=http)
            with pytest.raises(A2AError):
                await client.send_message("id", {})
            assert len(calls) == 1

        async def huge(request):
            return httpx.Response(200, content=b"x" * 1025)

        async with httpx.AsyncClient(transport=httpx.MockTransport(huge)) as http:
            client = A2AClient("http://test/rpc", client=http, max_response_bytes=1024)
            with pytest.raises(A2AError, match="byte limit"):
                await client.get_task("r")

    asyncio.run(check())


def test_tool_source_approval_unknown_then_read_only_reconcile(tmp_path):
    from relf_agent.a2a import A2AClient, A2AToolSource
    from relf_agent.tool_sources import ToolPolicy, register_tool_source

    from .helpers import tool_response

    async def check():
        app, remote, inbox = make_app(tmp_path, [ModelResponse(output={"remote": True})])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
            client = A2AClient(
                "http://test/rpc", client=http, headers={"Authorization": "Bearer trusted"}
            )
            source = A2AToolSource(client, poll_timeout=0.02, poll_interval=0.005)
            tools = ToolRegistry()
            await register_tool_source(
                tools,
                source,
                policies={
                    "remote_agent": ToolPolicy(
                        "1",
                        effect="queryable_write",
                        requires_approval=True,
                        effect_key_argument="message_id",
                        reconciler=source.reconcile,
                    )
                },
            )
            host = LocalEngine(
                SQLiteStore(tmp_path / "host.db"),
                providers={
                    "default": ScriptedProvider(
                        [
                            tool_response("remote_agent", {"input": {"request": "x"}}),
                            ModelResponse(output="parent complete"),
                        ]
                    )
                },
                tools=tools,
            )
            handle = host.submit(
                AgentSpec("host", "Use remote", ("remote_agent",)), {}, command_id="host"
            )
            pending = await host.drive(handle.run_id)
            assert pending.state == "waiting_approval"
            assert inbox.pending(Scope()) == []
            approval = pending.pending[0]
            host.approve(
                handle.run_id, approval["action_id"], approval["digest"], command_id="approve"
            )
            unknown = await host.drive(handle.run_id)
            assert unknown.state == "waiting_reconciliation"
            action = next(action for action in unknown.actions if action["kind"] == "tool")
            assert action["status"] == "outcome_unknown"
            assert (
                await source.reconcile(
                    {}, type("Context", (), {"effect_key": action["effect_key"]})()
                )
                is None
            )
            task = await client.get_by_message(action["effect_key"])
            await remote.drive(task["id"])
            done = await host.drive(handle.run_id)
            assert done.state == "succeeded" and done.result == "parent complete"
            assert remote.events(task["id"])[0].kind == "run_submitted"
            assert len([e for e in remote.events(task["id"]) if e.kind == "run_submitted"]) == 1
            assert any(
                e.kind == "tool_receipt_recorded" and e.data["source"] == "tool-reconciler"
                for e in host.events(handle.run_id)
            )
            host.close()
        inbox.close()
        remote.close()

    asyncio.run(check())


def test_owned_http_close_retries_and_invalid_timeout():
    from relf_agent.a2a import A2AClient, A2AError
    from relf_agent.errors import ValidationError

    class Client:
        closed = 0

        def build_request(self, *args, **kwargs):
            pass

        async def send(self, *args, **kwargs):
            pass

        async def aclose(self):
            self.closed += 1
            if self.closed == 1:
                raise RuntimeError("credential-secret")

    async def check():
        http = Client()
        client = A2AClient("http://test/rpc", client=http, owns_client=True)
        with pytest.raises(A2AError, match="close failed"):
            await client.aclose()
        await client.aclose()
        await client.aclose()
        assert http.closed == 2
        with pytest.raises(A2AError, match="closed"):
            await client.get_task("run")

    asyncio.run(check())
    for timeout in (0, -1, True, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            A2AClient("http://test/rpc", timeout=timeout)


def test_discovery_rejects_invalid_capabilities_and_task_identity_mismatch():
    from relf_agent.a2a import A2AClient, A2AError

    async def check():
        async def bad_card(request):
            return httpx.Response(
                200,
                json={
                    "protocolVersion": "0.3.0",
                    "preferredTransport": "JSONRPC",
                    "url": "http://test/rpc",
                    "name": "agent",
                    "version": "1",
                    "description": "test",
                    "skills": [],
                    "capabilities": {"streaming": "false"},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(bad_card)) as http:
            with pytest.raises(A2AError):
                await A2AClient("http://test/rpc", client=http).discover()

        async def bad_task(request):
            import json

            rpc = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": rpc["id"],
                    "result": {
                        "kind": "task",
                        "id": "wrong-task",
                        "contextId": "wrong-task",
                        "status": {"state": "completed"},
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(bad_task)) as http:
            with pytest.raises(A2AError):
                await A2AClient("http://test/rpc", client=http).get_task("requested-task")

    asyncio.run(check())


def test_tool_source_identity_tracks_changed_remote_client():
    from relf_agent.a2a import A2AClient, A2AToolSource

    one = A2AClient("http://one/rpc")
    two = A2AClient("http://two/rpc")
    source = A2AToolSource(one)
    initial = source.identity
    source.client = two
    assert source.identity != initial
    asyncio.run(one.aclose())
    asyncio.run(two.aclose())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_application_borrows_structural_durable_inbox(tmp_path, asynchronous):
    from relf_agent.a2a import A2AClient

    from .test_handoff import ComposedAsyncInbox, ComposedInbox

    async def check():
        app, runtime, inbox = make_app(
            tmp_path,
            [ModelResponse(output="composed")],
            inbox_factory=ComposedAsyncInbox if asynchronous else ComposedInbox,
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
            client = A2AClient(
                "http://test/rpc", client=http, headers={"Authorization": "Bearer trusted"}
            )
            first = await client.send_message("composed", {})
            assert (await client.send_message("composed", {}))["id"] == first["id"]
            await runtime.drive(first["id"])
            assert (await client.get_by_message("composed"))["status"]["state"] == "completed"
            assert not (inbox.inner.closed if asynchronous else inbox.closed)
            await client.aclose()
        if asynchronous:
            await inbox.aclose()
        else:
            inbox.close()
        runtime.close()

    asyncio.run(check())


class ComposedA2AClient:
    """Third-party client with the same wire contract and explicit async shape."""

    def __init__(self, client):
        self.inner = client
        self.closes = 0

    @property
    def url(self):
        return self.inner.url

    @property
    def identity(self):
        return self.inner.identity

    async def discover(self):
        return await self.inner.discover()

    async def send_message(self, message_id, input):
        return await self.inner.send_message(message_id, input)

    async def get_task(self, task_id):
        return await self.inner.get_task(task_id)

    async def get_by_message(self, message_id):
        return await self.inner.get_by_message(message_id)

    async def cancel_task(self, task_id, *, command_id):
        return await self.inner.cancel_task(task_id, command_id=command_id)

    async def aclose(self):
        self.closes += 1
        await self.inner.aclose()


def test_tool_source_accepts_composed_client_and_preserves_borrowed_lifecycle(tmp_path):
    from relf_agent.a2a import A2AClient, A2AClientPort, A2AToolSource
    from relf_agent.types import InvocationContext

    async def check():
        async def wakeup(scope, run_id):
            await runtime.drive(run_id)

        app, runtime, inbox = make_app(
            tmp_path, [ModelResponse(output={"custom": True})], wakeup=wakeup
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
            client = ComposedA2AClient(
                A2AClient(
                    "http://test/rpc", client=http, headers={"Authorization": "Bearer trusted"}
                )
            )
            assert isinstance(client, A2AClientPort)
            source = A2AToolSource(client)
            descriptor = (await source.list_tools())[0]
            context = InvocationContext(
                Scope(), "host", "action", "attempt", "stable-effect", "epoch"
            )
            result = await source.call_tool(
                descriptor, {"input": {}, "message_id": context.effect_key}, context
            )
            assert result["result"] == {"custom": True}
            assert (await source.reconcile({}, context)) == result
            await source.aclose()
            assert client.closes == 0 and not http.is_closed
            await client.aclose()
        inbox.close()
        runtime.close()

    asyncio.run(check())


def test_owned_structural_a2a_client_close_is_retriable():
    from relf_agent.a2a import A2AClient, A2AError, A2AToolSource

    class FailingClose(ComposedA2AClient):
        async def aclose(self):
            self.closes += 1
            if self.closes == 1:
                raise RuntimeError("credential-secret")
            await self.inner.aclose()

    async def check():
        client = FailingClose(A2AClient("http://test/rpc"))
        source = A2AToolSource(client, owns_client=True)
        with pytest.raises(A2AError, match="close failed") as error:
            await source.aclose()
        assert "secret" not in str(error.value)
        await source.aclose()
        await source.aclose()
        assert client.closes == 2

    asyncio.run(check())


def test_structural_a2a_client_validates_fixed_identity_and_rejects_lazy_discovery():
    from relf_agent.a2a import A2AClient, A2AToolSource
    from relf_agent.errors import ValidationError

    async def check():
        client = ComposedA2AClient(A2AClient("http://test/rpc"))

        async def lazy_discovery():
            return client.inner.discover()

        client.discover = lazy_discovery
        source = A2AToolSource(client)
        with pytest.raises(ValidationError, match="discover"):
            await source.list_tools()
        await client.aclose()

        client = ComposedA2AClient(A2AClient("http://test/rpc"))
        client.get_task = lambda task_id: None
        with pytest.raises(ValidationError, match="async"):
            A2AToolSource(client)
        await client.aclose()

    asyncio.run(check())


def test_structural_client_bad_protocol_identity_rejected_before_io():
    from relf_agent.a2a import A2AToolSource
    from relf_agent.errors import ValidationError

    class InvalidClient:
        url = "http://test/rpc"
        identity = {"kind": "third-party", "protocolVersion": "0.2.9", "url": url}

        async def discover(self):
            pytest.fail("Invalid protocol client reached discovery")

        async def send_message(self, *args):
            pytest.fail("Invalid protocol client reached submit")

        async def get_task(self, *args):
            pass

        async def get_by_message(self, *args):
            pass

        async def cancel_task(self, *args, **kwargs):
            pass

        async def aclose(self):
            pass

    with pytest.raises(ValidationError, match="fixed protocol"):
        A2AToolSource(InvalidClient())


def test_owned_structural_client_lazy_close_is_not_completed():
    from relf_agent.a2a import A2AClient, A2AError, A2AToolSource

    entered = []

    async def later():
        entered.append("entered")

    class LazyClose(ComposedA2AClient):
        lazy = True

        async def aclose(self):
            if self.lazy:
                return later()
            await self.inner.aclose()

    async def check():
        client = LazyClose(A2AClient("http://test/rpc"))
        source = A2AToolSource(client, owns_client=True)
        with pytest.raises(A2AError, match="close failed"):
            await source.aclose()
        assert entered == [] and not source._closed
        client.lazy = False
        await source.aclose()
        assert source._closed

    asyncio.run(check())


@pytest.mark.parametrize("endpoint", ["http://test", "http://test/", "http://127.0.0.1:8000"])
def test_origin_endpoint_discover_send_get_over_asgi_http(tmp_path, endpoint):
    from relf_agent.a2a import A2AApplication, A2AClient
    from relf_agent.handoff import SQLiteInbox

    async def check():
        runtime = LocalEngine(
            SQLiteStore(tmp_path / "origin-runs.db"),
            providers={"default": ScriptedProvider([ModelResponse(output={"origin": True})])},
            tools=ToolRegistry(),
        )
        inbox = SQLiteInbox(tmp_path / "origin-inbox.db")

        async def authenticate(headers):
            if headers.get("authorization") != "Bearer trusted":
                raise AuthorizationDenied("Unauthorized")
            return Scope()

        app = A2AApplication(
            engine_for_scope=lambda scope: runtime,
            spec=AgentSpec("origin-agent", "Answer"),
            inbox=inbox,
            authenticate=authenticate,
            url=endpoint,
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                client = A2AClient(
                    endpoint, client=http, headers={"Authorization": "Bearer trusted"}
                )
                assert (await client.discover())["url"] == client.url
                task = await client.send_message("origin-message", {})
                assert task["status"]["state"] == "submitted"
                await runtime.drive(task["id"])
                completed = await client.get_task(task["id"])
                assert completed["status"]["state"] == "completed"
                assert completed["artifacts"][0]["parts"][0]["data"]["result"] == {"origin": True}
                await client.aclose()
        finally:
            inbox.close()
            runtime.close()

    asyncio.run(check())
