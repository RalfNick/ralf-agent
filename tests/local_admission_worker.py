"""Portable actual-process fixture for original deployment capacity claims."""

import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, CapacityExceeded
from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.runtime_config import load_catalog

PRODUCT_FILE = str(Path(r.__file__).resolve())


def emit(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def make_owner(directory, mode, kind, scope):
    class Provider:
        identity = {"kind": "admission-process-provider", "version": "1"}

        async def complete(self, messages, descriptions):
            final = messages[-1]["role"] == "tool"
            with (directory / "model-calls.txt").open("a") as stream:
                stream.write(
                    "plain\n" if not descriptions else "final\n" if final else "proposal\n"
                )
            if not descriptions or final:
                return r.ModelResponse(output="completed")
            return r.ModelResponse(
                tool_calls=(r.ToolCall("change", {"value": "accepted"}, "original-call"),)
            )

    def change(arguments, context):
        with (directory / "business-effects.jsonl").open("a") as stream:
            stream.write(
                json.dumps({"effect_key": context.effect_key, "value": arguments["value"]}) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        if mode == "unknown-start":
            emit(
                directory / "crash-ready.json",
                {"pid": os.getpid(), "run_id": context.run_id, "effect_key": context.effect_key},
            )
            os._exit(77)
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
    provider, path = Provider(), directory / "runs.sqlite"
    if kind == "sdk":
        return r.LocalEngine(
            r.SQLiteStore(path),
            providers={"default": provider},
            tools=tools,
            scope=scope,
            admission_policy=DeploymentAdmissionPolicy("business", max_active_root_runs=1),
        )
    registry = r.ComponentRegistry()
    registry.register("provider", "process-provider", lambda config, context: provider)
    registry.register("tools", "process-tools", lambda config, context: tools)
    catalog = load_catalog(directory / f"profile.{kind}")
    return r.RuntimeBuilder(registry, base_dir=catalog.base_dir).build(
        catalog.default, path, scope=scope
    )


async def worker(directory, mode, kind):
    scope = (
        r.Scope("business", "original-owner")
        if mode != "foreign-refusal"
        else r.Scope("other-workspace", "other-owner")
    )
    owner = make_owner(directory, mode, kind, scope)
    original_spec = r.AgentSpec("business", "Apply the requested value", ("change",))
    next_spec = r.AgentSpec("next", "Answer without business tools")
    try:
        if mode in {"start", "unknown-start"}:
            handle = owner.submit(
                original_spec, "original task", command_id="original-submit", budget=4
            )
            waiting = await owner.drive(handle.run_id)
            assert waiting.state == "waiting_approval"
            run = owner.store.run(handle.run_id)
            pending = waiting.pending[0]
            action = next(
                action for action in run["actions"] if action["id"] == pending["action_id"]
            )
            emit(
                directory / "ready.json",
                {
                    "pid": os.getpid(),
                    "run_id": handle.run_id,
                    "receipt": asdict(handle.receipt),
                    "pending": pending,
                    "manifest": run["manifest"],
                    "local_admission": run["local_admission"],
                    "effect_key": action["effect_key"],
                    "holders": owner.store.local_capacity_holders(scope),
                    "product_file": PRODUCT_FILE,
                },
            )
            if mode == "start":
                await asyncio.Event().wait()
            owner.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approval"
            )
            await owner.drive(handle.run_id)
            raise AssertionError("Original handler must terminate the actual process")
        original = json.loads((directory / "ready.json").read_text())
        run_id, pending = original["run_id"], original["pending"]
        if mode == "foreign-refusal":
            try:
                owner.status(run_id)
            except AuthorizationDenied:
                pass
            else:
                raise AssertionError("Foreign Scope observed original Run")
            assert owner.store.local_capacity_holders(scope) == ()
            try:
                owner.submit(next_spec, "next task", command_id="next-submit")
            except CapacityExceeded as error:
                assert run_id not in str(error)
            else:
                raise AssertionError("Deployment quota was bypassed by a different Scope")
            emit(
                directory / "foreign-proof.json",
                {"pid": os.getpid(), "holders": [], "product_file": PRODUCT_FILE},
            )
            return
        duplicate = owner.submit(
            original_spec, "original task", command_id="original-submit", budget=4
        )
        assert duplicate.run_id == run_id and asdict(duplicate.receipt) == original["receipt"]
        if mode in {"blocked", "unknown-recover"}:
            if mode == "unknown-recover":
                recovered = await owner.drive(run_id)
                assert recovered.state == "waiting_reconciliation"
                owner.cancel(run_id, command_id="cancel-unknown")
                assert owner.status(run_id).state == "cancelled"
            assert owner.store.local_capacity_holders(scope) == (run_id,)
            try:
                owner.submit(next_spec, "next task", command_id="next-submit")
            except CapacityExceeded:
                pass
            else:
                raise AssertionError("Original claim was released without complete evidence")
            run = owner.store.run(run_id)
            emit(
                directory / f"{mode}-proof.json",
                {
                    "pid": os.getpid(),
                    "run_id": run_id,
                    "state": run["state"],
                    "manifest": run["manifest"],
                    "local_admission": run["local_admission"],
                    "holders": owner.store.local_capacity_holders(scope),
                    "budget": owner.store.budget(run_id),
                    "tool_status": next(
                        action["status"]
                        for action in run["actions"]
                        if action["id"] == pending["action_id"]
                    ),
                    "product_file": PRODUCT_FILE,
                },
            )
            return
        receipt = owner.approve(
            run_id, pending["action_id"], pending["digest"], command_id="approval"
        )
        assert receipt.apply_state == "applied"
        if mode == "approve-hold":
            assert owner.store.local_capacity_holders(scope) == (run_id,)
            emit(
                directory / "approved.json",
                {
                    "pid": os.getpid(),
                    "receipt": asdict(receipt),
                    "holders": owner.store.local_capacity_holders(scope),
                },
            )
            await asyncio.Event().wait()
        assert await owner.drive(run_id) == owner.status(run_id)
        assert owner.status(run_id).state == "succeeded"
        next_run = owner.submit(next_spec, "next task", command_id="next-submit")
        assert next_run.run_id != run_id
        assert (await owner.drive(next_run.run_id)).state == "succeeded"
        run = owner.store.run(run_id)
        action = next(action for action in run["actions"] if action["id"] == pending["action_id"])
        emit(
            directory / "success-proof.json",
            {
                "pid": os.getpid(),
                "run_id": run_id,
                "next_run_id": next_run.run_id,
                "receipt": asdict(receipt),
                "manifest": run["manifest"],
                "local_admission": run["local_admission"],
                "effect_key": action["effect_key"],
                "tool_attempts": len(action["attempts"]),
                "dispatch_events": sum(
                    event.kind == "tool_dispatch_intent" for event in owner.events(run_id)
                ),
                "holders": owner.store.local_capacity_holders(scope),
                "budget": owner.store.budget(run_id),
                "product_file": PRODUCT_FILE,
            },
        )
    finally:
        owner.close()


if __name__ == "__main__":
    asyncio.run(worker(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
