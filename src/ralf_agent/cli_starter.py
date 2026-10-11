"""Installed fixed-command business tool example with async resource ownership."""

CLI_FILES = {
    ".gitignore": ".ralf/\n__pycache__/\n.env\n",
    "agent_app/__init__.py": "",
    "agent_app/__main__.py": "from .runtime import main\n\nmain()\n",
    "agent_app/runtime.py": '''"""Configure a trusted program or replace tools/cli-json with another factory."""
import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

from ralf_agent import GraphNode, GraphWorkflowSpec, RuntimeBuilder, RuntimeProfile, ValueRef


async def create_runtime(db_path):
    root = Path(__file__).resolve().parent.parent
    business = root / "business_tool.py"
    descriptor = {"name": "apply_change", "description": "Apply one business change",
        "input_schema": {"type": "object", "properties": {"value": {"type": "integer"},
            "effect_key": {"type": "string"}}, "required": ["value", "effect_key"],
            "additionalProperties": False},
        "output_schema": {"type": "object", "properties": {"value": {"type": "integer"},
            "effect_key": {"type": "string"}}, "required": ["value", "effect_key"],
            "additionalProperties": False}}
    selected = RuntimeProfile("cli-change", "1", {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "cli-json", "config": {"tools": [{
            "descriptor": descriptor,
            "command": [sys.executable, str(business), str(Path(db_path).resolve().parent / "business.sqlite")],
            "version": hashlib.sha256(business.read_bytes()).hexdigest(),
            "cwd": str(root), "prefix": "cli_",
            "policy": {"version": "1", "effect": "idempotent_write", "requires_approval": True,
                       "effect_key_argument": "effect_key"}}]}}})
    return await RuntimeBuilder(base_dir=root).abuild(selected, db_path)


async def execute(args):
    async with await create_runtime(args.db) as runtime:
        if args.operation == "approve":
            return asdict(runtime.approve(args.run_id, args.action_id, args.digest,
                                          command_id=args.command_id))
        if args.operation == "resume":
            return asdict(await runtime.drive(args.run_id))
        flow = GraphWorkflowSpec("cli-change", [GraphNode("apply", tool="cli_apply_change")],
                                 output=ValueRef("apply"))
        handle = runtime.submit(flow, {"value": args.value}, command_id=args.command_id)
        return asdict(await runtime.drive(handle.run_id))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    commands = parser.add_subparsers(dest="operation", required=True)
    run = commands.add_parser("run")
    run.add_argument("--value", type=int, default=3)
    run.add_argument("--command-id", default="first-change")
    approve = commands.add_parser("approve")
    approve.add_argument("run_id")
    approve.add_argument("action_id")
    approve.add_argument("--digest", required=True)
    approve.add_argument("--command-id", required=True)
    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    print(json.dumps(asyncio.run(execute(parser.parse_args())), ensure_ascii=False, allow_nan=False))
''',
    "business_tool.py": '''"""Trusted local JSON command; business system owns effect-key deduplication."""
import json
import sqlite3
import sys
from pathlib import Path

arguments = json.load(sys.stdin)
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
with (path.parent / "call-audit").open("a") as audit:
    audit.write("call\\n")
with sqlite3.connect(path) as connection:
    connection.execute("CREATE TABLE IF NOT EXISTS effects (effect_key TEXT PRIMARY KEY, result TEXT NOT NULL)")
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute("SELECT result FROM effects WHERE effect_key=?", (arguments["effect_key"],)).fetchone()
    if row:
        result = json.loads(row[0])
    else:
        result = {"value": arguments["value"], "effect_key": arguments["effect_key"]}
        connection.execute("INSERT INTO effects VALUES (?,?)", (arguments["effect_key"], json.dumps(result)))
print(json.dumps(result), flush=True)
''',
    "README.md": """# Fixed-command JSON tools

Run `python -m agent_app run --value 3 --command-id first-change`.
The business command waits for approval before starting. Copy Run ID, Action ID
and digest from the returned pending entry:

```sh
python -m agent_app approve RUN_ID ACTION_ID --digest DIGEST --command-id approve-change
python -m agent_app resume RUN_ID
```

Repeat controls or the original submission to recover the same receipt and Run.
The downstream fixture deduplicates by the injected effect_key. `ralf --db
.ralf/runs.sqlite inspect RUN_ID` can read evidence; this application's commands
own async construction and cleanup, so it does not use a synchronous `--factory`.

Replace the fixed absolute executable/argv, descriptor and explicit ToolPolicy
in agent_app/runtime.py. Inputs are JSON stdin, output is bounded JSON stdout.
Retain original code, executable environment and Profile for historical recovery.
An arbitrary command's dependencies are the host's responsibility. This example
runs trusted code; it provides process management, not a security sandbox or
external Coding Agent. No model or network service is required.
""",
}
