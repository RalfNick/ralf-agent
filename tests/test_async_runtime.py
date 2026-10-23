"""Async factory/resource behavior over the real local execution authority."""

import asyncio
import sqlite3
import threading
from types import SimpleNamespace

import httpx
import pytest

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    ModelResponse,
    RuntimeBuilder,
    RuntimeBuildError,
    RuntimeProfile,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import CoordinatorBusy, ValidationError
from relf_agent.runtime_builder import EchoProvider


def profile(adapter="offline-echo"):
    return RuntimeProfile("async-app", "1", {"default": {"adapter": adapter}})


def assert_owned(path):
    with SQLiteStore(path) as store:
        lease = store.create_coordinator()
        try:
            with pytest.raises(CoordinatorBusy):
                lease.acquire()
        finally:
            lease.release()


class AsyncClient:
    def __init__(self):
        self.closes = 0
        self.closed = False

    async def aclose(self):
        self.closes += 1
        self.closed = True


def builder_for(factory):
    registry = ComponentRegistry()
    registry.register_async("provider", "managed", factory)
    return RuntimeBuilder(registry)


def test_default_abuild_keeps_existing_profile_and_submit_receipt(tmp_path):
    async def scenario():
        path = tmp_path / "default.sqlite"
        selected = profile()
        spec = AgentSpec("a", "Answer")
        with RuntimeBuilder().build(selected, path) as original:
            handle = original.submit(spec, "q", command_id="s")
            manifest = original.diagnostics(handle.run_id).manifest
        async with await RuntimeBuilder().abuild(selected, path) as runtime:
            assert runtime.submit(spec, "q", command_id="s") == handle
            assert runtime.diagnostics(handle.run_id).manifest == manifest
            result = await runtime.drive(handle.run_id)
            assert result.state == "succeeded"
            assert result.result == {"echo": "q", "label": "offline"}
        with RuntimeBuilder().build(selected, path) as resumed:
            assert resumed.submit(spec, "q", command_id="s") == handle
            assert resumed.status(handle.run_id).state == "succeeded"

    asyncio.run(scenario())


def test_sync_build_refuses_registered_async_factory_before_allocating_store(tmp_path):
    async def factory(config, context):
        pytest.fail("The synchronous builder must not invoke an async factory")

    path = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError, match="abuild"):
        builder_for(factory).build(profile("managed"), path)
    assert not path.exists()


def test_async_callable_factory_manages_a_real_http_client(tmp_path):
    async def scenario():
        clients = []

        class Factory:
            async def __call__(self, config, context):
                client = context.own_async(httpx.AsyncClient())
                clients.append(client)
                return EchoProvider("client")

        async with await builder_for(Factory()).abuild(
            profile("managed"), tmp_path / "http.sqlite"
        ) as runtime:
            handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            assert (await runtime.drive(handle.run_id)).result == {"echo": "q", "label": "client"}
            assert not clients[0].is_closed
        assert clients[0].is_closed

    asyncio.run(scenario())


def test_mixed_owned_resources_close_once_in_reverse_after_engine(tmp_path):
    async def scenario():
        events = []

        class SyncClient:
            def close(self):
                events.append("sync")

        class Client(AsyncClient):
            async def aclose(self):
                with pytest.raises(sqlite3.ProgrammingError):
                    context.store.conn.execute("SELECT 1")
                events.append("async")
                await super().aclose()

        async def factory(config, value):
            nonlocal context
            context = value
            context.own(SyncClient())
            client = context.own_async(Client())
            context.own_async(client)
            return EchoProvider("mixed")

        context = None
        runtime = await builder_for(factory).abuild(profile("managed"), tmp_path / "mixed.sqlite")
        await runtime.aclose()
        await runtime.aclose()
        runtime.close()
        assert events == ["async", "sync"]

    asyncio.run(scenario())


def test_sync_close_refuses_async_resources_before_closing_execution(tmp_path):
    async def scenario():
        client = AsyncClient()

        async def factory(config, context):
            context.own_async(client)
            return EchoProvider("managed")

        path = tmp_path / "sync-close.sqlite"
        runtime = await builder_for(factory).abuild(profile("managed"), path)
        try:
            with pytest.raises(ValidationError, match="aclose"):
                runtime.close()
            assert_owned(path)
            handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
            assert not client.closed
        finally:
            await runtime.aclose()
        assert client.closed

    asyncio.run(scenario())


