import asyncio

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, Scope, SQLiteStore, ToolRegistry
from relf_agent.errors import ValidationError

from .semantic_fixture import Embedding, facts


def test_task_planner_binds_current_facts_query_without_changing_recent_session():
    from relf_agent import MemoryRecallPolicy, RecallQuery, TaskRecallPlanner

    planner = TaskRecallPlanner()
    result = planner.plan(Scope(), "assistant", "session", "vehicle")
    assert result.facts.text == "vehicle" and result.session.text is None and result.max_pages == 1
    with pytest.raises(ValidationError):
        TaskRecallPlanner(MemoryRecallPolicy(max_pages=2))
    with pytest.raises(ValidationError):
        TaskRecallPlanner(MemoryRecallPolicy(facts=RecallQuery(text="constant")))


def test_original_engine_adopts_semantic_fact_and_keeps_authoritative_reference(tmp_path):
    from relf_agent import SemanticMemoryStore, TaskRecallPlanner

    class Provider:
        identity = {"kind": "semantic-reader", "version": "1"}

        async def complete(self, messages, tools):
            assert "automobile servicing" in str(messages)
            return ModelResponse(output="done")

    async def run():
        with SQLiteStore(tmp_path / "runs.sqlite") as store:
            engine = LocalEngine(
                store,
                providers={"default": Provider()},
                tools=ToolRegistry(),
                memory_store=SemanticMemoryStore(facts(), Embedding()),
                recall_planner=TaskRecallPlanner(),
            )
            handle = engine.submit(
                AgentSpec("assistant", "Use recalled evidence"),
                "vehicle",
                command_id="semantic",
                session_id="session",
            )
            done = await engine.drive(handle.run_id)
            assert done.state == "succeeded"
            run = store.run(handle.run_id)
            action = next(a for a in run["actions"] if a["kind"] == "model")
            assert [r["key"] for r in action["memory_references"]][:2] == ["b", "c"]
            engine.close()

    asyncio.run(run())
