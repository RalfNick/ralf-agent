"""Versioned config, sync/async assembly and lifecycle with explicit binding choices."""

import asyncio
import json

import pytest

from relf_agent import AgentSpec, Scope
from relf_agent.errors import ValidationError
from relf_agent.runtime_builder import ComponentRegistry, RuntimeBuilder
from relf_agent.runtime_config import RuntimeCatalog, RuntimeProfile, load_catalog
from relf_agent.runtime_router import ProfiledEngine

from .test_binding_execution import RecordingProvider, choice, definition


def declarations(label="selected"):
    return [
        {
            "role": "provider",
            "component_id": "model",
            "version": "1",
            "component": {"adapter": "offline-echo", "config": {"label": label}},
        }
    ]


def profile(label="selected", version="1"):
    return RuntimeProfile(
        "app",
        version,
        {"default": {"adapter": "offline-echo", "config": {"label": "host"}}},
        binding_components=declarations(label),
    )


def test_profile_detaches_binding_declarations_and_changes_only_new_identity():
    source = declarations()
    selected = RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=source
    )
    before = selected.identity
    source[0]["component"]["config"]["label"] = "changed"
    selected.binding_components[0]["component"]["config"]["label"] = "also changed"
    assert selected.identity == before
    assert selected.binding_components[0]["component"]["config"]["label"] == "selected"
    assert selected.schema_version == 2
    legacy = RuntimeProfile("app", "1", {"default": {"adapter": "offline-echo"}})
    assert legacy.schema_version == 1 and legacy.binding_components is None


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_v2_configuration_builds_selected_provider(extension, tmp_path):
    path = tmp_path / ("runtime." + extension)
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
                            "providers": {"default": {"adapter": "offline-echo"}},
                            "binding_components": declarations(),
                        }
                    ],
                }
            )
        )
    else:
        path.write_text("""schema_version = 2
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[[profiles.binding_components]]
role = "provider"
component_id = "model"
version = "1"
[profiles.binding_components.component]
adapter = "offline-echo"
[profiles.binding_components.component.config]
label = "selected"
""")
    selected = load_catalog(path).default
    with RuntimeBuilder().build(selected, tmp_path / "runtime.sqlite") as runtime:
        handle = runtime.submit(definition(provider=choice("model")), "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).result == {
            "echo": "q",
            "label": "selected",
        }


def test_v1_rejects_binding_fields_and_unknown_adapters_do_not_create_database(tmp_path):
    path = tmp_path / "v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default": {"name": "app", "version": "1"},
                "profiles": [
                    {
                        "name": "app",
                        "version": "1",
                        "providers": {"default": {"adapter": "offline-echo"}},
                        "binding_components": declarations(),
                    }
                ],
            }
        )
    )
    with pytest.raises(ValidationError):
        load_catalog(path)
    bad = declarations()
    bad[0]["component"]["adapter"] = "arbitrary.module:factory"
    selected = RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=bad
    )
    database = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(selected, database)
    assert not database.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"role": "host_policy"},
        {"version": ""},
        {"unknown": True},
        {"component": None},
        {"component_id": None},
    ],
)
def test_invalid_binding_component_declaration_is_rejected(change):
    values = declarations()
    values[0].update(change)
    with pytest.raises(ValidationError):
        RuntimeProfile(
            "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=values
        )


def test_duplicate_role_id_version_is_rejected():
    values = declarations()
    with pytest.raises(ValidationError):
        RuntimeProfile(
            "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=values * 2
        )


def test_profile_router_restores_original_bindings_after_default_changes(tmp_path):
    catalog = RuntimeCatalog()
    first = profile("first", "1")
    catalog.register(first, default=True)
    with ProfiledEngine(catalog, tmp_path / "routed.sqlite") as runtime:
        handle = runtime.submit(definition(provider=choice("model")), "q", command_id="s")
        catalog.register(profile("second", "2"), default=True)
        assert (
            runtime.submit(definition(provider=choice("model")), "q", command_id="s").run_id
            == handle.run_id
        )
        assert asyncio.run(runtime.drive(handle.run_id)).result == {"echo": "q", "label": "first"}
        assert runtime.diagnostics(handle.run_id).manifest["runtime_profile"] == first.identity


def test_binding_factory_cleanup_closes_only_owned_clients(tmp_path):
    events = []

    class Provider(RecordingProvider):
        def close(self):
            events.append("borrowed")

    class Client:
        def close(self):
            events.append("owned")

    registry = ComponentRegistry()

    def factory(config, context):
        context.own(Client())
        return Provider("selected")

    registry.register("provider", "custom", factory)
    values = declarations()
    values[0]["component"] = {"adapter": "custom"}
    selected = RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=values
    )
    with RuntimeBuilder(registry).build(selected, tmp_path / "lifecycle.sqlite") as runtime:
        handle = runtime.submit(definition(provider=choice("model")), "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).result["provider"] == "selected"
    assert events == ["owned"]


def test_async_binding_factory_cancellation_cleans_owned_resource(tmp_path):
    async def scenario():
        events, started = [], asyncio.Event()

        class Client:
            async def aclose(self):
                events.append("closed")

        async def factory(config, context):
            context.own_async(Client())
            started.set()
            await asyncio.Future()

        registry = ComponentRegistry()
        registry.register_async("provider", "cancelled", factory)
        values = declarations()
        values[0]["component"] = {"adapter": "cancelled"}
        selected = RuntimeProfile(
            "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=values
        )
        builder = RuntimeBuilder(registry)
        with pytest.raises(ValidationError):
            builder.build(selected, tmp_path / "sync-refused.sqlite")
        task = asyncio.create_task(builder.abuild(selected, tmp_path / "cancelled.sqlite"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == ["closed"]

    asyncio.run(scenario())


def test_v2_tool_subset_factory_preserves_host_registry(tmp_path):
    values = [
        {
            "role": "tool_set",
            "component_id": "none",
            "version": "1",
            "component": {"adapter": "names", "config": {"names": []}},
        }
    ]
    selected = RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=values
    )
    with RuntimeBuilder().build(selected, tmp_path / "tools.sqlite") as runtime:
        handle = runtime.submit(definition(tool_set=choice("none")), "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"


def test_new_public_types_are_importable_without_optional_dependencies():
    from relf_agent import (
        AgentBindingDescriptor,
        AgentDefinition,
        BindingCatalog,
        BindingSelection,
        BoundDefinition,
    )

    catalog = BindingCatalog(scope=Scope())
    catalog.register("provider", "model", "1", RecordingProvider("public"))
    wrapped = AgentDefinition(
        AgentSpec("a", "Answer"),
        AgentBindingDescriptor(provider=BindingSelection.ref("model", "1")),
    )
    assert wrapped.to_dict()["kind"] == "bound_agent"
    assert BoundDefinition.__name__ == "BoundDefinition"
