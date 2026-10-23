import asyncio
import json

import pytest

from relf_agent import AgentSpec, RuntimeBuilder, load_catalog
from relf_agent.errors import ValidationError
from tests.test_context_preparation import Provider, spec, tools


@pytest.mark.parametrize("extension", ["json", "toml"])
@pytest.mark.parametrize("assembly", ["sync", "async"])
def test_managed_context_factory_and_original_profile_recovery(tmp_path, extension, assembly):
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
                            "providers": {"default": {"adapter": "fixture"}},
                            "components": {
                                "tools": {"adapter": "fixture"},
                                "context_assembler": {
                                    "adapter": "managed-summary",
                                    "config": {
                                        "mode": "model",
                                        "counter": "utf8-estimate",
                                        "max_units": 10000,
                                    },
                                },
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
adapter = "fixture"
[profiles.components.tools]
adapter = "fixture"
[profiles.components.context_assembler]
adapter = "managed-summary"
[profiles.components.context_assembler.config]
mode = "model"
counter = "utf8-estimate"
max_units = 10000
""")
    from relf_agent import ComponentRegistry

    registry = ComponentRegistry()
    registry.register("provider", "fixture", lambda c, ctx: Provider())
    registry.register("tools", "fixture", lambda c, ctx: tools())
    catalog = load_catalog(path)

    async def exercise():
        builder = RuntimeBuilder(registry, base_dir=tmp_path)
        runtime = (
            builder.build(catalog.default, tmp_path / "runs.sqlite")
            if assembly == "sync"
            else await builder.abuild(catalog.default, tmp_path / "runs.sqlite")
        )
        try:
            handle = runtime.submit(spec(), "q", command_id="s")
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
            stages = runtime.context_stages(handle.run_id)
            assert stages[0]["status"] == "completed"
            original = runtime.diagnostics(handle.run_id).manifest
            assert (
                runtime.context.identity["assembler"]["counter"]["identity"]["kind"]
                == "utf8-token-estimate"
            )
        finally:
            await runtime.aclose()
        restored = await builder.abuild(
            catalog.resolve(original["runtime_profile"]), tmp_path / "runs.sqlite"
        )
        try:
            assert restored.submit(spec(), "q", command_id="s") == handle
            assert (await restored.drive(handle.run_id)).state == "succeeded"
        finally:
            await restored.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "config",
    [
        {"unknown": 1},
        {"mode": "hidden"},
        {"timeout": True},
        {"counter": "unknown"},
        {"max_units": True},
    ],
)
def test_invalid_factory_is_rejected_before_store_creation(tmp_path, config):
    from relf_agent import RuntimeProfile

    selected = RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"context_assembler": {"adapter": "managed-summary", "config": config}},
    )
    db = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(selected, db)
    assert not db.exists()


def test_export_is_additive_and_default_factory_has_no_extra_model_io(tmp_path):
    from relf_agent import ManagedContextPipeline, RuntimeProfile

    assert ManagedContextPipeline().identity["mode"] == "excerpt"
    p = RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"context_assembler": {"adapter": "managed-summary"}},
    )
    with RuntimeBuilder().build(p, tmp_path / "run.sqlite") as runtime:
        h = runtime.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.context_stages(h.run_id) == []


def test_sdk_version_matches_package_declaration():
    import tomllib
    from pathlib import Path

    from relf_agent import __version__

    assert (
        __version__
        == tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"][
            "version"
        ]
    )
