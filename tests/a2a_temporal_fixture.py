"""Shared HTTP process borrowing a Temporal facade and a PostgreSQL Inbox."""

import asyncio
import json
import os
import socket
import sys

import temporal_worker_fixture as fixture
import uvicorn
from temporalio.client import Client

from relf_agent import AgentSpec, Scope
from relf_agent.a2a import A2AApplication
from relf_agent.errors import AuthorizationDenied, ValidationError
from relf_agent.postgres_handoff import PostgresInbox
from relf_agent.temporal import TemporalEngine


async def main():
    port, fd, crash = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3] == "crash"
    runtime = await fixture.runtime()
    engine = TemporalEngine(
        await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"]),
        task_queue=os.environ["RALF_TEST_TEMPORAL_QUEUE"],
        release=runtime.manifest,
        scope=Scope(
            os.environ["RALF_TEST_SCOPE_WORKSPACE"], os.environ["RALF_TEST_SCOPE_PRINCIPAL"]
        ),
        activity_timeout=3,
        drive_timeout=10,
    )

    class Inbox(PostgresInbox):
        async def complete(self, scope, message, result):
            if crash:
                print("A2A_ACCEPTED_RUN " + json.dumps(result), flush=True)
                os._exit(78)
            await super().complete(scope, message, result)

    inbox = await Inbox.connect(os.environ["RALF_TEST_POSTGRES_DSN"], backend_id="http-shared")
    await inbox.initialize()

    async def auth(headers):
        if headers.get("authorization") != "Bearer test-owner":
            raise AuthorizationDenied("Rejected")
        return engine.scope

    async def wakeup(scope, run_id):
        await engine.drive(run_id, wait_seconds=2)

    class DiagnosedApplication(A2AApplication):
        async def _rpc(self, *args, **kwargs):
            try:
                return await super()._rpc(*args, **kwargs)
            except ValidationError as exc:
                # Test-only typed validation diagnostics; never request/credential data.
                print("A2A_VALIDATION_REJECTED " + str(exc), flush=True)
                raise

    app = DiagnosedApplication(
        engine_for_scope=lambda scope: engine,
        spec=AgentSpec("shared-http", "Answer"),
        inbox=inbox,
        authenticate=auth,
        wakeup=wakeup,
        url=f"http://127.0.0.1:{port}/rpc",
    )
    try:
        server = uvicorn.Server(
            uvicorn.Config(app, access_log=False, log_level="warning", lifespan="on")
        )
        await server.serve(sockets=[socket.socket(fileno=fd)])
    finally:
        await inbox.aclose()
        await engine.aclose()
        await runtime.journal.aclose()


if __name__ == "__main__":
    asyncio.run(main())
