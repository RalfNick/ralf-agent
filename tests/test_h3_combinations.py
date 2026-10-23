import asyncio
import copy
import json

import pytest

from relf_agent import AgentSpec, RuntimeBuilder, recommended_profile
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


def test_semantic_profile_requires_explicit_embedding_without_hash_fallback():
    for invalid in (
        None,
        {"type": "hash", "config": {"dimensions": 2}},
        {},
        {"type": "openai", "config": {"model": "fixture"}},
    ):
        with pytest.raises(ValidationError):
            recommended_profile("semantic-knowledge", embedding=invalid)
    config = embedding()
    profile = recommended_profile(
        "semantic-knowledge", embedding=config, knowledge_namespace="manuals"
    )
    config["config"]["model"] = "changed"
    kb = profile.components["knowledge"]
    assert kb["adapter"] == "sqlite-hybrid-http"
    assert kb["config"]["embedding"]["config"]["model"] == "fixture"
    assert kb["config"]["namespace"] == "manuals"
    assert kb["config"]["failure_policy"] == "strict"
    assert profile.components["context_assembler"]["adapter"] == "relevant-data"


def test_semantic_profile_async_only_and_owned_resources_close_without_network(tmp_path):
    profile = recommended_profile("semantic-knowledge", embedding=embedding())
    builder = RuntimeBuilder(base_dir=tmp_path)
    with pytest.raises(ValidationError):
        builder.build(profile, tmp_path / "not-created.sqlite")
    assert not (tmp_path / "not-created.sqlite").exists()

    async def run():
        instance = await builder.abuild(profile, tmp_path / "runs.sqlite")
        provider = instance.knowledge.retriever.retrievers["vector"].embedding
        assert provider._client is None
        await instance.aclose()
        assert provider._closed

    asyncio.run(run())


def test_memory_recall_profile_uses_matching_fact_namespace_and_survives_reconnect(tmp_path):
    profile = recommended_profile("memory-recall", agent_name="helper")
    assert profile.components["stage_policy"]["config"]["namespace"] == "helper"
    assert profile.components["context_assembler"]["adapter"] == "relevant-data"
    builder = RuntimeBuilder(base_dir=tmp_path)

    async def run():
        handle = None
        for _ in range(2):
            runtime = builder.build(profile, tmp_path / "runs.sqlite")
            try:
                actual = runtime.submit(AgentSpec("helper", "Answer"), "language", command_id="s")
                if handle is not None:
                    assert actual == handle
                handle = actual
                assert (await runtime.drive(actual.run_id)).state == "succeeded"
                assert len(runtime.memory.facts(runtime.scope, "helper")) == 1
            finally:
                await runtime.aclose()

    asyncio.run(run())


def test_new_profile_roundtrip_and_original_declarations_stay_identical(tmp_path):
    from relf_agent import load_catalog

    for kind in ("plan-and-execute", "team", "memory-recall", "semantic-knowledge"):
        profile = recommended_profile(
            kind, **({"embedding": embedding()} if kind == "semantic-knowledge" else {})
        )
        payload = {
            "schema_version": 1,
            "default": {"name": profile.name, "version": profile.version},
            "profiles": [
                {
                    "name": profile.name,
                    "version": profile.version,
                    "providers": profile.providers,
                    "components": profile.components,
                }
            ],
        }
        path = tmp_path / "profile.json"
        path.write_text(json.dumps(payload))
        assert load_catalog(path).default.identity == profile.identity
    original = {
        "context_assembler": {"adapter": "managed-data"},
        "recall_policy": {"adapter": "bounded-recall"},
        "verifier": {"adapter": "schema"},
    }
    for kind in ("local-basic", "local-knowledge", "managed-memory"):
        expected = copy.deepcopy(original)
        if kind == "local-knowledge":
            expected["knowledge"] = {"adapter": "sqlite-lexical"}
        if kind == "managed-memory":
            expected["stage_policy"] = {
                "adapter": "sourced-memory",
                "config": {"namespace": "assistant", "fields": {"result": ["result"]}},
            }
        for declaration in expected.values():
            declaration.setdefault("config", {})
        assert recommended_profile(kind).components == expected


