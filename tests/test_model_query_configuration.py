import asyncio
import json

import pytest

from ralf_agent import (
    ComponentRegistry,
    Document,
    ModelResponse,
    RuntimeBuilder,
    RuntimeProfile,
    load_catalog,
    recommended_profile,
)
from ralf_agent.errors import ValidationError
from tests.test_model_query import QueryModel
from tests.test_semantic_configuration import embedding


def declaration(provider="query"):
    return {"type": "model", "config": {"provider": provider}}


def profile(kind="sqlite-lexical-query", config=None, bindings=None):
    return RuntimeProfile(
        "model-query",
        "1",
        {"default": {"adapter": "offline-echo"}, "query": {"adapter": "query-fixture"}},
        {
            "knowledge": {
                "adapter": kind,
                "config": config or {"namespace": "docs", "query_transform": declaration()},
            }
        },
        binding_components=bindings,
    )


def registry(providers):
    result = ComponentRegistry()

    def build(c, ctx):
        value = ctx.own_async(QueryModel()) if ctx._allow_async else QueryModel()
        providers.append(value)
        return value

    result.register("provider", "query-fixture", build)
    return result


def test_named_query_provider_is_shared_without_extra_close_and_queries_real_store(tmp_path):
    async def run():
        providers = []
        instance = await RuntimeBuilder(registry(providers), base_dir=tmp_path).abuild(
            profile(), tmp_path / "runs.sqlite"
        )
        try:
            transform = instance.knowledge.retriever.transform
            assert transform.provider is instance.providers["query"]
            store = instance.knowledge.retriever.retriever.store
            store.put(instance.scope, "docs", Document("a", "automobile"), expected_version=0)
            references = await instance.knowledge.references(instance.scope, "car")
            assert len(references) == 1 and references[0]["value"]["text"] == "automobile"
            assert not providers[0].closed
        finally:
            await instance.aclose()
        assert providers[0].closed and providers[0].close_calls == 1

    asyncio.run(run())


@pytest.mark.parametrize("location", ["top", "knowledge-binding", "facts-binding", "facts-top"])
def test_missing_query_provider_fails_before_execution_database(location, tmp_path):
    query = declaration("missing")
    semantic = {
        "adapter": "semantic-recall-async",
        "config": {
            "backend": {"adapter": "sqlite"},
            "embedding": embedding(),
            "query_transform": query,
        },
    }
    knowledge = {"adapter": "sqlite-lexical-query", "config": {"query_transform": query}}
    bindings = None
    components = {}
    if location == "top":
        components["knowledge"] = knowledge
    elif location == "facts-top":
        components["memory_store"] = semantic
    else:
        role, adapter, backend = (
            ("knowledge", "knowledge-resource", knowledge)
            if location == "knowledge-binding"
            else ("facts", "facts-resource", semantic)
        )
        bindings = [
            {
                "role": role,
                "component_id": "data",
                "version": "1",
                "component": {
                    "adapter": adapter,
                    "config": {
                        "backend": backend,
                        "namespaces": ["docs"],
                        "default_namespace": "docs",
                    },
                },
            }
        ]
    selected = RuntimeProfile(
        "missing",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components,
        binding_components=bindings,
    )
    path = tmp_path / "absent.sqlite"

    async def run():
        with pytest.raises(ValidationError):
            await RuntimeBuilder(base_dir=tmp_path).abuild(selected, path)
        assert not path.exists()

    asyncio.run(run())


def test_unrelated_custom_adapter_query_named_field_is_not_interpreted(tmp_path):
    components = ComponentRegistry()
    from ralf_agent import ContextAssembler

    components.register("context_assembler", "custom", lambda c, ctx: ContextAssembler())
    selected = RuntimeProfile(
        "custom",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "context_assembler": {
                "adapter": "custom",
                "config": {"query_transform": declaration("not-a-real-provider")},
            }
        },
    )
    with RuntimeBuilder(components, base_dir=tmp_path).build(selected, tmp_path / "runs.sqlite"):
        pass


