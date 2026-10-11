"""Construction and shutdown retain retryable actual resource responsibility."""

import asyncio
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, ComponentRegistry, Scope
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import EchoProvider, RuntimeBuildError
from ralf_agent.temporal_builder import TemporalRuntimeBuilder
from ralf_agent.temporal_profile import TemporalProfile


def profile(adapter="offline-echo"):
    return TemporalProfile("worker", "1", {"default": {"adapter": adapter}})


def builder(factory, tmp_path):
    registry = ComponentRegistry()
    registry.register_async("provider", "managed", factory)
    return TemporalRuntimeBuilder(registry, base_dir=tmp_path)


@pytest.mark.parametrize("failure", ["startup", "shutdown"])
def test_failed_worker_lifecycle_can_still_release_resources(tmp_path, monkeypatch, failure):
    import ralf_agent.temporal

    async def run():
        events = []

        class Client:
            async def aclose(self):
                events.append("resource-closed")

        async def factory(config, context):
            context.own_async(Client())
            return EchoProvider("owned")

        class Worker:
            async def __aenter__(self):
                if failure == "startup":
                    raise ConnectionError("start failure")
                return self

            async def __aexit__(self, *args):
                events.append("worker-stop")
                if failure == "shutdown" and events.count("worker-stop") == 1:
                    raise ConnectionError("stop failure")

        monkeypatch.setattr(ralf_agent.temporal, "build_temporal_worker", lambda *a, **kw: Worker())
        assembly = await builder(factory, tmp_path).abuild(profile("managed"))
        if failure == "startup":
            with pytest.raises(ConnectionError):
                await assembly.start_worker(
                    SimpleNamespace(namespace="original"), task_queue="queue"
                )
        else:
            await assembly.start_worker(SimpleNamespace(namespace="original"), task_queue="queue")
            with pytest.raises(ConnectionError):
                await assembly.aclose()
            assert "resource-closed" not in events
        await assembly.aclose()
        assert events[-1] == "resource-closed"
        assert events.count("resource-closed") == 1

    asyncio.run(run())


def test_cancelled_construction_keeps_failed_cleanup_retry_handle(tmp_path):
    async def run():
        started = asyncio.Event()
        closes = []

        class Client:
            async def aclose(self):
                closes.append("close")
                if len(closes) == 1:
                    raise ConnectionError("fixture cleanup failure")

        async def factory(config, context):
            context.own_async(Client())
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(builder(factory, tmp_path).abuild(profile("managed")))
        await started.wait()
        task.cancel()
        with pytest.raises(RuntimeBuildError) as exc:
            await task
        assert len(closes) == 1
        await exc.value.cleanup.aclose()
        assert len(closes) == 2

    asyncio.run(run())


def test_cancelled_resource_cleanup_wait_keeps_single_actual_close(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        closes = []

        class Client:
            async def aclose(self):
                closes.append("close")
                started.set()
                await release.wait()

        async def factory(config, context):
            context.own_async(Client())
            return EchoProvider("owned")

        assembly = await builder(factory, tmp_path).abuild(profile("managed"))
        closing = asyncio.create_task(assembly.aclose())
        try:
            await started.wait()
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            with pytest.raises(ValidationError):
                assembly.create_engine(SimpleNamespace(namespace="original"), task_queue="queue")
            assert closes == ["close"]
            release.set()
            await assembly.aclose()
            assert closes == ["close"]
        finally:
            release.set()
            await asyncio.gather(closing, return_exceptions=True)
            await assembly.aclose()

    asyncio.run(run())


def test_engine_creation_pins_worker_queue_and_blocks_resource_transfer(tmp_path, monkeypatch):
    import ralf_agent.temporal

    async def run():
        calls = []
        monkeypatch.setattr(
            ralf_agent.temporal, "build_temporal_worker", lambda *a, **kw: calls.append("start")
        )
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(profile())
        client = SimpleNamespace(namespace="original")
        try:
            engine = assembly.create_engine(client, task_queue="original-queue")
            assert engine.scope == Scope()
            with pytest.raises(ValidationError):
                assembly.detach_components()
            with pytest.raises(ValidationError):
                await assembly.start_worker(client, task_queue="different-queue")
            assert not calls
        finally:
            await assembly.aclose()

    asyncio.run(run())


def test_profile_and_scope_are_readonly_assembly_bindings(tmp_path):
    async def run():
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(profile())
        try:
            with pytest.raises(AttributeError):
                assembly.scope = Scope("different", "operator")
            with pytest.raises(AttributeError):
                assembly.profile = profile()
        finally:
            await assembly.aclose()

    asyncio.run(run())


def test_sdk_fatal_worker_cancellation_closes_future_entry(tmp_path, monkeypatch):
    import ralf_agent.temporal

    async def run():
        class Worker:
            async def __aenter__(self):
                self.host = asyncio.current_task()
                return self

            async def __aexit__(self, *args):
                pass

        worker = Worker()
        monkeypatch.setattr(ralf_agent.temporal, "build_temporal_worker", lambda *a, **kw: worker)
        assembled = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(profile())
        client = SimpleNamespace(namespace="original")
        try:
            await assembled.start_worker(client, task_queue="queue")
            cached = assembled.create_engine(client, task_queue="queue")
            worker.host.cancel()
            await asyncio.gather(worker.host, return_exceptions=True)
            with pytest.raises(ValidationError):
                assembled.create_engine(client, task_queue="queue")
            with pytest.raises(ValidationError):
                await cached.submit(AgentSpec("agent", "Answer"), "question", command_id="new")
        finally:
            await assembled.aclose()

    asyncio.run(run())
