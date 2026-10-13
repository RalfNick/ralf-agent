"""Independent supplier/Local process death at original durable boundaries."""

import asyncio
import json
import os
import sqlite3
import sys
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path

from ralf_agent import AgentSpec, LocalEngine, SQLiteStore, ToolRegistry
from ralf_agent.model_adapter_contract_reference import (
    ReferenceModelSource,
    ReferenceSQLiteModelProvider,
)
from ralf_agent.types import canonical, digest


async def main(root, phase, window):
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

        def emit(self, run_id, event, data=None):
            super().emit(run_id, event, data)
            if (
                phase == "crash"
                and window == "recorded-response"
                and event == "model_response_recorded"
            ):
                self.trigger = True

    class ActualSupplier(ReferenceModelSource):
        def record_response(self, request_id, response, *, invalid=None):
            super().record_response(request_id, response, invalid=invalid)
            if (
                phase == "crash"
                and window == "accepted-response-lost"
                and self.audit()["response_count"] == 2
            ):
                # The selected supplier completed the follow-up after one signed
                # approved effect. No local received-response evidence exists yet.
                os._exit(77)

    source = ActualSupplier(root / "supplier.sqlite")
    provider = ReferenceSQLiteModelProvider(source)
    with closing(sqlite3.connect(root / "business.sqlite")) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS effects (effect_key TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS invocations (effect_key TEXT)")

    def write(arguments, context):
        with closing(sqlite3.connect(root / "business.sqlite")) as db, db:
            db.execute("INSERT INTO invocations VALUES (?)", (context.effect_key,))
            db.execute(
                "INSERT OR IGNORE INTO effects VALUES (?,?)",
                (context.effect_key, arguments["value"]),
            )
        return {"written": arguments["value"], "effect_key": context.effect_key}

    registry = ToolRegistry()
    from ralf_agent import ToolSpec

    registry.register(
        ToolSpec(
            "write",
            "Record resolution",
            {
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "string"}},
                "additionalProperties": False,
            },
            effect="idempotent_write",
            requires_approval=True,
            config={"source": "process-business-v1"},
        ),
        write,
    )
    engine = LocalEngine(
        CrashStore(root / "runs.sqlite"),
        providers={"default": provider},
        tools=registry,
        runtime_profile={
            "kind": "runtime-profile",
            "name": "model-process",
            "version": "1",
            "digest": digest({"supplier": "1"}),
        },
    )
    spec = AgentSpec(
        "process",
        "Consume actual request",
        ("write",) if window == "accepted-response-lost" else (),
    )
    try:
        if phase == "crash":
            if window == "recorded-response":
                source.configure("output", {"output": {"actual": [None, False, 7, "中文🙂"]}})
            else:
                source.configure(
                    "tools",
                    {
                        "name": "write",
                        "arguments": {"value": "approved"},
                        "call_id": "original-write",
                    },
                )
            handle = engine.submit(
                spec, {"task": "original"}, command_id="original-submit", budget=8
            )
            (root / "refs.json").write_text(canonical(asdict(handle)))
            snapshot = await engine.drive(handle.run_id)
            assert window == "accepted-response-lost" and snapshot.state == "waiting_approval"
            pending = snapshot.pending[0]
            receipt = engine.approve(
                handle.run_id,
                pending["action_id"],
                pending["digest"],
                command_id="original-approve",
            )
            assert (
                engine.approve(
                    handle.run_id,
                    pending["action_id"],
                    pending["digest"],
                    command_id="original-approve",
                )
                == receipt
            )
            (root / "approval.json").write_text(canonical(asdict(receipt)))
            await engine.drive(handle.run_id)
            raise AssertionError("Original process did not enter its crash window")
        refs = json.loads((root / "refs.json").read_text())
        handle = engine.submit(spec, {"task": "original"}, command_id="original-submit", budget=8)
        assert asdict(handle) == refs
        if window == "recorded-response":
            snapshot = await engine.drive(handle.run_id)
            assert snapshot.state == "succeeded"
            assert (await engine.drive(handle.run_id)).state == "succeeded"
        else:
            # Reconnection inspects original authority. An explicit drive is a
            # separately authorized resume and would allocate a new Attempt.
            snapshot = engine.status(handle.run_id)
            assert snapshot.state == "running"
            diagnosis = engine.diagnostics(handle.run_id)
            assert diagnosis.budget == {"limit": 8, "held": 1, "spent": 2}
            pending = next(a for a in snapshot.actions if a["kind"] == "tool")
            receipt = engine.approve(
                handle.run_id, pending["id"], pending["digest"], command_id="original-approve"
            )
            assert asdict(receipt) == json.loads((root / "approval.json").read_text())
        data = {"state": snapshot.state, "run_id": handle.run_id, "counts": source.audit()}
    finally:
        await engine.wait_for_threads()
        engine.close()
        await source.aclose()
    data.update(source_closed=source._closed, descriptor_closed=source._file_descriptor is None)
    print(canonical(data))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
