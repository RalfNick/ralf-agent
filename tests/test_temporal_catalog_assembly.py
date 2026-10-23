"""Catalog snapshots and complete preflight precede any construction I/O."""

import asyncio

import pytest

from relf_agent import (
    ComponentRegistry,
    TemporalProfile,
    TemporalProfileCatalog,
    TemporalRuntimeBuilder,
)
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import EchoProvider, RuntimeBuildError


def catalog(adapter="offline-echo", **second):
    value = TemporalProfileCatalog()
    value.register(TemporalProfile("app", "1", {"default": {"adapter": adapter}}), default=True)
    value.register(TemporalProfile("app", "2", {"default": {"adapter": adapter}}, **second))
    return value


def test_profiles_are_detached_immutable_values():
    source = catalog()
    profiles = source.profiles
    assert isinstance(profiles, tuple) and [p.version for p in profiles] == ["1", "2"]
    profiles[0].providers["default"]["adapter"] = "missing"
    assert source.default_profile.providers["default"]["adapter"] == "offline-echo"
    with pytest.raises(AttributeError):
        profiles[0].version = "changed"


def test_public_profile_host_export():
    from relf_agent import TemporalProfileHost

    assert TemporalProfileHost.__module__ == "relf_agent.temporal_profile_host"


def test_host_snapshot_does_not_follow_external_default_or_registrations(tmp_path):
    async def run():
        source = catalog()
        host = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild_catalog(source)
        try:
            source.set_default("app", "2")
            source.register(TemporalProfile("app", "3", {"default": {"adapter": "offline-echo"}}))
            assert host.default_profile.version == "1"
            assert [p.version for p in host.profiles] == ["1", "2"]
            assert not any(tmp_path.iterdir())
        finally:
            await host.aclose()

    asyncio.run(run())


def test_last_invalid_profile_refuses_before_first_factory(tmp_path):
    async def run():
        calls = []
        registry = ComponentRegistry()

        def factory(config, context):
            calls.append("io")
            return EchoProvider("test")

        registry.register("provider", "test", factory)
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(
                catalog("test", components={"memory_store": {"adapter": "absent"}})
            )
        assert calls == [] and not any(tmp_path.iterdir())

    asyncio.run(run())


def test_catalog_limit_checked_before_any_factory(tmp_path):
    async def run():
        source = catalog("test")
        for version in range(3, 34):
            source.register(TemporalProfile("app", str(version), {"default": {"adapter": "test"}}))
        calls = []
        registry = ComponentRegistry()
        registry.register("provider", "test", lambda c, ctx: calls.append("io"))
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(source)
        assert calls == []

    asyncio.run(run())


def test_shared_factory_resource_is_owned_and_closed_once(tmp_path):
    async def run():
        events, contexts = [], []

        class Client:
            async def aclose(self):
                events.append("closed")

        client = Client()

        async def factory(config, context):
            contexts.append(context)
            context.own_async(client)
            return EchoProvider("test")

        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        host = await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(
            catalog("test")
        )
        assert len(contexts) == 2 and all(c.store is None for c in contexts)
        with pytest.raises(ValidationError):
            await contexts[0].cleanup_async()
        assert events == []
        await host.aclose()
        await host.aclose()
        assert events == ["closed"]

    asyncio.run(run())


def test_conflicting_shared_close_modes_refuse_and_retain_cleanup(tmp_path):
    async def run():
        events = []

        class Client:
            def close(self):
                events.append("sync")

            async def aclose(self):
                events.append("async")

        client = Client()
        calls = []

        async def factory(config, context):
            calls.append(context)
            if len(calls) == 1:
                context.own(client)
            else:
                context.own_async(client)
            return EchoProvider("test")

        registry = ComponentRegistry()
        registry.register_async("provider", "test", factory)
        with pytest.raises((RuntimeBuildError, ValidationError)) as caught:
            await TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild_catalog(
                catalog("test")
            )
        if isinstance(caught.value, RuntimeBuildError):
            await caught.value.cleanup.aclose()
        assert events == ["sync"]

    asyncio.run(run())
