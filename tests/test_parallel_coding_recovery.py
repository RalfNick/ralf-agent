"""Original authority and physical stop boundaries of private parallel frames."""

import copy
import importlib

import pytest

from relf_agent import GraphNode, GraphWorkflowSpec, Literal
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.node_execution import NodeEngine, create_frame

from .test_parallel_workflow import runtime


def prepared(tmp_path):
    engine = runtime(tmp_path / "projection.db", lambda arguments, context: 1)
    handle = engine.submit(
        GraphWorkflowSpec(
            "projection",
            [
                GraphNode("left", tool="work", input=Literal({})),
                GraphNode("right", tool="work", input=Literal({})),
            ],
            max_concurrency=2,
        ),
        {},
        command_id="s",
    )
    with engine.store.transaction():
        run = engine.store.run(handle.run_id)
        for node in run["plan"]["nodes"]:
            run["workflow"]["nodes"][node["id"]] = {
                "state": "running",
                "execution": create_frame(engine, run, node["id"], {}),
            }
        run["actions"] = [
            {"id": "left-action", "node": 0, "status": "ready"},
            {"id": "right-action", "node": 1, "status": "ready"},
        ]
        engine.store.save_run(run)
    return engine, handle.run_id


def projection_api():
    spec = importlib.util.find_spec("relf_agent.node_coding_projection")
    assert spec is not None, "Exact original node Coding authority mapping is missing"
    return importlib.import_module(spec.name)


def test_node_projection_maps_original_action_without_losing_index(tmp_path):
    engine, run_id = prepared(tmp_path)
    try:
        api = projection_api()
        view = NodeEngine(engine, run_id, "right")
        frame = view.store.run(run_id)
        assert frame["actions"][0]["node"] == 0
        original, run, action = api.original_action(view, frame, frame["actions"][0])
        assert original is engine
        assert run["id"] == run_id and action["id"] == "right-action"
        assert action["node"] == 1 and run["release_digest"] != frame["release_digest"]
        assert api.original_engine(view) is engine
    finally:
        engine.close()


def test_node_projection_refuses_replaced_store_and_wrong_action(tmp_path):
    engine, run_id = prepared(tmp_path)
    try:
        api = projection_api()
        view = NodeEngine(engine, run_id, "right")
        frame = view.store.run(run_id)
        wrong = copy.deepcopy(frame["actions"][0])
        wrong["id"] = "left-action"
        with pytest.raises(DefinitionMismatch):
            api.original_action(view, frame, wrong)
        view.store.authority = object()
        with pytest.raises(DefinitionMismatch):
            api.original_engine(view)
    finally:
        engine.close()


def test_already_created_node_obeys_original_engine_quarantine(tmp_path):
    engine, run_id = prepared(tmp_path)
    view = NodeEngine(engine, run_id, "right")
    token = engine._begin_coding_cleanup()
    try:
        with pytest.raises(ValidationError, match="not open"):
            view._authorized(run_id)
        with pytest.raises(ValidationError):
            view._authorized(run_id, _cleanup_token=object())
        assert view._authorized(run_id, _cleanup_token=token)["id"] == run_id
    finally:
        engine._finish_coding_cleanup(token)
        engine.close()


def test_failed_frame_cannot_promote_parent_with_pending_sibling(tmp_path):
    engine, run_id = prepared(tmp_path)
    try:
        with engine.store.transaction():
            run = engine.store.run(run_id)
            run["actions"][0]["delegated_execution"] = {
                "version": 1,
                "pending_stop": True,
                "fenced": False,
            }
            engine.store.save_run(run)
        view = NodeEngine(engine, run_id, "right")
        frame = view.store.run(run_id)
        frame.update(state="failed", error={"code": "failed-node"})
        view.store.save_run(frame)
        parent = engine.store.run(run_id)
        assert parent["state"] == "cancelling"
        assert parent["delegated_failure"] == {"code": "failed-node", "terminal": "failed"}
        assert parent["actions"][0]["delegated_execution"]["pending_stop"] is True
    finally:
        with engine.store.transaction():
            run = engine.store.run(run_id)
            for action in run["actions"]:
                action.pop("delegated_execution", None)
            engine.store.save_run(run)
        engine.close()


