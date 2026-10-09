import asyncio
import importlib.util

import pytest

from ralf_agent import AgentSpec

from .test_orchestration import make_engine


def api():
    assert importlib.util.find_spec("ralf_agent.planning"), "Missing managed planning subsystem"
    from ralf_agent.orchestration_types import DynamicWorkflowSpec
    from ralf_agent.planning import PlanProposal, PlanStep, RulePlanner, Verification

    return DynamicWorkflowSpec, PlanProposal, PlanStep, RulePlanner, Verification


def test_rule_plan_creates_saved_revision_and_executes(tmp_path):
    Spec, *_ = api()
    spec = Spec(
        "plan", {"one": AgentSpec("one", "One"), "two": AgentSpec("two", "Two")}, child_budget=3
    )
    with make_engine(tmp_path / "plan.sqlite") as e:
        h = e.submit(spec, "task", command_id="s", budget=6)
        result = asyncio.run(e.drive(h.run_id))
        assert result.state == "succeeded"
        info = e.diagnostics(h.run_id).workflow
        assert len(info["revisions"]) == 1
        assert len(info["children"]) == 2
        assert e.diagnostics(h.run_id).budget["spent"] == 2
        assert any(event.kind == "plan_proposal_received" for event in e.events(h.run_id))
        assert any(event.kind == "plan_revision_adopted" for event in e.events(h.run_id))


def test_custom_planner_and_verifier_bounded_replanning(tmp_path):
    Spec, Proposal, Step, _, Verification = api()

    class Planner:
        identity = {"kind": "test-planner", "version": "1"}
        calls = 0

        async def plan(self, request, caller):
            self.calls += 1
            return Proposal([Step("work", "one", {"revision": request.revision})])

    class Verifier:
        identity = {"kind": "test-verifier", "version": "1"}

        def verify(self, request):
            return (
                Verification("replan")
                if request.revision == 0
                else Verification("succeeded", request.results[-1]["result"])
            )

    planner = Planner()
    spec = Spec(
        "repair",
        {"one": AgentSpec("one", "One")},
        planner="custom",
        verifier="custom",
        child_budget=3,
    )
    with make_engine(
        tmp_path / "repair.sqlite",
        planners={"custom": planner},
        plan_verifiers={"custom": Verifier()},
    ) as e:
        h = e.submit(spec, "task", command_id="s", budget=6)
        result = asyncio.run(e.drive(h.run_id))
        assert result.state == "succeeded" and planner.calls == 2
        assert len(e.diagnostics(h.run_id).workflow["revisions"]) == 2
        assert e.diagnostics(h.run_id).budget["spent"] == 2


def test_planner_cannot_call_unregistered_member(tmp_path):
    Spec, Proposal, Step, *_ = api()

    class Planner:
        identity = {"kind": "bad-planner", "version": "1"}

        async def plan(self, request, caller):
            return Proposal([Step("bad", "forbidden", "task")])

    with make_engine(tmp_path / "bad.sqlite", planners={"bad": Planner()}) as e:
        spec = Spec("bad", {"one": AgentSpec("one", "One")}, planner="bad")
        h = e.submit(spec, "task", command_id="s", budget=8)
        result = asyncio.run(e.drive(h.run_id))
        assert result.state == "failed" and result.error["code"] == "validation_error"
        assert e.diagnostics(h.run_id).workflow["children"] == []


def test_model_planner_runs_as_a_tool_free_budgeted_child(tmp_path):
    from ralf_agent import ModelResponse, ToolRegistry
    from ralf_agent.planning import ModelPlanner

    from .helpers import ScriptedProvider
    from .test_engine import engine

    Spec, *_ = api()
    provider = ScriptedProvider(
        [
            ModelResponse(
                output={"steps": [{"id": "answer", "member": "one", "input": "planned"}]}
            ),
            ModelResponse(output="answer"),
        ]
    )
    with engine(
        tmp_path / "model-plan.sqlite", provider, ToolRegistry(), planners={"model": ModelPlanner()}
    ) as e:
        h = e.submit(
            Spec("model", {"one": AgentSpec("one", "One")}, planner="model", child_budget=3),
            "task",
            command_id="s",
            budget=6,
        )
        result = asyncio.run(e.drive(h.run_id))
        assert result.state == "succeeded" and result.result == "answer"
        assert provider.calls == 2
        children = e.diagnostics(h.run_id).workflow["children"]
        assert [c["member"] for c in children] == ["@planner", "one"]
        assert e.store.run(children[0]["run_id"])["definition"]["steps"][0]["tools"] == []
        assert e.diagnostics(h.run_id).budget["spent"] == 2


