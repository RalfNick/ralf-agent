"""Declarative Temporal construction has no Local execution authority."""

import asyncio

import pytest

from ralf_agent import ComponentRegistry, Scope
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import EchoProvider
from ralf_agent.temporal_builder import TemporalRuntimeBuilder
from ralf_agent.temporal_profile import TemporalProfile


def profile(*, adapter="offline-echo", components=None, **kwargs):
    return TemporalProfile("worker", "1", {"default": {"adapter": adapter}}, components, **kwargs)


class Client:
    def __init__(self):
        self.closes = 0

    async def aclose(self):
        self.closes += 1


def test_public_temporal_builder_and_assembly_exports():
    from ralf_agent import TemporalRuntimeAssembly
    from ralf_agent import TemporalRuntimeBuilder as PublicBuilder

    assert PublicBuilder is TemporalRuntimeBuilder
    assert TemporalRuntimeAssembly.__module__ == "ralf_agent.temporal_assembly_lifecycle"


def test_default_assembly_has_fixed_profile_and_no_execution_database(tmp_path):
    async def run():
        selected = profile()
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(selected)
        try:
            assert assembly.profile.identity == selected.identity
            assert assembly.scope == Scope()
            assert assembly.release["runtime_profile"] == selected.identity
            assert not any(tmp_path.iterdir())
        finally:
            await assembly.aclose()
        assert not any(tmp_path.iterdir())

    asyncio.run(run())


def test_async_factory_receives_explicit_scope_and_owned_close(tmp_path):
    async def run():
        clients, stores = [], []

        async def factory(config, context):
            assert context.scope == Scope("team", "operator")
            stores.append(context.store)
            client = context.own_async(Client())
            clients.append(client)
            return EchoProvider("declared")

        registry = ComponentRegistry()
        registry.register_async("provider", "managed", factory)
        assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile(adapter="managed"), scope=Scope("team", "operator")
        )
        assert stores == [None] and clients[0].closes == 0
        await assembly.aclose()
        await assembly.aclose()
        assert clients[0].closes == 1

    asyncio.run(run())


def test_unsupported_adapter_is_checked_before_provider_factory_io(tmp_path):
    async def run():
        calls = []

        def factory(config, context):
            calls.append("constructed")
            return EchoProvider("custom")

        registry = ComponentRegistry()
        registry.register("provider", "custom", factory)
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                profile(adapter="custom", components={"knowledge": {"adapter": "missing"}})
            )
        assert calls == [] and not any(tmp_path.iterdir())

    asyncio.run(run())


def test_sqlite_without_data_path_refuses_before_any_factory(tmp_path):
    async def run():
        calls = []

        def factory(config, context):
            calls.append("constructed")
            return EchoProvider("custom")

        registry = ComponentRegistry()
        registry.register("provider", "custom", factory)
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                profile(adapter="custom", components={"session_store": {"adapter": "sqlite"}})
            )
        assert not calls and not any(tmp_path.iterdir())

    asyncio.run(run())


def test_detach_transfers_owned_resources_without_closing_them(tmp_path):
    async def run():
        client = Client()

        async def factory(config, context):
            context.own_async(client)
            return EchoProvider("borrowed-host")

        registry = ComponentRegistry()
        registry.register_async("provider", "owned", factory)
        assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile(adapter="owned")
        )
        runtime, cleanup = assembly.detach_components()
        assert runtime.manifest["runtime_profile"] == assembly.profile.identity
        await assembly.aclose()
        assert client.closes == 0
        with pytest.raises(ValidationError):
            assembly.create_engine(object(), task_queue="unused")
        await cleanup.cleanup_async()
        assert client.closes == 1

    asyncio.run(run())


def test_failure_cleans_already_owned_factory_client(tmp_path):
    async def run():
        client = Client()

        async def factory(config, context):
            context.own_async(client)
            raise ValidationError("fixture construction failure")

        registry = ComponentRegistry()
        registry.register_async("provider", "failure", factory)
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
                profile(adapter="failure")
            )
        assert client.closes == 1

    asyncio.run(run())


def test_all_ten_binding_roles_are_constructed_with_original_catalog(tmp_path):
    async def run():
        adapters = {
            "provider": "offline-echo",
            "decision_policy": "native",
            "context": "default",
            "session": "in-memory",
            "facts": "in-memory",
            "knowledge": "sqlite-lexical",
            "tool_set": "names",
            "verifier": "schema",
            "limits": "fixed",
            "stage_policy": "sourced-memory",
        }
        values = [
            {"role": role, "component_id": role, "version": "1", "component": {"adapter": adapter}}
            for role, adapter in adapters.items()
        ]
        values[-1]["component"]["config"] = {"memory": {"adapter": "in-memory"}}
        selected = profile(binding_components=values)
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(selected)
        runtime, cleanup = assembly.detach_components()
        try:
            assert {key[0] for key in runtime.binding_catalog._entries} == set(adapters)
            assert runtime.binding_catalog.scope == Scope()
            assert runtime.orchestration_release["runtime_profile"] == selected.identity
        finally:
            await cleanup.cleanup_async()
            await assembly.aclose()

    asyncio.run(run())


