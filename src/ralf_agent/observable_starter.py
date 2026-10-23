"""Installed observable application; deterministic read-only model fixture."""

OBSERVABLE_FILES = {
    "agent_app/__init__.py": "from .runtime import create_engine\n",
    "agent_app/runtime.py": """import json
from ralf_agent import (
    ComponentRegistry, ModelResponse, RuntimeBuilder, RuntimeProfile, ToolCall, ToolRegistry,
)

class FixtureProvider:
    identity = {"kind": "offline-observable-fixture", "version": "1"}

    async def complete(self, messages, tools):
        for message in reversed(messages):
            if message["role"] == "tool":
                return ModelResponse(json.loads(message["content"]))
        task = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
        return ModelResponse(tool_calls=(ToolCall("lookup", {"record_id": task["record_id"]}, "lookup"),))

def create_engine(db_path=".ralf/runs.sqlite", *, scope=None):
    registry = ComponentRegistry()
    def empty_config(config):
        if config:
            raise ValueError("Observable fixture configuration must be empty")
    registry.register("provider", "observable-fixture", lambda c, ctx: FixtureProvider(),
                      validator=empty_config)
    def tools(config, context):
        registry = ToolRegistry()
        @registry.tool(effect="read_only", description="Read a fixture record")
        def lookup(record_id: str):
            return {"record_id": record_id, "status": "available"}
        return registry
    registry.register("tools", "fixture-records", tools)
    profile = RuntimeProfile("observable", "1", {
        "default": {"adapter": "middleware", "config": {
            "provider": {"adapter": "observable-fixture"}, "logging": True,
        }},
    }, components={
        "tools": {"adapter": "fixture-records"},
        "tool_executor": {"adapter": "middleware-python", "config": {"logging": True}},
    })
    return RuntimeBuilder(registry).build(profile, db_path, scope=scope)
""",
    "agent_app/__main__.py": """import argparse
import asyncio
import json
from dataclasses import asdict
from ralf_agent import AgentSpec, RunEventSubscription
from .runtime import create_engine

async def run(args):
    with create_engine(args.db) as engine:
        handle = engine.submit(AgentSpec("record", "Read the fixture record.", ("lookup",)),
                               {"record_id": args.record}, command_id=args.command_id)
        drive = asyncio.create_task(engine.drive(handle.run_id))
        stream = RunEventSubscription(engine, handle.run_id, poll_interval=0.01)
        async def watch_drive():
            result = await drive
            if result.state not in {"succeeded", "failed", "cancelled"}:
                await stream.aclose()
        watcher = asyncio.create_task(watch_drive())
        try:
            async for record in stream:
                print(json.dumps({"type": "event", **record.to_dict()}, ensure_ascii=False), flush=True)
        finally:
            await stream.aclose()
            # Observation never cancels execution. This application owns and
            # joins its finite fixture drive before releasing the coordinator.
            snapshot = await drive
            await watcher
        if snapshot.state not in {"succeeded", "failed", "cancelled"}:
            # Drain the pause events already committed before reporting a pause.
            async for record in RunEventSubscription(engine, handle.run_id,
                                                     after=stream.cursor, follow=False):
                print(json.dumps({"type": "event", **record.to_dict()}, ensure_ascii=False), flush=True)
        print(json.dumps({"type": "result", "handle": asdict(handle),
                          "snapshot": asdict(snapshot), "model_quality": None}), flush=True)

parser = argparse.ArgumentParser(description="Offline middleware and committed event demo")
parser.add_argument("--db", default=".ralf/runs.sqlite")
parser.add_argument("--record", default="REC-001")
parser.add_argument("--command-id", default="observable-demo")
asyncio.run(run(parser.parse_args()))
""",
    "README.md": """# Observable starter

Install relf-agent, then run `python -m agent_app` from this directory.
The model is a deterministic fixture with one typed read-only lookup tool;
`model_quality` is null. Output is NDJSON committed events followed by the result.
Run the same command again to reuse its original receipt, or provide a new
`--command-id` when changing `--record`. No model credentials or paid calls.

Middleware logs only phase/operation/payload SHA256; hook errors after completed
responses do not discard receipts. Replace the registered Provider/tools or
construct SDK middleware explicitly in runtime.py. Secrets use host context/config.

Use `ralf-watch-events --db .ralf/runs.sqlite --run-id RUN_ID` to read stored events;
`--follow` is explicit, `--sse` encodes SSE frames, and `--after-cursor TOKEN` resumes
from a saved cursor_token. Tokens bind Scope/Run/sequence, not authentication.
Save only consumed cursor tokens. Closing observation leaves execution running.
This application explicitly owns/joins its finite drive before Engine shutdown.

Polling observes durable events, not live model text tokens. No HTTP server,
WebSocket, input continuation, workspace tools or container Sandbox is delivered
by this template. See the SDK middleware/event guide for lifecycle/limits.
""",
    ".gitignore": ".ralf/\n__pycache__/\n",
}
