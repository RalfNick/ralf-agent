"""Version hosting preserves the original queues and global resource ownership."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import ComponentRegistry, TemporalRuntimeBuilder
from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal_state import COMMAND_REGISTRY_NAME

from .test_temporal_catalog_assembly import catalog


@pytest.fixture
def sdk(monkeypatch):
    service = pytest.importorskip("temporalio.service")
    events, workers = [], []

    class Handle:
        def __init__(self, client, identity):
            self.client, self.identity = client, identity

        async def describe(self):
            if self.identity in self.client.descriptions:
                return self.client.descriptions[self.identity]
            if self.client.old_queue is None:
                raise service.RPCError("missing", service.RPCStatusCode.NOT_FOUND, b"")
            return SimpleNamespace(
                id=self.identity,
                namespace=self.client.namespace,
                workflow_type=COMMAND_REGISTRY_NAME,
                task_queue=self.client.old_queue,
                run_id="original-uuid",
            )

        async def query(self, name, request):
            self.client.query_calls.append((self.identity, name, request))
            return self.client.queries[self.identity][request["kind"]]

    class Client:
        namespace = "original"
        old_queue = None
        service_client = SimpleNamespace(config=SimpleNamespace(target_host="fixture:7233"))

        def __init__(self):
            self.descriptions, self.queries, self.query_calls = {}, {}, []

        def get_workflow_handle(self, identity):
            return Handle(self, identity)

    class Worker:
        def __init__(self, queue):
            self.queue = queue
            self.release = None
            self.entered = asyncio.Event()

        async def __aenter__(self):
            self.entered.set()
            if self.release is not None:
                await self.release.wait()
            events.append("started:" + self.queue)
            return self

        async def __aexit__(self, *args):
            events.append("stopped:" + self.queue)

    def worker(client, *, task_queue, **options):
        value = Worker(task_queue)
        workers.append(value)
        return value

    async def namespace(client):
        return "namespace-uuid"

    monkeypatch.setattr("ralf_agent.temporal.build_temporal_worker", worker)
    monkeypatch.setattr("ralf_agent.temporal_session_activities.namespace_id", namespace)
    return SimpleNamespace(client=Client(), events=events, workers=workers)


def test_default_switch_keeps_existing_runtime_and_all_worker_queues(tmp_path, sdk):
    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        try:
            await host.start_workers(sdk.client, queue_prefix="versions")
            first = host.runtime()
            host.select_default(host.profiles[1].identity)
            second = host.runtime()
            assert first.engine.release["runtime_profile"]["version"] == "1"
            assert second.engine.release["runtime_profile"]["version"] == "2"
            assert first.engine.task_queue != second.engine.task_queue
            assert len(sdk.workers) == 2
            assert host.default_profile.version == "2"
        finally:
            await host.aclose()
        assert len([e for e in sdk.events if e.startswith("stopped:")]) == 2

    asyncio.run(run())


def test_unavailable_original_registry_queue_refuses_before_workers(tmp_path, sdk):
    async def run():
        sdk.client.old_queue = "unserved-original-queue"
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        try:
            with pytest.raises(DefinitionMismatch):
                await host.start_workers(sdk.client)
            assert sdk.workers == []
        finally:
            await host.aclose()

    asyncio.run(run())


def test_global_close_keeps_all_workers_and_shared_resource_until_actual_call_ends(tmp_path, sdk):
    async def run():
        class Resource:
            async def aclose(self):
                sdk.events.append("resource-closed")

        resource = Resource()

        async def factory(config, context):
            context.own_async(resource)
            return EchoProvider("test")

        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        host = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(
            catalog("test")
        )
        started, release = asyncio.Event(), asyncio.Event()

        async def operation():
            started.set()
            await release.wait()
            return "finished"

        await host.start_workers(sdk.client)
        work = asyncio.create_task(
            host._assemblies[0]._calls.execute(
                operation,
                info=SimpleNamespace(
                    workflow_id="run", workflow_run_id="uuid", activity_id="model:0", attempt=1
                ),
                request={"scope": asdict(host.scope)},
            )
        )
        try:
            await started.wait()
            with pytest.raises(CloseIncomplete):
                await host.aclose(wait_timeout=0)
            assert not any(e.startswith("stopped:") for e in sdk.events)
            assert "resource-closed" not in sdk.events
            release.set()
            assert await work == "finished"
            await host.aclose()
            assert sdk.events[-1] == "resource-closed"
            assert len([e for e in sdk.events if e.startswith("stopped:")]) == 2
            assert sdk.events.count("resource-closed") == 1
        finally:
            release.set()
            await asyncio.gather(work, return_exceptions=True)
            await host.aclose()

    asyncio.run(run())


def test_namespace_change_during_startup_refuses_before_worker(tmp_path, sdk, monkeypatch):
    async def namespace(client):
        client.namespace = "changed"
        return "namespace-uuid"

    monkeypatch.setattr("ralf_agent.temporal_session_activities.namespace_id", namespace)

    async def run():
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(catalog())
        try:
            with pytest.raises(DefinitionMismatch):
                await host.start_workers(sdk.client)
            assert sdk.workers == []
        finally:
            await host.aclose()

    asyncio.run(run())