def test_same_runner_selected_nodes_hold_without_second_original_attempt(tmp_path):
    import asyncio

    from relf_agent import LocalEngine, SQLiteStore, ToolRegistry
    from relf_agent.delegated_coding import register_coding_tool

    from .test_local_delegated_coding import LifecycleRunner

    async def exercise():
        runner = LifecycleRunner(wait=True)
        tools = ToolRegistry()
        register_coding_tool(tools, runner, name="coding-left")
        register_coding_tool(tools, runner, name="coding-right")
        engine = LocalEngine(SQLiteStore(tmp_path / "same-runner.db"), tools=tools, providers={})
        handle = engine.submit(
            GraphWorkflowSpec(
                "same-runner",
                [
                    GraphNode("left", tool="coding-left", input=Literal({"task": "left"})),
                    GraphNode("right", tool="coding-right", input=Literal({"task": "right"})),
                ],
                max_concurrency=2,
            ),
            {},
            command_id="s",
        )
        await engine.drive(handle.run_id)
        for action in engine.store.run(handle.run_id)["actions"]:
            engine.approve(handle.run_id, action["id"], action["digest"], command_id=action["id"])
        driving = asyncio.create_task(engine.drive(handle.run_id))
        try:
            await asyncio.wait_for(runner.entered.wait(), 2)
            for _ in range(30):
                await asyncio.sleep(0)
            run = engine.store.run(handle.run_id)
            assert runner.calls.count("execute") == 1
            assert sum(len(action["attempts"]) for action in run["actions"]) == 1
        finally:
            runner.release.set()
            await driving
        # The held branch was not accepted until the first physical operation ended.
        await engine.drive(handle.run_id)
        for action in engine.store.run(handle.run_id)["actions"]:
            if action["status"] == "waiting_approval":
                engine.approve(
                    handle.run_id, action["id"], action["digest"], command_id=action["id"]
                )
        assert (await engine.drive(handle.run_id)).state == "succeeded"
        assert runner.calls.count("execute") == 2
        engine.close()

    asyncio.run(exercise())


def test_scheduler_holds_same_actual_resource_but_admits_unique_resource(tmp_path):
    from relf_agent.delegated_coding import register_coding_tool
    from relf_agent.workflow_parallel import ParallelWorkflowRuntime

    from .test_local_delegated_coding import LifecycleRunner

    engine, run_id = prepared(tmp_path)
    try:
        left, right = LifecycleRunner(), LifecycleRunner()
        register_coding_tool(engine.tools, left, name="coding-left")
        register_coding_tool(engine.tools, left, name="coding-same")
        register_coding_tool(engine.tools, right, name="coding-right")
        run = engine.store.run(run_id)
        run["plan"]["nodes"][0]["tool"] = "coding-left"
        run["plan"]["nodes"][1]["tool"] = "coding-same"
        run["manifest"]["delegated_composition_protocol"] = 1
        run["manifest"]["tools"].update(
            engine.tools.manifests(["coding-left", "coding-same", "coding-right"])
        )
        scheduler = ParallelWorkflowRuntime(engine)
        assert getattr(scheduler, "_admit", None) is not None, "Original resource admission missing"
        assert scheduler._admit(run, ["left", "right"], {}) == ["left"]
        run["plan"]["nodes"][1]["tool"] = "coding-right"
        assert scheduler._admit(run, ["left", "right"], {}) == ["left", "right"]
        left.active_operations = 1
        assert scheduler._admit(run, ["left", "right"], {}) == ["right"]
        left.active_operations = 0
    finally:
        engine.close()


