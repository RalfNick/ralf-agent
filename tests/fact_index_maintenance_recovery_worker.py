"""Original Session/ToolAction death at native index and receipt boundaries."""

import asyncio
import json
import linecache
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from ralf_agent import (
    GraphNode,
    GraphWorkflowSpec,
    Literal,
    LocalEngine,
    Runtime,
    Scope,
    SQLiteStore,
    ToolPolicy,
    ToolRegistry,
    ValueRef,
    register_tool_source,
)
from ralf_agent.agent_run import RunRef
from ralf_agent.embeddings import HashEmbeddingProvider
from ralf_agent.fact_index_generation import GenerationIndexedMemoryStore
from ralf_agent.fact_index_maintenance_tools import (
    NAME,
    READY_ONLY_SCHEMA,
    FactIndexMaintenanceToolSource,
)
from ralf_agent.fact_index_ports import FactIndexCatalog
from ralf_agent.memory import SQLiteMemory
from ralf_agent.runtime_router import SQLiteRunReader
from ralf_agent.session_types import SessionRef
from ralf_agent.types import canonical
from ralf_agent.vector import SQLiteVectorIndex

SCOPE = Scope("maintenance-process", "author")
NS = "facts"


def record(root, kind, value):
    with closing(sqlite3.connect(root / "trace.sqlite")) as db, db:
        db.execute("INSERT INTO observations(kind,value) VALUES (?,?)", (kind, canonical(value)))


def tracer(root, phase, window):
    def trace(frame, event, value):
        name = frame.f_code.co_qualname
        kind = None
        if name == "FactIndexMaintenanceToolSource._ensure" and event == "call":
            record(root, "dispatch", {"action_id": frame.f_locals["context"].action_id})
        if name == "HashEmbeddingProvider.embed" and event == "return" and isinstance(value, list):
            record(root, "embedding", {"texts": frame.f_locals["texts"], "vectors": value})
        if name == "IndexedMemoryStore.rebuild" and event == "line":
            state = frame.f_locals.get("state", {})
            if (
                "vectors" in frame.f_locals
                and state.get("phase") == "scan"
                and "pending" not in state
                and linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip()
                == "await self._current(scope, namespace, snapshot)"
            ):
                kind = "accepted-embedding"
        if name == "SQLiteVectorIndex.upsert" and event == "return":
            kind = "vector-commit"
        if name == "IndexedMemoryStore._save" and event == "return" and type(value) is int:
            state = frame.f_locals["state"]
            record(root, "checkpoint", {"revision": value, "state": state})
            if state["phase"] == "scan" and state["scanned"] > 0:
                kind = "page-checkpoint"
        if name == "IndexedMemoryStore._activate" and event == "return" and value is None:
            kind = "active-publication"
        if (
            name == "FactIndexMaintenanceToolSource._finish"
            and event == "return"
            and isinstance(value, dict)
        ):
            kind = "effect-receipt"
        if name == "LocalEngine._record_tool_observation" and event == "return" and value is True:
            kind = "tool-receipt"
        if kind is not None:
            record(root, kind, {"native_function": name})
            if phase == "crash" and kind == window:
                (root / "crash-boundary.json").write_text(
                    canonical({"window": window, "native_function": name})
                )
                os._exit(77)
        return trace

    return trace


