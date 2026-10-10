import asyncio
import json

import pytest

import ralf_agent as r
from ralf_agent.errors import ValidationError
from tests.test_memory_selection import Provider


@pytest.mark.parametrize("assembly", ["sync", "async"])
@pytest.mark.parametrize("extension", ["json", "toml"])
def test_model_memory_factory_and_profile_recovery(tmp_path, assembly, extension):
    declaration = {
        "schema_version": 1,
        "default": {"name": "app", "version": "1"},
        "profiles": [
            {
                "name": "app",
                "version": "1",
                "providers": {"default": {"adapter": "fixture"}},
                "components": {
                    "stage_policy": {
                        "adapter": "sourced-memory",
                        "config": {
                            "mode": "model",
                            "fields": {"name": ["result", "name"]},
                            "provider": "default",
                        },
                    }
                },
            }
        ],
    }
    path = tmp_path / ("runtime." + extension)
    path.write_text(
        json.dumps(declaration)
        if extension == "json"
        else """schema_version=1
[default]
name="app"
version="1"
[[profiles]]
name="app"
version="1"
[profiles.providers.default]
adapter="fixture"
[profiles.components.stage_policy]
adapter="sourced-memory"
[profiles.components.stage_policy.config]
mode="model"
provider="default"
[profiles.components.stage_policy.config.fields]
name=["result","name"]
"""
    )
    registry = r.ComponentRegistry()
    registry.register("provider", "fixture", lambda c, ctx: Provider())
    profile = r.load_catalog(path).default

    async def exercise():
        builder = r.RuntimeBuilder(registry)
        built = (
            builder.build(profile, tmp_path / "run.sqlite")
            if assembly == "sync"
            else await builder.abuild(profile, tmp_path / "run.sqlite")
        )
        async with r.Runtime(built, owned=True) as runtime:
            task = await runtime.create_agent(r.AgentSpec("a", "Answer")).submit(
                "q", command_id="s"
            )
            assert (await task.wait(wait_timeout=2)).snapshot.state == "succeeded"
            assert (await task.memory_stages())[0]["selection"]["keys"] == ["name"]
            run_id = task.ref.run_id
            receipt = task.receipt
        built = await builder.abuild(profile, tmp_path / "run.sqlite")
        async with r.Runtime(built, owned=True) as runtime:
            task = await runtime.create_agent(r.AgentSpec("a", "Answer")).submit(
                "q", command_id="s"
            )
            assert task.ref.run_id == run_id and task.receipt == receipt
            await task.wait(wait_timeout=2)
            assert (
                built.providers["default"].business == 0
                and built.providers["default"].selectors == 0
            )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "config",
    [
        {"mode": "unknown"},
        {"mode": "rule", "provider": "default"},
        {"mode": "model", "max_context_chars": 100000000},
    ],
)
def test_invalid_selection_factory_fails_before_store(tmp_path, config):
    p = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"stage_policy": {"adapter": "sourced-memory", "config": config}},
    )
    path = tmp_path / "absent.sqlite"
    with pytest.raises(ValidationError):
        r.RuntimeBuilder().build(p, path)
    assert not path.exists()


def test_model_policy_export_and_async_factory(tmp_path):
    assert r.ManagedModelMemoryPolicy
    p = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "fixture"}},
        {
            "stage_policy": {
                "adapter": "sourced-memory-async",
                "config": {"mode": "model", "fields": {"name": ["result", "name"]}},
            }
        },
    )
    registry = r.ComponentRegistry()
    registry.register("provider", "fixture", lambda c, ctx: Provider())

    async def exercise():
        built = await r.RuntimeBuilder(registry).abuild(p, tmp_path / "run.sqlite")
        async with r.Runtime(built, owned=True) as runtime:
            task = await runtime.create_agent(r.AgentSpec("a", "Answer")).submit(
                "q", command_id="s"
            )
            assert (await task.wait(wait_timeout=2)).snapshot.state == "succeeded"
            assert (await task.memory_stages())[0]["selection"]["status"] == "completed"

    asyncio.run(exercise())
