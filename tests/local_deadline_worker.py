"""Portable subprocess fixture for original Local deadline and approval facts."""

import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import ralf_agent as r
from ralf_agent.governance import LocalExecutionPolicy
from ralf_agent.runtime_builder import RuntimeBuilder
from ralf_agent.runtime_config import load_catalog

PRODUCT_FILE = str(Path(r.__file__).resolve())


def emit(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def components(directory):
    class Provider:
        identity = {"kind": "deadline-process-provider", "version": "1"}

        async def complete(self, messages, descriptions):
            final = messages[-1]["role"] == "tool"
            with (directory / "model-calls.txt").open("a") as stream:
                stream.write("final\n" if final else "proposal\n")
            return (
                r.ModelResponse(output="completed")
                if final
                else r.ModelResponse(
                    tool_calls=(r.ToolCall("change", {"value": "accepted"}, "original-call"),)
                )
            )

    def change(arguments, context):
        with (directory / "business-effects.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"effect_key": context.effect_key, "value": arguments["value"]}) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        return {"changed": True, "effect_key": context.effect_key}

    tools = r.ToolRegistry()
    tools.register(
        r.ToolSpec(
            "change",
            "Apply the approved business value",
            {"type": "object"},
            effect="unqueryable_write",
            requires_approval=True,
        ),
        change,
    )
    return Provider(), tools


async def worker(directory, mode, assembly_kind, approval_seconds):
    provider, tools = components(directory)
    scope = r.Scope("deadline-process", "original-owner")
    path = directory / "runs.sqlite"
    if assembly_kind == "sdk":
        owner = engine = r.LocalEngine(
            r.SQLiteStore(path),
            providers={"default": provider},
            tools=tools,
            scope=scope,
            execution_policy=LocalExecutionPolicy(approval_timeout_seconds=approval_seconds),
        )
    else:
        registry = r.ComponentRegistry()
        registry.register("provider", "process-provider", lambda config, context: provider)
        registry.register("tools", "process-tools", lambda config, context: tools)
        catalog = load_catalog(directory / f"profile.{assembly_kind}")
        owner = RuntimeBuilder(registry, base_dir=catalog.base_dir).build(
            catalog.default, path, scope=scope
        )
        engine = owner
    spec = r.AgentSpec("business", "Apply the requested value", ("change",))
    try:
        if mode == "start":
            handle = engine.submit(spec, "original task", command_id="original-submit", budget=4)
            waiting = await engine.drive(handle.run_id)
            assert waiting.state == "waiting_approval"
            run = engine.store.run(handle.run_id)
            pending = waiting.pending[0]
            action = next(
                action for action in run["actions"] if action["id"] == pending["action_id"]
            )
            emit(
                directory / "ready.json",
                {
                    "pid": os.getpid(),
                    "run_id": handle.run_id,
                    "pending": pending,
                    "scope": {"workspace": scope.workspace, "principal": scope.principal},
                    "manifest": run["manifest"],
                    "local_deadlines": run["local_deadlines"],
                    "approval_requested_at": action["approval_requested_at"],
                    "approval_expires_at": action["approval_expires_at"],
                    "effect_key": action["effect_key"],
                    "product_file": PRODUCT_FILE,
                },
            )
            # The parent kills this actual worker, so no graceful close can
            # manufacture proof that original business work was resumed.
            await asyncio.Event().wait()
        original = json.loads((directory / "ready.json").read_text())
        run_id, pending = original["run_id"], original["pending"]
        assert (
            engine.submit(spec, "original task", command_id="original-submit", budget=4).run_id
            == run_id
        )
        before = engine.store.run(run_id)
        receipt = engine.approve(
            run_id, pending["action_id"], pending["digest"], command_id="approval"
        )
        if mode == "approve-hold":
            assert receipt.apply_state == "applied"
            emit(
                directory / "approved.json",
                {"pid": os.getpid(), "run_id": run_id, "receipt": asdict(receipt)},
            )
            await asyncio.Event().wait()
        repeated = engine.approve(
            run_id, pending["action_id"], pending["digest"], command_id="approval"
        )
        assert repeated == receipt
        result = await engine.drive(run_id)
        current = engine.store.run(run_id)
        action = next(
            action for action in current["actions"] if action["id"] == pending["action_id"]
        )
        emit(
            directory / "proof.json",
            {
                "run_id": run_id,
                "state": result.state,
                "error": result.error,
                "receipt": asdict(receipt),
                "before_manifest": before["manifest"],
                "manifest": current["manifest"],
                "local_deadlines": current["local_deadlines"],
                "approval_requested_at": action["approval_requested_at"],
                "approval_expires_at": action["approval_expires_at"],
                "effect_key": action["effect_key"],
                "tool_attempts": len(action["attempts"]),
                "budget": engine.store.budget(run_id),
                "product_file": PRODUCT_FILE,
                "dispatch_events": sum(
                    event.kind == "tool_dispatch_intent" for event in engine.events(run_id)
                ),
            },
        )
    finally:
        owner.close()


if __name__ == "__main__":
    asyncio.run(worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3], float(sys.argv[4])))
