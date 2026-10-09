"""Isolated loopback HTTP service using a real native SQLite Run authority."""

import asyncio
import json
import socket
import sys
from pathlib import Path

import uvicorn

from ralf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, ToolRegistry
from ralf_agent.a2a import A2AApplication
from ralf_agent.errors import AuthorizationDenied
from ralf_agent.handoff import SQLiteInbox
from ralf_agent.storage import SQLiteStore


class Provider:
    identity = {"kind": "loopback-test", "version": "1"}

    async def complete(self, messages, tools):
        request = json.loads(messages[-1]["content"])["a2a"]["message"]["parts"][0]["data"]["input"]
        if request.get("wait"):
            await asyncio.sleep(0.05)
        return ModelResponse(output={"echo": request})


def main():
    directory, port, fd = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    runtime = LocalEngine(
        SQLiteStore(directory / "runs.db"), providers={"default": Provider()}, tools=ToolRegistry()
    )
    inbox = SQLiteInbox(directory / "inbox.db")
    active = set()

    async def authenticate(headers):
        if headers.get("authorization") != "Bearer test-owner":
            raise AuthorizationDenied("Rejected")
        return Scope()

    async def wakeup(scope, run_id):
        if runtime.status(run_id).state == "queued":
            task = asyncio.create_task(runtime.drive(run_id))
            active.add(task)
            task.add_done_callback(active.discard)

    app = A2AApplication(
        engine_for_scope=lambda scope: runtime,
        spec=AgentSpec("loopback", "Echo input"),
        inbox=inbox,
        authenticate=authenticate,
        url=f"http://127.0.0.1:{port}/rpc",
        wakeup=wakeup,
    )

    async def service(scope, receive, send):
        if scope["type"] != "lifespan":
            return await app(scope, receive, send)
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)
                await runtime.wait_for_threads()
                inbox.close()
                runtime.close()
                await send({"type": "lifespan.shutdown.complete"})
                return

    server = uvicorn.Server(
        uvicorn.Config(service, access_log=False, log_level="warning", lifespan="on")
    )
    server.run(sockets=[socket.socket(fileno=fd)])


if __name__ == "__main__":
    main()
