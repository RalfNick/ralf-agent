import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from ralf_agent import (
    AgentSpec,
    BranchCondition,
    ExecutionPlan,
    GraphNode,
    GraphWorkflowSpec,
    IdentityTransform,
    InputMap,
    Literal,
    LocalEngine,
    ModelResponse,
    StaticWorkflowCompiler,
    StaticWorkflowInterpreter,
    ToolRegistry,
    ToolSpec,
    ValueRef,
    WorkflowSelection,
)
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.storage import SQLiteStore
from ralf_agent.types import submission_request

from .helpers import ScriptedProvider, tool_response


def runtime(path, provider=None, tools=None, **options):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": provider or ScriptedProvider([])},
        tools=ToolRegistry() if tools is None else tools,
        **options,
    )


def test_graph_runs_dependencies_before_declaration_order(tmp_path):
    provider = ScriptedProvider(
        [ModelResponse(output={"count": 2}), ModelResponse(output="report")]
    )
    spec = GraphWorkflowSpec(
        "flow",
        [
            GraphNode(
                "report",
                agent=AgentSpec("report", "Write report"),
                depends_on=("read",),
                input=InputMap({"count": ValueRef("read", ("count",)), "fixed": Literal(0)}),
            ),
            GraphNode("read", agent=AgentSpec("read", "Read")),
        ],
        output=ValueRef("report"),
    )
    with runtime(tmp_path / "runs.db", provider) as engine:
        handle = engine.submit(spec, "task", command_id="submit")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == "report"
        assert provider.messages[1][1]["content"] == '{"count":2,"fixed":0}'
        details = engine.diagnostics(handle.run_id).workflow
        assert details["nodes"]["read"]["result"] == {"count": 2}
        assert details["nodes"]["report"]["state"] == "completed"
        assert [
            event.data["node_id"]
            for event in engine.events(handle.run_id)
            if event.kind == "workflow_node_started"
        ] == ["read", "report"]


def test_graph_branch_join_uses_explicit_optional_inputs(tmp_path):
    spec = GraphWorkflowSpec(
        "branches",
        [
            GraphNode("left", transform="identity", when=BranchCondition(ValueRef(), "left")),
            GraphNode(
                "right", transform="identity", when=BranchCondition(ValueRef(), "left", negate=True)
            ),
            GraphNode(
                "join",
                transform="identity",
                depends_on=("left", "right"),
                allow_skipped_dependencies=True,
                input=InputMap(
                    {
                        "left": ValueRef("left", required=False),
                        "right": ValueRef("right", required=False),
                    }
                ),
            ),
        ],
        output=ValueRef("join"),
    )
    with runtime(tmp_path / "runs.db") as engine:
        handle = engine.submit(spec, "right", command_id="submit")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {"left": None, "right": "right"}
        assert engine.diagnostics(handle.run_id).workflow["nodes"]["left"]["state"] == "skipped"
        assert engine.store.budget(handle.run_id)["spent"] == 0


def test_graph_receipt_replay_precedes_changed_compiler_or_provider(tmp_path):
    spec = GraphWorkflowSpec("flow", [GraphNode("a", agent=AgentSpec("a", "x"))])
    with runtime(tmp_path / "runs.db", ScriptedProvider([ModelResponse(output="done")])) as engine:
        original = engine.submit(spec, "task", command_id="submit")
        engine.providers.clear()
        engine.workflow_compiler = object()
        replay = engine.submit(spec, "task", command_id="submit")
        assert replay == original
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(original.run_id))
        assert submission_request(spec, "task")["definition"]["kind"] == "graph"


