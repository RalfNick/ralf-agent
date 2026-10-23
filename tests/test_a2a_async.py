import asyncio

import httpx

from relf_agent import AgentSpec, LocalEngine, Scope, SQLiteStore, ToolRegistry
from relf_agent.a2a import A2AApplication, A2AClient
from relf_agent.handoff import SQLiteInbox
from relf_agent.runtime_builder import EchoProvider


def test_a2a_accepts_composed_async_authority_with_real_local_receipts(tmp_path):
    async def run():
        engine = LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": EchoProvider("test")},
            tools=ToolRegistry(),
        )
        inbox = SQLiteInbox(tmp_path / "inbox.sqlite")

        class Async:
            scope = engine.scope

            async def submit(self, *args, **kwargs):
                await asyncio.sleep(0)
                return engine.submit(*args, **kwargs)

            async def status(self, *args, **kwargs):
                return engine.status(*args, **kwargs)

            async def cancel(self, *args, **kwargs):
                return engine.cancel(*args, **kwargs)

        async def auth(headers):
            return Scope()

        app = A2AApplication(
            engine_for_scope=lambda scope: Async(),
            spec=AgentSpec("a", "Answer"),
            inbox=inbox,
            authenticate=auth,
            url="http://test/rpc",
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as http:
                client = A2AClient("http://test/rpc", client=http)
                task = await client.send_message("same", "task")
                assert (await client.send_message("same", "task"))["id"] == task["id"]
                assert (await client.get_by_message("same"))["id"] == task["id"]
                assert (await client.cancel_task(task["id"], command_id="cancel"))["status"][
                    "state"
                ] == "canceled"
        finally:
            inbox.close()
            engine.close()

    asyncio.run(run())


def test_scope_drift_during_inbox_completion_prevents_wakeup(tmp_path):
    async def run():
        engine = LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": EchoProvider("test")},
            tools=ToolRegistry(),
        )
        inner = SQLiteInbox(tmp_path / "inbox.sqlite")
        called = []

        class Inbox:
            async def accept(self, *args):
                return inner.accept(*args)

            async def complete(self, *args):
                inner.complete(*args)
                engine.scope = Scope("other", "owner")

            async def result(self, *args):
                return inner.result(*args)

            async def pending(self, *args, **kwargs):
                return inner.pending(*args, **kwargs)

            async def aclose(self):
                inner.close()

        async def auth(headers):
            return Scope()

        async def wakeup(scope, run_id):
            called.append(run_id)

        app = A2AApplication(
            engine_for_scope=lambda scope: engine,
            spec=AgentSpec("a", "Answer"),
            inbox=Inbox(),
            authenticate=auth,
            url="http://test/rpc",
            wakeup=wakeup,
        )
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as http:
                response = await http.post(
                    "http://test/rpc",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "message/send",
                        "params": {
                            "message": {
                                "kind": "message",
                                "role": "user",
                                "messageId": "same",
                                "parts": [{"kind": "text", "text": "task"}],
                            }
                        },
                    },
                )
                assert response.status_code == 401
                assert called == []
        finally:
            inner.close()
            engine.close()

    asyncio.run(run())
