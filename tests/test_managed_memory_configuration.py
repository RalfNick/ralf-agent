import asyncio
import json

import pytest

import relf_agent as r
from relf_agent.errors import ValidationError


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("extension", ["json", "toml"])
def test_configured_default_stage_and_persistent_source(tmp_path, mode, extension):
    declaration = {
        "schema_version": 1,
        "default": {"name": "app", "version": "1"},
        "profiles": [
            {
                "name": "app",
                "version": "1",
                "providers": {"default": {"adapter": "offline-echo"}},
                "components": {
                    "stage_policy": {
                        "adapter": "sourced-memory",
                        "config": {
                            "fields": {"echo": ["result", "echo"]},
                            "namespace": "observations",
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
        else """schema_version = 1
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.stage_policy]
adapter = "sourced-memory"
[profiles.components.stage_policy.config]
namespace = "observations"
[profiles.components.stage_policy.config.fields]
echo = ["result", "echo"]
"""
    )
    profile = r.load_catalog(path).default

    async def run():
        runtime = (
            r.Runtime.from_profile(profile, tmp_path / "run.sqlite")
            if mode == "sync"
            else await r.Runtime.afrom_profile(profile, tmp_path / "run.sqlite")
        )
        async with runtime:
            task = await runtime.create_agent(r.AgentSpec("a", "Answer")).submit(
                "hello", command_id="s"
            )
            assert (await task.wait(wait_timeout=1)).snapshot.state == "succeeded"
            stages = await task.memory_stages()
            assert stages[0]["status"] == "completed"
            assert stages[0]["facts"][0]["value"]["value"] == "hello"
            assert runtime._local.memory.facts(runtime.scope, "observations")[0]["version"] == 1

    asyncio.run(run())


def test_stage_factory_explicit_backend_and_binding(tmp_path):
    registry = r.ComponentRegistry()
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        binding_components=[
            {
                "role": "stage_policy",
                "component_id": "memory",
                "version": "1",
                "component": {
                    "adapter": "sourced-memory",
                    "config": {
                        "memory": {"adapter": "in-memory", "config": {"backend_id": "write-facts"}}
                    },
                },
            }
        ],
    )
    with r.RuntimeBuilder(registry).build(profile, tmp_path / "run.sqlite") as built:
        definition = r.AgentDefinition(
            r.AgentSpec("a", "Answer"),
            r.AgentBindingDescriptor(stage_policy=r.BindingSelection.ref("memory", "1")),
        )
        h = built.submit(definition, "q", command_id="s")
        assert asyncio.run(built.drive(h.run_id)).state == "succeeded"
        assert built.memory_stages(h.run_id)[0]["policy"]["backend_id"] == "write-facts"


def test_async_stage_target_cleanup_and_sync_build_refusal(tmp_path):
    registry = r.ComponentRegistry()
    owned = []

    class Memory(r.InMemoryMemory):
        closed = False

        async def aclose(self):
            self.closed = True

    async def construct(config, context):
        memory = Memory(backend_id="async-owned-target")
        owned.append(memory)
        return context.own_async(memory)

    registry.register_async("memory_store", "fixture", construct)
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "stage_policy": {
                "adapter": "sourced-memory-async",
                "config": {"memory": {"adapter": "fixture"}},
            }
        },
    )
    builder = r.RuntimeBuilder(registry)
    with pytest.raises(ValidationError):
        builder.build(profile, tmp_path / "sync.sqlite")
    assert owned == []

    async def run():
        async with await builder.abuild(profile, tmp_path / "async.sqlite") as built:
            h = built.submit(r.AgentSpec("a", "Answer"), "q", command_id="s")
            assert (await built.drive(h.run_id)).state == "succeeded"
        assert owned[0].closed

    asyncio.run(run())
