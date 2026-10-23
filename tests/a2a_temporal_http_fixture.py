"""Borrow the actual Temporal authority in an independently restarted HTTP host."""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn
from temporalio.client import Client

from relf_agent import AgentSpec, Scope
from relf_agent.a2a import A2AApplication
from relf_agent.errors import AuthorizationDenied
from relf_agent.handoff import SQLiteInbox
from relf_agent.temporal import TemporalEngine


async def main():
    directory, fd = Path(sys.argv[1]), int(sys.argv[2])
    settings = json.loads((directory / "host.json").read_text())
    client = await Client.connect(
        os.environ["RALF_TEST_TEMPORAL_ADDRESS"], namespace=settings["namespace"]
    )
    scope = Scope(**settings["scope"])
    engine = TemporalEngine(
        client,
        task_queue=settings["queue"],
        release=settings["release"],
        scope=scope,
        activity_timeout=5,
        drive_timeout=30,
    )
    inbox = SQLiteInbox(directory / "inbox.sqlite", max_entries=1)

    async def authenticate(headers):
        if headers.get("authorization") != "Bearer owner":
            raise AuthorizationDenied("Rejected")
        return scope

    async def recovery(trusted, run_id):
        assert trusted == scope
        await engine.drive(run_id, wait_seconds=0)

    listener = socket.socket(fileno=fd)
    application = A2AApplication(
        engine_for_scope=lambda trusted: engine,
        spec=AgentSpec("writer", "Write once", ("write",)),
        inbox=inbox,
        authenticate=authenticate,
        url=f"http://127.0.0.1:{listener.getsockname()[1]}/rpc",
        enable_run_events=True,
        enable_run_controls=True,
        recovery_wakeup=recovery,
    )

    async def close_resources():
        await engine.aclose()
        inbox.close()
        (directory / f"host-closed-{os.getpid()}.json").write_text(
            json.dumps(
                {
                    "engine_closed": engine._closed,
                    "inbox_closed": inbox._closed,
                }
            )
        )

    async def hosted(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    # The host owns these resources. Uvicorn can re-raise SIGTERM
                    # before serve() returns, so close before acknowledging it.
                    await close_resources()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            await application(scope, receive, send)

    server = uvicorn.Server(
        uvicorn.Config(hosted, access_log=False, log_level="warning", lifespan="on")
    )
    try:
        await server.serve(sockets=[listener])
    finally:
        await close_resources()
        listener.close()


if __name__ == "__main__":
    asyncio.run(main())
