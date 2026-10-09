import asyncio
import importlib.util

import pytest

from ralf_agent import AgentSpec, DynamicWorkflowSpec, Literal, ValueRef

from .test_orchestration import make_engine


def test_dynamic_dag_binds_confirmed_dependency_output(tmp_path):
    assert importlib.util.find_spec("ralf_agent.dag_planning"), "Missing managed DAG planning"
    from ralf_agent.dag_planning import DAGNode, DAGProposal

    class Planner:
        identity = {"kind": "test-dag", "version": "1"}

        async def plan(self, request, caller):
            return DAGProposal(
                [
                    DAGNode("read", "reader", input=Literal("source")),
                    DAGNode("answer", "writer", depends_on=("read",), input=ValueRef("read")),
                ],
                output=ValueRef("answer"),
            )

    with make_engine(tmp_path / "dag.sqlite", planners={"dag": Planner()}) as engine:
        spec = DynamicWorkflowSpec(
            "dag",
            {
                "reader": AgentSpec("read", "Read"),
                "writer": AgentSpec("answer", "Answer"),
            },
            planner="dag",
            plan_mode="dag",
            child_budget=3,
        )
        handle = engine.submit(spec, "task", command_id="start", budget=6)
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        children = engine.diagnostics(handle.run_id).workflow["children"]
        assert (
            engine.store.run(children[1]["run_id"])["input"]
            == engine.status(children[0]["run_id"]).result
        )


def test_team_can_delegate_a_nested_sequence(tmp_path):
    from ralf_agent import TeamSpec, WorkflowSpec

    flow = WorkflowSpec("inner", (AgentSpec("one", "One"), AgentSpec("two", "Two")))
    spec = TeamSpec("outer", {"flow": flow}, child_budget=4, max_depth=3)
    with make_engine(tmp_path / "nested.sqlite") as engine:
        handle = engine.submit(spec, "task", command_id="start", budget=4)
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        child = engine.diagnostics(handle.run_id).workflow["children"][0]
        assert engine.store.run(child["run_id"])["definition"]["kind"] == "sequence"


def test_default_dag_planner_and_all_skipped_result(tmp_path):
    from ralf_agent import BranchCondition
    from ralf_agent.dag_planning import DAGNode, DAGProposal

    with make_engine(tmp_path / "default.sqlite") as engine:
        spec = DynamicWorkflowSpec("default", {"one": AgentSpec("one", "One")}, plan_mode="dag")
        handle = engine.submit(spec, "task", command_id="start")
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"

    class Planner:
        identity = {"kind": "skip", "version": "1"}

        async def plan(self, request, caller):
            return DAGProposal([DAGNode("skip", "one", when=BranchCondition(ValueRef(), "wanted"))])

    with make_engine(tmp_path / "skip.sqlite", planners={"skip": Planner()}) as engine:
        spec = DynamicWorkflowSpec(
            "skip", {"one": AgentSpec("one", "One")}, planner="skip", plan_mode="dag"
        )
        handle = engine.submit(spec, "different", command_id="start")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {}
        assert engine.diagnostics(handle.run_id).budget["spent"] == 0


