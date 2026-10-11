"""Real readers and notifications survive observation/loop cancellation."""

import asyncio
import threading

import pytest

from ralf_agent import InMemoryMemory, Scope, ThreadedMemoryAdapter
from ralf_agent.errors import CloseIncomplete, MemoryBackendError, ValidationError
from ralf_agent.recall import RecallQuery


def proof(action="run-a:context:0:1", epoch="epoch-a"):
    return {
        "scope": {"workspace": "app", "principal": "user"},
        "action_id": action,
        "release_digest": "c" * 64,
        "request_digest": "d" * 64,
        "execution_epoch": epoch,
    }


def owner(**options):
    from ralf_agent.temporal_context_execution import ContextExecutionOwner

    return ContextExecutionOwner(**options)


def blocked_reader():
    started, finish, stopped = threading.Event(), threading.Event(), threading.Event()

    class Source(InMemoryMemory):
        calls = 0

        def read_page(self, *args, **kwargs):
            self.calls += 1
            started.set()
            try:
                assert finish.wait(10), "fixture must release actual reader"
                return super().read_page(*args, **kwargs)
            finally:
                stopped.set()

    source = Source()
    return ThreadedMemoryAdapter(source), source, started, finish, stopped


async def wait_started(event):
    for _ in range(300):
        if event.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("real reader did not start")


def test_observer_cancel_keeps_real_thread_and_end_notification_owned():
    async def run():
        reader, source, started, finish, stopped = blocked_reader()
        execution = owner()
        delivered = []
        value = proof()

        async def operation():
            return await reader.read_page(Scope(), "s", RecallQuery())

        async def end(receipt):
            delivered.append(receipt)

        observer = asyncio.create_task(execution.execute(operation, proof=value, on_end=end))
        try:
            await wait_started(started)
            value["scope"]["workspace"] = "mutated"
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert execution.active_count == 1
            assert not await execution.wait(wait_timeout=0.01)
            with pytest.raises(CloseIncomplete):
                await execution.aclose(wait_timeout=0.01)
            assert not stopped.is_set() and not delivered
            finish.set()
            assert await execution.wait(wait_timeout=3)
            assert stopped.is_set() and source.calls == 1
            assert delivered == [proof()]
            await execution.aclose(wait_timeout=3)
            with pytest.raises(MemoryBackendError):
                await execution.execute(operation, proof=proof("later"))
        finally:
            finish.set()
            if not observer.done():
                observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
            await execution.aclose(wait_timeout=3)

    asyncio.run(run())


def test_async_reader_remains_on_original_loop_and_observer_cancel_does_not_stop_it():
    async def run():
        execution = owner()
        loop = asyncio.get_running_loop()
        started, finish = asyncio.Event(), asyncio.Event()
        returned = []

        async def operation():
            assert asyncio.get_running_loop() is loop
            started.set()
            await finish.wait()
            returned.append("value")
            return {"answer": "value"}

        observer = asyncio.create_task(execution.execute(operation, proof=proof()))
        try:
            await started.wait()
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert not await execution.wait(wait_timeout=0.01)
            finish.set()
            assert await execution.wait(wait_timeout=3)
            assert returned == ["value"]
        finally:
            finish.set()
            await execution.aclose(wait_timeout=3)

    asyncio.run(run())


def test_cancel_all_loop_tasks_does_not_disown_real_thread():
    reader, source, started, finish, stopped = blocked_reader()
    execution = owner()
    delivered = []
    loop = asyncio.new_event_loop()

    async def operation():
        return await reader.read_page(Scope(), "s", RecallQuery())

    async def end(receipt):
        delivered.append(receipt)

    async def begin():
        asyncio.create_task(execution.execute(operation, proof=proof(), on_end=end))
        await wait_started(started)

    try:
        loop.run_until_complete(begin())
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.close()

        async def after():
            assert execution.active_count == 1 and not stopped.is_set()
            assert not await execution.wait(wait_timeout=0.01)
            with pytest.raises(CloseIncomplete):
                await execution.aclose(wait_timeout=0.01)
            finish.set()
            assert await execution.wait(wait_timeout=3)
            assert stopped.is_set() and delivered == [proof()] and source.calls == 1
            await execution.aclose(wait_timeout=3)

        asyncio.run(after())
    finally:
        finish.set()
        if not loop.is_closed():
            loop.close()
        assert stopped.wait(3)
        asyncio.run(execution.aclose(wait_timeout=3))


def test_notification_failure_retains_entry_until_acknowledged():
    async def run():
        execution = owner()
        ack = False
        attempted = asyncio.Event()
        delivered = []

        async def operation():
            return "result"

        async def end(receipt):
            attempted.set()
            if not ack:
                raise RuntimeError("transport unavailable")
            delivered.append(receipt)

        assert await execution.execute(operation, proof=proof(), on_end=end) == "result"
        await attempted.wait()
        assert execution.active_count == 0
        assert not await execution.wait(wait_timeout=0.01)
        with pytest.raises(CloseIncomplete):
            await execution.aclose(wait_timeout=0.01)
        ack = True
        assert await execution.wait(wait_timeout=3)
        assert delivered == [proof()]
        await execution.aclose()

    asyncio.run(run())


