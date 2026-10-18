"""Owned loopback host; shutdown JSON is test evidence, not a log backend."""

import asyncio
import json
import os
import socket
import sys
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

import uvicorn

from ralf_agent.service_audit import ServiceAudit
from tests.test_a2a_scope_isolation import SCOPES, hosted


async def main():
    directory, fd = Path(sys.argv[1]), int(sys.argv[2])
    audit = ServiceAudit(key=b"a" * 32)
    with ExitStack() as resources:
        app, select = resources.enter_context(hosted(directory, audit=audit))

        async def service(scope, receive, send):
            if scope["type"] != "lifespan":
                return await app(scope, receive, send)
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    engine = select(SCOPES["alice"])
                    resources.close()
                    evidence = {
                        "hosted_closed": True,
                        "engine_closed": engine._lifecycle == "closed",
                        "active_drives": len(engine._active),
                        "active_threads": engine._threads.active_count,
                        "records": [asdict(record) for record in audit.sink.records],
                        "failures": audit.failures,
                        "dropped": audit.sink.dropped,
                    }
                    (directory / f"shutdown-{os.getpid()}.json").write_text(json.dumps(evidence))
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        server = uvicorn.Server(
            uvicorn.Config(service, access_log=False, log_level="warning", lifespan="on")
        )
        await server.serve(sockets=[socket.socket(fileno=fd)])


if __name__ == "__main__":
    asyncio.run(main())
