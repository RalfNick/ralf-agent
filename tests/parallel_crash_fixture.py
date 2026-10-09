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
binding_mode = sys.argv[4] if len(sys.argv) > 4 else None


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


class UnusedProvider:
    identity = {"kind": "must-not-be-selected", "version": "1"}

    async def complete(self, messages, tools):
        raise AssertionError("A bound worker fell back to the host model")


catalog = None
if binding_mode is not None:
    from ralf_agent import BindingCatalog, Scope

    catalog = BindingCatalog(scope=Scope())
    catalog.register("provider", "selected", "1", Provider())
with LocalEngine(
    CrashStore(root / "run.sqlite"),
    providers={"default": Provider() if binding_mode is None else UnusedProvider()},
    tools=registry,
    binding_catalog=catalog,
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
    if binding_mode is not None:
        from ralf_agent import AgentBindingDescriptor, BindingSelection, BoundDefinition, TeamSpec

        paths = {
            f"graph/nodes/n{i}": AgentBindingDescriptor(
                provider=BindingSelection.ref("selected", "1")
            )
            for i in range(2)
        }
        if binding_mode == "nested":
            spec = TeamSpec("outer", {"graph": spec}, child_budget=16)
            paths = {"team/members/graph/" + path: value for path, value in paths.items()}
        spec = BoundDefinition(spec, paths)
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
                "kernel": engine.diagnostics(handle.run_id).manifest["kernel"],
            }
        )
    )
