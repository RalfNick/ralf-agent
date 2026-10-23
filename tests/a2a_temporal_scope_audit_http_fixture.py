"""Two authenticated Scope facades borrowing one original Temporal deployment."""

import asyncio
import json
import os
import socket
import sys
from dataclasses import asdict
from pathlib import Path

import uvicorn
from temporalio.client import Client

from relf_agent import AgentSpec, Scope
from relf_agent.a2a import A2AApplication
from relf_agent.errors import AuthorizationDenied
from relf_agent.handoff import SQLiteInbox
from relf_agent.service_audit import ServiceAudit
from relf_agent.temporal import TemporalEngine


async def main():
    directory, fd = Path(sys.argv[1]), int(sys.argv[2])
    settings = json.loads((directory / "scope-host.json").read_text())
    client = await Client.connect(
        os.environ["RALF_TEST_TEMPORAL_ADDRESS"], namespace=settings["namespace"]
    )
    scopes = {name: Scope(**value) for name, value in settings["scopes"].items()}
    engines = {
        scope: TemporalEngine(
            client,
            task_queue=settings["queue"],
            release=settings["release"],
            scope=scope,
            activity_timeout=5,
            drive_timeout=30,
        )
        for scope in scopes.values()
    }
    inbox = SQLiteInbox(directory / "scope-inbox.sqlite")
    audit = ServiceAudit(key=b"t" * 32)

    async def authenticate(headers):
        for name, scope in scopes.items():
            if headers.get("authorization") == "Bearer " + name:
                return scope
        raise AuthorizationDenied("credential-secret")

    async def recovery(scope, run_id):
        await engines[scope].drive(run_id, wait_seconds=0)

    listener = socket.socket(fileno=fd)
    application = A2AApplication(
        engine_for_scope=engines.__getitem__,
        spec=AgentSpec("writer", "Write once", ("write",)),
        inbox=inbox,
        authenticate=authenticate,
        url=f"http://127.0.0.1:{listener.getsockname()[1]}/rpc",
        enable_run_events=True,
        enable_run_controls=True,
        recovery_wakeup=recovery,
        audit=audit,
    )

    async def close_resources():
        for engine in engines.values():
            await engine.aclose()
        inbox.close()
        (directory / f"scope-host-closed-{os.getpid()}.json").write_text(
            json.dumps(
                {
                    "engines_closed": all(engine._closed for engine in engines.values()),
                    "inbox_closed": inbox._closed,
                    "records": [asdict(record) for record in audit.sink.records],
                    "failures": audit.failures,
                    "dropped": audit.sink.dropped,
                }
            )
        )

    async def hosted(scope, receive, send):
        if scope["type"] != "lifespan":
            return await application(scope, receive, send)
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await close_resources()
                await send({"type": "lifespan.shutdown.complete"})
                return

    try:
        server = uvicorn.Server(
            uvicorn.Config(hosted, access_log=False, log_level="warning", lifespan="on")
        )
        await server.serve(sockets=[listener])
    finally:
        await close_resources()
        listener.close()


if __name__ == "__main__":
    asyncio.run(main())
