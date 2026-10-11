"""Real delegated read handlers survive cancellation of their Activity observer."""

import asyncio
import threading

import pytest

from ralf_agent import InMemoryMemory, ManagedContextPipeline, ThreadedMemoryAdapter
from ralf_agent.errors import CloseIncomplete, DefinitionMismatch, ValidationError
from ralf_agent.temporal_context_execution import ContextExecutionOwner
from ralf_agent.temporal_session_state import TemporalSessionState
from ralf_agent.temporal_state import TemporalRunState

from .test_temporal_context_read_state import admission
from .test_temporal_persistent_session_data import accepted, runtime


class WaitingMemory(InMemoryMemory):
    def __init__(self):
        super().__init__()
        self.started, self.release, self.stopped = (threading.Event() for _ in range(3))
        self.block_dataset = False
        self.block_page = True
        self.reads, self.closes = 0, 0

    def _wait(self):
        self.started.set()
        try:
            assert self.release.wait(10)
        finally:
            self.stopped.set()

    def read_page(self, *args, **kwargs):
        self.reads += 1
        if self.block_page:
            self._wait()
        return super().read_page(*args, **kwargs)

    def inspect_session_identity(self):
        if self.block_dataset and self.reads:
            self._wait()
        return super().inspect_session_identity()

    def close(self):
        self.closes += 1


def turn(host, session_id="s"):
    session = TemporalSessionState({**accepted(host), "session_id": session_id})
    session.command(
        {
            "scope": session.scope,
            "kind": "submit",
            "command_id": "first",
            "session_ref": session.ref.to_dict(),
            "input": "task",
            "budget": 32,
        }
    )
    intent = session.active
    state = TemporalRunState(
        intent["run_id"],
        session.scope,
        intent["command_id"],
        intent["request"],
        intent["manifest"],
        execution_epoch="original-uuid",
    )
    return session, state


async def wait_for_event(event):
    assert await asyncio.to_thread(event.wait, 3)


async def call(host, state, action, request):
    async def grant(value):
        return state.admit_context_dispatch(admission(value))

    async def ended(proof):
        state.context_execution_ended(proof)

    if action["kind"] == "context":
        return await host.prepare_context(request, dispatch_guard=grant, on_end=ended)
    return await host.manage_context(request, dispatch_guard=grant, on_end=ended)


@pytest.mark.parametrize("managed", [False, True])
def test_actual_native_reader_and_turn_remain_owned_after_observer_cancel(managed):
    async def run():
        source = WaitingMemory()
        host = runtime(
            ThreadedMemoryAdapter(source),
            context_reads=True,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        session, state = turn(host)
        action, request = state.next_operation()
        task = asyncio.create_task(call(host, state, action, request))
        try:
            await wait_for_event(source.started)
            state.command("cancel", {"kind": "cancel", "scope": state.scope})
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            method = state.accept_managed_context if managed else state.accept_context
            method(action["id"], {"ok": False, "code": "activity_outcome_unknown"})
            assert not source.stopped.is_set() and not state.quiescent
            assert await host.wait_context_executions(wait_timeout=0) is False
            assert (
                session.adopt_observation(
                    {"scope": state.scope, "request": state.request, **state.diagnostics()}
                )
                is False
            )
            with pytest.raises(CloseIncomplete):
                await host.close_context_execution(wait_timeout=0)
            assert source.closes == 0 and host.context_execution.active_count == 1
            source.release.set()
            await wait_for_event(source.stopped)
            assert await host.wait_context_executions(wait_timeout=3) is True
            assert state.quiescent and source.reads == 1
            assert (
                session.adopt_observation(
                    {"scope": state.scope, "request": state.request, **state.diagnostics()}
                )
                is True
            )
            assert host.providers["default"].messages == []
        finally:
            source.release.set()
            await asyncio.gather(task, return_exceptions=True)
            await host.close_context_execution(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)
        assert host.context_execution._closed and source.closes == 0

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_dataset_metadata_thread_is_owned_after_source_snapshot(managed):
    async def run():
        source = WaitingMemory()
        source.block_page = False
        source.block_dataset = True
        host = runtime(
            ThreadedMemoryAdapter(source),
            context_reads=True,
            context_builder=ManagedContextPipeline() if managed else None,
        )
        _, state = turn(host)
        action, request = state.next_operation()
        task = asyncio.create_task(call(host, state, action, request))
        try:
            await wait_for_event(source.started)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            method = state.accept_managed_context if managed else state.accept_context
            method(action["id"], {"ok": False, "code": "timeout"})
            assert not state.quiescent and not await host.wait_context_executions(wait_timeout=0)
            source.release.set()
            await wait_for_event(source.stopped)
            assert await host.wait_context_executions(wait_timeout=3)
            assert state.quiescent and source.reads == 1
        finally:
            source.release.set()
            await asyncio.gather(task, return_exceptions=True)
            await host.close_context_execution(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)

    asyncio.run(run())


def test_missing_or_denied_original_admission_cannot_read_source():
    async def run():
        source = WaitingMemory()
        host = runtime(ThreadedMemoryAdapter(source), context_reads=True)
        _, state = turn(host)
        action, request = state.next_operation()
        try:
            response = await host.prepare_context(request)
            assert response["ok"] is False and source.reads == 0
            state.command("cancel", {"kind": "cancel", "scope": state.scope})
            assert (await call(host, state, action, request))["ok"] is False
            assert source.reads == 0 and not source.started.is_set()
        finally:
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())


