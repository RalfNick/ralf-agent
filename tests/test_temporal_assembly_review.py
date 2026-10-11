"""Final review regressions for construction, preflight and SDK shutdown."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from ralf_agent import (
    ComponentRegistry,
    InMemoryMemory,
    RecallQuery,
    Scope,
    TemporalProfile,
    TemporalRuntimeBuilder,
    ThreadedMemoryAdapter,
)
from ralf_agent.errors import CloseIncomplete, ValidationError
from ralf_agent.runtime_builder import EchoProvider, RuntimeBuildError


def profile(components=None, adapter="test"):
    return TemporalProfile("review", "1", {"default": {"adapter": adapter}}, components)


def test_cancelled_construction_retains_actual_bridge_before_resource_close(tmp_path):
    async def run():
        started, release, stopped = (threading.Event() for _ in range(3))
        closes = []

        class Source(InMemoryMemory):
            def read_page(self, *args):
                started.set()
                try:
                    assert release.wait(10)
                    return super().read_page(*args)
                finally:
                    stopped.set()

            def close(self):
                closes.append(stopped.is_set())

        async def factory(config, context):
            await ThreadedMemoryAdapter(context.own(Source())).read_page(
                Scope(), "history", RecallQuery()
            )
            return EchoProvider("test")

        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        task = asyncio.create_task(
            TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(profile())
        )
        try:
            assert await asyncio.to_thread(started.wait, 3)
            task.cancel()
            with pytest.raises(RuntimeBuildError) as caught:
                await task
            assert not stopped.is_set() and closes == []
            with pytest.raises(CloseIncomplete):
                await caught.value.cleanup.aclose(wait_timeout=0)
            assert closes == []
            release.set()
            await caught.value.cleanup.aclose()
            assert stopped.is_set() and closes == [True]
        finally:
            release.set()
            await asyncio.to_thread(stopped.wait, 3)
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_concurrent_construction_cleanup_refuses_without_losing_resources(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        events = []

        class First:
            async def aclose(self):
                started.set()
                await release.wait()
                events.append("first")

        class Last:
            calls = 0

            async def aclose(self):
                self.calls += 1
                if self.calls == 1:
                    raise OSError("first close fails")
                await asyncio.sleep(0)
                events.append("last")

        async def factory(config, context):
            context.own_async(First())
            context.own_async(Last())
            raise ValueError("construction failure")

        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        with pytest.raises(RuntimeBuildError) as caught:
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(profile())
        cleanup = caught.value.cleanup
        first = asyncio.create_task(cleanup.aclose())
        try:
            await started.wait()
            with pytest.raises(ValidationError, match="already closing"):
                await asyncio.wait_for(cleanup.aclose(), 0.2)
            assert not first.done() and events == ["last"]
            release.set()
            await first
            await cleanup.aclose()
            assert events == ["last", "first"]
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)

    asyncio.run(run())


def test_actual_sdk_fatal_error_surfaces_after_owned_cleanup(tmp_path, monkeypatch):
    Worker = pytest.importorskip("temporalio.worker").Worker

    async def run():
        error = RuntimeError("actual worker fatal")
        events = []

        class Client:
            async def aclose(self):
                events.append("resource-closed")

        async def factory(config, context):
            context.own_async(Client())
            return EchoProvider("test")

        class ActualSDKContext:
            __aenter__ = Worker.__aenter__
            __aexit__ = Worker.__aexit__

            def __init__(self):
                self._async_context_inner_task = None
                self._async_context_run_task = None
                self._async_context_run_exception = None
                self.trigger = asyncio.Event()

            async def run(self):
                await self.trigger.wait()
                raise error

            async def shutdown(self):
                events.append("sdk-shutdown")

        worker = ActualSDKContext()
        monkeypatch.setattr("ralf_agent.temporal.build_temporal_worker", lambda *a, **kw: worker)
        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        assembled = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(profile())
        await assembled.start_worker(SimpleNamespace(namespace="default"), task_queue="queue")
        worker.trigger.set()
        await asyncio.gather(assembled._worker_start, return_exceptions=True)
        with pytest.raises(RuntimeError) as caught:
            await assembled.aclose()
        assert caught.value is error and events[-1] == "resource-closed"
        assert assembled._closed
        await assembled.aclose()

    asyncio.run(run())


def test_indexed_memory_implicit_sqlite_gets_temporal_data_path(tmp_path):
    async def run():
        assembled = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
            profile({"memory_store": {"adapter": "indexed-recall-async"}}, "offline-echo"),
            data_path="data",
        )
        try:
            assert (tmp_path / "data.memory_store.sqlite").is_file()
            assert not (tmp_path / "data").exists()
        finally:
            await assembled.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["invalid-sqlite", "missing-query-provider"])
def test_builtin_configuration_refuses_before_factory_or_file_io(tmp_path, kind):
    async def run():
        calls = []

        def factory(config, context):
            calls.append("provider-io")
            return EchoProvider("test")

        declaration = (
            {"memory_store": {"adapter": "sqlite", "config": {"path": "data", "unknown": 1}}}
            if kind == "invalid-sqlite"
            else {
                "knowledge": {
                    "adapter": "sqlite-lexical-query",
                    "config": {
                        "path": "data",
                        "query_transform": {"type": "model", "config": {"provider": "absent"}},
                    },
                }
            }
        )
        registry = ComponentRegistry()
        registry.register("provider", "test", factory)
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(profile(declaration))
        assert calls == [] and not any(tmp_path.iterdir())

    asyncio.run(run())
