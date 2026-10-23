"""Scoped data declarations reuse original factories and own only actual clients."""

import asyncio
import json

import pytest

from relf_agent import InMemoryMemory, RuntimeBuilder, RuntimeProfile, Scope
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import ComponentRegistry
from relf_agent.runtime_config import load_catalog

from .test_data_binding_execution import definitions
from .test_data_binding_resources import resources


def declarations():
    return [
        {
            "role": role,
            "component_id": name,
            "version": "1",
            "component": {
                "adapter": role + "-resource",
                "config": {
                    "backend": {"adapter": backend},
                    "namespaces": ["red", "blue"],
                    "default_namespace": "red",
                },
            },
        }
        for role, name, backend in (
            ("facts", "facts", "sqlite"),
            ("knowledge", "docs", "sqlite-lexical"),
        )
    ]


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_scoped_data_profiles_build_run_and_resume(tmp_path, extension):
    path = tmp_path / ("runtime." + extension)
    profile = RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=declarations()
    )
    if extension == "json":
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "default": {"name": "app", "version": "1"},
                    "profiles": [
                        {
                            "name": "app",
                            "version": "1",
                            "providers": profile.providers,
                            "binding_components": declarations(),
                        }
                    ],
                }
            )
        )
    else:
        header = 'schema_version = 2\n[default]\nname="app"\nversion="1"\n[[profiles]]\nname="app"\nversion="1"\n[profiles.providers.default]\nadapter="offline-echo"\n'
        for value in declarations():
            header += f'[[profiles.binding_components]]\nrole="{value["role"]}"\ncomponent_id="{value["component_id"]}"\nversion="1"\n[profiles.binding_components.component]\nadapter="{value["component"]["adapter"]}"\n[profiles.binding_components.component.config]\nnamespaces=["red","blue"]\ndefault_namespace="red"\n[profiles.binding_components.component.config.backend]\nadapter="{value["component"]["config"]["backend"]["adapter"]}"\n'
        path.write_text(header)
    parsed = load_catalog(path).default
    with RuntimeBuilder().build(parsed, tmp_path / "runs.sqlite") as runtime:
        h = runtime.submit(definitions("native"), "pool", command_id="s")
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
    with RuntimeBuilder().build(parsed, tmp_path / "runs.sqlite") as runtime:
        assert runtime.submit(definitions("native"), "pool", command_id="s") == h
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"


def test_async_facts_factory_keeps_original_owned_cleanup(tmp_path):
    async def scenario():
        events = []

        class Backend(InMemoryMemory):
            async def aclose(self):
                events.append("closed")

        async def factory(config, context):
            return context.own_async(Backend())

        registry = ComponentRegistry()
        registry.register_async("memory_store", "custom", factory)
        values = declarations()
        values[0]["component"]["config"]["backend"] = {"adapter": "custom"}
        profile = RuntimeProfile(
            "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=values
        )
        with pytest.raises(ValidationError):
            RuntimeBuilder(registry).build(profile, tmp_path / "sync.sqlite")
        async with await RuntimeBuilder(registry).abuild(
            profile, tmp_path / "async.sqlite"
        ) as runtime:
            handle = runtime.submit(definitions("native"), "pool", command_id="s")
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
        assert events == ["closed"]

    asyncio.run(scenario())


@pytest.mark.parametrize("role", ["facts", "knowledge"])
def test_invalid_wrapper_namespace_fails_before_database_creation(tmp_path, role):
    values = declarations()
    next(value for value in values if value["role"] == role)["component"]["config"][
        "namespaces"
    ] = [None]
    profile = RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=values
    )
    path = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, path)
    assert not path.exists()


def test_prepared_fact_wrapper_freezes_mutable_default_and_public_exports():
    api = resources()
    import relf_agent

    assert relf_agent.FactsBindingResource is api.FactsBindingResource
    assert relf_agent.KnowledgeBindingResource is api.KnowledgeBindingResource
    declaration = declarations()[0]["component"]
    declaration["config"]["backend"] = {"adapter": "in-memory"}
    factory, config = ComponentRegistry().prepare("memory_store", declaration)
    declaration["config"]["default_namespace"] = "blue"
    resource = factory(config, None)
    assert resource.select({}, Scope()).namespace == "red"
