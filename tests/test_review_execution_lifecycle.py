import asyncio
import copy

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry
from relf_agent.errors import DefinitionMismatch, IdempotencyConflict

from .helpers import ScriptedProvider


@pytest.mark.parametrize("provider_available", [True, False])
def test_submit_retry_returns_original_receipt_after_configuration_moves(
    tmp_path, provider_available
):
    path = tmp_path / "runs.db"
    spec = AgentSpec("agent", "Answer the request")
    with LocalEngine(
        SQLiteStore(path), providers={"default": ScriptedProvider([])}, tools=ToolRegistry()
    ) as runtime:
        original = runtime.submit(spec, "question", command_id="request", session_id="session")
        pinned = copy.deepcopy(runtime.store.run(original.run_id)["manifest"])

    replacement = ScriptedProvider([])
    replacement.identity = {"kind": "replacement", "version": "2"}
    with LocalEngine(
        SQLiteStore(path),
        providers={"default": replacement} if provider_available else {},
        tools=ToolRegistry(),
    ) as runtime:
        retry = runtime.submit(spec, "question", command_id="request", session_id="session")
        assert retry == original
        assert runtime.store.run(retry.run_id)["manifest"] == pinned
        assert len(runtime.events(retry.run_id)) == 1
        assert runtime.store.budget(retry.run_id) == {"limit": 32, "held": 0, "spent": 0}
        with pytest.raises(IdempotencyConflict):
            runtime.submit(spec, "changed", command_id="request", session_id="session")
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(retry.run_id))


@pytest.mark.parametrize("change", ["definition", "input", "budget", "session"])
def test_submit_retry_with_changed_caller_request_conflicts_before_configuration(tmp_path, change):
    with LocalEngine(
        SQLiteStore(tmp_path / "runs.db"),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
    ) as runtime:
        spec, task, budget, session = AgentSpec("agent", "Answer"), "question", 32, "session"
        run = runtime.submit(spec, task, command_id="s", budget=budget, session_id=session)
        runtime.providers.clear()
        if change == "definition":
            spec = AgentSpec("agent", "Changed instructions")
        elif change == "input":
            task = "changed"
        elif change == "budget":
            budget = 33
        else:
            session = "changed"
        with pytest.raises(IdempotencyConflict):
            runtime.submit(spec, task, command_id="s", budget=budget, session_id=session)
        assert runtime.status(run.run_id).state == "queued"
        assert len(runtime.events(run.run_id)) == 1


def test_completed_runs_release_process_local_execution_objects(tmp_path):
    async def exercise():
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.db"),
            providers={"default": ScriptedProvider([ModelResponse(output="done")] * 100)},
            tools=ToolRegistry(),
        ) as runtime:
            for number in range(100):
                run = runtime.submit(
                    AgentSpec("agent", "Answer"), "question", command_id=str(number)
                )
                assert (await runtime.drive(run.run_id)).state == "succeeded"
            await asyncio.sleep(0)
            assert not runtime._active
            assert not runtime._inflight
            assert not runtime._locks

    asyncio.run(exercise())


def test_cancelled_waiter_keeps_the_owners_lock_until_dispatch_finishes(tmp_path):
    async def exercise():
        model_completed, append_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Provider(ScriptedProvider):
            async def complete(self, messages, tools):
                model_completed.set()
                return await super().complete(messages, tools)

        class Sessions:
            backend_id = "async-session:1"

            async def read(self, *args):
                return 0, []

            async def append(self, *args, **kwargs):
                append_started.set()
                await release.wait()
                return 1

        with LocalEngine(
            SQLiteStore(tmp_path / "runs.db"),
            providers={"default": Provider([ModelResponse(output="done")])},
            tools=ToolRegistry(),
            session_store=Sessions(),
        ) as runtime:
            run = runtime.submit(AgentSpec("agent", "Answer"), "question", command_id="s")

            async def wait_for_owner():
                await model_completed.wait()
                return await runtime.drive(run.run_id)

            waiter = asyncio.create_task(wait_for_owner())
            owner = asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(append_started.wait(), 2)
            owned_lock = runtime._locks[run.run_id]
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert runtime._locks[run.run_id] is owned_lock
            assert runtime.status(run.run_id).state == "running"
            release.set()
            assert (await owner).state == "succeeded"
            assert not runtime._locks
            assert not runtime._inflight

    asyncio.run(exercise())