def test_cancelled_close_wait_retains_one_real_cleanup_and_guards_cached_entry(tmp_path):
    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()

        class Client(AsyncClient):
            async def aclose(self):
                self.closes += 1
                started.set()
                await finish.wait()
                self.closed = True

        client = Client()

        async def factory(config, context):
            context.own_async(client)
            return EchoProvider("managed")

        runtime = await builder_for(factory).abuild(profile("managed"), tmp_path / "cancel.sqlite")
        submit = runtime.submit
        closing = asyncio.create_task(runtime.aclose())
        try:
            await asyncio.wait_for(started.wait(), 2)
            with pytest.raises(ValidationError):
                await runtime.aclose()
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert not client.closed and client.closes == 1
            with pytest.raises(ValidationError):
                submit(AgentSpec("a", "Answer"), "q", command_id="late")
        finally:
            finish.set()
            if not closing.done():
                await closing
            await runtime.aclose()
        assert client.closed and client.closes == 1

    asyncio.run(scenario())


def test_failed_resource_close_retries_only_uncompleted_resources(tmp_path):
    async def scenario():
        events = []

        class Client:
            def __init__(self, name, fail=False):
                self.name, self.fail = name, fail

            async def aclose(self):
                events.append(self.name)
                if self.fail:
                    self.fail = False
                    raise ConnectionError("cleanup incomplete")

        async def factory(config, context):
            for client in (Client("first"), Client("retry", True), Client("last")):
                context.own_async(client)
            return EchoProvider("managed")

        runtime = await builder_for(factory).abuild(profile("managed"), tmp_path / "retry.sqlite")
        with pytest.raises(ConnectionError):
            await runtime.aclose()
        assert events == ["last", "retry"]
        with pytest.raises(ValidationError):
            runtime.submit(AgentSpec("a", "Answer"), "q", command_id="late")
        await runtime.aclose()
        assert events == ["last", "retry", "retry", "first"]

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [False, "context", "coroutine"])
def test_async_close_requires_completed_none_and_allows_safe_retry(tmp_path, bad):
    async def scenario():
        class Client(AsyncClient):
            async def aclose(self):
                self.closes += 1
                if self.closes == 1:
                    if bad == "coroutine":
                        return super().aclose()
                    if bad == "context":
                        from contextlib import nullcontext

                        return nullcontext()
                    return False
                self.closed = True

        client = Client()

        async def factory(config, context):
            context.own_async(client)
            return EchoProvider("managed")

        runtime = await builder_for(factory).abuild(profile("managed"), tmp_path / "invalid.sqlite")
        with pytest.raises(ValidationError):
            await runtime.aclose()
        assert not client.closed
        await runtime.aclose()
        assert client.closed and client.closes == 2

    asyncio.run(scenario())


def test_cancelled_factory_closes_declared_resources_before_propagating_cancel(tmp_path):
    async def scenario():
        started = asyncio.Event()
        client = AsyncClient()

        async def factory(config, context):
            context.own_async(client)
            started.set()
            await asyncio.Future()

        building = asyncio.create_task(
            builder_for(factory).abuild(profile("managed"), tmp_path / "construct.sqlite")
        )
        await asyncio.wait_for(started.wait(), 2)
        building.cancel()
        with pytest.raises(asyncio.CancelledError):
            await building
        assert client.closed and client.closes == 1

    asyncio.run(scenario())


def test_failed_construction_keeps_async_cleanup_handle(tmp_path):
    async def scenario():
        class Client(AsyncClient):
            async def aclose(self):
                self.closes += 1
                if self.closes == 1:
                    raise ConnectionError("retry cleanup")
                self.closed = True

        client = Client()

        async def factory(config, context):
            context.own_async(client)
            raise RuntimeError("factory failed")

        with pytest.raises(RuntimeBuildError) as error:
            await builder_for(factory).abuild(profile("managed"), tmp_path / "failure.sqlite")
        await error.value.cleanup.aclose()
        assert client.closed and client.closes == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("malformed_drain", [False, True])