def test_dag_patch_cas_replay_and_frozen_dispatched_node(tmp_path):
    from ralf_agent import ModelResponse, ToolRegistry, ToolSpec
    from ralf_agent.dag_planning import DAGNode, DAGProposal
    from ralf_agent.errors import IdempotencyConflict, ValidationError

    from .helpers import ScriptedProvider, tool_response
    from .test_engine import engine as configured_engine

    first = DAGNode("operation", "operator", input=Literal("original"))

    class Planner:
        identity = {"kind": "patch", "version": "1"}

        async def plan(self, request, caller):
            return DAGProposal(
                [first, DAGNode("later", "answer", depends_on=("operation",), input=Literal("old"))]
            )

    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change",
            "Change",
            {"type": "object"},
            effect="idempotent_write",
            requires_approval=True,
        ),
        lambda a, c: a,
    )
    with configured_engine(
        tmp_path / "patch.sqlite",
        ScriptedProvider(
            [
                tool_response(),
                ModelResponse(output={"accepted": True}),
                ModelResponse(output="new-answer"),
            ]
        ),
        tools,
        planners={"patch": Planner()},
    ) as engine:
        spec = DynamicWorkflowSpec(
            "patch",
            {
                "operator": AgentSpec("op", "Operation", ("change",)),
                "answer": AgentSpec("answer", "Answer"),
            },
            planner="patch",
            plan_mode="dag",
        )
        handle = engine.submit(spec, "task", command_id="start")
        assert asyncio.run(engine.drive(handle.run_id)).state == "waiting_approval"
        proposal = DAGProposal(
            [first, DAGNode("later", "answer", depends_on=("operation",), input=Literal("new"))],
            output=ValueRef("later"),
        )
        receipt = engine.patch_plan(
            handle.run_id, proposal, expected_plan_revision=0, command_id="patch"
        )
        assert (
            engine.patch_plan(handle.run_id, proposal, expected_plan_revision=0, command_id="patch")
            == receipt
        )
        with pytest.raises(ValidationError, match="revision"):
            engine.patch_plan(handle.run_id, proposal, expected_plan_revision=0, command_id="stale")
        with pytest.raises(IdempotencyConflict):
            engine.patch_plan(handle.run_id, proposal, expected_plan_revision=1, command_id="patch")
        with pytest.raises(ValidationError, match="dispatched"):
            engine.patch_plan(
                handle.run_id,
                DAGProposal([DAGNode("operation", "operator", input=Literal("changed"))]),
                expected_plan_revision=1,
                command_id="unsafe",
            )
        child = engine.diagnostics(handle.run_id).workflow["children"][0]["run_id"]
        pending = engine.status(child).pending[0]
        engine.approve(child, pending["action_id"], pending["digest"], command_id="approve")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == "new-answer"
        later = engine.diagnostics(handle.run_id).workflow["children"][1]["run_id"]
        assert engine.store.run(later)["input"] == "new"


def test_nested_team_and_graph_pin_parent_release_and_settle_tree(tmp_path):
    from ralf_agent import GraphNode, GraphWorkflowSpec, TeamSpec
    from ralf_agent.errors import DefinitionMismatch

    inner = TeamSpec("inner", {"leaf": AgentSpec("leaf", "Leaf")}, child_budget=2)
    graph = GraphWorkflowSpec("graph", [GraphNode("one", agent=AgentSpec("one", "One"))])
    outer = TeamSpec("outer", {"team": inner, "graph": graph}, child_budget=5, max_depth=4)
    path = tmp_path / "tree.sqlite"
    with make_engine(path) as engine:
        handle = engine.submit(outer, "task", command_id="start", budget=10)
    with make_engine(path) as engine:
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded"
        assert engine.diagnostics(handle.run_id).budget == {"limit": 10, "spent": 2, "held": 0}
        team = engine.diagnostics(handle.run_id).workflow["children"][0]["run_id"]
        leaf = engine.diagnostics(team).workflow["children"][0]["run_id"]
        assert engine.store.run(leaf)["parent_call"]["parent_id"] == team
        engine.providers["default"].label = "changed"
        with pytest.raises(DefinitionMismatch):
            engine._check_release(engine.store.run(leaf))


@pytest.mark.parametrize("invalid", ["cycle", "reference", "member"])
def test_dag_rejects_invalid_structure_before_delegation(tmp_path, invalid):
    from ralf_agent.dag_planning import DAGNode, DAGProposal
    from ralf_agent.errors import ValidationError

    if invalid == "cycle":
        with pytest.raises(ValidationError, match="cycle"):
            DAGProposal(
                [DAGNode("a", "one", depends_on=("b",)), DAGNode("b", "one", depends_on=("a",))]
            )
    elif invalid == "reference":
        with pytest.raises(ValidationError, match="ancestor"):
            DAGProposal([DAGNode("a", "one"), DAGNode("b", "one", input=ValueRef("a"))])
    else:
        with pytest.raises(ValidationError, match="registered"):
            DAGProposal([DAGNode("a", "forbidden")]).validate_members({"one"})


