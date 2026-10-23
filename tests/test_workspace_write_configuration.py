"""Default declared writes remain opt-in, owned once, and approved."""

import asyncio
import json

import pytest

import relf_agent as r
from relf_agent.errors import ValidationError
from relf_agent.runtime_config import load_catalog

from .test_workspace_binding_execution import finish


class Writer:
    identity = {"kind": "workspace-write-config-provider", "version": "1"}

    async def complete(self, messages, tools):
        evidence = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if evidence:
            return r.ModelResponse(output=evidence[-1])
        names = [t["function"]["name"] for t in tools]
        name = next((n for n in names if n.endswith("workspace_write_text")), None)
        return (
            r.ModelResponse(output={"available": names})
            if name is None
            else r.ModelResponse(
                tool_calls=[
                    r.ToolCall(
                        name, {"path": "note", "text": "A", "expected_version": None}, "write"
                    )
                ]
            )
        )


def bound():
    return r.AgentDefinition(
        r.AgentSpec("writer", "Write allowed note", tools=("workspace_write_text",)),
        r.AgentBindingDescriptor(workspace=r.BindingSelection.ref("files", "1")),
    )


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_default_declared_writer_reuses_registry_and_keeps_approval_before_file_effect(
    tmp_path, extension
):
    root = tmp_path / "files"
    root.mkdir()
    path = tmp_path / ("runtime." + extension)
    profile = {
        "name": "app",
        "version": "1",
        "providers": {"default": {"adapter": "writer"}},
        "components": {
            "tools": {
                "adapter": "workspace-read-write",
                "config": {"root": "files", "version": "1"},
            }
        },
        "binding_components": [
            {
                "role": "workspace",
                "component_id": "files",
                "version": "1",
                "component": {
                    "adapter": "registered-tools",
                    "config": {"names": ["workspace_write_text"]},
                },
            }
        ],
    }
    if extension == "json":
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "default": {"name": "app", "version": "1"},
                    "profiles": [profile],
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
adapter = "writer"
[profiles.components.tools]
adapter = "workspace-read-write"
[profiles.components.tools.config]
root = "files"
version = "1"
[[profiles.binding_components]]
role = "workspace"
component_id = "files"
version = "1"
[profiles.binding_components.component]
adapter = "registered-tools"
[profiles.binding_components.component.config]
names = ["workspace_write_text"]
""")
    factories = r.ComponentRegistry()
    factories.register("provider", "writer", lambda c, ctx: Writer())
    prepared = load_catalog(path).default

    async def run():
        runtime = await r.RuntimeBuilder(factories, base_dir=tmp_path).abuild(
            prepared, tmp_path / "runs.sqlite"
        )
        try:
            selected, _ = runtime.binding_catalog.resolve(
                "workspace", r.BindingSelection.ref("files", "1"), r.Scope()
            )
            assert selected.registry is runtime.tools
            handle = runtime.submit(bound(), "q", command_id="submit")
            waiting = await runtime.drive(handle.run_id)
            assert waiting.state == "waiting_approval" and not (root / "note").exists()
            done = await finish(runtime, handle.run_id)
            assert done.state == "succeeded" and (root / "note").read_text() == "A"
            assert runtime.tools.get("workspace_write_text").spec.requires_approval
        finally:
            await runtime.aclose()
        replacement = r.FileSystemWritableWorkspace(root, version="1")
        replacement.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "extra",
    [
        {"capacity": True},
        {"capacity": 0},
        {"write_requires_approval": False},
        {"max_bytes": 0},
        {"scope": "model"},
    ],
)
def test_invalid_default_write_declaration_is_pure_before_root_or_execution_store(tmp_path, extra):
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "echo"}},
        {
            "tools": {
                "adapter": "workspace-read-write",
                "config": {"root": "files", "version": "1", **extra},
            }
        },
    )

    async def run():
        with pytest.raises(ValidationError):
            await r.RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert not (tmp_path / "runs.sqlite").exists() and not (tmp_path / "files").exists()


def test_partial_binding_failure_drains_source_and_releases_only_owned_writer(
    tmp_path, monkeypatch
):
    import relf_agent.workspace_write_factories as module

    root = tmp_path / "files"
    root.mkdir()
    original, allocated = module.FileSystemWritableWorkspace, []

    def allocate(*args, **kwargs):
        port = original(*args, **kwargs)
        allocated.append(port)
        return port

    monkeypatch.setattr(module, "FileSystemWritableWorkspace", allocate)
    profile = r.RuntimeProfile(
        "broken",
        "1",
        {"default": {"adapter": "echo"}},
        {
            "tools": {
                "adapter": "workspace-read-write",
                "config": {"root": str(root), "version": "1"},
            }
        },
        binding_components=[
            {
                "role": "workspace",
                "component_id": "files",
                "version": "1",
                "component": {"adapter": "registered-tools", "config": {"names": ["missing"]}},
            }
        ],
    )

    async def run():
        from relf_agent.errors import DefinitionMismatch

        factories = r.ComponentRegistry()
        factories.register("provider", "echo", lambda c, ctx: Writer())
        with pytest.raises(DefinitionMismatch):
            await r.RuntimeBuilder(factories).abuild(profile, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert len(allocated) == 1
    from relf_agent.workspace import WorkspaceError

    with pytest.raises(WorkspaceError):
        allocated[0].write_text(r.Scope(), "note", "A", expected_version=None, effect_key="k")
    replacement = original(root, version="1")
    replacement.close()