async def main(root, phase, window):
    refs_path = root / "refs.json"
    if phase == "observe":
        refs = json.loads(refs_path.read_text())
        reader = SQLiteRunReader(root / "runs.sqlite", scope=SCOPE)
        run_id = refs["run"]["run_id"]
        output = {
            "status": asdict(reader.status(run_id)),
            "diagnostics": asdict(reader.diagnostics(run_id)),
            "events": [asdict(event) for event in reader.events(run_id)],
            "observation_only": True,
        }
        print(canonical(output))
        return
    backend = SQLiteMemory(root / "source.sqlite")
    vector = SQLiteVectorIndex(root / "vector.sqlite", dimensions=16)
    metadata = SQLiteMemory(root / "catalog.sqlite")
    source = None
    runtime = None
    with closing(sqlite3.connect(root / "trace.sqlite")) as db, db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,kind TEXT,value TEXT)"
        )
    try:
        index = GenerationIndexedMemoryStore(
            backend,
            HashEmbeddingProvider(dimensions=16),
            vector,
            FactIndexCatalog(metadata),
            scope=SCOPE,
            namespace=NS,
            batch_size=1,
        )
        source = FactIndexMaintenanceToolSource(
            index, version="process-1", scope=SCOPE, namespace=NS, max_pages=1
        )
        registry = ToolRegistry()
        await register_tool_source(
            registry,
            source,
            policies={
                NAME: ToolPolicy(
                    "process-1",
                    effect="idempotent_write",
                    requires_approval=False,
                    effect_key_argument="effect_key",
                    reconciler=source.reconcile,
                )
            },
        )
        engine = LocalEngine(
            SQLiteStore(root / "runs.sqlite"), providers={}, tools=registry, scope=SCOPE
        )
        runtime = Runtime(engine, owned=True)
        spec = GraphWorkflowSpec(
            "maintenance-process",
            [
                GraphNode(
                    "ensure",
                    tool=NAME,
                    input=Literal({}),
                    output_schema=READY_ONLY_SCHEMA,
                )
            ],
            output=ValueRef("ensure"),
            max_concurrency=1,
        )
        if phase == "crash":
            backend.put_fact(SCOPE, NS, "original", "violet target", expected_version=0)
            session = await runtime.create_agent(spec).open_session(
                "original-session", command_id="original-open"
            )
            handle = await session.submit("original-task", command_id="original-turn", budget=8)
            refs_path.write_text(
                canonical(
                    {
                        "run": handle.ref.to_dict(),
                        "session": session.ref.to_dict(),
                        "turn": handle.turn.to_dict(),
                        "receipt": asdict(handle.receipt),
                        "definition": spec.to_dict(),
                        "index_definition": index.identity,
                    }
                )
            )
            sys.settrace(tracer(root, phase, window))
            await handle.wait(wait_timeout=5, terminal_only=True)
            raise AssertionError("Original process did not enter selected native crash boundary")
        refs = json.loads(refs_path.read_text())
        assert index.identity == refs["index_definition"]
        session = runtime.attach_session(SessionRef.from_dict(refs["session"]))
        handle = runtime.attach(RunRef.from_dict(refs["run"]))
        assert (await session.status()).busy
        assert (await session.turns())[0].to_dict() == refs["turn"]
        sys.settrace(tracer(root, phase, window))
        await handle.resume()
        result = (await handle.wait(wait_timeout=5, terminal_only=True)).snapshot
        assert result.state == "succeeded", result
        replay = await session.submit("original-task", command_id="original-turn", budget=8)
        assert replay.receipt == handle.receipt or asdict(replay.receipt) == refs["receipt"]
        assert replay.ref == handle.ref
        assert (await replay.wait(wait_timeout=5, terminal_only=True)).snapshot == result
        await runtime._supervisor.drain()
        assert not (await session.status()).busy and len(await session.turns()) == 1
        output = {
            "state": result.state,
            "result": result.result,
            "run": engine.store.run(handle.ref.run_id),
            "budget": engine.store.budget(handle.ref.run_id),
            "session": asdict(await session.status()),
            "turns": [turn.to_dict() for turn in await session.turns()],
        }
        print(canonical(output))
    finally:
        sys.settrace(None)
        if source is not None:
            await source.aclose(wait_timeout=2)
            assert source._owner._execution.active_count == 0
        if runtime is not None:
            await runtime.aclose()
        for port in (vector, metadata, backend):
            port.close()
            try:
                port.store.conn.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                pass
            else:
                raise AssertionError("Borrowed host connection did not close")
        (root / (phase + "-closed.json")).write_text(
            canonical(
                {
                    "active_owner": 0,
                    "other_live_tasks": len(asyncio.all_tasks()) - 1,
                    "connections_closed": 3,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
