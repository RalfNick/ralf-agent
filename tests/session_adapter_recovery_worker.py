"""Canonical independent processes at actual original Session save windows."""

import asyncio
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    RunRef,
    Runtime,
    RuntimeBuilder,
    SessionRef,
    SQLiteStore,
    recommended_profile,
)
from ralf_agent.session_adapter_contract_reference import (
    ReferenceSessionSource,
    register_session_reference_components,
)


class WindowSource(ReferenceSessionSource):
    def __init__(self, path, phase, window):
        super().__init__(path)
        self.phase, self.window = phase, window

    def append(self, *arguments, **keywords):
        revision = super().append(*arguments, **keywords)
        if self.phase == "crash" and self.window == "accepted-save-lost-ack":
            os._exit(77)
        return revision


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
                "SELECT run_id FROM events WHERE kind='remote_session_save_confirmed' ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                os._exit(77)


def create(directory, phase, window):
    directory = Path(directory)
    source = WindowSource(directory / "sessions.sqlite", phase, window)
    try:
        registry = ComponentRegistry()
        register_session_reference_components(registry, source, owned=True)
        profile = recommended_profile(
            "local-basic",
            name="independent-session-window",
            provider={"adapter": "external-session-reader"},
            components={
                "session_store": {"adapter": "external-session"},
                "context_assembler": {"adapter": "default"},
            },
        )
        builder = RuntimeBuilder(
            registry,
            store_factory=lambda path: WindowStore(
                path, trigger=phase == "crash" and window == "confirmed-before-terminal"
            ),
        )
        return builder.build(profile, directory / "runs.sqlite"), source
    except BaseException:
        source.close()
        raise


async def execute(directory, phase, window):
    instance, source = create(directory, phase, window)
    refs_path = Path(directory) / "refs.json"
    async with Runtime(instance, owned=True) as runtime:
        if phase == "crash":
            # No seeding: recovery must retain exactly the actual original save.
            agent = runtime.create_agent(
                AgentSpec("reader", "Read original Session", model_credits=2)
            )
            session = await agent.open_session("original-session", command_id="open")
            handle = await session.submit("original input", command_id="submit", budget=32)
            refs_path.write_text(
                json.dumps(
                    {
                        "session": session.ref.to_dict(),
                        "run": handle.ref.to_dict(),
                        "receipt": asdict(handle.receipt),
                    }
                )
            )
            await handle.wait(wait_timeout=10, terminal_only=True)
            raise AssertionError("The original process did not reach its actual save window")
        refs = json.loads(refs_path.read_text())
        session = runtime.attach_session(SessionRef.from_dict(refs["session"]))
        assert (await session.status()).busy
        handle = await runtime.resume(RunRef.from_dict(refs["run"]))
        done = await handle.wait(wait_timeout=10, terminal_only=True)
        async with asyncio.timeout(10):
            while (await session.status()).busy:  # noqa: ASYNC110 -- original actual-stop gate
                await asyncio.sleep(0.01)
        assert (
            asdict((await session.submit("original input", command_id="submit", budget=32)).receipt)
            == refs["receipt"]
        )
        return {
            "run_id": handle.ref.run_id,
            "state": done.snapshot.state,
            "result": done.snapshot.result,
            "busy": (await session.status()).busy,
            "audit": source.audit(),
        }


def main():
    print(json.dumps(asyncio.run(execute(*sys.argv[1:])), allow_nan=False))


if __name__ == "__main__":
    from tests.session_adapter_recovery_worker import main as canonical_main

    canonical_main()
