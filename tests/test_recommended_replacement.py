import asyncio

import pytest

from relf_agent import (
    AgentSpec,
    ComponentRegistry,
    Document,
    InMemoryKnowledgeStore,
    InMemoryMemory,
    KnowledgeContext,
    LexicalRetriever,
    ModelResponse,
    Runtime,
    RuntimeBuilder,
    recommended_profile,
)
from relf_agent.errors import ValidationError
from relf_agent.types import canonical


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


class ReferenceReader:
    identity = {"kind": "replacement-reference-reader", "version": "1"}

    async def complete(self, messages, tools):
        return ModelResponse(
            output={
                "result": "zh-CN"
                if "preferred language zh-CN" in canonical(messages)
                else "missing"
            }
        )


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize(
    "kind,recall_role,expected_text",
    [
        ("local-basic", "recall_planner", "preferred language"),
        ("semantic-memory", None, "preferred language"),
        ("semantic-memory", "recall_policy", None),
    ],
)
def test_v2_memory_replacement_uses_selected_recall_and_resource_ownership(
    tmp_path, kind, recall_role, expected_text, owned
):
    class Memory(InMemoryMemory):
        def __init__(self):
            super().__init__(backend_id="replacement-memory")
            self.queries = []
            self.closes = 0

        def recall(self, scope, namespace, query):
            self.queries.append((namespace, query.text))
            return super().recall(scope, namespace, query)

        def close(self):
            self.closes += 1

    source = Memory()
    registry = ComponentRegistry()
    registry.register("provider", "reference-reader", lambda c, ctx: ReferenceReader())
    registry.register(
        "memory_store", "replacement", lambda c, ctx: ctx.own(source) if owned else source
    )
    components = {"memory_store": {"adapter": "replacement"}}
    if recall_role is not None:
        components[recall_role] = {
            "adapter": "task-text" if recall_role == "recall_planner" else "bounded-recall"
        }
    profile = recommended_profile(
        kind, version="2", provider={"adapter": "reference-reader"}, components=components
    )

    async def exercise():
        instance = await RuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile, tmp_path / "runs.sqlite"
        )
        async with Runtime(instance, owned=True) as runtime:
            source.put_fact(
                instance.scope,
                "assistant",
                "preference",
                "preferred language zh-CN",
                expected_version=0,
            )
            source.put_fact(
                instance.scope, "assistant", "disk", "unrelated disk snapshot", expected_version=0
            )
            handle = await runtime.submit(
                AgentSpec("assistant", "Answer from available references"),
                "preferred language",
                command_id="language",
            )
            done = await handle.wait(wait_timeout=5)
            assert done.snapshot.state == "succeeded", done.snapshot.error
            assert done.snapshot.result == {"result": "zh-CN"}
            assert source.queries == [("assistant", expected_text)]
            if kind == "semantic-memory":
                saved = instance.stage_policy.memory.facts(instance.scope, "assistant")
                assert len(saved) == 1
                assert saved[0]["value"]["value"] == {"result": "zh-CN"}
        assert source.closes == int(owned)

    try:
        asyncio.run(exercise())
    finally:
        if not owned:
            source.close()


@pytest.mark.parametrize("owned", [False, True])
def test_v2_knowledge_replacement_runs_without_unused_http_embedding(tmp_path, owned):
    class Knowledge(InMemoryKnowledgeStore):
        def __init__(self):
            super().__init__(backend_id="replacement-knowledge")
            self.closes = 0

        def close(self):
            self.closes += 1

    source = Knowledge()
    registry = ComponentRegistry()
    registry.register("provider", "reference-reader", lambda c, ctx: ReferenceReader())

    def knowledge(config, context):
        selected = context.own(source) if owned else source
        return KnowledgeContext(LexicalRetriever(selected), namespace="manuals")

    registry.register("knowledge", "replacement", knowledge)
    profile = recommended_profile(
        "semantic-knowledge",
        version="2",
        provider={"adapter": "reference-reader"},
        components={"knowledge": {"adapter": "replacement"}},
    )

    async def exercise():
        instance = await RuntimeBuilder(registry, base_dir=tmp_path).abuild(
            profile, tmp_path / "runs.sqlite"
        )
        async with Runtime(instance, owned=True) as runtime:
            source.put(
                instance.scope,
                "manuals",
                Document("language", "preferred language zh-CN"),
                expected_version=0,
            )
            handle = await runtime.submit(
                AgentSpec("assistant", "Answer using the manual"),
                "preferred language",
                command_id="language",
            )
            done = await handle.wait(wait_timeout=5)
            assert done.snapshot.state == "succeeded", done.snapshot.error
            assert done.snapshot.result == {"result": "zh-CN"}
        assert source.closes == int(owned)

    try:
        asyncio.run(exercise())
    finally:
        if not owned:
            source.close()


@pytest.mark.parametrize(
    "kind,components",
    [
        ("local-basic", {"recall_planner": {"adapter": "task-text"}}),
        ("semantic-memory", {"memory_store": {"adapter": "sqlite"}}),
        ("semantic-knowledge", {"knowledge": {"adapter": "sqlite-lexical"}}),
    ],
)
def test_v1_keeps_original_replacement_validation(kind, components):
    with pytest.raises(ValidationError):
        recommended_profile(kind, components=components)


@pytest.mark.parametrize("version", ["1", "2"])
def test_explicit_conflicting_recall_roles_are_rejected(version):
    with pytest.raises(ValidationError, match="recall policy or planner"):
        recommended_profile(
            version=version,
            components={
                "recall_policy": {"adapter": "bounded-recall"},
                "recall_planner": {"adapter": "task-text"},
            },
        )


@pytest.mark.parametrize("kind", ["semantic-knowledge", "semantic-memory"])
def test_v2_default_semantic_adapter_still_requires_explicit_embedding(kind):
    with pytest.raises(ValidationError, match="explicit HTTP embedding"):
        recommended_profile(kind, version="2")


@pytest.mark.parametrize(
    "kind,role,adapter",
    [
        ("semantic-knowledge", "knowledge", "sqlite-hybrid-http"),
        ("semantic-memory", "memory_store", "semantic-recall-async"),
    ],
)
def test_v2_replacement_semantic_adapter_missing_embedding_rejects_before_database(
    tmp_path, kind, role, adapter
):
    profile = recommended_profile(
        kind,
        version="2",
        components={role: {"adapter": adapter}},
    )

    async def exercise():
        with pytest.raises(ValidationError):
            await RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "absent.sqlite")
        assert not (tmp_path / "absent.sqlite").exists()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "kind,role,declaration",
    [
        (
            "semantic-knowledge",
            "knowledge",
            {"adapter": "sqlite-hybrid-http", "config": {"embedding": embedding()}},
        ),
        (
            "semantic-memory",
            "memory_store",
            {
                "adapter": "semantic-recall-async",
                "config": {"backend": {"adapter": "sqlite"}, "embedding": embedding()},
            },
        ),
    ],
)
def test_v2_full_semantic_declaration_uses_its_own_embedding_and_closes(
    tmp_path, kind, role, declaration
):
    profile = recommended_profile(kind, version="2", components={role: declaration})

    async def exercise():
        instance = await RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "runs.sqlite")
        provider = (
            instance.memory.embedding
            if kind == "semantic-memory"
            else instance.knowledge.retriever.retrievers["vector"].embedding
        )
        try:
            assert provider._client is None
        finally:
            await instance.aclose()
        assert provider._closed

    asyncio.run(exercise())
