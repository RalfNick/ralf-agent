"""Original grants cannot outlive their reader or escape close/cancellation."""

import asyncio
import copy

import pytest

from ralf_agent import ContextExecutionOwner, InMemoryMemory, ManagedContextPipeline
from ralf_agent.errors import CloseIncomplete

from .test_temporal_context_read_runtime import call, turn
from .test_temporal_context_read_state import admission, proof, state_for
from .test_temporal_context_read_worker_contracts import Client, setup
from .test_temporal_persistent_session_data import runtime


class Source(InMemoryMemory):
    def __init__(self):
        super().__init__()
        self.reads = 0

    async def read_page(self, scope, address, query):
        self.reads += 1
        return super().read_page(scope, address, query)


@pytest.mark.parametrize("managed", [False, True])
def test_end_ack_before_response_never_redispatches_original_reader(managed):
    async def run():
        source = Source()
        host = runtime(
            source,
            context_reads=True,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        _, state = turn(host)
        action, request = state.next_operation()
        try:
            first = await call(host, state, action, request)
            assert first["ok"] is True
            assert await host.wait_context_executions(wait_timeout=3)
            assert not state.quiescent
            duplicate = await call(host, state, action, request)
            assert duplicate["ok"] is False
            assert source.reads == 1
            method = state.accept_managed_context if managed else state.accept_context
            method(action["id"], first)
            assert state.quiescent
        finally:
            await host.close_context_execution(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_borrowed_close_owns_pending_admission_and_refuses_late_reader(managed):
    async def run():
        source, owner = Source(), ContextExecutionOwner()
        host = runtime(
            source,
            context_reads=True,
            context_execution=owner,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        _, state = turn(host)
        action, request = state.next_operation()
        admitted, release = asyncio.Event(), asyncio.Event()

        async def guard(value):
            granted = state.admit_context_dispatch(admission(value))
            admitted.set()
            await release.wait()
            return granted

        async def ended(value):
            state.context_execution_ended(value)

        method = host.manage_context if managed else host.prepare_context
        observer = asyncio.create_task(method(request, dispatch_guard=guard, on_end=ended))
        try:
            await asyncio.wait_for(admitted.wait(), 3)
            with pytest.raises(CloseIncomplete):
                await host.close_context_execution(wait_timeout=0)
            assert source.reads == 0 and not owner._closed
            release.set()
            result = await observer
            assert result["ok"] is False and result["handler_not_started"] is True
            receiver = state.accept_managed_context if managed else state.accept_context
            receiver(action["id"], result)
            await host.close_context_execution(wait_timeout=3)
            assert source.reads == 0 and state.quiescent and not owner._closed
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)
            await host.close_context_execution(wait_timeout=3)
            await owner.aclose(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_observer_cancel_during_admission_retains_original_completion(managed):
    async def run():
        source = Source()
        host = runtime(
            source,
            context_reads=True,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        _, state = turn(host)
        action, request = state.next_operation()
        admitted, release = asyncio.Event(), asyncio.Event()

        async def guard(value):
            result = state.admit_context_dispatch(admission(value))
            admitted.set()
            await release.wait()
            return result

        async def ended(value):
            state.context_execution_ended(value)

        method = host.manage_context if managed else host.prepare_context
        observer = asyncio.create_task(method(request, dispatch_guard=guard, on_end=ended))
        try:
            await asyncio.wait_for(admitted.wait(), 3)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            receiver = state.accept_managed_context if managed else state.accept_context
            receiver(action["id"], {"ok": False, "code": "activity_outcome_unknown"})
            assert not state.quiescent
            assert not await host.wait_context_executions(wait_timeout=0)
            release.set()
            assert await host.wait_context_executions(wait_timeout=3)
            assert state.quiescent
            assert state.context_read_stages[action["id"]]["execution_end_proof"] == proof(request)
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)
            await host.close_context_execution(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["context", "plan", "read", "verify", "finalize"])
def test_original_end_fences_later_dispatch_without_changing_original_grant(phase):
    state, action, request = state_for(phase)
    granted = state.admit_context_dispatch(admission(request))
    state.context_execution_ended(proof(request))
    later = state.admit_context_dispatch(admission(request))
    assert later["allowed"] is False
    assert action["dispatch_grant"] == granted and not state.quiescent


def test_sdk_repeat_guard_cannot_reuse_server_cached_allow_after_end():
    class CachedClient(Client):
        def __init__(self, state):
            super().__init__(state)
            self.cache = {}

        async def execute_update(self, name, payload, *, id):
            if id not in self.cache:
                self.cache[id] = await super().execute_update(name, payload, id=id)
            return copy.deepcopy(self.cache[id])

    async def run():
        from ralf_agent.temporal_context_read_activities import callbacks

        state, _, request, _, info = setup()
        client = CachedClient(state)
        guard, ended = callbacks(client, request, info)
        assert (await guard(request))["allowed"] is True
        await ended(proof(request))
        assert (await guard(request))["allowed"] is False

    asyncio.run(run())


def test_failed_guard_after_persisted_grant_keeps_completion_responsibility():
    async def run():
        source = Source()
        host = runtime(source, context_reads=True)
        _, state = turn(host)
        action, request = state.next_operation()
        attempts = 0

        async def guard(value):
            nonlocal attempts
            attempts += 1
            granted = state.admit_context_dispatch(admission(value))
            if attempts == 1:
                raise OSError("response lost after original grant")
            return granted

        async def ended(value):
            state.context_execution_ended(value)

        try:
            result = await host.prepare_context(request, dispatch_guard=guard, on_end=ended)
            assert result["ok"] is False and source.reads == 0
            state.accept_context(action["id"], result)
            assert await host.wait_context_executions(wait_timeout=3)
            assert state.quiescent
            assert state.context_read_stages[action["id"]]["execution_end_proof"] == proof(request)
        finally:
            await host.close_context_execution(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)

    asyncio.run(run())


def test_all_loop_cancel_during_admission_retains_non_start_end_proof():
    source = Source()
    host = runtime(source, context_reads=True)
    _, state = turn(host)
    action, request = state.next_operation()
    loop = asyncio.new_event_loop()
    admitted, release = asyncio.Event(), asyncio.Event()

    async def guard(value):
        granted = state.admit_context_dispatch(admission(value))
        admitted.set()
        await release.wait()
        return granted

    async def ended(value):
        state.context_execution_ended(value)

    async def begin():
        asyncio.create_task(host.prepare_context(request, dispatch_guard=guard, on_end=ended))
        await admitted.wait()

    try:
        loop.run_until_complete(begin())
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.close()
        state.accept_context(action["id"], {"ok": False, "code": "activity_outcome_unknown"})

        async def finish():
            assert not await host.wait_context_executions(wait_timeout=0)
            release.set()
            assert await host.wait_context_executions(wait_timeout=3)
            assert source.reads == 0 and state.quiescent
            assert state.context_read_stages[action["id"]]["execution_end_proof"] == proof(request)

        asyncio.run(finish())
    finally:
        release.set()
        if not loop.is_closed():
            loop.close()
        asyncio.run(host.close_context_execution(wait_timeout=3))
        asyncio.run(host.close_session_execution(wait_timeout=3))