def test_capacity_and_duplicate_refusal_never_start_extra_reader():
    async def run():
        execution = owner(max_calls=1)
        started, finish = asyncio.Event(), asyncio.Event()
        extra = []

        async def original():
            started.set()
            await finish.wait()
            return "first"

        async def another():
            extra.append("started")
            return "extra"

        observer = asyncio.create_task(execution.execute(original, proof=proof()))
        try:
            await started.wait()
            for value in (proof(), proof("different")):
                with pytest.raises(MemoryBackendError):
                    await execution.execute(another, proof=value)
            assert not extra and execution.active_count == 1
            finish.set()
            assert await observer == "first"
            assert await execution.wait(wait_timeout=3)
        finally:
            finish.set()
            await asyncio.gather(observer, return_exceptions=True)
            await execution.aclose(wait_timeout=3)

    asyncio.run(run())


@pytest.mark.parametrize("timeout", [True, -1, float("nan"), float("inf"), "1"])
def test_invalid_wait_never_closes_or_reports_quiet(timeout):
    async def run():
        execution = owner()
        with pytest.raises(ValidationError):
            await execution.wait(wait_timeout=timeout)
        with pytest.raises(ValidationError):
            await execution.aclose(wait_timeout=timeout)

        async def operation():
            return "still-open"

        assert await execution.execute(operation, proof=proof()) == "still-open"
        await execution.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("value", [0, 257, True, 1.5])
def test_invalid_capacity_refuses_construction(value):
    with pytest.raises(ValidationError):
        owner(max_calls=value)


def test_lazy_operation_and_malformed_proof_are_rejected_before_execution():
    async def run():
        execution = owner()
        calls = []

        async def operation():
            calls.append("started")
            return None

        with pytest.raises(ValidationError):
            await execution.execute(lambda: operation(), proof=proof())
        bad = proof()
        bad["execution_epoch"] = ""
        with pytest.raises(ValidationError):
            await execution.execute(operation, proof=bad)
        assert not calls
        await execution.aclose()

    asyncio.run(run())


def test_notification_must_finish_with_none_not_lazy_ack():
    async def run():
        execution = owner()
        correct = False

        async def operation():
            return None

        async def end(value):
            return None if correct else True

        await execution.execute(operation, proof=proof(), on_end=end)
        assert not await execution.wait(wait_timeout=0.01)
        correct = True
        assert await execution.wait(wait_timeout=3)
        await execution.aclose()

    asyncio.run(run())


def test_returned_unfinished_task_is_stopped_before_end_ack():
    async def run():
        execution = owner()
        started, stopped, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
        children = []

        async def child():
            started.set()
            try:
                await finish.wait()
            finally:
                stopped.set()

        async def operation():
            task = asyncio.create_task(child())
            children.append(task)
            await started.wait()
            return task

        try:
            with pytest.raises(ValidationError):
                await execution.execute(operation, proof=proof())
            assert await execution.wait(wait_timeout=3)
            assert stopped.is_set() and children[0].done()
        finally:
            finish.set()
            await asyncio.gather(*children, return_exceptions=True)
            await execution.aclose(wait_timeout=3)

    asyncio.run(run())


def test_open_async_generator_cannot_be_an_execution_result():
    async def run():
        execution = owner()
        stopped = []
        streams = []

        async def stream():
            try:
                yield "value"
            finally:
                stopped.append("closed")

        async def operation():
            value = stream()
            streams.append(value)
            await anext(value)
            return value

        try:
            with pytest.raises(ValidationError):
                await execution.execute(operation, proof=proof())
            assert await execution.wait(wait_timeout=3)
            assert stopped == ["closed"]
        finally:
            for value in streams:
                await value.aclose()
            await execution.aclose(wait_timeout=3)

    asyncio.run(run())


def test_timed_out_thread_notifies_autonomously_after_real_reader_exits():
    async def run():
        execution = owner()
        reader, source, started, finish, stopped = blocked_reader()
        delivered = asyncio.Event()

        async def operation():
            try:
                await asyncio.wait_for(reader.read_page(Scope(), "s", RecallQuery()), timeout=0.05)
            except TimeoutError:
                return {"ok": False}

        async def end(value):
            delivered.set()

        try:
            assert await execution.execute(operation, proof=proof(), on_end=end) == {"ok": False}
            assert started.is_set() and not stopped.is_set()
            assert execution.active_count == 1 and not delivered.is_set()
            finish.set()
            await asyncio.wait_for(delivered.wait(), timeout=3)
            assert stopped.is_set() and source.calls == 1
        finally:
            finish.set()
            await execution.aclose(wait_timeout=3)

    asyncio.run(run())


def test_foreign_future_refusal_does_not_claim_its_pending_work_stopped():
    foreign = asyncio.new_event_loop()
    value = foreign.create_future()

    async def run():
        execution = owner()

        async def operation():
            return value

        with pytest.raises(ValidationError):
            await execution.execute(operation, proof=proof())
        assert not await execution.wait(wait_timeout=0.01)
        with pytest.raises(CloseIncomplete):
            await execution.aclose(wait_timeout=0.01)
        value.set_result("completed")
        assert await execution.wait(wait_timeout=3)
        await execution.aclose()

    try:
        asyncio.run(run())
    finally:
        foreign.close()