def test_explicit_sqlite_paths_use_independent_data_files(tmp_path):
    async def run():
        selected = profile(
            components={
                "session_store": {"adapter": "sqlite"},
                "memory_store": {"adapter": "sqlite"},
            },
            execution={"enable_sessions": True, "session_writes": True, "context_reads": True},
        )
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
            selected, data_path="data"
        )
        try:
            assert (tmp_path / "data.session_store.sqlite").is_file()
            assert (tmp_path / "data.memory_store.sqlite").is_file()
            assert not (tmp_path / "data").exists()
        finally:
            await assembly.aclose()

    asyncio.run(run())


def test_nested_stage_sqlite_missing_path_refuses_before_provider_factory(tmp_path):
    async def run():
        calls = []

        def factory(config, context):
            calls.append("provider-created")
            return EchoProvider("custom")

        registry = ComponentRegistry()
        registry.register("provider", "custom", factory)
        selected = profile(
            adapter="custom",
            components={
                "stage_policy": {
                    "adapter": "sourced-memory",
                    "config": {"memory": {"adapter": "sqlite"}},
                }
            },
        )
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(selected)
        assert calls == []

    asyncio.run(run())


def test_resource_backend_without_config_is_normalized_before_sqlite_paths(tmp_path):
    async def run():
        selected = profile(
            components={
                "session_store": {
                    "adapter": "session-resource",
                    "config": {"backend": {"adapter": "sqlite"}},
                }
            },
            execution={"session_writes": True},
        )
        assembled = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(
            selected, data_path="data"
        )
        try:
            assert (tmp_path / "data.session_store.sqlite").is_file()
        finally:
            await assembled.aclose()

    asyncio.run(run())


def test_managed_worker_stays_open_until_actual_call_ends(tmp_path, monkeypatch):
    from dataclasses import asdict
    from types import SimpleNamespace

    import ralf_agent.temporal
    from ralf_agent.errors import CloseIncomplete

    async def run():
        client = Client()

        async def factory(config, context):
            context.own_async(client)
            return EchoProvider("owned")

        class Worker:
            def __init__(self):
                self.starts, self.closes = 0, 0

            async def __aenter__(self):
                self.starts += 1
                return self

            async def __aexit__(self, *args):
                self.closes += 1

        worker = Worker()
        monkeypatch.setattr(ralf_agent.temporal, "build_temporal_worker", lambda *a, **kw: worker)
        registry = ComponentRegistry()
        registry.register_async("provider", "owned", factory)
        assembly = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile(adapter="owned")
        )
        sdk_client = SimpleNamespace(namespace="original")
        await assembly.start_worker(sdk_client, task_queue="queue")
        started, release = asyncio.Event(), asyncio.Event()

        async def operation():
            started.set()
            await release.wait()
            return "finished"

        task = asyncio.create_task(
            assembly._calls.execute(
                operation,
                info=SimpleNamespace(
                    workflow_id="run", workflow_run_id="uuid", activity_id="model:0", attempt=1
                ),
                request={"scope": asdict(Scope())},
            )
        )
        try:
            await started.wait()
            with pytest.raises(CloseIncomplete):
                await assembly.aclose(wait_timeout=0)
            assert worker.closes == client.closes == 0
            release.set()
            assert await task == "finished"
            await assembly.aclose(wait_timeout=3)
            assert worker.closes == client.closes == 1
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await assembly.aclose(wait_timeout=3)

    asyncio.run(run())


def test_cancelled_worker_start_is_retained_for_close(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import ralf_agent.temporal
    from ralf_agent.errors import CloseIncomplete

    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        class Worker:
            def __init__(self):
                self.closes = 0

            async def __aenter__(self):
                started.set()
                await release.wait()
                return self

            async def __aexit__(self, *args):
                self.closes += 1

        worker = Worker()
        monkeypatch.setattr(ralf_agent.temporal, "build_temporal_worker", lambda *a, **kw: worker)
        assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(profile())
        observer = asyncio.create_task(
            assembly.start_worker(SimpleNamespace(namespace="original"), task_queue="queue")
        )
        try:
            await started.wait()
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            with pytest.raises(CloseIncomplete):
                await assembly.aclose(wait_timeout=0)
            assert worker.closes == 0
            release.set()
            await assembly.aclose(wait_timeout=3)
            assert worker.closes == 1
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)
            await assembly.aclose(wait_timeout=3)

    asyncio.run(run())
