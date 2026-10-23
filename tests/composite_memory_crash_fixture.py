"""Kill a real process at an original memory commit; keep audit outside its journal."""

import asyncio
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from relf_agent import (
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    SQLiteMemory,
    SQLiteStore,
    ToolRegistry,
)
from tests.test_composite_memory_stages import Provider, definition, policy, records

root, kind, window, mode, selection = Path(sys.argv[1]), *sys.argv[2:]


class Store(SQLiteStore):
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

    def emit(self, run_id, event, data=None):
        super().emit(run_id, event, data)
        if mode == "crash" and event == window:
            self.trigger = True


def audit(kind):
    with sqlite3.connect(root / "audit.sqlite") as db:
        db.execute("INSERT INTO calls VALUES (?)", (kind,))


class RecordedProvider(Provider):
    async def complete(self, messages, tools):
        audit(
            "selector"
            if messages[0]["content"].startswith("memory-field-selector:")
            else "business"
        )
        return await super().complete(messages, tools)


class Memory(SQLiteMemory):
    def put_fact(self, *args, **kwargs):
        audit("cas")
        result = super().put_fact(*args, **kwargs)
        if mode == "crash" and window == "cas_committed":
            os._exit(77)
        return result


with sqlite3.connect(root / "audit.sqlite") as db:
    db.execute("CREATE TABLE IF NOT EXISTS calls(kind TEXT)")
memory = Memory(root / "facts.sqlite")
spec = definition(kind)
if kind == "parallel":
    # Isolate this crash window from unrelated unconfirmed sibling model calls.
    a, b = spec.nodes
    spec = GraphWorkflowSpec(
        "graph", [a, GraphNode("b", agent=b.agent, depends_on=["a"])], max_concurrency=2
    )
with LocalEngine(
    Store(root / "runs.sqlite"),
    providers={"default": RecordedProvider()},
    tools=ToolRegistry(),
    stage_policy=policy(memory, selection),
) as local:
    if mode == "crash":
        h = local.submit(spec, "task", command_id="s", budget=32)
        (root / "run-id").write_text(h.run_id)
        asyncio.run(local.drive(h.run_id))
        raise AssertionError("Crash checkpoint was not reached")
    run_id = (root / "run-id").read_text()
    assert asyncio.run(local.drive(run_id)).state == "succeeded"
    assert all(r["status"] == "completed" for r in records(local, run_id))
    assert len(memory.facts(local.scope, "observations")) == 2
    assert local.diagnostics(run_id).budget["held"] == 0
    asyncio.run(local.drive(run_id))
memory.close()