def test_model_query_json_toml_and_semantic_memory_factory_bind_same_provider(tmp_path):
    selected = recommended_profile(
        "semantic-memory", embedding=embedding(), query_transform=declaration()
    )
    selected = RuntimeProfile(
        selected.name,
        selected.version,
        {**selected.providers, "query": {"adapter": "query-fixture"}},
        selected.components,
    )
    values = {
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
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(values))
    assert load_catalog(path).default.identity == selected.identity
    toml = tmp_path / "profile.toml"
    toml.write_text("""schema_version=1
[default]
name="model-query"
version="1"
[[profiles]]
name="model-query"
version="1"
[profiles.providers.default]
adapter="offline-echo"
[profiles.providers.query]
adapter="query-fixture"
[profiles.components.knowledge]
adapter="sqlite-lexical-query"
[profiles.components.knowledge.config]
namespace="docs"
[profiles.components.knowledge.config.query_transform]
type="model"
[profiles.components.knowledge.config.query_transform.config]
provider="query"
""")
    assert load_catalog(toml).default.identity == profile().identity

    async def run():
        providers = []
        runtime = await RuntimeBuilder(registry(providers), base_dir=tmp_path).abuild(
            load_catalog(path).default, tmp_path / "runs.sqlite"
        )
        try:
            assert runtime.memory.transform.provider is runtime.providers["query"]
            assert await runtime.memory.transform.transform("car") == ("car", "automobile")
            assert providers[0].calls == 1
        finally:
            await runtime.aclose()
        assert providers[0].closed and providers[0].close_calls == 1

    asyncio.run(run())


def test_later_factory_failure_releases_original_owned_query_provider(tmp_path):
    providers = []
    entries = registry(providers)

    def failing(c, ctx):
        raise ValidationError("later construction failed")

    entries.register("harness", "broken", failing)
    selected = profile()
    selected = RuntimeProfile(
        selected.name,
        selected.version,
        selected.providers,
        {**selected.components, "harness": {"adapter": "broken"}},
    )

    async def run():
        with pytest.raises(ValidationError):
            await RuntimeBuilder(entries, base_dir=tmp_path).abuild(
                selected, tmp_path / "runs.sqlite"
            )
        assert len(providers) == 1 and providers[0].closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"provider": ""},
        {"provider": "q", "max_queries": True},
        {"provider": "q", "max_queries": 4},
        {"provider": "q", "api_key": "forbidden"},
        {"provider": "q", "instructions": "\ud800"},
    ],
)
def test_invalid_model_query_declaration_preflight(config, tmp_path):
    selected = profile(config={"query_transform": {"type": "model", "config": config}})
    providers = []
    with pytest.raises(ValidationError):
        RuntimeBuilder(registry(providers), base_dir=tmp_path).build(
            selected, tmp_path / "absent.sqlite"
        )
    assert not providers and not (tmp_path / "absent.sqlite").exists()


def test_scoped_knowledge_binding_uses_shared_query_model_and_preserves_namespace(tmp_path):
    from ralf_agent import AgentBindingDescriptor, AgentDefinition, AgentSpec, BindingSelection

    class Reader:
        identity = {"kind": "scoped-query-reader", "version": "1"}

        async def complete(self, messages, tools):
            assert "automobile red" in str(messages) and "automobile blue" not in str(messages)
            return ModelResponse(output="done")

    async def run():
        providers = []
        entries = registry(providers)
        entries.register("provider", "reader", lambda c, ctx: Reader())
        selected = RuntimeProfile(
            "scoped",
            "1",
            {"default": {"adapter": "reader"}, "query": {"adapter": "query-fixture"}},
            binding_components=[
                {
                    "role": "knowledge",
                    "component_id": "docs",
                    "version": "1",
                    "component": {
                        "adapter": "knowledge-resource",
                        "config": {
                            "backend": {
                                "adapter": "sqlite-lexical-query",
                                "config": {"query_transform": declaration()},
                            },
                            "namespaces": ["red", "blue"],
                            "default_namespace": "red",
                        },
                    },
                }
            ],
        )
        runtime = await RuntimeBuilder(entries, base_dir=tmp_path).abuild(
            selected, tmp_path / "runs.sqlite"
        )
        try:
            choice = BindingSelection.ref("docs", "1", selector={"namespace": "red"})
            view, _ = runtime.binding_catalog.resolve("knowledge", choice, runtime.scope)
            store = view.context.retriever.retriever.store
            for namespace in ("red", "blue"):
                store.put(
                    runtime.scope,
                    namespace,
                    Document("guide", "automobile " + namespace),
                    expected_version=0,
                )
            definition = AgentDefinition(
                AgentSpec("reader", "Use evidence"), AgentBindingDescriptor(knowledge=choice)
            )
            handle = runtime.submit(definition, "car", command_id="s")
            result = await runtime.drive(handle.run_id)
            assert result.state == "succeeded", result.error
            assert providers[0].calls == 1
        finally:
            await runtime.aclose()
        assert providers[0].close_calls == 1

    asyncio.run(run())
