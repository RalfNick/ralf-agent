"""Owned Coding cleanup keeps the original Local authority until fencing is durable."""

import asyncio

import pytest

from ralf_agent import AgentSpec
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_lifecycle import BuildContext, RuntimeInstance

from .test_local_delegated_coding import LifecycleRunner, coding_engine


class OwnedRunner(LifecycleRunner):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.closed = 0
        self.close_failure = False
        self.close_entered = asyncio.Event()
        self.close_release = None
        self.engine = None

    async def aclose(self):
        self.close_entered.set()
        assert self.engine.store.run(self.run_id)["actions"][-1]["delegated_execution"]["fenced"]
        assert self.engine._lifecycle == "open"
        if self.close_release is not None:
            await self.close_release.wait()
        if self.close_failure:
            raise RuntimeError("close unavailable")
        assert self.active_operations == 0
        self.closed += 1


class Journal:
    def __init__(self, runner):
        self.runner, self.closed = runner, 0

    def close(self):
        assert self.runner.closed == 1
        assert self.runner.engine._lifecycle == "open"
        self.closed += 1


async def managed_pending(tmp_path, *, fail_stop=True):
    runner = OwnedRunner(crash=True, fail_stop=fail_stop)
    engine, _ = coding_engine(tmp_path, runner)
    handle = engine.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
    await engine.drive(handle.run_id)
    action = engine.store.run(handle.run_id)["actions"][-1]
    engine.approve(handle.run_id, action["id"], action["digest"], command_id="a")
    await engine.drive(handle.run_id)
    runner.engine, runner.run_id = engine, handle.run_id
    context = BuildContext(
        engine.store, tmp_path / "coding.db", engine.scope, tmp_path, allow_async=True
    )
    journal = context.own(Journal(runner))
    context.own_async(runner)
    return RuntimeInstance(engine, context), engine, runner, journal


def test_owned_coding_stops_and_closes_before_original_sqlite(tmp_path):
    async def exercise():
        runtime, engine, runner, journal = await managed_pending(tmp_path)
        runner.fail_stop = False
        await runtime.aclose()
        assert runner.calls.count("execute") == 1
        assert "reconcile" not in runner.calls
        assert runner.closed == journal.closed == 1
        assert engine._lifecycle == "closed"

    asyncio.run(exercise())


def test_stop_fault_retains_original_authority_and_resource_ledger(tmp_path):
    async def exercise():
        runtime, engine, runner, journal = await managed_pending(tmp_path)
        with pytest.raises(ValidationError, match="delegated|Coding"):
            await runtime.aclose()
        assert engine._lifecycle == "open"
        assert len(runtime._context._resources) == 2
        assert runner.closed == journal.closed == 0
        with pytest.raises(ValidationError, match="open"):
            engine.submit(AgentSpec("new", "x"), "x", command_id="new")
        assert engine.store.run(runner.run_id)["actions"][-1]["delegated_execution"]["pending_stop"]
        runner.fail_stop = False
        await runtime.aclose()
        assert runner.closed == journal.closed == 1

    asyncio.run(exercise())


def test_runner_close_fault_keeps_journal_coordinator_and_retries(tmp_path):
    async def exercise():
        runtime, engine, runner, journal = await managed_pending(tmp_path)
        runner.fail_stop, runner.close_failure = False, True
        with pytest.raises(RuntimeError, match="close unavailable"):
            await runtime.aclose()
        assert engine._lifecycle == "open"
        assert journal.closed == 0
        assert len(runtime._context._resources) == 2
        assert engine.store.run(runner.run_id)["actions"][-1]["delegated_execution"]["fenced"]
        with pytest.raises(ValidationError, match="open"):
            engine.submit(AgentSpec("new", "x"), "x", command_id="new")
        runner.close_failure = False
        await runtime.aclose()
        assert runner.closed == journal.closed == 1

    asyncio.run(exercise())