def test_custom_transform_and_interpreter_choose_ready_order(tmp_path):
    class Add:
        identity = {"kind": "add", "version": "1"}

        def transform(self, input, config):
            return input + config["amount"]

    class Reverse(StaticWorkflowInterpreter):
        identity = {"kind": "reverse", "version": "1"}

        def select(self, plan, input, states):
            value = plan.to_dict()
            value["nodes"].reverse()
            return super().select(ExecutionPlan(value), input, states)

    spec = GraphWorkflowSpec(
        "custom",
        [
            GraphNode("a", transform="add", config={"amount": 1}),
            GraphNode("b", transform="add", config={"amount": 2}),
        ],
    )
    with runtime(
        tmp_path / "runs.db", workflow_transforms={"add": Add()}, workflow_interpreter=Reverse()
    ) as engine:
        handle = engine.submit(spec, 10, command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {"a": 11, "b": 12}
        assert [
            e.data["node_id"]
            for e in engine.events(handle.run_id)
            if e.kind == "workflow_node_started"
        ] == ["b", "a"]


@pytest.mark.parametrize("bad", ["input", "node", "skip", "done", "mutate"])
def test_engine_validates_custom_interpreter_decisions(tmp_path, bad):
    class Invalid(StaticWorkflowInterpreter):
        identity = {"kind": "invalid", "version": "1"}

        def select(self, plan, input, states):
            if bad == "input":
                return WorkflowSelection("a", "changed")
            if bad == "node":
                return WorkflowSelection("b", input)
            if bad == "skip":
                return WorkflowSelection("a", input, ("b",))
            if bad == "done":
                return WorkflowSelection(done=True, result="invented")
            states["a"] = {"state": "completed", "result": "invented"}
            return super().select(plan, input, states)

    spec = GraphWorkflowSpec(
        "flow",
        [
            GraphNode("a", transform="identity"),
            GraphNode("b", transform="identity", depends_on=("a",)),
        ],
    )
    with runtime(tmp_path / "runs.db", workflow_interpreter=Invalid()) as engine:
        handle = engine.submit(spec, "original", command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed" and result.error["code"] == "validation_error"
        assert not any(e.kind == "workflow_node_completed" for e in engine.events(handle.run_id))


@pytest.mark.parametrize("component", ["compiler", "interpreter", "transform"])
def test_actual_component_identity_drift_is_not_adopted(tmp_path, component):
    class Compiler(StaticWorkflowCompiler):
        identity = {"kind": "compiler", "version": "1"}

        def compile(self, spec):
            value = super().compile(spec)
            if component == "compiler":
                self.identity = {"kind": "compiler", "version": "2"}
            return value

    class Interpreter(StaticWorkflowInterpreter):
        identity = {"kind": "interpreter", "version": "1"}

        def select(self, *args):
            value = super().select(*args)
            if component == "interpreter":
                self.identity = {"kind": "interpreter", "version": "2"}
            return value

    class Transform(IdentityTransform):
        identity = {"kind": "transform", "version": "1"}

        def transform(self, *args):
            value = super().transform(*args)
            if component == "transform":
                self.identity = {"kind": "transform", "version": "2"}
            return value

    spec = GraphWorkflowSpec("flow", [GraphNode("a", transform="custom")])
    with runtime(
        tmp_path / "runs.db",
        workflow_compiler=Compiler(),
        workflow_interpreter=Interpreter(),
        workflow_transforms={"custom": Transform()},
    ) as engine:
        if component == "compiler":
            with pytest.raises(DefinitionMismatch):
                engine.submit(spec, "task", command_id="s")
        else:
            handle = engine.submit(spec, "task", command_id="s")
            result = asyncio.run(engine.drive(handle.run_id))
            assert result.state == "failed" and result.error["code"] == "definition_mismatch"


@pytest.mark.parametrize("lazy", ["coroutine", "generator", "contextmanager"])
def test_lazy_transform_results_reject_without_entering(tmp_path, lazy):
    executed = []

    async def coroutine():
        executed.append(1)

    def generator():
        executed.append(1)
        yield "output"

    @contextmanager
    def manager():
        executed.append(1)
        yield "output"

    class Lazy:
        identity = {"kind": "lazy", "version": "1"}

        def transform(self, input, config):
            return {"coroutine": coroutine, "generator": generator, "contextmanager": manager}[
                lazy
            ]()

    with runtime(tmp_path / "runs.db", workflow_transforms={"lazy": Lazy()}) as engine:
        handle = engine.submit(
            GraphWorkflowSpec("flow", [GraphNode("a", transform="lazy")]), "task", command_id="s"
        )
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed" and executed == []


def test_transform_cancel_callback_cannot_commit_node_or_schedule(tmp_path):
    class Cancel:
        identity = {"kind": "cancel", "version": "1"}

        def transform(self, input, config):
            engine.cancel(handle.run_id, command_id="cancel")
            return input

    with runtime(tmp_path / "runs.db", workflow_transforms={"cancel": Cancel()}) as engine:
        handle = engine.submit(
            GraphWorkflowSpec(
                "flow",
                [
                    GraphNode("a", transform="cancel"),
                    GraphNode("b", transform="identity", depends_on=("a",)),
                ],
            ),
            "task",
            command_id="s",
        )
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "cancelled"
        assert not any(e.kind == "workflow_node_completed" for e in engine.events(handle.run_id))


def test_output_schema_failure_keeps_completed_node_evidence(tmp_path):
    spec = GraphWorkflowSpec(
        "flow",
        [GraphNode("a", transform="identity")],
        output=ValueRef("a"),
        output_schema={"type": "integer"},
    )
    with runtime(tmp_path / "runs.db") as engine:
        handle = engine.submit(spec, "not integer", command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed"
        assert engine.diagnostics(handle.run_id).workflow["nodes"]["a"]["result"] == "not integer"


def test_graph_approval_close_and_restart_runs_business_write_once(tmp_path):
    path = tmp_path / "runs.db"
    effects = []
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change", "Write", {"type": "object"}, effect="idempotent_write", requires_approval=True
        ),
        lambda arguments, context: effects.append(context.effect_key) or arguments,
    )
    spec = GraphWorkflowSpec(
        "flow",
        [
            GraphNode("prepare", transform="identity"),
            GraphNode(
                "apply",
                agent=AgentSpec("apply", "Apply", ("change",)),
                depends_on=("prepare",),
                input=ValueRef("prepare"),
            ),
        ],
        output=ValueRef("apply"),
    )
    with runtime(path, ScriptedProvider([tool_response()]), tools) as engine:
        handle = engine.submit(spec, {"value": 1}, command_id="s")
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_approval"
        accepted_plan = engine.diagnostics(handle.run_id).workflow["plan"]
        pending_action = waiting.pending[0]
        receipt = engine.approve(
            handle.run_id,
            pending_action["action_id"],
            pending_action["digest"],
            command_id="approve",
        )
    with runtime(path, ScriptedProvider([ModelResponse(output="applied")]), tools) as engine:
        assert (
            engine.approve(
                handle.run_id,
                pending_action["action_id"],
                pending_action["digest"],
                command_id="approve",
            )
            == receipt
        )
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == "applied" and len(effects) == 1
        assert engine.diagnostics(handle.run_id).workflow["plan"] == accepted_plan
        assert asyncio.run(engine.drive(handle.run_id)) == result


def test_resume_saved_plan_never_recompiles(tmp_path):
    path = tmp_path / "runs.db"

    class Compiler(StaticWorkflowCompiler):
        identity = {"kind": "compile-once", "version": "1"}
        calls = 0

        def compile(self, spec):
            self.calls += 1
            assert self.calls == 1
            return super().compile(spec)

    compiler = Compiler()
    spec = GraphWorkflowSpec("flow", [GraphNode("a", transform="identity")])
    with runtime(path, workflow_compiler=compiler) as engine:
        handle = engine.submit(spec, "task", command_id="s")
    with runtime(path, workflow_compiler=compiler) as engine:
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        assert compiler.calls == 1


def test_invalid_plan_mutation_fails_before_dispatch(tmp_path):
    provider = ScriptedProvider([ModelResponse(output="wrong")])
    spec = GraphWorkflowSpec("flow", [GraphNode("a", agent=AgentSpec("a", "x"))])
    with runtime(tmp_path / "runs.db", provider) as engine:
        handle = engine.submit(spec, "task", command_id="s")
        record = engine.store.run(handle.run_id)
        record["plan"]["nodes"][0]["agent"]["instructions"] = "changed"
        with engine.store.transaction():
            engine.store.save_run(record)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(handle.run_id))
        assert provider.calls == 0