def test_coding_parent_failure_waits_for_actual_frame_worker_after_fence(tmp_path):
    import asyncio

    async def exercise():
        engine, run_id = prepared(tmp_path)
        release = asyncio.Event()
        worker = asyncio.create_task(release.wait())
        engine._parallel_tasks[run_id] = {worker}
        try:
            with engine.store.transaction():
                run = engine.store.run(run_id)
                run["manifest"]["delegated_coding_tools"] = ["coding"]
                engine.store.save_run(run)
            view = NodeEngine(engine, run_id, "right")
            frame = view.store.run(run_id)
            frame.update(state="failed", error={"code": "failed-node"})
            view.store.save_run(frame)
            assert engine.store.run(run_id)["state"] == "cancelling"
        finally:
            release.set()
            await worker
            engine._parallel_tasks.clear()
            engine.close()

    asyncio.run(exercise())


def coding_graph_engine(tmp_path, left, right):
    from relf_agent import LocalEngine, SQLiteStore, ToolRegistry
    from relf_agent.delegated_coding import register_coding_tool

    tools = ToolRegistry()
    register_coding_tool(tools, left, name="coding-left")
    register_coding_tool(tools, right, name="coding-right")
    engine = LocalEngine(SQLiteStore(tmp_path / "native-graph.db"), tools=tools, providers={})
    handle = engine.submit(
        GraphWorkflowSpec(
            "original-native",
            [
                GraphNode("left", tool="coding-left", input=Literal({"task": "left"})),
                GraphNode("right", tool="coding-right", input=Literal({"task": "right"})),
            ],
            max_concurrency=2,
        ),
        {},
        command_id="s",
    )
    return engine, handle.run_id


async def approve_graph(engine, run_id):
    await engine.drive(run_id)
    for action in engine.store.run(run_id)["actions"]:
        if action["status"] == "waiting_approval":
            engine.approve(run_id, action["id"], action["digest"], command_id=action["id"])


def test_distinct_runners_overlap_with_original_request_digests_and_indices(tmp_path):
    import asyncio

    from relf_agent.types import digest

    from .test_local_delegated_coding import LifecycleRunner

    async def exercise():
        left, right = LifecycleRunner(wait=True), LifecycleRunner(wait=True)
        engine, run_id = coding_graph_engine(tmp_path, left, right)
        await approve_graph(engine, run_id)
        driving = asyncio.create_task(engine.drive(run_id))
        try:
            await asyncio.wait_for(asyncio.gather(left.entered.wait(), right.entered.wait()), 2)
            run = engine.store.run(run_id)
            actions = [a for a in run["actions"] if "delegated_execution" in a]
            assert {a["node"] for a in actions} == {0, 1}
            assert all(len(a["attempts"]) == 1 for a in actions)
            for action in actions:
                request = action["delegated_execution"]["request"]
                assert request["release_digest"] == run["release_digest"]
                assert request["definition_digest"] == digest(run["definition"])
                assert request["dispatch"]["action_id"] == action["id"]
                assert request["dispatch"]["run_id"] == run_id
            # Commit one branch while the other is suspended; it cannot erase a sibling grant.
            left.release.set()
            for _ in range(50):
                await asyncio.sleep(0)
            current = engine.store.run(run_id)
            assert current["workflow"]["nodes"]["left"]["state"] == "completed"
            sibling = next(a for a in current["actions"] if a["node"] == 1)
            assert sibling["delegated_execution"]["pending_stop"] is True
            assert sibling["delegated_execution"]["turn"]["turn_id"] == "turn"
        finally:
            left.release.set()
            right.release.set()
            result = await driving
        assert result.state == "succeeded"
        engine._check_release(engine.store.run(run_id))
        assert left.calls.count("execute") == right.calls.count("execute") == 1
        engine.close()

    asyncio.run(exercise())


