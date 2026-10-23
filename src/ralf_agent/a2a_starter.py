"""Installed, editable local HTTP service with explicit single-owner credentials."""

A2A_FILES = {
    ".gitignore": ".ralf/\n__pycache__/\n.env\n",
    "agent_app/__init__.py": "",
    "agent_app/__main__.py": "from .runtime import main\n\nmain()\n",
    "agent_app/runtime.py": r'''"""Offline echo over real HTTP; replace Provider/tools explicitly."""

import argparse
import asyncio
import json
import os
import secrets
from pathlib import Path

from ralf_agent import (
    A2AClient, AgentSpec, LocalA2AService, LocalEngine, ModelResponse,
    Scope, SQLiteInbox, SQLiteStore, ToolRegistry,
)
from ralf_agent.errors import AuthorizationDenied, ValidationError


class OfflineProvider:
    identity = {"kind": "a2a-starter-offline", "version": "1"}

    async def complete(self, messages, tools):
        wire = json.loads(messages[1]["content"])["a2a"]["message"]
        parts = wire["parts"]
        if len(parts) == 1 and parts[0]["kind"] == "data":
            value = parts[0]["data"]["input"]
        else:
            value = "\n".join(part["text"] for part in parts if part["kind"] == "text")
        return ModelResponse(output={"echo": value})


def create_engine(db_path):
    return LocalEngine(SQLiteStore(db_path), providers={"default": OfflineProvider()},
                       tools=ToolRegistry(), scope=Scope())


def token():
    value = os.environ.get("RALF_A2A_TOKEN")
    if not value or not value.strip():
        raise ValidationError("Set RALF_A2A_TOKEN locally before serving or calling")
    return value


def create_service(db_path, url):
    credential = token()

    async def authenticate(headers):
        actual = headers.get("authorization", "")
        if not secrets.compare_digest(actual.encode(), ("Bearer " + credential).encode()):
            raise AuthorizationDenied("Rejected")
        return Scope()

    engine = create_engine(db_path)
    inbox = None
    try:
        inbox = SQLiteInbox(str(Path(db_path).resolve()) + ".inbox.sqlite")
        return LocalA2AService(engine=engine, inbox=inbox,
            spec=AgentSpec("a2a-starter", "Echo the provided input"),
            authenticate=authenticate, url=url)
    except BaseException:
        engine.close()
        if inbox is not None:
            inbox.close()
        raise


async def request(args):
    client = A2AClient(args.url, headers={"Authorization":"Bearer " + token()})
    try:
        if args.task:
            return await client.get_task(args.task)
        return await client.send_message(args.command_id, args.input)
    finally:
        await client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--db", default=".ralf/runs.sqlite")
    serve.add_argument("--port", type=int, default=8000)
    client = commands.add_parser("client")
    client.add_argument("--url", default="http://127.0.0.1:8000/rpc")
    client.add_argument("--input", default="hello")
    client.add_argument("--command-id", default="first")
    client.add_argument("--task")
    args = parser.parse_args()
    try:
        if args.command == "serve":
            if not 1 <= args.port <= 65535:
                parser.error("Port must be 1..65535")
            try:
                import uvicorn
            except ImportError:
                parser.error("Install relf-agent[server] to serve HTTP")
            service = create_service(args.db, f"http://127.0.0.1:{args.port}/rpc")
            # This local authority is a single-worker application instance.
            uvicorn.run(service, host="127.0.0.1", port=args.port, lifespan="on", access_log=False)
        else:
            print(json.dumps(asyncio.run(request(args)), ensure_ascii=False))
    except ValidationError as exc:
        parser.error(str(exc))
''',
    "README.md": """# Local A2A service starter

Install relf-agent[server]. Set RALF_A2A_TOKEN locally to a fresh owner credential
in both terminals; no token is generated or printed by this application.
Run from this directory:

```shell
python -m agent_app serve --port 8000
```

In another terminal from the same directory:

```shell
python -m agent_app client --input hello --command-id first
python -m agent_app client --input hello --command-id first
python -m agent_app client --task TASK_ID
ralf --db .ralf/runs.sqlite --format text inspect TASK_ID
```

The Provider is offline Echo; HTTP and durable Run/Inbox are real, with no paid
model calls. Keep the generated definitions and identities for restart recovery.
The same message retains its original Run. Task acceptance and completion differ;
poll the original Task to observe completion. Change command IDs for new input.

LocalA2AService owns the local Engine/Inbox, tracks drives and drains real handlers
before closing. This default has one HTTP worker/one local coordinator. For shared
multi-worker deployment, compose A2AApplication with TemporalEngine and PostgresInbox
as documented in the async handoff guide. Host authentication is a single trusted
owner mapping, not an enterprise identity/ACL service. Extend it explicitly.
""",
}