def test_rejected_partial_engine_still_releases_its_real_authority(tmp_path, malformed_drain):
    async def scenario():
        client = AsyncClient()
        engines = []

        async def factory(config, context):
            context.own_async(client)
            return EchoProvider("managed")

        def invalid_engine(store, **options):
            from relf_agent import LocalEngine

            actual = LocalEngine(store, **options)
            engines.append(actual)
            candidate = SimpleNamespace(close=actual.close)
            if malformed_drain:
                candidate.wait_for_threads = lambda: None
            return candidate

        registry = ComponentRegistry()
        registry.register_async("provider", "managed", factory)
        path = tmp_path / "rejected-engine.sqlite"
        try:
            with pytest.raises(ValidationError):
                await RuntimeBuilder(registry, engine_factory=invalid_engine).abuild(
                    profile("managed"), path
                )
            assert client.closed
            with SQLiteStore(path) as store:
                lease = store.create_coordinator()
                lease.acquire()
                lease.release()
        finally:
            for actual in engines:
                actual.close()
            if not client.closed:
                await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["runtime", "context"])
def test_resource_reentering_shutdown_after_outer_cancel_is_rejected(tmp_path, entry):
    async def scenario():
        started, finish, reentered = asyncio.Event(), asyncio.Event(), asyncio.Event()
        errors = []

        class Client(AsyncClient):
            reenter = True

            async def aclose(self):
                self.closes += 1
                started.set()
                await finish.wait()
                if self.reenter:
                    try:
                        if entry == "runtime":
                            await runtime.aclose()
                        else:
                            await runtime._context.cleanup_async()
                    except ValidationError as exc:
                        errors.append(exc)
                    reentered.set()
                self.closed = True

        client = Client()

        async def factory(config, context):
            context.own_async(client)
            return EchoProvider("managed")

        runtime = await builder_for(factory).abuild(profile("managed"), tmp_path / "reenter.sqlite")
        closing = asyncio.create_task(runtime.aclose())
        try:
            await asyncio.wait_for(started.wait(), 2)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            finish.set()
            await asyncio.wait_for(reentered.wait(), 0.5)
            assert len(errors) == 1
            await runtime.aclose()
            assert client.closed and client.closes == 1
        finally:
            client.reenter = False
            finish.set()
            owned = runtime._context._resources
            for record in owned:
                if record.task is not None and not record.task.done():
                    record.task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await record.task
            try:
                await runtime.aclose()
            except asyncio.CancelledError:
                await runtime.aclose()

    asyncio.run(scenario())


def test_incomplete_thread_drain_cannot_release_execution_ownership(tmp_path):
    async def scenario():
        from relf_agent import LocalEngine

        class Proxy:
            def __init__(self, engine):
                self.engine = engine
                self.invalid = True

            def __getattr__(self, name):
                return getattr(self.engine, name)

            async def wait_for_threads(self):
                if self.invalid:
                    return False
                await self.engine.wait_for_threads()

        proxies = []

        def factory(store, **options):
            proxy = Proxy(LocalEngine(store, **options))
            proxies.append(proxy)
            return proxy

        path = tmp_path / "drain-completion.sqlite"
        runtime = await RuntimeBuilder(engine_factory=factory).abuild(profile(), path)
        try:
            with pytest.raises(ValidationError):
                await runtime.aclose()
            assert_owned(path)
        finally:
            proxies[0].invalid = False
            await runtime.aclose()

    asyncio.run(scenario())


def test_wrong_loop_refuses_shutdown_before_releasing_authority(tmp_path):
    owner, other = asyncio.new_event_loop(), asyncio.new_event_loop()
    client = AsyncClient()

    async def factory(config, context):
        context.own_async(client)
        return EchoProvider("managed")

    path = tmp_path / "loop.sqlite"
    runtime = None
    try:
        runtime = owner.run_until_complete(builder_for(factory).abuild(profile("managed"), path))
        with pytest.raises(ValidationError, match="loop"):
            other.run_until_complete(runtime.aclose())
        assert_owned(path)
        assert not client.closed
    finally:
        if runtime is not None:
            owner.run_until_complete(runtime.aclose())
        owner.close()
        other.close()
    assert client.closed


def test_wrong_loop_cannot_dispatch_through_a_cached_drive(tmp_path):
    owner, other = asyncio.new_event_loop(), asyncio.new_event_loop()
    client = AsyncClient()

    async def factory(config, context):
        context.own_async(client)
        return EchoProvider("managed")

    path = tmp_path / "wrong-dispatch.sqlite"
    runtime = None
    try:
        runtime = owner.run_until_complete(builder_for(factory).abuild(profile("managed"), path))
        handle = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        drive = runtime.drive
        with pytest.raises(ValidationError, match="loop"):
            other.run_until_complete(drive(handle.run_id))
        assert runtime.status(handle.run_id).state == "queued"
        assert runtime.diagnostics(handle.run_id).budget["spent"] == 0
        assert owner.run_until_complete(drive(handle.run_id)).state == "succeeded"
    finally:
        if runtime is not None:
            owner.run_until_complete(runtime.aclose())
        owner.close()
        other.close()


