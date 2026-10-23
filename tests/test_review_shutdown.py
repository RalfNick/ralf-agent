import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry, ToolSpec
from relf_agent.errors import CoordinatorBusy, ValidationError

from .helpers import ScriptedProvider, tool_response


def runtime_with(store, *, tools=None, provider=None):
    return LocalEngine(
        store,
        providers={"default": ScriptedProvider([]) if provider is None else provider},
        tools=ToolRegistry() if tools is None else tools,
    )


def write_registry(handler, *, approval=False):
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change",
            "Write a test business value",
            {"type": "object"},
            effect="unqueryable_write",
            requires_approval=approval,
        ),
        handler,
    )
    return tools


def cancel_all_tasks(loop):
    pending = list(asyncio.all_tasks(loop))
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))


def finish_loop(loop):
    cancel_all_tasks(loop)
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(loop.shutdown_default_executor())
    loop.run_until_complete(asyncio.sleep(0))


def call_runtime_operation(runtime, run_id, operation, action=None):
    action = {"action_id": "action", "digest": "digest"} if action is None else action
    if operation == "submit":
        return runtime.submit(AgentSpec("a", "x"), "x", command_id="after-close")
    if operation == "drive":
        return asyncio.run(runtime.drive(run_id))
    if operation == "cancel":
        return runtime.cancel(run_id, command_id="after-close")
    if operation == "approve":
        return runtime.approve(
            run_id, action["action_id"], action["digest"], command_id="after-close"
        )
    if operation == "reconcile":
        return runtime.reconcile(run_id, action["action_id"], {}, command_id="after-close")
    if operation == "status":
        return runtime.status(run_id)
    return runtime.events(run_id)


def test_failed_store_close_keeps_the_coordinator_until_retry_succeeds(tmp_path):
    class RetryCloseStore(SQLiteStore):
        close_attempts = 0

        def close(self):
            self.close_attempts += 1
            if self.close_attempts == 1:
                raise ConnectionError("The adapter could not close its connection")
            super().close()

    path = tmp_path / "close-failure.db"
    runtime = runtime_with(RetryCloseStore(path))
    try:
        with pytest.raises(ConnectionError):
            runtime.close()

        with SQLiteStore(path) as contender_store:
            contender = None
            try:
                with pytest.raises(CoordinatorBusy):
                    contender = runtime_with(contender_store)
            finally:
                if contender is not None:
                    contender.close()

        runtime.close()
        assert runtime.store.close_attempts == 2
        with runtime_with(SQLiteStore(path)) as replacement:
            accepted = replacement.submit(AgentSpec("a", "x"), "x", command_id="replacement")
            assert replacement.status(accepted.run_id).state == "queued"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "operation", ["submit", "drive", "cancel", "approve", "reconcile", "status", "events"]
)
def test_successfully_closed_runtime_rejects_further_execution(tmp_path, operation):
    path = tmp_path / "closed.db"
    runtime = runtime_with(SQLiteStore(path))
    run = runtime.submit(AgentSpec("a", "x"), "x", command_id="first")
    runtime.close()
    with runtime_with(SQLiteStore(path)) as replacement:
        with pytest.raises(ValidationError):
            call_runtime_operation(runtime, run.run_id, operation)
        assert replacement.status(run.run_id).state == "queued"


@pytest.mark.parametrize(
    "operation", ["submit", "drive", "cancel", "approve", "reconcile", "status", "events"]
)
def test_failed_close_runtime_only_allows_retrying_close(tmp_path, operation):
    class RetryCloseStore(SQLiteStore):
        close_attempts = 0

        def close(self):
            self.close_attempts += 1
            if self.close_attempts == 1:
                raise ConnectionError("The adapter could not close its connection")
            super().close()

    async def change(arguments, context):
        if operation == "reconcile":
            raise ConnectionError("The business response was lost")
        return arguments

    needs_action = operation in {"approve", "reconcile"}
    tools = write_registry(change, approval=operation == "approve") if needs_action else None
    runtime = runtime_with(
        RetryCloseStore(tmp_path / "failed-close-state.db"),
        tools=tools,
        provider=ScriptedProvider([tool_response()]) if needs_action else None,
    )
    try:
        run = runtime.submit(
            AgentSpec("a", "x", ("change",) if needs_action else ()), "x", command_id="first"
        )
        action = None
        if needs_action:
            snapshot = asyncio.run(runtime.drive(run.run_id))
            if operation == "approve":
                assert snapshot.state == "waiting_approval"
                action = snapshot.pending[0]
            else:
                assert snapshot.state == "waiting_reconciliation"
                action = {"action_id": snapshot.actions[-1]["id"]}
        with pytest.raises(ConnectionError):
            runtime.close()
        with pytest.raises(ValidationError):
            call_runtime_operation(runtime, run.run_id, operation, action)
    finally:
        runtime.close()