def test_nested_root_session_stays_reserved_until_real_child_thread_finishes(tmp_path):
    import threading

    from ralf_agent import (
        LocalEngine,
        ModelResponse,
        SQLiteStore,
        TeamSpec,
        ToolCall,
        ToolRegistry,
        ToolSpec,
    )
    from ralf_agent.errors import ValidationError

    async def scenario():
        started, failed = asyncio.Event(), asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()

        class Provider:
            identity = {"kind": "nested-thread", "version": "1"}

            async def complete(self, messages, tools):
                if messages[0]["content"] == "bad":
                    await started.wait()
                    return ModelResponse()
                return ModelResponse(tool_calls=[ToolCall("wait", {})])

        def handler(arguments, context):
            loop.call_soon_threadsafe(started.set)
            finish.wait(5)
            return {"done": True}

        tools = ToolRegistry()
        tools.register(ToolSpec("wait", "Wait", {"type": "object"}, effect="read_only"), handler)
        inner = TeamSpec("inner", {"leaf": AgentSpec("leaf", "wait", ("wait",))}, child_budget=4)
        outer = TeamSpec(
            "outer",
            {
                "bad": AgentSpec("bad", "bad"),
                "inner": inner,
                "boss": AgentSpec("boss", "summarize"),
            },
            strategy="supervisor",
            strategy_config={"supervisor": "boss"},
            child_budget=6,
            max_concurrency=2,
            max_depth=4,
        )
        e = LocalEngine(
            SQLiteStore(tmp_path / "thread.sqlite"), providers={"default": Provider()}, tools=tools
        )
        task = None
        try:
            handle = e.submit(outer, "task", command_id="start", session_id="shared", budget=18)
            emit = e.store.emit

            def observe(run_id, kind, data=None):
                result = emit(run_id, kind, data)
                if run_id == handle.run_id and kind == "run_failed":
                    failed.set()
                return result

            e.store.emit = observe
            task = asyncio.create_task(e.drive(handle.run_id))
            await asyncio.wait_for(failed.wait(), 2)
            replacement = TeamSpec("replacement", {"other": AgentSpec("other", "Other")})
            with pytest.raises(ValidationError, match="Session"):
                e.submit(replacement, "new", command_id="replacement", session_id="shared")
            assert not task.done()
            finish.set()
            assert (await task).state == "failed"
            e.submit(replacement, "new", command_id="replacement", session_id="shared")
        finally:
            finish.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await e.wait_for_threads()
            e.close()

    asyncio.run(scenario())


def test_dag_planner_receives_registered_capabilities_and_remaining_limits(tmp_path):
    from ralf_agent.dag_planning import DAGNode, DAGProposal

    class Planner:
        identity = {"kind": "capability-aware", "version": "1"}

        async def plan(self, request, caller):
            assert request.capabilities["one"]["instructions"] == "Only read authorized records"
            assert request.constraints["remaining_steps"] == 2
            assert request.constraints["max_concurrency"] == 1
            return DAGProposal([DAGNode("one", "one")])

    with make_engine(tmp_path / "capabilities.sqlite", planners={"aware": Planner()}) as engine:
        spec = DynamicWorkflowSpec(
            "aware",
            {"one": AgentSpec("one", "Only read authorized records")},
            plan_mode="dag",
            planner="aware",
            max_steps=2,
        )
        handle = engine.submit(spec, "task", command_id="start")
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"