@pytest.mark.parametrize("component", ["compiler", "transform"])
def test_json_identity_type_drift_cannot_hide_behind_equal_python_values(tmp_path, component):
    class Compiler(StaticWorkflowCompiler):
        identity = {"kind": "compiler", "version": True}

        def compile(self, spec):
            result = super().compile(spec)
            self.identity = {"kind": "compiler", "version": 1}
            return result

    class Transform(IdentityTransform):
        identity = {"kind": "transform", "version": True}

        def transform(self, *args):
            result = super().transform(*args)
            self.identity = {"kind": "transform", "version": 1}
            engine.workflow_transforms["custom"] = Pinned()
            return result

    class Pinned(IdentityTransform):
        identity = {"kind": "transform", "version": True}

    options = (
        {"workflow_compiler": Compiler()}
        if component == "compiler"
        else {"workflow_transforms": {"custom": Transform()}}
    )
    node = GraphNode("a", transform="identity" if component == "compiler" else "custom")
    with runtime(tmp_path / "runs.db", **options) as engine:
        if component == "compiler":
            with pytest.raises(DefinitionMismatch):
                engine.submit(GraphWorkflowSpec("flow", [node]), "task", command_id="s")
        else:
            handle = engine.submit(GraphWorkflowSpec("flow", [node]), "task", command_id="s")
            result = asyncio.run(engine.drive(handle.run_id))
            assert result.state == "failed" and result.error["code"] == "definition_mismatch"


