"""Owned loopback service using the actual control integration fixture."""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

from tests.test_a2a_run_controls import hosted


async def main():
    directory, fd, uncertain = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3] == "uncertain"
    async with hosted(directory, uncertain=uncertain) as (service, engine, _, _):

        async def observed(scope, receive, send):
            async def acknowledge(message):
                if message["type"] == "lifespan.shutdown.complete":
                    (directory / f"shutdown-{os.getpid()}.json").write_text(
                        json.dumps(
                            {
                                "service_closed": service.closed,
                                "engine_closed": engine._lifecycle == "closed",
                                "active_drives": sum(
                                    not task.done() for task in service._active.values()
                                ),
                                "active_threads": engine._threads.active_count,
                            }
                        )
                    )
                await send(message)

            await service(scope, receive, acknowledge)

        # Bind the published path to the inherited listening socket.
        server = uvicorn.Server(
            uvicorn.Config(observed, access_log=False, log_level="warning", lifespan="on")
        )
        await server.serve(sockets=[socket.socket(fileno=fd)])


if __name__ == "__main__":
    asyncio.run(main())
