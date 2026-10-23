"""Actual process death after original composite auxiliary commits."""

import asyncio
import json
import os
import sqlite3
import sys
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path

from relf_agent import FileArtifactStore, LocalEngine, SQLiteArtifactStore, SQLiteStore
from relf_agent.errors import NotFound
from tests.test_composite_data_context import Provider, definition, registry
from tests.test_managed_data_context import context

root, kind, window, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
relevant = "relevant" in sys.argv[5:]
file_artifacts = "file" in sys.argv[5:]
artifact_dispatch = ContextVar("artifact_dispatch", default=None)


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
        if event == "context_artifact_dispatched":
            artifact_dispatch.set((run_id, data.get("workflow_node"), data["artifact_id"]))
        if mode == "crash" and event == window:
            self.trigger = True


class RecordedProvider(Provider):
    async def complete(self, messages, tools):
        kind = "summary" if messages[0]["content"].startswith("context-summary:") else "business"
        with closing(sqlite3.connect(root / "business.sqlite")) as db, db:
            db.execute("INSERT INTO calls VALUES (?)", (kind,))
        return await super().complete(messages, tools)


class Artifacts(FileArtifactStore if file_artifacts else SQLiteArtifactStore):
    def put(self, *args, **kwargs):
        identity = artifact_dispatch.get()
        with closing(sqlite3.connect(root / "business.sqlite")) as db, db:
            db.execute("INSERT INTO calls VALUES ('artifact')")
            # Record entry even when recovery calls without a dispatch context.
            # prepare may catch a put error after finding existing content.
            db.execute("INSERT INTO artifact_calls VALUES (?,?,?)", identity or (None, None, None))
        assert identity is not None
        result = super().put(*args, **kwargs)
        if mode == "crash" and window == "artifact_commit":
            os._exit(77)
        return result


class RendezvousArtifacts:
    """Make both original node frames observe the same missing content."""

    def __init__(self, target):
        self.target = target
        self._missing = self._puts = 0
        self._entered = 0
        self._both_missing = asyncio.Event()
        self._both_written = asyncio.Event()
        self._both_entered = asyncio.Event()

    @property
    def backend_id(self):
        return self.target.backend_id

    @property
    def identity(self):
        return {
            "kind": "context-rendezvous-fixture",
            "version": "1",
            "backend_id": self.backend_id,
            "target": self.target.identity,
        }

    async def get(self, *args, **kwargs):
        try:
            return self.target.get(*args, **kwargs)
        except NotFound:
            if mode == "crash":
                self._missing += 1
                if self._missing == 2:
                    self._both_missing.set()
                await asyncio.wait_for(self._both_missing.wait(), 5)
            raise

    async def put(self, *args, **kwargs):
        if mode == "crash" and window == "artifact_commit":
            self._entered += 1
            if self._entered == 2:
                self._both_entered.set()
            await asyncio.wait_for(self._both_entered.wait(), 5)
        reference = self.target.put(*args, **kwargs)
        if mode == "crash":
            self._puts += 1
            if self._puts == 2:
                self._both_written.set()
            await asyncio.wait_for(self._both_written.wait(), 5)
        return reference

    def close(self):
        self.target.close()


with closing(sqlite3.connect(root / "business.sqlite")) as db, db:
    db.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, result TEXT)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS artifact_calls (run_id TEXT, node_id TEXT, artifact_id TEXT)"
    )
with closing(
    Artifacts(root / ("file-artifacts" if file_artifacts else "artifacts.sqlite"))
) as artifacts:
    if "rendezvous" in sys.argv[5:]:
        artifacts = RendezvousArtifacts(artifacts)
    tools = registry([])
    registered = tools.get("lookup")
    original = registered.handler

    async def lookup(arguments, invocation):
        value = original(arguments, invocation)
        with closing(sqlite3.connect(root / "business.sqlite")) as db, db:
            db.execute("INSERT INTO calls VALUES ('tool')")
            db.execute(
                "INSERT OR IGNORE INTO effects VALUES (?,?)",
                (invocation.effect_key, json.dumps(value)),
            )
        return value

    def reconcile(arguments, invocation):
        with closing(sqlite3.connect(root / "business.sqlite")) as db, db:
            row = db.execute(
                "SELECT result FROM effects WHERE key=?", (invocation.effect_key,)
            ).fetchone()
        return None if row is None else json.loads(row[0])

    tools = type(tools)()
    tools.register(
        replace(registered.spec, effect="idempotent_write"), lookup, reconciler=reconcile
    )
    if relevant:
        from relf_agent import RelevantDataContext

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
