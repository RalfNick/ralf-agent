"""Declared skill catalogs validate before I/O and reuse original async ownership."""

import asyncio
import json

import pytest

import ralf_agent as r
from ralf_agent.errors import ValidationError
from ralf_agent.runtime_config import load_catalog
from ralf_agent.types import InvocationContext


def bundle(tmp_path):
    root = tmp_path / "skills"
    (root / "help").mkdir(parents=True)
    (root / "help/SKILL.md").write_text("Use allowed tools")
    (root / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {
                        "name": "help",
                        "description": "Reference",
                        "version": "1",
                        "path": "help/SKILL.md",
                    }
                ],
            }
        )
    )
    return root


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_default_declaration_json_toml_and_original_scope(tmp_path, extension):
    bundle(tmp_path)
    path = tmp_path / ("runtime." + extension)
    if extension == "json":
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
                            "components": {
                                "tools": {
                                    "adapter": "skills-file",
                                    "config": {
                                        "root": "skills",
                                        "version": "1",
                                        "prefix": "guide_",
                                        "max_entries": 1,
                                        "cost": 2,
                                    },
                                }
                            },
                        }
                    ],
                }
            )
        )
    else:
        path.write_text("""schema_version = 1
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.tools]
adapter = "skills-file"
[profiles.components.tools.config]
root = "skills"
version = "1"
prefix = "guide_"
max_entries = 1
cost = 2
""")
    profile = load_catalog(path).default

    async def run():
        runtime = await r.RuntimeBuilder(base_dir=tmp_path).abuild(
            profile, tmp_path / "runs.sqlite"
        )
        try:
            entry = runtime.tools.get("guide_skill_get")
            assert entry.spec.effect == "read_only" and entry.spec.cost == 2
            value = await entry.handler(
                {"name": "help"},
                InvocationContext(r.Scope(), "run", "action", "attempt", "effect", "epoch"),
            )
            assert value["skill"]["instructions"] == "Use allowed tools"
            assert runtime.tools.get("guide_skill_list").spec.effect == "read_only"
        finally:
            await runtime.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "extra",
    [
        {"max_skills": True},
        {"max_entries": 0},
        {"max_bytes": 0},
        {"manifest": "../secret"},
        {"activate_tools": True},
        {"scope": "model"},
    ],
)
def test_invalid_declarations_refuse_before_resource_allocation(tmp_path, extra):
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "tools": {
                "adapter": "skills-file",
                "config": {"root": "skills", "version": "1", **extra},
            }
        },
    )

    async def run():
        with pytest.raises(ValidationError):
            await r.RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert not (tmp_path / "runs.sqlite").exists() and not (tmp_path / "skills").exists()


def test_partial_bad_workspace_binding_closes_only_original_owned_skill_catalog(
    tmp_path, monkeypatch
):
    import ralf_agent.skill_factories as module

    root = bundle(tmp_path)
    allocated, original = [], module.FileSystemSkillCatalog

    def allocate(*args, **kwargs):
        catalog = original(*args, **kwargs)
        allocated.append(catalog)
        return catalog

    monkeypatch.setattr(module, "FileSystemSkillCatalog", allocate)
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "skills-file", "config": {"root": str(root), "version": "1"}}},
        binding_components=[
            {
                "role": "workspace",
                "component_id": "wrong",
                "version": "1",
                "component": {"adapter": "registered-tools", "config": {"names": ["skill_get"]}},
            }
        ],
    )

    async def run():
        with pytest.raises(ValidationError):
            await r.RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert len(allocated) == 1 and allocated[0]._workspace._root_fd is None


@pytest.mark.parametrize("version", ["\u3000", "x" * 257, "\x00"])
def test_invalid_catalog_behavior_version_refuses_before_store(tmp_path, version):
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "skills-file", "config": {"root": "skills", "version": version}}},
    )

    async def run():
        with pytest.raises(ValidationError):
            await r.RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert not (tmp_path / "runs.sqlite").exists()
