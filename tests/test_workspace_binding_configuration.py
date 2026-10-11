"""Normal Profile assembly reuses original tools and their existing resource ledger."""

import asyncio
import json

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    ComponentRegistry,
    RuntimeBuilder,
    RuntimeProfile,
    Scope,
)
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_config import load_catalog
from ralf_agent.workspace import WorkspaceError

from .test_workspace_binding_execution import Reader, finish
from .test_workspace_bindings import registered as registered


def declaration(names=None):
    return {
        "role": "workspace",
        "component_id": "root",
        "version": "1",
        "component": {
            "adapter": "registered-tools",
            "config": {"names": names or ["a_workspace_read_text"]},
        },
    }


def bound(name="a_workspace_read_text"):
    return AgentDefinition(
        AgentSpec("reader", "Read note", tools=(name,)),
        AgentBindingDescriptor(workspace=BindingSelection.ref("root", "1")),
    )


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_normal_config_wraps_original_registry_and_reads_selected_tool(
    tmp_path, registered, extension
):
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
                            "providers": {"default": {"adapter": "reader"}},
                            "components": {"tools": {"adapter": "borrowed"}},
                            "binding_components": [declaration()],
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
adapter = "reader"
[profiles.components.tools]
adapter = "borrowed"
[[profiles.binding_components]]
role = "workspace"
component_id = "root"
version = "1"
[profiles.binding_components.component]
adapter = "registered-tools"
[profiles.binding_components.component.config]
names = ["a_workspace_read_text"]
""")
    factories = ComponentRegistry()
    factories.register("tools", "borrowed", lambda c, ctx: registered)
    factories.register("provider", "reader", lambda c, ctx: Reader())
    with RuntimeBuilder(factories).build(
        load_catalog(path).default, tmp_path / "runs.sqlite"
    ) as runtime:
        handle = runtime.submit(bound(), "q", command_id="submit")
        done = asyncio.run(finish(runtime, handle.run_id))
        assert done.state == "succeeded" and done.result["text"] == "alpha"
        component, _ = runtime.binding_catalog.resolve(
            "workspace", BindingSelection.ref("root", "1"), Scope()
        )
        assert component.registry is registered
    assert registered.get("a_workspace_read_text").spec.effect == "read_only"


def test_async_default_filesystem_source_is_allocated_once_and_closed_in_original_order(
    tmp_path, monkeypatch
):
    import ralf_agent.workspace_factories as module

    root = tmp_path / "files"
    root.mkdir()
    (root / "note").write_text("real file")
    allocated, original = [], module.FileSystemWorkspace

    def allocate(*args, **kwargs):
        port = original(*args, **kwargs)
        allocated.append(port)
        return port

    monkeypatch.setattr(module, "FileSystemWorkspace", allocate)
    factories = ComponentRegistry()
    factories.register("provider", "reader", lambda c, ctx: Reader())
    profile = RuntimeProfile(
        "files",
        "1",
        {"default": {"adapter": "reader"}},
        {"tools": {"adapter": "workspace-read", "config": {"root": str(root), "version": "1"}}},
        binding_components=[declaration(["workspace_read_text"])],
    )

    async def run():
        async with await RuntimeBuilder(factories).abuild(
            profile, tmp_path / "runs.sqlite"
        ) as runtime:
            handle = runtime.submit(bound("workspace_read_text"), "q", command_id="submit")
            done = await runtime.drive(handle.run_id)
            assert done.state == "succeeded" and done.result["text"] == "real file"
            assert len(allocated) == 1

    asyncio.run(run())
    assert len(allocated) == 1
    with pytest.raises(WorkspaceError):
        allocated[0].stat(Scope(), "")
    allocated[0].close()


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"names": []},
        {"names": ["x", "x"]},
        {"names": "x"},
        {"names": [True]},
        {"names": ["x" * 129]},
        {"names": ["x"], "root": "/unused"},
    ],
)
def test_bad_binding_declaration_refused_before_store_or_root_allocation(tmp_path, config):
    profile = RuntimeProfile(
        "bad",
        "1",
        {"default": {"adapter": "offline-echo"}},
        binding_components=[
            {**declaration(), "component": {"adapter": "registered-tools", "config": config}}
        ],
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, tmp_path / "runs.sqlite")
    assert not (tmp_path / "runs.sqlite").exists()
