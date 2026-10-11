"""Shared construction and cleanup retain their actual work through cancellation."""

import asyncio
import threading

import pytest

from ralf_agent import (
    ComponentRegistry,
    InMemoryMemory,
    RecallQuery,
    Scope,
    TemporalRuntimeBuilder,
    ThreadedMemoryAdapter,
)
from ralf_agent.errors import CloseIncomplete, ValidationError
from ralf_agent.runtime_builder import EchoProvider, RuntimeBuildError

from .test_temporal_catalog_assembly import catalog


def test_later_constructor_cancel_keeps_earlier_shared_resource_until_thread_stops(tmp_path):
    async def run():
        builder = TemporalRuntimeBuilder(base_dir=tmp_path)
        assert hasattr(builder, "abuild_catalog")
        started, release, stopped = (threading.Event() for _ in range(3))
        closes, calls = [], []

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
            calls.append("factory")
            context.own(source)
            if len(calls) == 2:
                await ThreadedMemoryAdapter(source).read_page(Scope(), "s", RecallQuery())
            return EchoProvider("test")

        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        task = asyncio.create_task(
            TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(catalog("test"))
        )
        try:
            assert await asyncio.to_thread(started.wait, 3)
            task.cancel()
            with pytest.raises(RuntimeBuildError) as caught:
                await task
            assert closes == []
            with pytest.raises(CloseIncomplete):
                await caught.value.cleanup.aclose(wait_timeout=0)
            assert closes == [] and not stopped.is_set()
            release.set()
            await caught.value.cleanup.aclose()
            assert closes == [True]
        finally:
            release.set()
            await asyncio.to_thread(stopped.wait, 3)
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_shared_close_observer_cancel_and_concurrent_retry_do_not_duplicate_close(tmp_path):
    async def run():
        assert hasattr(TemporalRuntimeBuilder(), "abuild_catalog")
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        class Client:
            async def aclose(self):
                calls.append("close")
                started.set()
                await release.wait()

        client = Client()

        async def factory(config, context):
            context.own_async(client)
            return EchoProvider("test")

        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        host = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(
            catalog("test")
        )
        first = asyncio.create_task(host.aclose())
        try:
            await started.wait()
            with pytest.raises(ValidationError, match="already closing"):
                await host.aclose()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert calls == ["close"]
            release.set()
            await host.aclose()
            assert calls == ["close"]
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            await host.aclose()

    asyncio.run(run())