def test_graph_session_message_records_bound_node_input(tmp_path):
    spec = GraphWorkflowSpec(
        "flow",
        [
            GraphNode("prepare", transform="identity", input=Literal({"selected": "node task"})),
            GraphNode(
                "answer",
                agent=AgentSpec("answer", "Answer"),
                depends_on=("prepare",),
                input=ValueRef("prepare"),
            ),
        ],
    )
    with runtime(
        tmp_path / "runs.db", ScriptedProvider([ModelResponse(output="answer")])
    ) as engine:
        handle = engine.submit(spec, "original task", command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        _, messages = engine.sessions.read(engine.scope, handle.run_id)
        assert messages[-1]["task"] == {"selected": "node task"}


@pytest.mark.parametrize("window", ["started", "completed", "session"])
def test_graph_real_process_crash_preserves_node_and_business_effect(tmp_path, window):
    path = tmp_path / "runs.db"
    root = Path(__file__).resolve().parents[1]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
    }

    def worker(*arguments, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "tests.workflow_crash_fixture", str(path), *arguments],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == expected, result.stderr
        return json.loads(result.stdout)

    run_id = worker("--crash", window, expected=77)["run_id"]
    done = worker("--run-id", run_id)
    assert done["state"] == "succeeded" and done["result"]["written"] == 7
    with sqlite3.connect(str(path) + ".evidence.sqlite") as connection:
        counts = dict(connection.execute("SELECT kind, count FROM calls"))
        assert counts["handler"] == 1 and counts["model"] == 2
        assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
    from .receipt_runtime import create_engine

    with create_engine(path, "queryable_write") as engine:
        _, messages = engine.sessions.read(engine.scope, run_id)
        assert len(messages) == 1
        assert engine.diagnostics(run_id).workflow["nodes"]["apply"]["state"] == "completed"
        assert asyncio.run(engine.drive(run_id)).state == "succeeded"


@pytest.mark.parametrize("event", ["model_response_recorded", "tool_receipt_recorded"])
def test_graph_cancelled_received_evidence_cannot_start_successors(tmp_path, event):
    from .receipt_runtime import create_engine
    from .workflow_crash_fixture import graph_spec

    with create_engine(
        tmp_path / "runs.db", "queryable_write", trigger_event=event, trigger_mode="callback"
    ) as engine:
        handle = engine.submit(graph_spec(), "task", command_id="s", budget=12)
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "cancelled"
        assert engine.diagnostics(handle.run_id).workflow["nodes"]["finish"]["state"] == "cancelled"
        assert not any(e.kind == "workflow_node_completed" for e in engine.events(handle.run_id))


def test_custom_interpreter_may_order_semantically_valid_skips(tmp_path):
    class Reverse(StaticWorkflowInterpreter):
        identity = {"kind": "reverse", "version": "1"}

        def select(self, plan, input, states):
            value = plan.to_dict()
            value["nodes"].reverse()
            return super().select(ExecutionPlan(value), input, states)

    nodes = [
        GraphNode(name, transform="identity", when=BranchCondition(ValueRef(), True))
        for name in ("a", "b")
    ]
    with runtime(tmp_path / "runs.db", workflow_interpreter=Reverse()) as engine:
        handle = engine.submit(GraphWorkflowSpec("flow", nodes), False, command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {}
        assert [
            e.data["node_id"]
            for e in engine.events(handle.run_id)
            if e.kind == "workflow_node_skipped"
        ] == ["b", "a"]


def test_downlevel_native_release_check_refuses_graph_without_dispatch(tmp_path):
    # dev9 reads definition.steps before checking its native Manifest. Retain
    # that read shape so it refuses the graph protocol before scheduling.
    from ralf_agent.types import digest

    with runtime(tmp_path / "runs.db") as engine:
        handle = engine.submit(
            GraphWorkflowSpec("flow", [GraphNode("a", transform="identity")]),
            "task",
            command_id="s",
        )
        run = engine.store.run(handle.run_id)
        native_manifest = engine._manifest(run["definition"]["steps"])
        assert digest(native_manifest) != digest(run["manifest"])
        assert run["state"] == "queued" and run["actions"] == []