def test_cancelled_resource_close_keeps_authority_until_same_loop_retry(tmp_path):
    async def exercise():
        runtime, engine, runner, journal = await managed_pending(tmp_path)
        runner.fail_stop = False
        runner.close_release = asyncio.Event()
        closing = asyncio.create_task(runtime.aclose())
        await runner.close_entered.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert engine._lifecycle == "open"
        assert journal.closed == 0
        assert len(runtime._context._resources) == 2
        runner.close_release.set()
        await runtime.aclose()
        assert runner.closed == journal.closed == 1
        assert engine._lifecycle == "closed"

    asyncio.run(exercise())


def test_pending_query_failure_retains_ownership_for_retry(tmp_path):
    async def exercise():
        runtime, engine, runner, journal = await managed_pending(tmp_path)
        original = engine.store.delegated_pending
        engine.store.delegated_pending = lambda scope: ()
        with pytest.raises(ValidationError, match="Store"):
            await runtime.aclose()
        assert engine._lifecycle == "open"
        assert len(runtime._context._resources) == 2
        assert runner.closed == journal.closed == 0
        engine.store.delegated_pending = original
        runner.fail_stop = False
        await runtime.aclose()

    asyncio.run(exercise())


def test_fenced_receipt_does_not_close_an_actual_active_worker(tmp_path):
    async def exercise():
        runtime, engine, runner, journal = await managed_pending(tmp_path, fail_stop=False)
        runner.active_operations = 1
        with pytest.raises(ValidationError, match="active"):
            await runtime.aclose()
        assert engine._lifecycle == "open"
        assert len(runtime._context._resources) == 2
        assert runner.closed == journal.closed == 0
        runner.active_operations = 0
        await runtime.aclose()

    asyncio.run(exercise())


def test_sqlite_close_failure_after_coding_cleanup_permits_retry(tmp_path):
    async def exercise():
        runtime, engine, runner, journal = await managed_pending(tmp_path, fail_stop=False)
        original = engine.store.close

        def failed_close():
            raise RuntimeError("sqlite close fault")

        engine.store.close = failed_close
        with pytest.raises(RuntimeError, match="sqlite close fault"):
            await runtime.aclose()
        assert engine._lifecycle == "close_failed"
        assert runner.closed == journal.closed == 1
        engine.store.close = original
        await runtime.aclose()
        assert engine._lifecycle == "closed"
        assert runner.closed == journal.closed == 1

    asyncio.run(exercise())


def test_borrowed_coding_resource_is_never_closed_by_runtime(tmp_path):
    async def exercise():
        runtime, engine, runner, journal = await managed_pending(tmp_path, fail_stop=False)
        runtime._context._resources.clear()
        await runtime.aclose()
        assert engine._lifecycle == "closed"
        assert runner.closed == journal.closed == 0

    asyncio.run(exercise())


def test_preclose_adopts_each_original_runner_before_any_resource_close(tmp_path):
    from ralf_agent.delegated_coding import register_coding_tool

    from .helpers import tool_response

    async def exercise():
        first, second = (
            OwnedRunner(crash=True, fail_stop=True),
            OwnedRunner(crash=True, fail_stop=True),
        )
        engine, _ = coding_engine(
            tmp_path,
            first,
            [tool_response("coding", {"task": "one"}), tool_response("second", {"task": "two"})],
        )
        register_coding_tool(engine.tools, second, name="second")
        context = BuildContext(
            engine.store, tmp_path / "coding.db", engine.scope, tmp_path, allow_async=True
        )
        journals = []
        for index, (name, runner) in enumerate((("coding", first), ("second", second))):
            handle = engine.submit(AgentSpec(name, "x", (name,)), "x", command_id=f"s{index}")
            await engine.drive(handle.run_id)
            action = engine.store.run(handle.run_id)["actions"][-1]
            engine.approve(handle.run_id, action["id"], action["digest"], command_id=f"a{index}")
            await engine.drive(handle.run_id)
            runner.engine, runner.run_id = engine, handle.run_id
            journals.append(context.own(Journal(runner)))
            context.own_async(runner)
        runtime = RuntimeInstance(engine, context)
        first.fail_stop = False
        with pytest.raises(ValidationError, match="incomplete"):
            await runtime.aclose()
        assert engine.store.run(first.run_id)["actions"][-1]["delegated_execution"]["fenced"]
        assert not engine.store.run(second.run_id)["actions"][-1]["delegated_execution"]["fenced"]
        assert first.closed == second.closed == 0
        assert len(context._resources) == 4
        second.fail_stop = False
        await runtime.aclose()
        assert first.closed == second.closed == 1
        assert all(journal.closed == 1 for journal in journals)
        assert first.calls.count("execute") == second.calls.count("execute") == 1
        assert "reconcile" not in first.calls + second.calls

    asyncio.run(exercise())