def test_cold_parallel_cancel_retries_original_stop_without_new_frame_attempt(tmp_path):
    import asyncio

    from .test_local_delegated_coding import LifecycleRunner

    async def exercise():
        left, right = LifecycleRunner(wait=True, fail_stop=True), LifecycleRunner(wait=True)
        engine, run_id = coding_graph_engine(tmp_path, left, right)
        await approve_graph(engine, run_id)
        driving = asyncio.create_task(engine.drive(run_id))
        await asyncio.wait_for(asyncio.gather(left.entered.wait(), right.entered.wait()), 2)
        original = engine.store.run(run_id)
        identities = [(a["id"], a["attempts"][0]["id"]) for a in original["actions"]]
        engine.cancel(run_id, command_id="cancel")
        left.release.set()
        right.release.set()
        assert (await driving).state == "cancelling"
        assert not engine._parallel_tasks
        assert (await engine.drive(run_id)).state == "cancelling"
        assert list(engine.store.delegated_pending(engine.scope)) == [run_id]
        left.fail_stop = False
        assert (await engine.drive(run_id)).state == "cancelled"
        final = engine.store.run(run_id)
        assert [(a["id"], a["attempts"][0]["id"]) for a in final["actions"]] == identities
        assert all(a["delegated_execution"]["fenced"] for a in final["actions"])
        assert engine.store.budget(run_id)["held"] == 2
        assert left.calls.count("execute") == right.calls.count("execute") == 1
        engine.close()

    asyncio.run(exercise())


def test_scheduler_failure_waits_for_fenced_but_live_coding_worker(tmp_path):
    import asyncio

    from relf_agent import LocalEngine, SQLiteStore, StaticWorkflowScheduler, ToolRegistry, ValueRef
    from relf_agent.delegated_coding import register_coding_tool

    from .test_local_delegated_coding import LifecycleRunner

    class LateRunner(LifecycleRunner):
        def __init__(self):
            super().__init__()
            self.fenced, self.finish = asyncio.Event(), asyncio.Event()

        async def execute(self, envelope, authority):
            observation = await super().execute(envelope, authority)
            self.fenced.set()
            await self.finish.wait()
            return observation

    class FailingScheduler(StaticWorkflowScheduler):
        identity = {"kind": "late-failure", "version": "1"}

        def select(self, plan, input, states, limit):
            if states["left"]["state"] == "completed" and states["right"]["state"] == "running":
                raise ValidationError("original scheduler failed")
            return super().select(plan, input, states, limit)

    async def exercise():
        left, right = LifecycleRunner(wait=True), LateRunner()
        tools = ToolRegistry()
        register_coding_tool(tools, left, name="coding-left")
        register_coding_tool(tools, right, name="coding-right")
        engine = LocalEngine(
            SQLiteStore(tmp_path / "late-worker.db"),
            tools=tools,
            providers={},
            workflow_scheduler=FailingScheduler(),
        )
        run_id = engine.submit(
            GraphWorkflowSpec(
                "late-worker",
                [
                    GraphNode("left", tool="coding-left", input=Literal({"task": "left"})),
                    GraphNode("right", tool="coding-right", input=Literal({"task": "right"})),
                    GraphNode(
                        "next", transform="identity", depends_on=("left",), input=ValueRef("left")
                    ),
                ],
                max_concurrency=2,
            ),
            {},
            command_id="s",
        ).run_id
        await approve_graph(engine, run_id)
        driving = asyncio.create_task(engine.drive(run_id))
        try:
            await asyncio.wait_for(right.fenced.wait(), 2)
            left.release.set()
            for _ in range(80):
                await asyncio.sleep(0)
            assert not driving.done()
            assert engine.store.run(run_id)["state"] == "cancelling"
        finally:
            left.release.set()
            right.finish.set()
            await driving
        assert engine.store.run(run_id)["state"] == "failed"
        engine.close()

    asyncio.run(exercise())


