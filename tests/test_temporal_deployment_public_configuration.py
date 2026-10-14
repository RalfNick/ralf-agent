"""Public policy entry points and pre-I/O errors; service evidence is separate."""

import asyncio
from types import SimpleNamespace

import pytest

from ralf_agent import (
    ComponentRegistry,
    DeploymentAdmissionPolicy,
    ModelResponse,
    TemporalEngine,
    TemporalProfile,
    TemporalRuntime,
    TemporalRuntimeBuilder,
    ToolRegistry,
)
from ralf_agent.errors import ValidationError


class Provider:
    identity = {"kind": "public-config-model", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(output="done")


def test_public_policy_selects_v2_and_private_policy_stays_v1():
    policy = DeploymentAdmissionPolicy("configuration")
    args = {"providers": {"default": Provider()}, "tools": ToolRegistry()}
    public = TemporalRuntime(**args, admission_policy=policy)
    private = TemporalRuntime(**args, _deployment_admission_policy=policy)
    plain = TemporalRuntime(**args)
    assert public.manifest["deployment_admission_protocol"]["version"] == 2
    assert private.manifest["deployment_admission_protocol"]["version"] == 1
    assert "deployment_admission_protocol" not in plain.manifest
    engine = TemporalEngine(
        SimpleNamespace(namespace="default"), task_queue="q", release=public.manifest
    )
    assert (
        engine.command_registry_id
        == public.manifest["deployment_admission_protocol"]["registry_id"]
    )
    with pytest.raises(ValidationError):
        TemporalEngine(
            SimpleNamespace(namespace="default"), task_queue="q", release=private.manifest
        )
    with pytest.raises(ValidationError):
        TemporalRuntime(**args, admission_policy=policy, _deployment_admission_policy=policy)


def test_public_profile_reuses_sync_and_async_component_factories():
    async def run():
        calls = []
        registry = ComponentRegistry()
        registry.register("provider", "public-model", lambda c, ctx: Provider())
        policy = DeploymentAdmissionPolicy("profile")
        for asynchronous in [False, True]:
            if asynchronous:

                async def factory(config, context):
                    calls.append("async")
                    return policy

                registry.register_async("admission_policy", "public-capacity-async", factory)
            else:
                registry.register(
                    "admission_policy",
                    "public-capacity",
                    lambda c, ctx: calls.append("sync") or policy,
                )
            profile = TemporalProfile(
                "profile",
                "1",
                {"default": {"adapter": "public-model"}},
                components={
                    "admission_policy": {
                        "adapter": "public-capacity-async" if asynchronous else "public-capacity"
                    }
                },
            )
            assembly = await TemporalRuntimeBuilder(registry).abuild(profile)
            assert assembly.release["deployment_admission_protocol"]["policy"] == policy.identity
            await assembly.aclose()
        assert calls == ["sync", "async"]

    asyncio.run(run())


def test_invalid_policy_and_dual_source_refuse_before_provider_io():
    async def run():
        calls = []
        registry = ComponentRegistry()
        registry.register(
            "provider", "counted", lambda c, ctx: calls.append("provider") or Provider()
        )
        builder = TemporalRuntimeBuilder(registry)
        profile = TemporalProfile(
            "profile",
            "1",
            {"default": {"adapter": "counted"}},
            components={
                "admission_policy": {"adapter": "bounded", "config": {"deployment_id": "profile"}}
            },
        )
        for policy in [object(), DeploymentAdmissionPolicy("host")]:
            with pytest.raises(ValidationError):
                await builder.abuild(profile, admission_policy=policy)
        assert not calls

    asyncio.run(run())


def test_declared_wrong_policy_result_does_not_silently_disable_admission():
    async def run():
        registry = ComponentRegistry()
        registry.register("provider", "public-model", lambda c, ctx: Provider())
        registry.register("admission_policy", "none", lambda c, ctx: None)
        profile = TemporalProfile(
            "profile",
            "1",
            {"default": {"adapter": "public-model"}},
            components={"admission_policy": {"adapter": "none"}},
        )
        with pytest.raises(ValidationError):
            await TemporalRuntimeBuilder(registry).abuild(profile)

    asyncio.run(run())


def test_catalog_host_policy_is_never_silently_omitted_and_conflicts_before_io():
    async def run():
        from ralf_agent import TemporalProfileCatalog

        calls = []
        registry = ComponentRegistry()
        registry.register(
            "provider", "catalog-model", lambda c, ctx: calls.append("provider") or Provider()
        )
        builder = TemporalRuntimeBuilder(registry)
        plain = TemporalProfile("plain", "1", {"default": {"adapter": "catalog-model"}})
        catalog = TemporalProfileCatalog()
        catalog.register(plain, default=True)
        policy = DeploymentAdmissionPolicy("catalog-host")
        host = await builder.abuild_catalog(catalog, admission_policy=policy)
        try:
            assert all(
                a.release.get("deployment_admission_protocol", {}).get("policy") == policy.identity
                for a in host._assemblies
            )
        finally:
            await host.aclose()
        calls.clear()
        selected = TemporalProfile(
            "selected",
            "1",
            {"default": {"adapter": "catalog-model"}},
            components={
                "admission_policy": {"adapter": "bounded", "config": {"deployment_id": "selected"}}
            },
        )
        mixed = TemporalProfileCatalog()
        mixed.register(plain, default=True)
        mixed.register(selected)
        with pytest.raises(ValidationError):
            await builder.abuild_catalog(mixed, admission_policy=policy)
        assert not calls

    asyncio.run(run())
