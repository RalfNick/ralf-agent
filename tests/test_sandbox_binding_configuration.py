"""Skills declarations borrow native registrations and retain original cleanup."""

import asyncio
import json

import pytest

import ralf_agent as r
from ralf_agent.errors import RalfError, ValidationError
from ralf_agent.runtime_config import load_catalog

from .test_sandbox_binding_execution import Reader
from .test_sandbox_bindings import registered as registered
from .test_workspace_binding_execution import finish


def declaration(names):
    return {
        "role": "sandbox",
        "component_id": "catalog",
        "version": "1",
        "component": {"adapter": "registered-tools", "config": {"names": names}},
    }


def bound(name):
    return r.AgentDefinition(
        r.AgentSpec("reader", "Read help", tools=(name,)),
        r.AgentBindingDescriptor(sandbox=r.BindingSelection.ref("catalog", "1")),
    )


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_normal_declaration_reuses_borrowed_registry_and_role(tmp_path, registered, extension):
    registry, ports = registered
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
                            "binding_components": [declaration(["a_sandbox_run"])],
                        }
                    ],
                }
            )
        )
    else:
        path.write_text(
            'schema_version=2\n[default]\nname="app"\nversion="1"\n[[profiles]]\nname="app"\nversion="1"\n[profiles.providers.default]\nadapter="reader"\n[profiles.components.tools]\nadapter="borrowed"\n[[profiles.binding_components]]\nrole="sandbox"\ncomponent_id="catalog"\nversion="1"\n[profiles.binding_components.component]\nadapter="registered-tools"\n[profiles.binding_components.component.config]\nnames=["a_sandbox_run"]\n'
        )
    factories = r.ComponentRegistry()
    factories.register("provider", "reader", lambda c, ctx: Reader())
    factories.register("tools", "borrowed", lambda c, ctx: registry)
    with r.RuntimeBuilder(factories).build(
        load_catalog(path).default, tmp_path / "runs.sqlite"
    ) as runtime:
        handle = runtime.submit(bound("a_sandbox_run"), "read", command_id="same")
        done = asyncio.run(finish(runtime, handle.run_id))
        assert done.state == "succeeded" and done.result["stdout"] == "result"
        resource, _ = runtime.binding_catalog.resolve(
            "sandbox", r.BindingSelection.ref("catalog", "1"), r.Scope()
        )
        assert resource.registry is registry
    assert not ports[0].closed


@pytest.mark.parametrize(
    "config",
    [{}, {"names": []}, {"names": "x"}, {"names": [True]}, {"names": ["x"], "root": "unused"}],
)
def test_invalid_binding_preflight_does_not_allocate_store(tmp_path, config):
    declaration_value = declaration(["sandbox_run"])
    declaration_value["component"]["config"] = config
    profile = r.RuntimeProfile(
        "app", "1", {"default": {"adapter": "offline-echo"}}, binding_components=[declaration_value]
    )
    with pytest.raises(ValidationError):
        r.RuntimeBuilder().build(profile, tmp_path / "runs.sqlite")
    assert not (tmp_path / "runs.sqlite").exists()


def test_owned_file_catalog_closed_after_wrong_registered_family(tmp_path, monkeypatch):
    import ralf_agent.skill_factories as module

    root = tmp_path / "skills"
    root.mkdir()
    (root / "help.md").write_text("Original")
    (root / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {"name": "help", "description": "Reference", "version": "1", "path": "help.md"}
                ],
            }
        )
    )
    allocated = []
    original = module.FileSystemSkillCatalog

    def allocate(*args, **kwargs):
        port = original(*args, **kwargs)
        allocated.append(port)
        return port

    monkeypatch.setattr(module, "FileSystemSkillCatalog", allocate)
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "tools": {
                "adapter": "skills-file",
                "config": {
                    "root": str(root),
                    "version": "1",
                    "scopes": [{"workspace": "default", "principal": "local-owner"}],
                },
            }
        },
        binding_components=[declaration(["missing_business"])],
    )

    async def run():
        with pytest.raises(RalfError):
            await r.RuntimeBuilder().abuild(profile, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert len(allocated) == 1 and allocated[0]._workspace._root_fd is None