def test_shared_injected_owner_is_borrowed_but_runtime_closes_its_read_admission():
    async def run():
        source = InMemoryMemory()
        owner = ContextExecutionOwner()
        host = runtime(source, context_reads=True, context_execution=owner)
        try:
            await host.close_context_execution()
            assert not owner._closed
            _, state = turn(host)
            action, request = state.next_operation()
            response = await call(host, state, action, request)
            assert response["ok"] is False and owner.active_count == 0
            assert action.get("dispatch_grant") is None
        finally:
            await host.close_session_execution()
            await owner.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("value", [True, False])
def test_read_publication_is_explicit_and_preserves_legacy_release(value):
    source = InMemoryMemory()
    legacy = runtime(source)
    host = runtime(source, context_reads=value)
    if value:
        assert host.manifest["binding_protocol"] == 2
        assert host.manifest["context_read_protocol"]["version"] == 1
        assert host.capabilities["context_read_lifetime"] is True
    else:
        assert host.manifest == legacy.manifest and host.context_execution is None


@pytest.mark.parametrize("value", [None, 0, "true"])
def test_read_enable_flag_requires_strict_boolean(value):
    with pytest.raises(ValidationError):
        runtime(InMemoryMemory(), context_reads=value)


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "1"])
def test_invalid_close_timeout_does_not_close_read_admission(value):
    async def run():
        host = runtime(InMemoryMemory(), context_reads=True)
        try:
            with pytest.raises(ValidationError):
                await host.close_context_execution(wait_timeout=value)
            _, state = turn(host)
            action, request = state.next_operation()
            response = await call(host, state, action, request)
            assert response["ok"] is True, response
            state.accept_context(action["id"], response)
            assert await host.wait_context_executions(wait_timeout=3)
            assert state.quiescent
        finally:
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())


def test_replacement_owner_requires_enable_and_is_fixed_before_read_dispatch():
    owner = ContextExecutionOwner()
    with pytest.raises(ValidationError):
        runtime(InMemoryMemory(), context_execution=owner)
    host = runtime(InMemoryMemory(), context_reads=True, context_execution=owner)
    host.context_execution = ContextExecutionOwner()
    with pytest.raises(DefinitionMismatch):
        host.validate_release()


def test_threaded_metadata_bridge_is_pinned_in_new_release_before_io():
    source = ThreadedMemoryAdapter(InMemoryMemory())
    host = runtime(source, context_reads=True)
    assert host.manifest["context_read_metadata_bridges"]

    async def replaced():
        pytest.fail("replacement metadata method cannot run")

    source.inspect_session_identity = replaced
    with pytest.raises(DefinitionMismatch):
        host.validate_release()


def test_capacity_refusal_can_release_only_the_handler_that_never_started():
    async def run():
        source = WaitingMemory()
        owner = ContextExecutionOwner(max_calls=1)
        host = runtime(ThreadedMemoryAdapter(source), context_reads=True, context_execution=owner)
        _, first = turn(host)
        action, request = first.next_operation()
        task = asyncio.create_task(call(host, first, action, request))
        try:
            await wait_for_event(source.started)
            _, second = turn(host, "another-session")
            second_action, second_request = second.next_operation()
            refused = await call(host, second, second_action, second_request)
            second.accept_context(second_action["id"], refused)
            assert refused["handler_not_started"] is True
            assert second.quiescent and not first.quiescent
            assert source.reads == 1 and not await host.wait_context_executions(wait_timeout=0)
            duplicate = await call(host, first, action, request)
            assert duplicate.get("handler_not_started", False) is False
            assert not first.quiescent and source.reads == 1
        finally:
            source.release.set()
            result = await task
            first.accept_context(action["id"], result)
            await host.close_context_execution(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)
            await owner.aclose()
        assert first.quiescent

    asyncio.run(run())