def test_failed_lease_release_retry_does_not_close_the_store_again(tmp_path):
    class CountingStore(SQLiteStore):
        close_attempts = 0

        def close(self):
            self.close_attempts += 1
            super().close()

    class RetryReleaseLease:
        release_attempts = 0

        def __init__(self, actual):
            self.actual = actual

        def acquire(self):
            self.actual.acquire()

        def release(self):
            self.release_attempts += 1
            if self.release_attempts == 1:
                raise ConnectionError("The lease could not finish releasing")
            self.actual.release()

    path = tmp_path / "release-failure.db"
    store = CountingStore(path)
    lease = RetryReleaseLease(store.create_coordinator())
    runtime = LocalEngine(store, providers={}, tools=ToolRegistry(), coordinator=lease)
    try:
        with pytest.raises(ConnectionError):
            runtime.close()
        assert store.close_attempts == 1
        with SQLiteStore(path) as contender_store:
            contender = None
            try:
                with pytest.raises(CoordinatorBusy):
                    contender = runtime_with(contender_store)
            finally:
                if contender is not None:
                    contender.close()
        with pytest.raises(ValidationError):
            runtime.submit(AgentSpec("a", "x"), "x", command_id="blocked")
        runtime.close()
        assert store.close_attempts == 1
        assert lease.release_attempts == 2
        with runtime_with(SQLiteStore(path)):
            pass
    finally:
        runtime.close()


def test_cancelling_all_service_tasks_does_not_release_a_running_sync_effect(tmp_path):
    loop = asyncio.new_event_loop()
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    effects = []

    def change(arguments, context):
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise TimeoutError("The test did not release its worker")
            effects.append(context.effect_key)
            return arguments
        finally:
            finished.set()

    path = tmp_path / "sync-shutdown.db"
    runtime = runtime_with(
        SQLiteStore(path),
        tools=write_registry(change),
        provider=ScriptedProvider([tool_response(), ModelResponse(output="done")]),
    )
    try:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="first")

        async def begin():
            asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 2)

        loop.run_until_complete(begin())
        cancel_all_tasks(loop)
        assert not finished.is_set()
        assert not asyncio.all_tasks(loop)
        with pytest.raises(CoordinatorBusy):
            loop.run_until_complete(runtime.drive(run.run_id))
        runtime.cancel(run.run_id, command_id="while-thread-running")
        action = runtime.status(run.run_id).actions[-1]
        assert action["status"] == "executing"
        assert action["attempts"][-1]["status"] == "executing"
        with pytest.raises(ValidationError):
            runtime.close()

        with SQLiteStore(path) as contender_store:
            contender = None
            try:
                with pytest.raises(CoordinatorBusy):
                    contender = runtime_with(contender_store)
            finally:
                if contender is not None:
                    contender.close()

        release.set()
        finish_loop(loop)
        assert finished.is_set()
        assert len(effects) == 1
        runtime.close()
        with runtime_with(SQLiteStore(path)):
            pass
    finally:
        release.set()
        try:
            finish_loop(loop)
            runtime.close()
        finally:
            loop.close()


def test_closed_service_loop_does_not_hide_a_running_sync_effect(tmp_path):
    loop = asyncio.new_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(executor)
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()

    def change(arguments, context):
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise TimeoutError("The test did not release its worker")
            return arguments
        finally:
            finished.set()

    path = tmp_path / "closed-loop.db"
    runtime = runtime_with(
        SQLiteStore(path),
        tools=write_registry(change),
        provider=ScriptedProvider([tool_response()]),
    )
    try:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="first")

        async def begin():
            asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 2)

        loop.run_until_complete(begin())
        cancel_all_tasks(loop)
        loop.close()
        assert not finished.is_set()
        with pytest.raises(ValidationError):
            runtime.close()
        with SQLiteStore(path) as contender_store:
            contender = None
            try:
                with pytest.raises(CoordinatorBusy):
                    contender = runtime_with(contender_store)
            finally:
                if contender is not None:
                    contender.close()
        release.set()
        executor.shutdown(wait=True)
        assert finished.is_set()
        runtime.close()
        with runtime_with(SQLiteStore(path)):
            pass
    finally:
        release.set()
        try:
            if not loop.is_closed():
                finish_loop(loop)
                loop.close()
            executor.shutdown(wait=True)
            runtime.close()
        finally:
            if not loop.is_closed():
                loop.close()


@pytest.mark.parametrize("handler_kind", ["function", "callable_object", "sync_wrapper"])
def test_cancelled_async_handler_does_not_leave_shutdown_permanently_blocked(
    tmp_path, handler_kind
):
    loop = asyncio.new_event_loop()
    started, exited = asyncio.Event(), asyncio.Event()

    async def change(arguments, context):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    class AsyncHandler:
        async def __call__(self, arguments, context):
            return await change(arguments, context)

    def sync_wrapper(arguments, context):
        return change(arguments, context)

    handler = {"function": change, "callable_object": AsyncHandler(), "sync_wrapper": sync_wrapper}[
        handler_kind
    ]
    path = tmp_path / "async-shutdown.db"
    runtime = runtime_with(
        SQLiteStore(path),
        tools=write_registry(handler),
        provider=ScriptedProvider([tool_response()]),
    )
    try:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="first")

        async def begin():
            asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 2)

        loop.run_until_complete(begin())
        cancel_all_tasks(loop)
        assert exited.is_set()
        assert not asyncio.all_tasks(loop)
        runtime.close()
        with runtime_with(SQLiteStore(path)):
            pass
    finally:
        try:
            finish_loop(loop)
            runtime.close()
        finally:
            loop.close()