def test_dag_parallel_roots_join_confirmed_results_under_capacity(tmp_path):
    from ralf_agent import InputMap, LocalEngine, ModelResponse, SQLiteStore, ToolRegistry
    from ralf_agent.dag_planning import DAGNode, DAGProposal

    async def scenario():
        overlap = asyncio.Event()
        active = peak = 0
        inputs = {}

        class Provider:
            identity = {"kind": "dag-parallel", "version": "1"}

            async def complete(self, messages, tools):
                nonlocal active, peak
                import json

                name = messages[0]["content"]
                inputs[name] = json.loads(messages[1]["content"])
                if name == "join":
                    assert active == 0
                    return ModelResponse(output=inputs[name])
                active += 1
                peak = max(peak, active)
                if active == 2:
                    overlap.set()
                try:
                    await asyncio.wait_for(overlap.wait(), 2)
                    return ModelResponse(output={"source": name})
                finally:
                    active -= 1

        class Planner:
            identity = {"kind": "parallel-plan", "version": "1"}

            async def plan(self, request, caller):
                return DAGProposal(
                    [
                        DAGNode("a", "a"),
                        DAGNode("b", "b"),
                        DAGNode(
                            "join",
                            "join",
                            depends_on=("a", "b"),
                            input=InputMap({"a": ValueRef("a"), "b": ValueRef("b")}),
                        ),
                    ],
                    output=ValueRef("join"),
                )

        with LocalEngine(
            SQLiteStore(tmp_path / "parallel.sqlite"),
            providers={"default": Provider()},
            tools=ToolRegistry(),
            planners={"parallel": Planner()},
        ) as engine:
            spec = DynamicWorkflowSpec(
                "parallel",
                {name: AgentSpec(name, name) for name in ("a", "b", "join")},
                plan_mode="dag",
                planner="parallel",
                max_concurrency=2,
                child_budget=2,
            )
            handle = engine.submit(spec, {"task": "question"}, command_id="start", budget=6)
            result = await engine.drive(handle.run_id)
            assert result.state == "succeeded"
            assert result.result == {"a": {"source": "a"}, "b": {"source": "b"}}
            assert peak == 2
            assert engine.diagnostics(handle.run_id).budget == {"limit": 6, "held": 0, "spent": 3}

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["refused", "needs_input"])
def test_model_dag_conclusion_stops_without_worker_dispatch(tmp_path, status):
    from ralf_agent import LocalEngine, ModelDAGPlanner, ModelResponse, SQLiteStore, ToolRegistry

    class Provider:
        identity = {"kind": "dag-stop", "version": "1"}
        calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            assert tools == []
            return ModelResponse(output={"status": status, "reason": "Need an authorized target"})

    provider = Provider()
    with LocalEngine(
        SQLiteStore(tmp_path / "stop.sqlite"),
        providers={"default": provider},
        tools=ToolRegistry(),
        planners={"model": ModelDAGPlanner()},
    ) as engine:
        handle = engine.submit(
            DynamicWorkflowSpec(
                "stop",
                {"worker": AgentSpec("worker", "work")},
                plan_mode="dag",
                planner="model",
                child_budget=2,
            ),
            "task",
            command_id="start",
            budget=4,
        )
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded"
        assert result.result == {"status": status, "reason": "Need an authorized target"}
        assert provider.calls == 1
        children = engine.diagnostics(handle.run_id).workflow["children"]
        assert len(children) == 1 and children[0]["member"] == "@planner"


def test_nested_depth_limit_refuses_leaf_before_model_dispatch(tmp_path):
    from ralf_agent import TeamSpec

    inner = TeamSpec("inner", {"leaf": AgentSpec("leaf", "leaf")}, child_budget=2)
    outer = TeamSpec("outer", {"inner": inner}, child_budget=4, max_depth=1)
    with make_engine(tmp_path / "depth.sqlite") as engine:
        handle = engine.submit(outer, "task", command_id="start", budget=4)
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        child = engine.diagnostics(handle.run_id).workflow["children"][0]["run_id"]
        assert engine.diagnostics(child).workflow["children"] == []
        assert engine.diagnostics(handle.run_id).budget["spent"] == 0


def test_dag_condition_rejects_unknown_fields():
    from ralf_agent import BranchCondition
    from ralf_agent.dag_planning import DAGNode
    from ralf_agent.errors import ValidationError

    node = DAGNode("one", "one", when=BranchCondition(ValueRef(), "ok")).to_dict()
    node["when"]["negatte"] = True
    with pytest.raises(ValidationError, match="condition"):
        DAGNode.from_dict(node)
