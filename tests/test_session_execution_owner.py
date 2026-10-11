import asyncio
import threading

import pytest

from ralf_agent import InMemoryMemory, ThreadedMemoryAdapter
from ralf_agent.recall import RecallQuery
from ralf_agent.temporal_session_data import SessionReadRegistration


def test_cancelled_observer_does_not_discard_the_real_sync_handler():
    from ralf_agent.temporal_session_execution import SessionExecutionOwner

    class Source(InMemoryMemory):
        def append(self, *args, **kwargs):
            entered.set()
            release.wait(3)
            return super().append(*args, **kwargs)

    entered, release = threading.Event(), threading.Event()
    ended = []

    async def run():
        from ralf_agent import Scope

        owner = SessionExecutionOwner()
        source = SessionReadRegistration(ThreadedMemoryAdapter(Source()), RecallQuery())

        async def notify(proof):
            ended.append(proof)

        proof = {"action_id": "a"}
        task = asyncio.create_task(
            owner.append(
                source,
                Scope(),
                "s",
                {},
                expected_revision=0,
                message_id="m",
                proof=proof,
                on_end=notify,
            )
        )
        await asyncio.to_thread(entered.wait, 2)
        assert entered.is_set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert owner.active_count == 1 and not ended
        assert not await owner.wait(wait_timeout=0)
        release.set()
        assert await owner.wait(wait_timeout=3)
        assert ended == [proof] and owner.active_count == 0
        await owner.aclose()

    try:
        asyncio.run(run())
    finally:
        release.set()


def test_actual_method_error_still_proves_handler_ended():
    from ralf_agent.temporal_session_execution import SessionExecutionOwner

    class Source(InMemoryMemory):
        def append(self, *args, **kwargs):
            raise OSError("stopped")

    async def run():
        from ralf_agent import Scope

        owner = SessionExecutionOwner()
        source = SessionReadRegistration(ThreadedMemoryAdapter(Source()), RecallQuery())
        ended = []

        async def notify(proof):
            ended.append(proof)

        try:
            await owner.append(
                source,
                Scope(),
                "s",
                {},
                expected_revision=0,
                message_id="m",
                proof={"action_id": "a"},
                on_end=notify,
            )
        except Exception:
            pass
        assert await owner.wait(wait_timeout=2)
        assert ended == [{"action_id": "a"}]
        await owner.aclose()

    asyncio.run(run())


def test_global_loop_cancellation_keeps_actual_thread_and_later_end_delivery():
    from ralf_agent import Scope
    from ralf_agent.temporal_session_execution import SessionExecutionOwner

    entered, release = threading.Event(), threading.Event()
    ended = []

    class Source(InMemoryMemory):
        def append(self, *args, **kwargs):
            entered.set()
            release.wait(3)
            return super().append(*args, **kwargs)

    owner = SessionExecutionOwner()
    source = SessionReadRegistration(ThreadedMemoryAdapter(Source()), RecallQuery())

    async def notify(proof):
        ended.append(proof)

    loop = asyncio.new_event_loop()

    async def start():
        asyncio.create_task(
            owner.append(
                source,
                Scope(),
                "s",
                {},
                expected_revision=0,
                message_id="m",
                proof={"action_id": "a"},
                on_end=notify,
            )
        )
        await asyncio.to_thread(entered.wait, 2)

    try:
        loop.run_until_complete(start())
        pending = list(asyncio.all_tasks(loop))
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        assert owner.active_count == 1 and not ended
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
        release.set()

        async def finish():
            assert await owner.wait(wait_timeout=3)
            assert ended == [{"action_id": "a"}]
            await owner.aclose()

        asyncio.run(finish())
    finally:
        release.set()
        if not loop.is_closed():
            loop.close()


def test_end_notification_failure_retains_proof_and_refuses_close_then_retries():
    from ralf_agent import Scope
    from ralf_agent.errors import CloseIncomplete
    from ralf_agent.temporal_session_execution import SessionExecutionOwner

    async def run():
        owner = SessionExecutionOwner()
        backend = InMemoryMemory()
        source = SessionReadRegistration(backend, RecallQuery())
        allow = False
        received = []

        async def notify(proof):
            if not allow:
                raise OSError("control unavailable")
            received.append(proof)

        await owner.append(
            source,
            Scope(),
            "s",
            {},
            expected_revision=0,
            message_id="m",
            proof={"action_id": "a"},
            on_end=notify,
        )
        with pytest.raises(CloseIncomplete):
            await owner.aclose(wait_timeout=0.02)
        assert owner.active_count == 0 and not received
        allow = True
        assert await owner.wait(wait_timeout=2)
        assert received == [{"action_id": "a"}] and backend.read(Scope(), "s")[0] == 1
        await owner.aclose()

    asyncio.run(run())