def test_memory_combination_routes_relevant_bounded_facts_to_model(tmp_path):
    from relf_agent import ComponentRegistry, ModelResponse
    from relf_agent.types import canonical

    class Evidence:
        identity = {"kind": "recall-evidence-fixture", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output=canonical(messages))

    registry = ComponentRegistry()
    registry.register("provider", "evidence", lambda c, ctx: Evidence())
    profile = recommended_profile("memory-recall", provider={"adapter": "evidence"})

    async def run():
        runtime = RuntimeBuilder(registry, base_dir=tmp_path).build(
            profile, tmp_path / "runs.sqlite"
        )
        try:
            runtime.memory.put_fact(
                runtime.scope, "assistant", "a", "disk snapshot " * 65, expected_version=0
            )
            runtime.memory.put_fact(
                runtime.scope, "assistant", "b", "preferred language zh-CN", expected_version=0
            )
            handle = runtime.submit(
                AgentSpec("assistant", "Answer", max_context_chars=1000),
                "preferred language",
                command_id="s",
            )
            done = await runtime.drive(handle.run_id)
            assert done.state == "succeeded", done.error
            assert "zh-CN" in done.result and "disk snapshot" not in done.result
            assert len(runtime.memory.facts(runtime.scope, "assistant")) == 3
        finally:
            await runtime.aclose()

    asyncio.run(run())


def test_memory_profile_toml_roundtrip(tmp_path):
    from relf_agent import load_catalog

    path = tmp_path / "runtime.toml"
    path.write_text("""schema_version = 1
[default]
name = "ralf.memory-recall"
version = "1"
[[profiles]]
name = "ralf.memory-recall"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.context_assembler]
adapter = "relevant-data"
[profiles.components.recall_policy]
adapter = "bounded-recall"
[profiles.components.verifier]
adapter = "schema"
[profiles.components.stage_policy]
adapter = "sourced-memory"
[profiles.components.stage_policy.config]
namespace = "assistant"
[profiles.components.stage_policy.config.fields]
result = ["result"]
""")
    assert load_catalog(path).default.identity == recommended_profile("memory-recall").identity


def test_invalid_selector_factory_preflight_creates_no_execution_database(tmp_path):
    profile = recommended_profile(
        "memory-recall",
        components={
            "context_assembler": {
                "adapter": "relevant-data",
                "config": {"selector": {"adapter": "overlap", "config": {"max_references": True}}},
            }
        },
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder(base_dir=tmp_path).build(profile, tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()


def test_plan_profile_supports_explicit_managed_model_planner(tmp_path):
    from relf_agent import ComponentRegistry, ModelResponse, recommended_harness

    class Model:
        identity = {"kind": "planner-model-fixture", "version": "1"}

        async def complete(self, messages, tools):
            if messages[0]["content"].startswith("Return a JSON object with steps"):
                assert not tools
                return ModelResponse(
                    output={"steps": [{"id": "chosen", "member": "writer", "input": "chosen task"}]}
                )
            return ModelResponse(output="completed chosen task")

    registry = ComponentRegistry()
    registry.register("provider", "model", lambda c, ctx: Model())
    profile = recommended_profile("plan-and-execute", provider={"adapter": "model"})

    async def run():
        runtime = RuntimeBuilder(registry, base_dir=tmp_path).build(
            profile, tmp_path / "runs.sqlite"
        )
        try:
            handle = runtime.submit(
                recommended_harness("plan-and-execute", planner="model").definition,
                "task",
                command_id="s",
            )
            done = await runtime.drive(handle.run_id)
            assert done.state == "succeeded" and done.result == "completed chosen task"
            children = runtime.diagnostics(handle.run_id).workflow["children"]
            assert len(children) == 2
        finally:
            await runtime.aclose()

    asyncio.run(run())
