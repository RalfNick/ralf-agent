import json

import pytest

from ralf_agent import AgentSpec, ComponentRegistry, RuntimeBuilder, RuntimeProfile, load_spec
from ralf_agent.errors import ValidationError


def test_public_sdk_exports_all_new_layers():
    import ralf_agent

    names = [
        "RedisMemory",
        "PostgresMemory",
        "PostgresKnowledgeStore",
        "QdrantVectorIndex",
        "HashEmbeddingProvider",
        "TeamSpec",
        "DynamicWorkflowSpec",
        "TeamStrategy",
        "AgentCaller",
        "SequentialTeam",
        "RouterTeam",
        "SupervisorTeam",
        "Planner",
        "PlanVerifier",
        "RulePlanner",
        "ModelPlanner",
        "PlanProposal",
        "PlanStep",
        "Verification",
    ]
    for name in names:
        assert name in ralf_agent.__all__, f"Missing public API {name}"
        assert getattr(ralf_agent, name)


@pytest.mark.parametrize("kind", ["team", "dynamic"])
def test_json_definition_round_trip_keeps_member_order(tmp_path, kind):
    from ralf_agent.orchestration_types import DynamicWorkflowSpec, TeamSpec

    cls = TeamSpec if kind == "team" else DynamicWorkflowSpec
    spec = cls("app", {"z": AgentSpec("z", "Z"), "a": AgentSpec("a", "A")})
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec.to_dict()))
    assert load_spec(path).to_dict() == spec.to_dict()


def test_default_registered_orchestration_components_run(tmp_path):
    from ralf_agent.orchestration_types import DynamicWorkflowSpec

    selected = RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={
            "planners": {"adapter": "rule"},
            "plan_verifiers": {"adapter": "complete"},
            "team_strategies": {"adapter": "defaults"},
        },
    )
    import asyncio

    with RuntimeBuilder().build(selected, tmp_path / "app.sqlite") as runtime:
        h = runtime.submit(
            DynamicWorkflowSpec("app", {"one": AgentSpec("one", "One")}), "task", command_id="s"
        )
        assert asyncio.run(runtime.drive(h.run_id)).state == "succeeded"


@pytest.mark.parametrize(
    "kind,adapter,config",
    [
        ("session_store", "redis", {"url_env": "RALF_MISSING_REDIS", "backend_id": "test-redis"}),
        ("memory_store", "postgres", {"dsn_env": "RALF_MISSING_POSTGRES", "backend_id": "test-pg"}),
        (
            "knowledge",
            "postgres-lexical",
            {"dsn_env": "RALF_MISSING_POSTGRES", "backend_id": "test-kb"},
        ),
    ],
)
def test_remote_factory_requires_explicit_env_before_allocating_authority(
    tmp_path, kind, adapter, config, monkeypatch
):
    for key in ("RALF_MISSING_REDIS", "RALF_MISSING_POSTGRES"):
        monkeypatch.delenv(key, raising=False)
    registry = ComponentRegistry()
    assert (kind, adapter) in registry._factories, "Missing remote factory"
    selected = RuntimeProfile(
        "remote",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={kind: {"adapter": adapter, "config": config}},
    )
    path = tmp_path / "missing.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder(registry).build(selected, path)
    assert not path.exists()


def test_default_hash_embedding_is_explicit_deterministic_and_local():
    import asyncio

    from ralf_agent import HashEmbeddingProvider

    embedding = HashEmbeddingProvider(dimensions=16)
    vectors = asyncio.run(embedding.embed(["Redis 数据库", "Redis 数据库", ""]))
    assert vectors[0] == vectors[1]
    assert len(vectors[0]) == 16 and len(vectors[2]) == 16
    assert abs(sum(v * v for v in vectors[0]) - 1) < 1e-9
