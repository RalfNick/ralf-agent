"""Real receiver and commit-window crashes for isolated parallel frames."""

import asyncio
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from ralf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)

root, window, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]


class CrashStore(SQLiteStore):
    depth = 0
    trigger = False

    @contextmanager
    def transaction(self):
        self.depth += 1
        try:
            with super().transaction():
                yield
        finally:
            self.depth -= 1
        if not self.depth and self.trigger:
            os._exit(77)

    def emit(self, run_id, kind, data=None):
        super().emit(run_id, kind, data)
        if mode == "crash" and kind == window:
            self.trigger = True


class Provider:
    identity = {"kind": "parallel-crash", "version": "1"}

    async def complete(self, messages, tools):
        i = int(messages[1]["content"])
        with sqlite3.connect(root / "business.sqlite") as db:
            db.execute("INSERT INTO model_calls VALUES (?)", (i,))
        await asyncio.sleep(0)
        if not any(m["role"] == "tool" for m in messages):
            return ModelResponse(tool_calls=(ToolCall("write", {"i": i}),))
        return ModelResponse(output={"i": i})


with sqlite3.connect(root / "business.sqlite") as db:
    db.execute("CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, value INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS model_calls (value INTEGER)")


def write(arguments, ctx):
    with sqlite3.connect(root / "business.sqlite") as db:
        db.execute("INSERT OR IGNORE INTO effects VALUES (?,?)", (ctx.effect_key, arguments["i"]))
    if mode == "crash" and window == "external_commit":
        os._exit(77)
    return {"i": arguments["i"]}


def reconcile(arguments, ctx):
    with sqlite3.connect(root / "business.sqlite") as db:
        row = db.execute("SELECT value FROM effects WHERE key=?", (ctx.effect_key,)).fetchone()
    return None if row is None else {"i": row[0]}


registry = ToolRegistry()
registry.register(
    ToolSpec("write", "Write", {"type": "object"}, effect="idempotent_write"),
    write,
    reconciler=reconcile,
)
with LocalEngine(
    CrashStore(root / "run.sqlite"), providers={"default": Provider()}, tools=registry
) as engine:
    if mode == "crash" and window == "session_append":
        original = engine.sessions.append

        def append(*args, **kwargs):
            value = original(*args, **kwargs)
            os._exit(77)
            return value

        engine.sessions.append = append
    from ralf_agent import Literal

    spec = GraphWorkflowSpec(
        "crash",
        [
            GraphNode(
                f"n{i}", agent=AgentSpec(f"a{i}", "A", tools=("write",)), input=Literal(str(i))
            )
            for i in range(2)
        ],
        max_concurrency=2,
    )
    handle = engine.submit(spec, {}, command_id="s")
    result = asyncio.run(engine.drive(handle.run_id))
    with sqlite3.connect(root / "business.sqlite") as db:
        effects = db.execute("SELECT count(*) FROM effects").fetchone()[0]
        calls = db.execute("SELECT count(*) FROM model_calls").fetchone()[0]
    print(
        json.dumps(
            {
                "state": result.state,
                "result": result.result,
                "effects": effects,
                "model_calls": calls,
            }
        )
    )