def test_replanning_stops_at_revision_limit(tmp_path):
    Spec, _, _, _, Verification = api()

    class Verifier:
        identity = {"kind": "again", "version": "1"}

        def verify(self, request):
            return Verification("replan")

    with make_engine(tmp_path / "limit.sqlite", plan_verifiers={"again": Verifier()}) as e:
        spec = Spec(
            "limit",
            {"one": AgentSpec("one", "One")},
            verifier="again",
            max_revisions=2,
            child_budget=3,
        )
        h = e.submit(spec, "task", command_id="s", budget=6)
        result = asyncio.run(e.drive(h.run_id))
        assert result.state == "failed" and result.error["code"] == "plan_revision_limit"
        assert len(e.diagnostics(h.run_id).workflow["revisions"]) == 2


def test_planner_caller_cannot_execute_worker_before_proposal(tmp_path):
    Spec, *_ = api()

    class Planner:
        identity = {"kind": "improper", "version": "1"}

        async def plan(self, request, caller):
            await caller.call("hidden", "one", "task")

    with make_engine(tmp_path / "hidden.sqlite", planners={"bad": Planner()}) as e:
        h = e.submit(
            Spec("hidden", {"one": AgentSpec("one", "One")}, planner="bad"), "task", command_id="s"
        )
        assert asyncio.run(e.drive(h.run_id)).state == "failed"
        assert e.diagnostics(h.run_id).workflow["children"] == []


def test_model_plan_worker_id_cannot_collide_with_planning_call(tmp_path):
    from ralf_agent import ModelResponse, ToolRegistry
    from ralf_agent.planning import ModelPlanner

    from .helpers import ScriptedProvider
    from .test_engine import engine

    Spec, *_ = api()
    provider = ScriptedProvider(
        [
            ModelResponse(output={"steps": [{"id": "planner", "member": "one", "input": "task"}]}),
            ModelResponse(output="done"),
        ]
    )
    with engine(
        tmp_path / "collision.sqlite", provider, ToolRegistry(), planners={"model": ModelPlanner()}
    ) as e:
        h = e.submit(
            Spec("collision", {"one": AgentSpec("one", "One")}, planner="model"),
            "task",
            command_id="s",
        )
        assert asyncio.run(e.drive(h.run_id)).state == "succeeded"
        assert len(e.diagnostics(h.run_id).workflow["children"]) == 2


@pytest.mark.parametrize("limit", [1, 2])
def test_custom_planner_managed_calls_respect_parent_concurrency(tmp_path, limit):
    from ralf_agent import LocalEngine, ModelResponse, SQLiteStore, ToolRegistry

    Spec, Proposal, Step, *_ = api()

    class Planner:
        identity = {"kind": "parallel-planner", "version": "1"}
        agent = AgentSpec("planner", "plan")

        async def plan(self, request, caller):
            snapshots = await asyncio.gather(
                caller.call("first", "@planner", "first"),
                caller.call("second", "@planner", "second"),
            )
            assert all(s.state == "succeeded" for s in snapshots)
            return Proposal([Step("work", "one", "task")])

    class Provider:
        identity = {"kind": "measured-planning", "version": "1"}
        active = peak = calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            if messages[0]["content"] == "plan":
                self.active += 1
                self.peak = max(self.peak, self.active)
                try:
                    for _ in range(5):
                        await asyncio.sleep(0)
                finally:
                    self.active -= 1
            return ModelResponse(output="done")

    provider = Provider()
    with LocalEngine(
        SQLiteStore(tmp_path / "concurrency.sqlite"),
        providers={"default": provider},
        tools=ToolRegistry(),
        planners={"custom": Planner()},
    ) as e:
        handle = e.submit(
            Spec(
                "bounded",
                {"one": AgentSpec("one", "work")},
                planner="custom",
                max_concurrency=limit,
                child_budget=3,
            ),
            "task",
            command_id="start",
            budget=9,
        )
        assert asyncio.run(e.drive(handle.run_id)).state == "succeeded"
        assert provider.peak == limit and provider.calls == 3
        assert e.diagnostics(handle.run_id).budget == {"limit": 9, "spent": 3, "held": 0}