def test_original_engine_rejects_business_while_owned_coding_cleanup_is_awaiting(tmp_path):
    from ralf_agent.agent_runtime import Runtime as AgentRuntime
    from ralf_agent.errors import AuthorizationDenied, CoordinatorBusy
    from ralf_agent.storage import SQLiteStore

    async def exercise():
        runtime, engine, runner, _ = await managed_pending(tmp_path, fail_stop=False)
        borrowed = AgentRuntime(engine)
        queued = engine.submit(AgentSpec("queued", "x"), "x", command_id="queued")
        runner.close_release = asyncio.Event()
        closing = asyncio.create_task(runtime.aclose())
        await runner.close_entered.wait()
        try:
            with pytest.raises(ValidationError, match="closing|cleanup|open"):
                engine.submit(AgentSpec("new", "x"), "x", command_id="new")
            with pytest.raises(ValidationError, match="closing|cleanup|open"):
                await engine.drive(queued.run_id)
            with pytest.raises(ValidationError, match="closing|cleanup|open"):
                await borrowed.submit(AgentSpec("borrowed", "x"), "x", command_id="borrowed")
            with pytest.raises(ValidationError, match="closing|cleanup"):
                engine.close()
            with SQLiteStore(tmp_path / "coding.db") as competing:
                with pytest.raises(CoordinatorBusy):
                    competing.create_coordinator().acquire()
            runner.authority.check(runner.envelope, runner.identity)
            runner.authority.adopt("error", {"code": "late_stop_evidence"})
            with pytest.raises(AuthorizationDenied, match="cleanup"):
                runner.authority.authorize("turn/start", {}, {})
            assert engine._lifecycle == "open"
            assert engine.store.run(queued.run_id)["state"] == "queued"
        finally:
            runner.close_release.set()
            await closing

    asyncio.run(exercise())


def test_original_engine_remains_cleanup_only_after_cancelled_owned_close(tmp_path):
    async def exercise():
        runtime, engine, runner, _ = await managed_pending(tmp_path, fail_stop=False)
        queued = engine.submit(AgentSpec("queued", "x"), "x", command_id="queued")
        runner.close_release = asyncio.Event()
        closing = asyncio.create_task(runtime.aclose())
        await runner.close_entered.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        try:
            with pytest.raises(ValidationError, match="closing|cleanup|open"):
                engine.submit(AgentSpec("new", "x"), "x", command_id="new")
            with pytest.raises(ValidationError, match="closing|cleanup|open"):
                await engine.drive(queued.run_id)
            assert engine.store.run(queued.run_id)["actions"] == []
        finally:
            runner.close_release.set()
            await runtime.aclose()

    asyncio.run(exercise())


def test_cancelled_initial_drain_also_keeps_original_engine_cleanup_only(tmp_path):
    async def exercise():
        runtime, engine, _, _ = await managed_pending(tmp_path, fail_stop=False)
        entered, release = asyncio.Event(), asyncio.Event()
        original = engine.wait_for_threads

        async def wait():
            entered.set()
            await release.wait()

        engine.wait_for_threads = wait
        closing = asyncio.create_task(runtime.aclose())
        await entered.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        try:
            with pytest.raises(ValidationError, match="open|cleanup"):
                engine.submit(AgentSpec("new", "x"), "x", command_id="new")
        finally:
            engine.wait_for_threads = original
            await runtime.aclose()

    asyncio.run(exercise())