def test_native_async_source_stays_on_its_original_client_loop():
    async def run():
        created_loop = asyncio.get_running_loop()
        started, release = asyncio.Event(), asyncio.Event()

        class AsyncSource(InMemoryMemory):
            async def read_page(self, *args, **kwargs):
                assert asyncio.get_running_loop() is created_loop
                started.set()
                await release.wait()
                return super().read_page(*args, **kwargs)

        host = runtime(AsyncSource(), context_reads=True)
        _, state = turn(host)
        action, request = state.next_operation()
        task = asyncio.create_task(call(host, state, action, request))
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            state.accept_context(action["id"], {"ok": False, "code": "timeout"})
            assert not state.quiescent and not await host.wait_context_executions(wait_timeout=0)
            release.set()
            assert await host.wait_context_executions(wait_timeout=3)
            assert state.quiescent
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await host.close_context_execution(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)

    asyncio.run(run())


def test_source_replacement_during_owned_read_refuses_disclosure_but_proves_original_end():
    async def run():
        source = WaitingMemory()
        adapter = ThreadedMemoryAdapter(source)
        host = runtime(adapter, context_reads=True)
        _, state = turn(host)
        action, request = state.next_operation()
        task = asyncio.create_task(call(host, state, action, request))
        try:
            await wait_for_event(source.started)
            adapter.backend = InMemoryMemory(backend_id=source.backend_id)
            source.release.set()
            response = await task
            assert response == {"ok": False, "code": "definition_mismatch"}
            state.accept_context(action["id"], response)
            assert await host.wait_context_executions(wait_timeout=3)
            assert state.state == "failed" and state.quiescent and state.context_snapshot is None
        finally:
            source.release.set()
            await asyncio.gather(task, return_exceptions=True)
            await host.close_context_execution(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)

    asyncio.run(run())


def test_rag_reference_io_is_owned_on_the_original_async_loop():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        loop = asyncio.get_running_loop()

        class Knowledge:
            identity = {"kind": "read-runtime-knowledge", "version": "1"}
            limit, max_chars = 8, 4096

            async def references(self, scope, query):
                assert asyncio.get_running_loop() is loop
                started.set()
                await release.wait()
                return [{"key": "knowledge:doc", "version": 1, "value": "evidence"}]

            async def validate(self, scope, references):
                assert asyncio.get_running_loop() is loop

        host = runtime(InMemoryMemory(), context_reads=True, knowledge=Knowledge())
        _, state = turn(host)
        action, request = state.next_operation()
        task = asyncio.create_task(call(host, state, action, request))
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            state.accept_context(action["id"], {"ok": False, "code": "timeout"})
            assert not state.quiescent and not await host.wait_context_executions(wait_timeout=0)
            release.set()
            assert await host.wait_context_executions(wait_timeout=3)
            assert state.quiescent and state.context_snapshot is None
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["read", "verify"])
def test_actual_artifact_read_phase_is_owned_until_async_get_finishes(phase):
    async def run():
        from ralf_agent import InMemoryArtifactStore, Scope

        from .test_managed_data_context import context, history

        started, release = asyncio.Event(), asyncio.Event()

        class Artifacts(InMemoryArtifactStore):
            async def put(self, *args, **kwargs):
                return super().put(*args, **kwargs)

            async def get(self, *args, **kwargs):
                started.set()
                await release.wait()
                return super().get(*args, **kwargs)

        artifacts = Artifacts(backend_id="artifacts")
        builder = context(artifacts)
        host = runtime(InMemoryMemory(), context_reads=True, context_builder=builder)
        _, state = turn(host)
        # Original adopted plan contains this fixed artifact projection.
        value = builder.offloads(history())[0]
        await artifacts.put(Scope(), builder.namespace, value["value"])
        state.managed_context_stages["0:0"] = {
            "key": "0:0",
            "source_digest": "fixed-original-history",
            "status": "preparing",
            "phase": phase,
            "operations": [],
            "index": 0,
            "prepared": {"offloads": [value], "plan": None, "references": []},
        }
        action, request = state.next_operation()
        assert action["phase"] == phase
        task = asyncio.create_task(call(host, state, action, request))
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            state.accept_managed_context(action["id"], {"ok": False, "code": "timeout"})
            assert not state.quiescent and not await host.wait_context_executions(wait_timeout=0)
            release.set()
            assert await host.wait_context_executions(wait_timeout=3)
            assert state.quiescent
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())
