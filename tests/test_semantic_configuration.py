import asyncio
import json

import pytest

from relf_agent import (
    ComponentRegistry,
    RuntimeBuilder,
    RuntimeProfile,
    load_catalog,
    recommended_profile,
)
from relf_agent.errors import ValidationError


def embedding():
    return {
        "type": "openai",
        "config": {
            "model": "fixture",
            "dimensions": 2,
            "base_url": "http://127.0.0.1:1/v1",
            "anonymous": True,
        },
    }


def transform():
    return {"type": "aliases", "config": {"aliases": {"car": "automobile"}}}


def profile(config=None):
    return RuntimeProfile(
        "semantic",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "memory_store": {
                "adapter": "semantic-recall-async",
                "config": config
                or {
                    "backend": {"adapter": "sqlite"},
                    "embedding": embedding(),
                    "query_transform": transform(),
                },
            },
            "recall_planner": {"adapter": "task-text"},
        },
    )


def test_semantic_memory_profile_is_explicit_async_owned_and_roundtrips(tmp_path):
    selected = recommended_profile(
        "semantic-memory", embedding=embedding(), query_transform=transform()
    )
    assert "recall_policy" not in selected.components
    assert selected.components["recall_planner"]["adapter"] == "task-text"
    assert selected.components["context_assembler"]["config"]["selector"]["adapter"] == "ordered"
    builder = RuntimeBuilder(base_dir=tmp_path)
    with pytest.raises(ValidationError):
        builder.build(selected, tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()
    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default": {"name": selected.name, "version": selected.version},
                "profiles": [
                    {
                        "name": selected.name,
                        "version": selected.version,
                        "providers": selected.providers,
                        "components": selected.components,
                    }
                ],
            }
        )
    )
    assert load_catalog(config).default.identity == selected.identity

    async def run():
        instance = await builder.abuild(selected, tmp_path / "runs.sqlite")
        memory = instance.memory
        provider = memory.embedding
        assert provider._client is None
        assert memory.transform.transform("car") == ("car", "automobile")
        await instance.aclose()
        assert provider._closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "damage",
    [
        {"backend": {"adapter": "semantic-recall-async"}, "embedding": embedding()},
        {"backend": {"adapter": "facts-resource"}, "embedding": embedding()},
        {"backend": {"adapter": "sqlite"}, "embedding": {"type": "hash", "config": {}}},
        {
            "backend": {"adapter": "sqlite"},
            "embedding": embedding(),
            "query_transform": {"type": "aliases", "config": {"aliases": {"": "bad"}}},
        },
    ],
)
def test_invalid_semantic_config_rejects_before_storage(tmp_path, damage):
    async def run():
        with pytest.raises(ValidationError):
            await RuntimeBuilder().abuild(profile(damage), tmp_path / "missing.sqlite")
        assert not (tmp_path / "missing.sqlite").exists()

    asyncio.run(run())


def test_query_knowledge_composes_original_hybrid_and_lexical_without_default_changes(tmp_path):
    plain = recommended_profile("semantic-knowledge", embedding=embedding())
    selected = recommended_profile(
        "semantic-knowledge", embedding=embedding(), query_transform=transform()
    )
    assert "query_transform" not in plain.components["knowledge"]["config"]
    assert selected.components["knowledge"]["config"]["query_transform"] == transform()
    profile = RuntimeProfile(
        "queries",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "knowledge": {
                "adapter": "sqlite-lexical-query",
                "config": {"namespace": "manuals", "query_transform": transform()},
            }
        },
    )
    with RuntimeBuilder(base_dir=tmp_path).build(profile, tmp_path / "runs.sqlite") as instance:
        from relf_agent import Document

        wrapper = instance.knowledge.retriever
        store = wrapper.retriever.store
        store.put(instance.scope, "manuals", Document("guide", "automobile"), expected_version=0)
        refs = asyncio.run(instance.knowledge.references(instance.scope, "car"))
        assert len(refs) == 1 and refs[0]["value"]["text"] == "automobile"


def test_later_factory_failure_releases_owned_embedding(tmp_path, monkeypatch):
    from relf_agent.semantic_embedding import ManagedEmbeddingProvider

    closed = []
    original = ManagedEmbeddingProvider.aclose

    async def close(self):
        await original(self)
        closed.append(self._closed)

    monkeypatch.setattr(ManagedEmbeddingProvider, "aclose", close)
    registry = ComponentRegistry()

    def fail(config, context):
        raise RuntimeError("later factory failed")

    registry.register("planners", "fail", fail)
    selected = profile()
    selected = RuntimeProfile(
        selected.name,
        selected.version,
        selected.providers,
        {**selected.components, "planners": {"adapter": "fail"}},
    )

    async def run():
        with pytest.raises(ValidationError):
            await RuntimeBuilder(registry=registry).abuild(selected, tmp_path / "runs.sqlite")
        assert closed == [True]

    asyncio.run(run())


def test_semantic_credential_reference_is_resolved_only_for_explicit_adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SEMANTIC_KEY", "fixture-key")
    selected = embedding()
    selected["config"].pop("anonymous")
    selected["config"]["api_key_env"] = "APP_SEMANTIC_KEY"

    async def run():
        instance = await RuntimeBuilder().abuild(
            profile({"backend": {"adapter": "sqlite"}, "embedding": selected}),
            tmp_path / "runs.sqlite",
        )
        try:
            provider = instance.memory.embedding
            assert provider._api_key == "fixture-key" and provider._client is None
            assert "fixture-key" not in json.dumps(instance.memory.identity)
        finally:
            await instance.aclose()

    asyncio.run(run())


def test_toml_nested_semantic_and_query_declarations_roundtrip(tmp_path):
    path = tmp_path / "runtime.toml"
    path.write_text("""schema_version=1
[default]
name="semantic"
version="1"
[[profiles]]
name="semantic"
version="1"
[profiles.providers.default]
adapter="offline-echo"
[profiles.components.recall_planner]
adapter="task-text"
[profiles.components.memory_store]
adapter="semantic-recall-async"
[profiles.components.memory_store.config.backend]
adapter="sqlite"
[profiles.components.memory_store.config.embedding]
type="openai"
[profiles.components.memory_store.config.embedding.config]
model="fixture"
dimensions=2
base_url="http://127.0.0.1:1/v1"
anonymous=true
[profiles.components.memory_store.config.query_transform]
type="aliases"
[profiles.components.memory_store.config.query_transform.config.aliases]
car="automobile"
""")
    assert load_catalog(path).default.identity == profile().identity

    async def run():
        instance = await RuntimeBuilder().abuild(
            load_catalog(path).default, tmp_path / "runs.sqlite"
        )
        assert instance.memory.transform.transform("car") == ("car", "automobile")
        await instance.aclose()

    asyncio.run(run())


def test_semantic_reference_order_is_not_overwritten_by_lexical_overlap():
    from relf_agent import InMemoryArtifactStore, OrderedReferenceSelector, RelevantDataContext

    context = RelevantDataContext(InMemoryArtifactStore(), selector=OrderedReferenceSelector())
    history = [{"role": "system", "content": "Answer"}, {"role": "user", "content": "car"}]
    references = [
        {"key": "best", "value": "automobile servicing", "version": 1, "expires_at": None},
        {"key": "noise", "value": "car misleading", "version": 1, "expires_at": None},
        {"session": [{"role": "assistant", "task": "before", "content": "previous"}]},
    ]
    messages, manifest = context.assemble(history, references, 12000)
    assert manifest["reference_selection"]["indices"] == [2, 0, 1]
    assert str(messages).index("automobile servicing") < str(messages).index("car misleading")
