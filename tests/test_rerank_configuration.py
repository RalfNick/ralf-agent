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


def declaration():
    return {
        "type": "http",
        "config": {"model": "fixture", "base_url": "http://127.0.0.1:1/v2", "anonymous": True},
    }


def profile(adapter="sqlite-hybrid-rerank-http", **options):
    return RuntimeProfile(
        "rerank",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"knowledge": {"adapter": adapter, "config": {"reranker": declaration(), **options}}},
    )


def test_hash_http_combination_is_explicit_async_lazy_and_owned(tmp_path):
    selected = profile()
    builder = RuntimeBuilder(base_dir=tmp_path)
    with pytest.raises(ValidationError):
        builder.build(selected, tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()

    async def run():
        instance = await builder.abuild(selected, tmp_path / "runs.sqlite")
        ranker = instance.knowledge.retriever.reranker
        assert ranker.identity["protocol"] == "indexed-results-v1" and ranker._client is None
        await instance.aclose()
        assert ranker._closed

    asyncio.run(run())


def test_semantic_profile_reranker_roundtrips_without_changing_original_presets(tmp_path):
    embed = {
        "type": "openai",
        "config": {
            "model": "embed",
            "dimensions": 2,
            "base_url": "http://127.0.0.1:1/v1",
            "anonymous": True,
        },
    }
    plain = recommended_profile("semantic-knowledge", embedding=embed)
    new = recommended_profile("semantic-knowledge", embedding=embed, reranker=declaration())
    assert plain.components["knowledge"]["config"]["reranker"] == "preserve-order"
    assert new.components["knowledge"]["config"]["reranker"] == declaration()
    payload = {
        "schema_version": 1,
        "default": {"name": new.name, "version": new.version},
        "profiles": [
            {
                "name": new.name,
                "version": new.version,
                "providers": new.providers,
                "components": new.components,
            }
        ],
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload))
    assert load_catalog(path).default.identity == new.identity

    async def run():
        instance = await RuntimeBuilder(base_dir=tmp_path).abuild(new, tmp_path / "runs.sqlite")
        ranker = instance.knowledge.retriever.reranker
        embed = instance.knowledge.retriever.retrievers["vector"].embedding
        assert ranker._client is None and embed._client is None
        await instance.aclose()
        assert ranker._closed and embed._closed

    asyncio.run(run())


def test_nested_reranker_toml_decl_is_explicit(tmp_path):
    path = tmp_path / "runtime.toml"
    path.write_text("""schema_version = 1
[default]
name = "rerank"
version = "1"
[[profiles]]
name = "rerank"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.knowledge]
adapter = "sqlite-hybrid-rerank-http"
[profiles.components.knowledge.config.reranker]
type = "http"
[profiles.components.knowledge.config.reranker.config]
model = "fixture"
base_url = "http://127.0.0.1:1/v2"
anonymous = true
""")
    assert load_catalog(path).default.identity == profile().identity


@pytest.mark.parametrize(
    "damage",
    [
        {"type": "unknown", "config": {}},
        {"type": "http", "config": {"model": "m"}},
        {
            "type": "http",
            "config": {
                "model": "m",
                "base_url": "http://localhost/v2",
                "anonymous": True,
                "max_documents": True,
            },
        },
    ],
)
def test_invalid_reranker_config_has_no_database_side_effect(tmp_path, damage):
    selected = profile(reranker=damage)

    async def run():
        with pytest.raises(ValidationError):
            await RuntimeBuilder(base_dir=tmp_path).abuild(selected, tmp_path / "missing.sqlite")
        assert not (tmp_path / "missing.sqlite").exists()

    asyncio.run(run())


def test_pure_knowledge_factory_rejects_http_rerank_before_database(tmp_path):
    with pytest.raises(ValidationError):
        RuntimeBuilder(base_dir=tmp_path).build(
            profile("sqlite-hybrid"), tmp_path / "missing.sqlite"
        )
    assert not (tmp_path / "missing.sqlite").exists()


def test_later_factory_failure_closes_owned_reranker_and_source(tmp_path, monkeypatch):
    from relf_agent import HTTPReranker

    closed = []
    original = HTTPReranker.aclose

    async def close(self):
        await original(self)
        closed.append(self)

    monkeypatch.setattr(HTTPReranker, "aclose", close)
    registry = ComponentRegistry()

    def fails(c, ctx):
        raise ValidationError("later factory failed")

    registry.register("verifier", "fail", fails)
    base = profile()
    selected = RuntimeProfile(
        base.name,
        base.version,
        base.providers,
        {**base.components, "verifier": {"adapter": "fail"}},
    )

    async def run():
        with pytest.raises(ValidationError, match="later factory"):
            await RuntimeBuilder(registry, base_dir=tmp_path).abuild(
                selected, tmp_path / "runs.sqlite"
            )
        assert len(closed) == 1 and closed[0]._closed

    asyncio.run(run())
