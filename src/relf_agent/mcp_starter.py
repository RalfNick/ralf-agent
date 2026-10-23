"""Offline MCP application template contained in the installed package."""

MCP_FILES = {
    ".gitignore": ".ralf/\n__pycache__/\n.env\n",
    "agent_app/__init__.py": "",
    "agent_app/__main__.py": "from .runtime import main\n\nmain()\n",
    "agent_app/runtime.py": '''"""Edit the peer command/policies, or replace MCPToolSource with your own source."""
import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

from relf_agent import (GraphNode, GraphWorkflowSpec, LocalEngine, MCPStdioTransport,
    MCPToolSource, SQLiteStore, ToolPolicy, ToolRegistry, ValueRef, register_tool_source)


def create_engine(db_path):
    root = Path(__file__).resolve().parent.parent
    peer = root / "mcp_server.py"
    registry = ToolRegistry()
    source = MCPToolSource(MCPStdioTransport(
        [sys.executable, str(peer), str(Path(db_path).resolve().parent / "business.sqlite")],
        version=hashlib.sha256(peer.read_bytes()).hexdigest(), cwd=root,
    ))
    asyncio.run(register_tool_source(registry, source, policies={
        "apply_change": ToolPolicy("1", effect="idempotent_write", requires_approval=True,
                                   effect_key_argument="effect_key"),
    }, prefix="mcp_"))
    return LocalEngine(SQLiteStore(db_path), providers={}, tools=registry)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--value", type=int, default=3)
    parser.add_argument("--command-id", default="first-change")
    args = parser.parse_args()
    flow = GraphWorkflowSpec("mcp-change", [GraphNode("apply", tool="mcp_apply_change")],
                             output=ValueRef("apply"))
    with create_engine(".ralf/runs.sqlite") as engine:
        handle = engine.submit(flow, {"value": args.value}, command_id=args.command_id)
        print(json.dumps(asdict(asyncio.run(engine.drive(handle.run_id))), ensure_ascii=False))
''',
    "mcp_server.py": '''"""An offline MCP business fixture; this process is trusted, not sandboxed."""
import json
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
schema = {"type": "object", "properties": {"value": {"type": "integer"},
          "effect_key": {"type": "string"}}, "required": ["value", "effect_key"],
          "additionalProperties": False}
tool = {"name": "apply_change", "description": "Apply one offline business change",
        "inputSchema": schema, "outputSchema": {"type": "object", "required": ["value", "effect_key"]}}
initialized = False
for line in sys.stdin:
    message = json.loads(line)
    method = message["method"]
    if method == "notifications/initialized":
        initialized = True
        continue
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "ralf-offline-business", "version": "1"}}
    elif method == "tools/list":
        assert initialized
        result = {"tools": [tool]}
    elif method == "tools/call":
        assert initialized and message["params"]["name"] == "apply_change"
        arguments = message["params"]["arguments"]
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS effects (effect_key TEXT PRIMARY KEY, result TEXT NOT NULL)")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT result FROM effects WHERE effect_key=?", (arguments["effect_key"],)).fetchone()
            if row:
                output = json.loads(row[0])
            else:
                output = {"value": arguments["value"], "effect_key": arguments["effect_key"]}
                connection.execute("INSERT INTO effects VALUES (?,?)", (arguments["effect_key"], json.dumps(output)))
        result = {"content": [{"type": "text", "text": "Change confirmed"}],
                  "structuredContent": output, "isError": False}
    else:
        raise ValueError("Unsupported fixture method")
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
''',
    "README.md": """# Managed MCP tool example

Run `python -m agent_app --value 3 --command-id first-change`.
Inspect the returned Run ID with:

```sh
relf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

Approve using the printed command, then resume with the retained factory:

```sh
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

The graph executes a Tool node without a model. The local MCP peer deduplicates
writes by the framework-injected effect_key. Repeating the same submission returns
the original Run. Edit the explicit command and policies in agent_app/runtime.py;
retain old peer code/configuration for historical Runs. Remote annotations never
replace the host's effect/approval policy. The stdio peer is trusted code; process
management does not provide a sandbox. This offline fixture proves the execution
path, not model quality or compatibility with every external MCP server.
""",
}
