"""Completed default H3 data operations must not leave a root quota occupied."""

import asyncio

import relf_agent as r
from relf_agent.governance import DeploymentAdmissionPolicy
from relf_agent.managed_memory import ManagedMemoryPolicy
from relf_agent.types import canonical

from .helpers import ScriptedProvider
from .test_composite_data_context import Provider as ContextProvider
from .test_composite_data_context import agent as context_agent
from .test_composite_data_context import registry as context_tools
from .test_local_parent_completion import Provider as CompletionProvider
from .test_local_parent_completion import policy as completion_policy
from .test_local_parent_completion import spec as completion_spec
from .test_local_parent_completion import tools as completion_tools
from .test_local_session_model_history import FIRST_FINAL, options, spec
from .test_managed_data_context import context

POLICY = DeploymentAdmissionPolicy("h3-business", max_active_root_runs=1)


def assert_next_root_admitted_after_original_operations_end(engine, original_id):
    assert engine.store.local_capacity_holders(engine.scope) == ()
    assert not engine._threads.has_active_for(original_id)
    next_run = engine.submit(r.AgentSpec("next", "Answer"), "next task", command_id="next-submit")
    assert next_run.run_id != original_id
    assert engine.store.local_capacity_holders(engine.scope) == (next_run.run_id,)


def test_completed_default_managed_memory_extraction_releases_original_root(tmp_path):
    memory = r.InMemoryMemory()
    stage = ManagedMemoryPolicy(
        memory, admission=r.MemoryAdmissionPolicy({"value": ("result", "value")})
    )
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "memory.sqlite"),
        providers={"default": ScriptedProvider([r.ModelResponse(output={"value": 7})])},
        tools=r.ToolRegistry(),
        stage_policy=stage,
        admission_policy=POLICY,
    ) as engine:
        original = engine.submit(r.AgentSpec("worker", "Answer"), "q", command_id="s", budget=2)
        result = asyncio.run(engine.drive(original.run_id))
        assert result.state == "succeeded" and result.result == {"value": 7}
        records = engine.memory_stages(original.run_id)
        assert len(records) == 1 and records[0]["status"] == "completed"
        assert all(fact["status"] == "completed" for fact in records[0]["facts"])
        facts = memory.facts(engine.scope, "auto-memory")
        assert len(facts) == 1 and facts[0]["value"]["value"] == 7
        assert engine.store.budget(original.run_id) == {"limit": 2, "held": 0, "spent": 2}
        assert_next_root_admitted_after_original_operations_end(engine, original.run_id)


def test_model_summary_and_durable_large_result_artifact_release_original_root(tmp_path):
    artifacts = r.SQLiteArtifactStore(tmp_path / "artifacts.sqlite")
    provider, reads = ContextProvider(), []
    try:
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "context.sqlite"),
            providers={"default": provider},
            tools=context_tools(reads),
            context_assembler=context(artifacts, mode="model", summary_max_chars=256),
            admission_policy=POLICY,
        ) as engine:
            original = engine.submit(context_agent(), "task", command_id="s", budget=16)
            result = asyncio.run(engine.drive(original.run_id))
            assert result.state == "succeeded" and result.result == "finished"
            assert provider.summaries > 0 and len(reads) == 4
            stages = engine.context_stages(original.run_id)
            assert stages and all(stage["status"] == "completed" for stage in stages)
            run = engine.store.run(original.run_id)
            records = list(run["context_artifacts"].values())
            assert records and all(record["status"] == "verified" for record in records)
            large = next(
                record
                for record in records
                if artifacts.get(
                    engine.scope, r.ArtifactReference.from_dict(record["intent"]["reference"])
                )
                == canonical("BIG" * 4000)
            )
            assert large["dispatched"] is True
            assert engine.store.budget(original.run_id)["held"] == 0
            assert_next_root_admitted_after_original_operations_end(engine, original.run_id)
    finally:
        artifacts.close()


def test_complete_native_session_history_allows_next_turn_under_single_root_quota(tmp_path):
    async def scenario():
        requests, queries = [], []
        with r.LocalEngine(
            r.SQLiteStore(tmp_path / "native.sqlite"),
            **options(requests, queries),
            admission_policy=POLICY,
        ) as engine:
            first = engine.submit(spec(), "first-task", session_id="same", command_id="first")
            assert (await engine.drive(first.run_id)).state == "succeeded"
            first_run = engine.store.run(first.run_id)
            assert first_run["manifest"]["model_history_protocol"] == 2
            assert first_run["native_model_history"]
            assert engine.store.local_capacity_holders(engine.scope) == ()
            second = engine.submit(spec(), "second-task", session_id="same", command_id="second")
            assert engine.store.local_capacity_holders(engine.scope) == (second.run_id,)
            assert (await engine.drive(second.run_id)).state == "succeeded"
            assert len(requests) == 4 and requests[2][4]["content"] == FIRST_FINAL
            assert requests[2][1]["content"] == "first-task"
            assert requests[2][5]["content"] == "second-task"
            assert (
                engine.store.budget(first.run_id)["held"]
                == engine.store.budget(second.run_id)["held"]
                == 0
            )
            assert_next_root_admitted_after_original_operations_end(engine, second.run_id)

    asyncio.run(scenario())


def test_adopted_parent_completion_with_managed_verifier_releases_root_tree(tmp_path):
    provider, effects = CompletionProvider(), []
    with r.LocalEngine(
        r.SQLiteStore(tmp_path / "completion.sqlite"),
        providers={"default": provider},
        tools=completion_tools(effects),
        parent_completion_policies={"business": completion_policy(model=True)},
        admission_policy=POLICY,
    ) as engine:
        original = engine.submit(completion_spec("team"), {"value": 7}, command_id="s", budget=10)
        result = asyncio.run(engine.drive(original.run_id))
        assert result.state == "succeeded" and result.result == {"value": 7}
        run = engine.store.run(original.run_id)
        assert run["parent_completion_stages"]["r0"]["status"] == "adopted"
        children = run["orchestration"]["children"]
        assert [child["role"] for child in children] == ["worker", "verifier"]
        assert all(child["settled"] for child in children)
        assert len(effects) == 1 and engine.store.budget(original.run_id)["held"] == 0
        assert_next_root_admitted_after_original_operations_end(engine, original.run_id)
