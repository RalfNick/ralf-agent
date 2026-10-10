"""Isolated real Local processes using the default external SQLite Session data."""

import asyncio
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

import ralf_agent as r


def create(directory, phase, kind, window):
    directory = Path(directory)
    evidence = directory / "effects.sqlite"
    with sqlite3.connect(evidence) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS effects (action_id TEXT PRIMARY KEY)")

    def record(label):
        with sqlite3.connect(evidence) as connection:
            connection.execute("INSERT INTO calls VALUES (?)", (label,))

    class Provider:
        identity = {"kind": "default-session-process", "version": "1"}

        async def complete(self, messages, tools):
            record("model")
            if any(message.get("role") == "tool" for message in messages):
                return r.ModelResponse(output="applied")
            return r.ModelResponse(tool_calls=[r.ToolCall("change", {})])

    class Backend(r.SQLiteMemory):
        def append(self, *args, **kwargs):
            record("append")
            if phase == "crash" and window == "before":
                os._exit(77)
            result = super().append(*args, **kwargs)
            if phase == "crash":
                os._exit(77)
            return result

    backend = Backend(directory / "data.sqlite")
    tools = r.ToolRegistry()

    def change(arguments, context):
        with sqlite3.connect(evidence) as connection:
            connection.execute("INSERT INTO effects VALUES (?)", (context.action_id,))
        return {"applied": True}

    tools.register(
        r.ToolSpec(
            "change",
            "Change",
            {"type": "object"},
            effect="idempotent_write",
            requires_approval=True,
        ),
        change,
    )
    spec = r.AgentSpec("a", "Apply once", ("change",))
    resource = r.SessionBindingResource(backend, namespaces=("red",), default_namespace="red")
    options = {}
    if kind == "agent":
        catalog = r.BindingCatalog(scope=r.Scope())
        catalog.register("session", "data", "1", resource)
        options["binding_catalog"] = catalog
        definition = r.AgentDefinition(
            spec, r.AgentBindingDescriptor(session=r.BindingSelection.ref("data", "1"))
        )
    else:
        options["conversation_resource"] = resource
        definition = r.TeamSpec("t", {"a": spec})
    raw = r.LocalEngine(
        r.SQLiteStore(directory / "run.sqlite"),
        providers={"default": Provider()},
        tools=tools,
        **options,
    )
    return r.Runtime(raw, owned=True), backend, definition


async def run(directory, phase, kind, window):
    runtime, backend, definition = create(directory, phase, kind, window)
    path = Path(directory) / "refs.json"
    try:
        async with runtime:
            if phase == "prepare":
                session = await runtime.create_agent(definition).open_session(
                    "s", command_id="open"
                )
                handle = await session.submit("q", command_id="submit", budget=64)
                done = await handle.wait(wait_timeout=5)
                assert done.snapshot.state == "waiting_approval", done
                controls = await handle.pending()
                assert len(controls) == 1, controls
                path.write_text(
                    json.dumps(
                        {
                            "session": session.ref.to_dict(),
                            "run": handle.ref.to_dict(),
                            "receipt": asdict(handle.receipt),
                            "control": controls[0],
                        }
                    )
                )
                assert (await session.status()).busy
                return
            refs = json.loads(path.read_text())
            session = runtime.attach_session(r.SessionRef.from_dict(refs["session"]))
            handle = await runtime.aattach(r.RunRef.from_dict(refs["run"]))
            assert (await session.status()).busy
            if phase == "crash":
                control = refs["control"]
                owner = await runtime.aattach(r.RunRef.from_dict(control["ref"]))
                await owner.approve(control["action_id"], control["digest"], command_id="approve")
                await handle.wait(wait_timeout=5)
                raise AssertionError("crash did not reach the real SQLite append")
            await runtime.resume(handle.ref)
            done = await handle.wait(wait_timeout=5, terminal_only=True)
            assert done.snapshot.state == "succeeded", done
            assert done.snapshot.result == "applied"
            assert not (await session.status()).busy
            assert (
                asdict((await session.submit("q", command_id="submit", budget=64)).receipt)
                == refs["receipt"]
            )
            print(
                json.dumps(
                    {
                        "state": done.snapshot.state,
                        "revision": backend.read(r.Scope(), session.ref.key.storage_key)[0],
                    }
                )
            )
    finally:
        backend.close()


if __name__ == "__main__":
    asyncio.run(run(*sys.argv[1:]))
