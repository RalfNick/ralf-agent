import asyncio

import pytest

from relf_agent import AgentSpec, RuntimeBuilder, RuntimeProfile
from relf_agent.errors import ValidationError


@pytest.mark.parametrize("kind", ["local-basic", "local-knowledge", "managed-memory"])
@pytest.mark.parametrize("assembly", ["sync", "async"])
def test_recommended_profile_is_offline_usable_and_reconnects(tmp_path, kind, assembly):
    from relf_agent.recommended import recommended_profile

    selected = recommended_profile(kind)

    async def run():
        builder = RuntimeBuilder(base_dir=tmp_path)
        instance = (
            builder.build(selected, tmp_path / "runs.db")
            if assembly == "sync"
            else await builder.abuild(selected, tmp_path / "runs.db")
        )
        try:
            h = instance.submit(AgentSpec("assistant", "Answer"), "hello", command_id="s")
            assert (await instance.drive(h.run_id)).state == "succeeded"
            assert instance.context.identity["kind"] == "managed-data-context"
            assert instance.context.artifacts.backend_id.startswith("sqlite-artifacts:")
            if kind == "managed-memory":
                facts = instance.memory.facts(instance.scope, "assistant")
                assert facts[0]["value"]["value"]["echo"] == "hello"
        finally:
            await instance.aclose()
        restored = await builder.abuild(selected, tmp_path / "runs.db")
        try:
            assert restored.submit(AgentSpec("assistant", "Answer"), "hello", command_id="s") == h
            assert (await restored.drive(h.run_id)).state == "succeeded"
        finally:
            await restored.aclose()

    asyncio.run(run())


def test_invalid_data_factory_is_rejected_before_database_creation(tmp_path):
    selected = RuntimeProfile(
        "bad",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "context_assembler": {"adapter": "managed-data", "config": {"preview_chars": True}},
        },
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(selected, tmp_path / "not-created.db")
    assert not (tmp_path / "not-created.db").exists()


def test_unknown_preset_does_not_silently_select_defaults():
    from relf_agent.recommended import recommended_profile

    with pytest.raises(ValidationError):
        recommended_profile("enterprise")


@pytest.mark.parametrize("kind", ["graph", "parallel", "team", "dynamic", "dynamic-dag", "nested"])
@pytest.mark.parametrize("assembly", ["sync", "async"])
def test_managed_memory_preset_advanced_facade_reconnects(tmp_path, kind, assembly):
    from relf_agent import Runtime, recommended_profile
    from tests.test_composite_memory_stages import definition, records

    profile = recommended_profile("managed-memory")
    builder = RuntimeBuilder(base_dir=tmp_path)

    async def run():
        instance = (
            builder.build(profile, tmp_path / "runs.db")
            if assembly == "sync"
            else await builder.abuild(profile, tmp_path / "runs.db")
        )
        async with Runtime(instance, owned=True) as runtime:
            h = await runtime.submit(definition(kind), "hello", command_id="s")
            assert (await h.wait(wait_timeout=5)).snapshot.state == "succeeded"
            assert len(instance.memory.facts(instance.scope, "assistant")) == 2
            assert len(records(instance, h.ref.run_id)) == 2
        instance = await builder.abuild(profile, tmp_path / "runs.db")
        async with Runtime(instance, owned=True) as runtime:
            again = await runtime.submit(definition(kind), "hello", command_id="s")
            assert again.ref == h.ref
            assert (await again.wait(wait_timeout=5)).snapshot.state == "succeeded"
            assert len(instance.memory.facts(instance.scope, "assistant")) == 2
            assert len(records(instance, again.ref.run_id)) == 2

    asyncio.run(run())


def test_async_artifact_factory_can_be_replaced_and_owned_resources_close(tmp_path):
    from relf_agent import ComponentRegistry, InMemoryArtifactStore, recommended_profile

    resources = []

    class AsyncArtifacts:
        def __init__(self):
            self.base = InMemoryArtifactStore(backend_id="custom-artifacts")
            self.identity, self.backend_id = self.base.identity, self.base.backend_id
            self.closed = False

        async def put(self, *args, **kwargs):
            return self.base.put(*args, **kwargs)

        async def get(self, *args, **kwargs):
            return self.base.get(*args, **kwargs)

        async def aclose(self):
            self.closed = True
            self.base.close()

    async def factory(config, ctx):
        resource = ctx.own_async(AsyncArtifacts())
        resources.append(resource)
        return resource

    registry = ComponentRegistry()
    registry.register_async("artifact_store", "custom", factory)
    profile = recommended_profile(
        components={
            "context_assembler": {
                "adapter": "managed-data-async",
                "config": {"artifacts": {"adapter": "custom"}},
            }
        }
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder(registry).build(profile, tmp_path / "absent.db")
    assert not (tmp_path / "absent.db").exists() and resources == []

    async def exercise():
        runtime = await RuntimeBuilder(registry).abuild(profile, tmp_path / "runs.db")
        h = runtime.submit(AgentSpec("assistant", "Answer"), "hello", command_id="s")
        assert (await runtime.drive(h.run_id)).state == "succeeded"
        assert runtime.context.artifacts is resources[0]
        await runtime.aclose()
        assert resources[0].closed

    asyncio.run(exercise())


def test_recommended_profile_roundtrips_json_and_toml(tmp_path):
    import json

    from relf_agent import load_catalog, recommended_profile

    profile = recommended_profile("local-knowledge", version="application-1")
    payload = {
        "name": profile.name,
        "version": profile.version,
        "providers": profile.providers,
        "components": profile.components,
    }
    (tmp_path / "runtime.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default": {"name": profile.name, "version": profile.version},
                "profiles": [payload],
            }
        )
    )
    (tmp_path / "runtime.toml").write_text("""schema_version = 1
[default]
name = "ralf.local-knowledge"
version = "application-1"
[[profiles]]
name = "ralf.local-knowledge"
version = "application-1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.context_assembler]
adapter = "managed-data"
[profiles.components.recall_policy]
adapter = "bounded-recall"
[profiles.components.verifier]
adapter = "schema"
[profiles.components.knowledge]
adapter = "sqlite-lexical"
""")
    for extension in ("json", "toml"):
        assert (
            load_catalog(tmp_path / ("runtime." + extension)).default.identity == profile.identity
        )
