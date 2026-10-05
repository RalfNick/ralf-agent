import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ralf_agent import Scope
from ralf_agent.tools import invoke
from ralf_agent.types import InvocationContext


def tracker():
    from ralf_agent.tools import ThreadExecutionTracker

    return ThreadExecutionTracker()


async def wait_until_started(started):
    async with asyncio.timeout(5):
        while not started.is_set():  # noqa: ASYNC110 - tests may occupy the sole executor worker
            await asyncio.sleep(0.001)


def test_cancelled_invocation_tracks_the_real_thread_after_loop_close():
    execution = tracker()
    started = threading.Event()
    release = threading.Event()
    ended = threading.Event()
    loop = asyncio.new_event_loop()
    context = InvocationContext(Scope(), "run", "action", "attempt", "effect", "epoch")

    def handler(arguments, context):
        started.set()
        try:
            assert release.wait(5)
            return {"written": True}
        finally:
            ended.set()

    async def start_and_cancel():
        task = asyncio.create_task(invoke(handler, {}, context, thread_tracker=execution))
        await wait_until_started(started)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        loop.run_until_complete(start_and_cancel())
        loop.close()
        assert execution.has_active
        assert execution.active_count == 1
        assert execution.has_active_for("run")
        assert not execution.has_active_for("other")
        assert not ended.is_set()
        release.set()
        asyncio.run(execution.drain())
        assert ended.is_set()
        assert not execution.has_active
    finally:
        release.set()
        if not loop.is_closed():
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
        assert ended.wait(5)


def test_cancelled_queued_invocation_never_starts_and_releases_tracking():
    execution = tracker()
    occupied = threading.Event()
    release = threading.Event()
    writes = []
    pool = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.new_event_loop()
    loop.set_default_executor(pool)

    def occupy_executor():
        occupied.set()
        assert release.wait(5)

    def handler():
        writes.append("executed")

    async def queue_and_cancel():
        blocker = loop.run_in_executor(None, occupy_executor)
        await wait_until_started(occupied)
        task = asyncio.create_task(execution.run(handler, group="queued"))
        await asyncio.sleep(0)
        assert execution.active_count == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not execution.has_active
        release.set()
        await blocker
        await loop.shutdown_default_executor()

    try:
        loop.run_until_complete(queue_and_cancel())
        assert writes == []
    finally:
        release.set()
        pool.shutdown(wait=True)
        loop.close()


def test_cancelled_call_cannot_begin_after_executor_worker_has_started():
    execution = tracker()
    worker_started = threading.Event()
    release_worker = threading.Event()
    writes = []

    class PausedExecutor(ThreadPoolExecutor):
        def submit(self, function, *args, **kwargs):
            def run():
                worker_started.set()
                assert release_worker.wait(5)
                return function(*args, **kwargs)

            return super().submit(run)

    pool = PausedExecutor(max_workers=1)
    loop = asyncio.new_event_loop()
    loop.set_default_executor(pool)

    def handler():
        writes.append("executed")

    async def start_and_cancel():
        task = asyncio.create_task(execution.run(handler, group="run"))
        await wait_until_started(worker_started)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not execution.has_active
        release_worker.set()
        await loop.shutdown_default_executor()

    try:
        loop.run_until_complete(start_and_cancel())
        assert writes == []
    finally:
        release_worker.set()
        pool.shutdown(wait=True)
        loop.close()


def test_cancelling_drain_does_not_forget_a_running_handler():
    execution = tracker()
    started = threading.Event()
    release = threading.Event()

    def handler():
        started.set()
        assert release.wait(5)

    async def exercise():
        invocation = asyncio.create_task(execution.run(handler, group="run"))
        await wait_until_started(started)
        draining = asyncio.create_task(execution.drain("run"))
        await asyncio.sleep(0)
        draining.cancel()
        with pytest.raises(asyncio.CancelledError):
            await draining
        assert execution.has_active_for("run")
        release.set()
        await invocation
        await execution.drain("run")
        assert not execution.has_active_for("run")

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_thread_exception_releases_tracking():
    execution = tracker()

    def handler():
        raise ValueError("handler failed")

    async def exercise():
        with pytest.raises(ValueError, match="handler failed"):
            await execution.run(handler, group="run")
        assert not execution.has_active

    asyncio.run(exercise())


def test_sync_handler_returning_coroutine_is_still_awaited():
    execution = tracker()
    context = InvocationContext(Scope(), "run", "action", "attempt", "effect", "epoch")

    async def result():
        return {"value": 42}

    def handler(arguments, context):
        return result()

    async def exercise():
        assert await invoke(handler, {}, context, thread_tracker=execution) == {"value": 42}
        assert not execution.has_active

    asyncio.run(exercise())
