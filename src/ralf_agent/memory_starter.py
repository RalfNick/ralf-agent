"""Installed offline automatic memory application; real models are explicit."""

MEMORY_FILES = {
    "agent_app/__init__.py": "",
    "agent_app/__main__.py": "from .runtime import main\nraise SystemExit(main())\n",
    "agent_app/runtime.py": '''"""Edit result fields and admission policy for your application."""
import argparse
import asyncio
import json

from ralf_agent import (
    AgentSpec, LocalEngine, MemoryAdmissionPolicy, MemoryPipeline,
    ModelResponse, SQLiteStore, ToolRegistry,
)


class OfflineProvider:
    identity = {"kind": "offline-memory-starter", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output={"language": "zh-CN", "project": "RALF"})


def create_engine(db_path):
    return LocalEngine(SQLiteStore(db_path), providers={"default": OfflineProvider()}, tools=ToolRegistry())


async def run(args):
    with create_engine(args.db) as engine:
        policy = MemoryAdmissionPolicy({"language": ("result", "language"), "project": ("result", "project")})
        return await MemoryPipeline(engine, policy=policy).run(AgentSpec("preferences", "Return observed preferences as JSON with language and project"), args.input, command_id=args.command_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    parser.add_argument("--input", default="Remember project RALF and language zh-CN")
    parser.add_argument("--command-id", default="memory-first")
    result = asyncio.run(run(parser.parse_args(argv)))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["task"]["state"] == "succeeded" and result["memory"]["status"] == "completed" else 1
''',
    "README.md": """# Automatic sourced memory

Run `python -m agent_app` from this directory after installing ralf-agent.
The offline provider returns fixture preferences; rule extraction has zero model
calls. SQLite execution and facts persist under `.ralf/runs.sqlite`. Repeat the
command or restart the process to recover the same task and memory observations.

Edit runtime.py to supply your Provider and result fields. Select
ModelMemoryExtractor(policy) explicitly to use a separate one-credit managed
extraction Run. Every value is checked against the host allowlisted source path;
observations are untrusted evidence, not authorization or confirmed truth.
Business and memory receipts are separate; memory failure does not undo business
success. Partial admission is resumable; multi-fact admission is not atomic.
Borrowed memory/provider resources are owned and closed by your application.
""",
}
