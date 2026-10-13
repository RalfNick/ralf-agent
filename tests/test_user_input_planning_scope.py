"""Planner clarifications belong to its original question owner, not all children."""

import asyncio
import json

import pytest

from ralf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    LocalEngine,
    ModelResponse,
    PlanProposal,
    PlanStep,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    UserInputPolicy,
    register_user_input,
)
from ralf_agent.dag_planning import DAGNode, DAGProposal, PlanningConclusion
from ralf_agent.workflow import Literal, ValueRef


class ChildQuestionProvider:
    identity = {"kind": "planner-clarification-scope-provider", "version": "1"}

    async def complete(self, messages, tools):
        replies = [message for message in messages if message["role"] == "tool"]
        if replies:
            return ModelResponse(output={"selected": json.loads(replies[-1]["content"])})
        return ModelResponse(
            tool_calls=(ToolCall("request_input", {"prompt": "Select this child"}, "ask"),)
        )


class ManyChildrenPlanner:
    identity = {"kind": "planner-clarification-scope", "version": "1"}

    def __init__(self, mode, parent_question):
        self.mode, self.parent_question = mode, parent_question

    async def plan(self, request, caller):
        if self.parent_question and not getattr(request, "clarifications", None):
            return PlanningConclusion("needs_input", "Which parent target?")
        if self.mode == "flat":
            return PlanProposal([PlanStep(f"c{index}", "worker", {}) for index in range(33)])
        return DAGProposal(
            [DAGNode(f"c{index}", "worker", input=Literal({})) for index in range(33)],
            output=ValueRef("c32"),
        )


@pytest.mark.parametrize("mode", ["flat", "dag"])
@pytest.mark.parametrize("parent_question", [False, True])
def test_legal_child_answers_do_not_consume_planner_clarification_capacity(
    tmp_path, mode, parent_question
):
    async def run():
        tools = ToolRegistry()
        register_user_input(tools)
        with LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": ChildQuestionProvider()},
            tools=tools,
            planners={"many": ManyChildrenPlanner(mode, parent_question)},
            user_input_policies={"ask": UserInputPolicy()},
        ) as engine:
            spec = DynamicWorkflowSpec(
                "plan",
                {"worker": AgentSpec("worker", "Ask once", ("request_input",))},
                planner="many",
                plan_mode=mode,
                max_steps=33,
                max_revisions=2,
                child_budget=4,
                input_policy="ask" if parent_question else None,
            )
            root = engine.submit(spec, "original task", command_id="submit", budget=200).run_id
            if parent_question:
                assert (await engine.drive(root)).state == "waiting_input"
                pending = engine.status(root).pending[0]
                assert (
                    engine.send_input(
                        root,
                        pending["pending_id"],
                        pending["target_digest"],
                        "parent target",
                        command_id="parent-answer",
                    ).apply_state
                    == "applied"
                )
            for index in range(33):
                assert (await engine.drive(root)).state == "waiting_input"
                flow = engine.diagnostics(root).workflow
                child = next(call for call in flow["children"] if call["state"] == "waiting_input")
                pending = engine.status(child["run_id"]).pending[0]
                assert (
                    engine.send_input(
                        child["run_id"],
                        pending["pending_id"],
                        pending["target_digest"],
                        f"child-{index}",
                        command_id=f"answer-{index}",
                    ).apply_state
                    == "applied"
                )
            result = await engine.drive(root)
            assert result.state == "succeeded", result.error
            assert result.result == {"selected": "child-32"}
            original = engine.store.run(root)
            assert original["input"] == "original task"
            assert (
                sum(
                    child["state"] == "succeeded" for child in original["orchestration"]["children"]
                )
                == 33
            )
            request = engine._orchestration._request(original).to_dict()
            if parent_question:
                assert len(request["clarifications"]) == 1
                assert request["clarifications"][0]["request"]["owner"]["run_id"] == root
                assert request["clarifications"][0]["value"] == "parent target"
            else:
                assert "clarifications" not in request
            assert engine.store.budget(root) == {"limit": 200, "spent": 66, "held": 0}
            for child in original["orchestration"]["children"]:
                record = next(iter(engine.store.run(child["run_id"])["input_requests"].values()))
                assert record["state"] == "answered"
                assert record["request"]["owner"]["run_id"] == child["run_id"]

    asyncio.run(run())
