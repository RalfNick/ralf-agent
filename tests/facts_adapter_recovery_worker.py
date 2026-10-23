"""Canonical processes at actual independent put and original receipt windows."""

import asyncio
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from agent_app.adapter import ReferenceFactsSource, register_facts_reference_components
from agent_app.runtime import create_engine

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    ProfiledEngine,
    RuntimeBuilder,
    SQLiteStore,
    load_catalog,
)


class WindowSource(ReferenceFactsSource):
    def __init__(self, path, phase, window):
        super().__init__(path)
        self.phase, self.window = phase, window

    def put_fact(self, *arguments, **keywords):
        version = super().put_fact(*arguments, **keywords)
        if self.phase == "crash" and self.window == "accepted-put-lost-ack":
            os._exit(77)
        return version


class WindowStore(SQLiteStore):
    def __init__(self, path, *, trigger=False):
        super().__init__(path)
        self.trigger = trigger

    @contextmanager
    def transaction(self):
        outermost = not self.conn.in_transaction
        with super().transaction():
            yield
        if outermost and getattr(self, "trigger", False):
            row = self.conn.execute(
                "SELECT run_id FROM events WHERE kind='memory_fact_receipt_recorded' ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                os._exit(77)


async def execute(directory, phase, window):
    directory = Path(directory)
    refs_path = directory / "refs.json"
    if phase == "crash":
        source = WindowSource(directory / ".ralf/facts.sqlite", phase, window)
        try:
            registry = ComponentRegistry()
            register_facts_reference_components(registry, source, owned=True)
            builder = RuntimeBuilder(
                registry,
                base_dir=directory,
                store_factory=lambda path: WindowStore(
                    path, trigger=window == "receipt-before-settlement"
                ),
            )
            with ProfiledEngine(
                load_catalog(directory / "runtime.toml"),
                directory / ".ralf/runs.sqlite",
                builder=builder,
            ) as engine:
                # No seed: the one fact is the actual original accepted stage put.
                handle = engine.submit(
                    AgentSpec("reader", "Read actual original facts", model_credits=2),
                    "original input",
                    command_id="facts-window-submit",
                    budget=32,
                )
                refs_path.write_text(
                    json.dumps({"run_id": handle.run_id, "receipt": asdict(handle.receipt)})
                )
                await engine.drive(handle.run_id)
                raise AssertionError("The original process missed its actual memory window")
        finally:
            source.close()
    refs = json.loads(refs_path.read_text())
    with create_engine(directory / ".ralf/runs.sqlite") as engine:
        original = engine.status(refs["run_id"])
        assert original.state == "running"
        snapshot = await engine.drive(refs["run_id"])
        source = engine._active.memory._original_source
        descriptor = source._file_descriptor
        handle = engine.submit(
            AgentSpec("reader", "Read actual original facts", model_credits=2),
            "original input",
            command_id="facts-window-submit",
            budget=32,
        )
        assert asdict(handle.receipt) == refs["receipt"]
    closed = False
    try:
        os.fstat(descriptor)
    except OSError:
        closed = True
    return {
        "run_id": snapshot.run_id,
        "state": snapshot.state,
        "result": snapshot.result,
        "audit": source.audit(),
        "source_closed": source._closed,
        "descriptor_closed": closed,
    }


def main():
    print(json.dumps(asyncio.run(execute(*sys.argv[1:])), allow_nan=False))


if __name__ == "__main__":
    from tests.facts_adapter_recovery_worker import main as canonical_main

    canonical_main()
