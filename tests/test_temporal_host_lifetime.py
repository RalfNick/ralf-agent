"""Observer cancellation and fatal siblings never release live shared clients."""

import asyncio
import threading
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import (
    ComponentRegistry,
    InMemoryMemory,
    RecallQuery,
    TemporalRuntimeBuilder,
    ThreadedMemoryAdapter,
)
from ralf_agent.errors import CloseIncomplete, RuntimeClosed
from ralf_agent.runtime_builder import EchoProvider

from .test_temporal_catalog_assembly import catalog
from .test_temporal_profile_host import sdk as sdk_fixture

sdk = sdk_fixture


def test_cancelled_startup_keeps_partial_worker_until_original_enter_finishes(
    tmp_path, sdk, monkeypatch
):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        stopped = []

        class Worker:
            async def __aenter__(self):
                entered.set()
                await release.wait()
                return self

            async def __aexit__(self, *args):
                stopped.append("stop")

        workers = []

        def create(*args, **options):
            value = Worker()
            workers.append(value)
            return value

        monkeypatch.setattr("ralf_agent.temporal.build_temporal_worker", create)
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        startup = asyncio.create_task(host.start_workers(sdk.client))
        try:
            await entered.wait()
            startup.cancel()
            with pytest.raises(asyncio.CancelledError):
                await startup
            with pytest.raises(CloseIncomplete):
                await host.aclose(wait_timeout=0)
            assert len(workers) == 1 and stopped == []
            release.set()
            await host.aclose()
            assert stopped == ["stop"] and len(workers) == 1
        finally:
            release.set()
            await asyncio.gather(startup, return_exceptions=True)
            await host.aclose()

    asyncio.run(run())


def test_cancelled_worker_observer_keeps_actual_thread_and_all_shared_resources(tmp_path, sdk):
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

        source = Source()

        async def factory(config, context):
            context.own(source)
            return EchoProvider("test")

        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        host = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(
            catalog("test")
        )
        await host.start_workers(sdk.client)

        async def operation():
            return await ThreadedMemoryAdapter(source).read_page(host.scope, "s", RecallQuery())

        observer = asyncio.create_task(
            host._assemblies[1]._calls.execute(
                operation,
                info=SimpleNamespace(
                    workflow_id="run", workflow_run_id="uuid", activity_id="model:0", attempt=1
                ),
                request={"scope": asdict(host.scope)},
            )
        )
        try:
            assert await asyncio.to_thread(started.wait, 3)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            with pytest.raises(CloseIncomplete):
                await host.aclose(wait_timeout=0.05)
            assert closes == [] and not any(e.startswith("stopped:") for e in sdk.events)
            release.set()
            await host.aclose()
            assert closes == [True] and stopped.is_set()
        finally:
            release.set()
            await asyncio.to_thread(stopped.wait, 3)
            await asyncio.gather(observer, return_exceptions=True)
            await host.aclose()

    asyncio.run(run())


def test_actual_sdk_fatal_sibling_closes_all_entry_then_reports_after_cleanup(
    tmp_path, sdk, monkeypatch
):
    Worker = pytest.importorskip("temporalio.worker").Worker

    async def run():
        error = RuntimeError("original SDK fatal")
        events, workers = [], []

        class Resource:
            async def aclose(self):
                events.append("resource-closed")

        resource = Resource()

        async def factory(config, context):
            context.own_async(resource)
            return EchoProvider("test")

        class SDKWorker:
            __aenter__, __aexit__ = Worker.__aenter__, Worker.__aexit__

            def __init__(self):
                self._async_context_inner_task = None
                self._async_context_run_task = None
                self._async_context_run_exception = None
                self.trigger = asyncio.Event()

            async def run(self):
                await self.trigger.wait()
                raise error

            async def shutdown(self):
                events.append("sdk-stop")

        def create(*args, **options):
            value = SDKWorker()
            workers.append(value)
            return value

        monkeypatch.setattr("ralf_agent.temporal.build_temporal_worker", create)
        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        host = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(
            catalog("test")
        )
        await host.start_workers(sdk.client)
        cached = host.runtime(host.profiles[1].identity)
        workers[0].trigger.set()
        await asyncio.gather(host._assemblies[0]._worker_start, return_exceptions=True)
        with pytest.raises(RuntimeClosed):
            host.runtime()
        with pytest.raises(RuntimeClosed):
            cached._check(accepting=True)
        with pytest.raises(RuntimeError) as caught:
            await host.aclose()
        assert caught.value is error
        assert events[-1] == "resource-closed" and events.count("resource-closed") == 1
        await host.aclose()

    asyncio.run(run())