@pytest.mark.parametrize("first", ["sync", "async"])
def test_owned_resource_cannot_switch_cleanup_mode(tmp_path, first):
    async def scenario():
        closed = []

        class Client:
            def close(self):
                closed.append("sync")

            async def aclose(self):
                closed.append("async")

        async def factory(config, context):
            client = Client()
            if first == "sync":
                context.own(client)
                context.own_async(client)
            else:
                context.own_async(client)
                context.own(client)

        with pytest.raises(ValidationError):
            await builder_for(factory).abuild(profile("managed"), tmp_path / "mode.sqlite")
        assert closed == [first]

    asyncio.run(scenario())


def test_async_ownership_rejects_a_synchronous_lazy_close(tmp_path):
    async def scenario():
        async def factory(config, context):
            context.own_async(SimpleNamespace(aclose=lambda: asyncio.sleep(0)))

        with pytest.raises(ValidationError):
            await builder_for(factory).abuild(profile("managed"), tmp_path / "shape.sqlite")

    asyncio.run(scenario())


def test_cancelled_construction_cleanup_retains_an_inflight_handle(tmp_path):
    async def scenario():
        creating, cleaning, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Client(AsyncClient):
            async def aclose(self):
                self.closes += 1
                cleaning.set()
                await finish.wait()
                self.closed = True

        client = Client()

        async def factory(config, context):
            context.own_async(client)
            creating.set()
            await asyncio.Future()

        building = asyncio.create_task(
            builder_for(factory).abuild(profile("managed"), tmp_path / "cancel-cleanup.sqlite")
        )
        await asyncio.wait_for(creating.wait(), 2)
        building.cancel()
        await asyncio.wait_for(cleaning.wait(), 2)
        building.cancel()
        try:
            with pytest.raises(RuntimeBuildError) as error:
                await building
            assert client.closes == 1 and not client.closed
        finally:
            finish.set()
        await error.value.cleanup.aclose()
        assert client.closes == 1 and client.closed

    asyncio.run(scenario())


def test_async_shutdown_drains_real_threads_and_rejects_cached_submit(tmp_path):
    async def scenario():
        started, finish, exited = threading.Event(), threading.Event(), threading.Event()
        client = AsyncClient()

        def work(arguments, ctx):
            started.set()
            try:
                assert finish.wait(5)
                return "done"
            finally:
                exited.set()

        class Provider:
            identity = {"kind": "thread-drain", "version": "1"}

            async def complete(self, messages, tools):
                return ModelResponse(tool_calls=(ToolCall("work", {}),))

        def tools_factory(config, context):
            registry = ToolRegistry()
            registry.register(ToolSpec("work", "Work", {"type": "object"}), work)
            return registry

        async def provider_factory(config, context):
            context.own_async(client)
            return Provider()

        registry = ComponentRegistry()
        registry.register_async("provider", "thread", provider_factory)
        registry.register("tools", "thread", tools_factory)
        selected = RuntimeProfile(
            "thread", "1", {"default": {"adapter": "thread"}}, {"tools": {"adapter": "thread"}}
        )
        path = tmp_path / "thread.sqlite"
        runtime = await RuntimeBuilder(registry).abuild(selected, path)
        submit = runtime.submit
        handle = submit(AgentSpec("a", "Run", ("work",)), "q", command_id="s")
        driving = asyncio.create_task(runtime.drive(handle.run_id))
        closing = None
        try:
            assert await asyncio.to_thread(started.wait, 2)
            victims = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in victims:
                task.cancel()
            await asyncio.gather(*victims, return_exceptions=True)
            closing = asyncio.create_task(runtime.aclose())
            await asyncio.sleep(0)
            assert not closing.done() and not exited.is_set()
            assert_owned(path)
            with pytest.raises(ValidationError):
                submit(AgentSpec("b", "Answer"), "q", command_id="late")
        finally:
            finish.set()
            if closing is not None:
                await closing
            await runtime.aclose()
            if not driving.done():
                await driving
        assert exited.is_set() and client.closed

    asyncio.run(scenario())