def test_busy_resource_prefix_does_not_block_independent_ready_runner(tmp_path):
    import asyncio

    from relf_agent import LocalEngine, SQLiteStore, ToolRegistry
    from relf_agent.delegated_coding import register_coding_tool

    from .test_local_delegated_coding import LifecycleRunner

    async def exercise():
        left, right = LifecycleRunner(wait=True), LifecycleRunner(wait=True)
        tools = ToolRegistry()
        register_coding_tool(tools, left, name="coding-left")
        register_coding_tool(tools, right, name="coding-right")
        engine = LocalEngine(SQLiteStore(tmp_path / "prefix.db"), tools=tools, providers={})
        run_id = engine.submit(
            GraphWorkflowSpec(
                "prefix",
                [
                    GraphNode("first", tool="coding-left", input=Literal({"task": "first"})),
                    GraphNode("second", tool="coding-left", input=Literal({"task": "second"})),
                    GraphNode(
                        "independent", tool="coding-right", input=Literal({"task": "independent"})
                    ),
                ],
                max_concurrency=2,
            ),
            {},
            command_id="s",
        ).run_id
        await approve_graph(engine, run_id)
        driving = asyncio.create_task(engine.drive(run_id))
        try:
            await asyncio.wait_for(asyncio.gather(left.entered.wait(), right.entered.wait()), 1)
            assert left.calls.count("execute") == right.calls.count("execute") == 1
        finally:
            left.release.set()
            right.release.set()
            await driving
            engine.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("resource", ["tools", "_threads"])
def test_projection_refuses_replaced_actual_shared_resource(tmp_path, resource):
    from relf_agent import ToolRegistry

    engine, run_id = prepared(tmp_path)
    try:
        view = NodeEngine(engine, run_id, "right")
        setattr(view, resource, ToolRegistry() if resource == "tools" else object())
        with pytest.raises(DefinitionMismatch):
            projection_api().original_engine(view)
    finally:
        engine.close()


@pytest.mark.parametrize("selected", [False, True])
def test_bound_excluded_coding_resource_does_not_hold_ordinary_node(tmp_path, selected):
    from relf_agent import AgentSpec, LocalEngine, SQLiteStore, ToolRegistry
    from relf_agent.binding_definitions import BoundDefinition
    from relf_agent.binding_types import AgentBindingDescriptor, BindingSelection
    from relf_agent.delegated_coding import register_coding_tool
    from relf_agent.workflow_parallel import ParallelWorkflowRuntime

    from .helpers import ScriptedProvider
    from .test_local_delegated_coding import LifecycleRunner

    runner, tools = LifecycleRunner(), ToolRegistry()
    register_coding_tool(tools, runner)
    engine = LocalEngine(
        SQLiteStore(tmp_path / "excluded.db"),
        tools=tools,
        providers={"default": ScriptedProvider([])},
    )
    graph = GraphWorkflowSpec(
        "excluded",
        [
            GraphNode("ordinary", agent=AgentSpec("ordinary", "x", ("coding",))),
            (
                GraphNode("selected", tool="coding", input=Literal({"task": "x"}))
                if selected
                else GraphNode("selected", transform="identity")
            ),
        ],
        max_concurrency=2,
    )
    definition = BoundDefinition(
        graph,
        {
            "graph/nodes/ordinary": AgentBindingDescriptor(tool_set=BindingSelection.disabled()),
        },
    )
    run_id = engine.submit(definition, {}, command_id="s").run_id
    try:
        runner.active_operations = 1
        run = engine.store.run(run_id)
        assert "coding" not in engine._step_manifest(run, 0)["tools"]
        assert ParallelWorkflowRuntime(engine)._admit(run, ["ordinary"], {}) == ["ordinary"]
        if not selected:
            assert "delegated_composition_protocol" not in run["manifest"]
    finally:
        runner.active_operations = 0
        engine.close()
