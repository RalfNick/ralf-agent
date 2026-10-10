"""Actual process death after original composite auxiliary commits."""

import asyncio
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from ralf_agent import LocalEngine, SQLiteArtifactStore, SQLiteStore
from tests.test_composite_data_context import Provider, definition, registry
from tests.test_managed_data_context import context

root, kind, window, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
relevant = len(sys.argv) == 6 and sys.argv[5] == "relevant"


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


class RecordedProvider(Provider):
    async def complete(self, messages, tools):
        kind = "summary" if messages[0]["content"].startswith("context-summary:") else "business"
        with sqlite3.connect(root / "business.sqlite") as db:
            db.execute("INSERT INTO calls VALUES (?)", (kind,))
        return await super().complete(messages, tools)


class Artifacts(SQLiteArtifactStore):
    def put(self, *args, **kwargs):
        with sqlite3.connect(root / "business.sqlite") as db:
            db.execute("INSERT INTO calls VALUES ('artifact')")
        result = super().put(*args, **kwargs)
        if mode == "crash" and window == "artifact_commit":
            os._exit(77)
        return result


with sqlite3.connect(root / "business.sqlite") as db:
    db.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, result TEXT)")
artifacts = Artifacts(root / "artifacts.sqlite")
tools = registry([])
registered = tools.get("lookup")
original = registered.handler


async def lookup(arguments, invocation):
    value = original(arguments, invocation)
    with sqlite3.connect(root / "business.sqlite") as db:
        db.execute("INSERT INTO calls VALUES ('tool')")
        db.execute(
            "INSERT OR IGNORE INTO effects VALUES (?,?)", (invocation.effect_key, json.dumps(value))
        )
    return value


def reconcile(arguments, invocation):
    with sqlite3.connect(root / "business.sqlite") as db:
        row = db.execute(
            "SELECT result FROM effects WHERE key=?", (invocation.effect_key,)
        ).fetchone()
    return None if row is None else json.loads(row[0])


tools = type(tools)()
tools.register(replace(registered.spec, effect="idempotent_write"), lookup, reconciler=reconcile)
if relevant:
    from ralf_agent import RelevantDataContext

    builder = RelevantDataContext(
        artifacts, tool_result_chars=1024, preview_chars=64, mode="model", summary_max_chars=256
    )
else:
    builder = context(artifacts, mode="model", summary_max_chars=256)
with LocalEngine(
    Store(root / "runs.sqlite"),
    providers={"default": RecordedProvider()},
    tools=tools,
    context_assembler=builder,
) as engine:
    if mode == "crash":
        if relevant:
            for namespace in ("a", "b"):
                engine.memory.put_fact(
                    engine.scope,
                    namespace,
                    "language",
                    "task preferred language zh-CN",
                    expected_version=0,
                )
        h = engine.submit(definition(kind), "task", command_id="s", budget=32)
        (root / "run-id").write_text(h.run_id)
    else:
        run_id = (root / "run-id").read_text()
        result = asyncio.run(engine.drive(run_id))
        assert result.state == "succeeded", result
        assert (
            all(
                r["status"] in {"completed", "outcome_unknown"}
                for r in engine.context_stages(run_id)
            )
            if kind in {"graph", "parallel"}
            else True
        )
        sys.exit(0)
    asyncio.run(engine.drive(h.run_id))
