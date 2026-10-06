import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ralf_agent import (
    AgentSpec,
    ExecutionPlan,
    GraphNode,
    GraphWorkflowSpec,
    InputMap,
    Literal,
    LocalEngine,
    SQLiteStore,
    StaticWorkflowCompiler,
    ToolRegistry,
    ToolSpec,
    ValueRef,
)
from ralf_agent.errors import AuthorizationDenied, ValidationError


def runtime(path, handler, *, effect="read_only", approval=False, reconciler=None, policy=None):
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "business",
            "Managed business operation",
            {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            effect=effect,
            requires_approval=approval,
        ),
        handler,
        reconciler=reconciler,
    )
    return LocalEngine(SQLiteStore(path), providers={}, tools=tools, policy=policy)


def graph(**options):
    return GraphWorkflowSpec(
        "tools", [GraphNode("business", tool="business", **options)], output=ValueRef("business")
    )


def test_tool_node_uses_managed_async_handler_without_model(tmp_path):
    calls = []

    async def handler(arguments, ctx):
        await asyncio.sleep(0)
        calls.append((arguments, ctx.effect_key))
        return {"value": arguments["value"] + 1}

    with runtime(tmp_path / "runs.db", handler) as engine:
        handle = engine.submit(graph(), {"value": 4}, command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {"value": 5}
        assert len(calls) == 1 and calls[0][0] == {"value": 4}
        run = engine.store.run(handle.run_id)
        assert [a["kind"] for a in run["actions"]] == ["tool"]
        assert engine.sessions.read(engine.scope, run["session_id"])[1] == []
        assert engine.diagnostics(handle.run_id).budget["spent"] == 1


def test_tool_node_approval_and_duplicate_command_then_restart(tmp_path):
    calls = []

    async def handler(arguments, ctx):
        calls.append(ctx.effect_key)
        return arguments

    path = tmp_path / "runs.db"
    with runtime(path, handler, effect="unqueryable_write", approval=True) as engine:
        handle = engine.submit(graph(), {"value": 1}, command_id="s")
        pending = asyncio.run(engine.drive(handle.run_id))
        assert pending.state == "waiting_approval" and not calls
        action = pending.pending[0]
        approved = engine.approve(
            handle.run_id, action["action_id"], action["digest"], command_id="a"
        )
        assert (
            engine.approve(handle.run_id, action["action_id"], action["digest"], command_id="a")
            == approved
        )
    with runtime(path, handler, effect="unqueryable_write", approval=True) as engine:
        assert asyncio.run(engine.drive(handle.run_id)).result == {"value": 1}
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
    assert len(calls) == 1


def test_tool_node_dependency_mapping_and_output_validation(tmp_path):
    def handler(arguments, ctx):
        return arguments["value"] * 2

    spec = GraphWorkflowSpec(
        "mapped",
        [
            GraphNode("prepare", transform="identity"),
            GraphNode(
                "apply",
                tool="business",
                depends_on=("prepare",),
                input=InputMap({"value": ValueRef("prepare", ("number",))}),
                output_schema={"type": "integer"},
            ),
        ],
        output=ValueRef("apply"),
    )
    with runtime(tmp_path / "runs.db", handler) as engine:
        handle = engine.submit(spec, {"number": 3}, command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == 6


@pytest.mark.parametrize("case", ["schema", "arguments", "budget", "authorization"])
def test_tool_node_governance_applies(case, tmp_path):
    calls = []

    def handler(arguments, ctx):
        calls.append(1)
        return "bad" if case == "schema" else arguments

    def policy(scope, spec, arguments):
        if case == "authorization":
            raise AuthorizationDenied("deny")

    options = {"output_schema": {"type": "object"}} if case == "schema" else {}
    with runtime(tmp_path / "runs.db", handler, policy=policy) as engine:
        handle = engine.submit(
            graph(**options),
            {"value": "bad"} if case == "arguments" else {"value": 1},
            command_id="s",
            budget=0 if case == "budget" else 10,
        )
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed"
        assert (
            result.error["code"]
            == {
                "schema": "validation_error",
                "arguments": "validation_error",
                "budget": "budget_exceeded",
                "authorization": "authorization_denied",
            }[case]
        )
        assert len(calls) == (1 if case == "schema" else 0)


def test_unknown_write_is_not_repeated_and_can_be_reconciled(tmp_path):
    calls = []

    def handler(arguments, ctx):
        calls.append(ctx.effect_key)
        raise RuntimeError("response lost")

    with runtime(tmp_path / "runs.db", handler, effect="unqueryable_write") as engine:
        handle = engine.submit(graph(), {"value": 2}, command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).state == "waiting_reconciliation"
        assert asyncio.run(engine.drive(handle.run_id)).state == "waiting_reconciliation"
        action = engine.store.run(handle.run_id)["actions"][0]
        engine.reconcile(handle.run_id, action["id"], {"confirmed": True}, command_id="confirm")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {"confirmed": True}
        assert len(calls) == 1


def test_cancelled_async_tool_retains_result_but_does_not_schedule_successor(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def handler(arguments, ctx):
            calls.append(arguments["value"])
            started.set()
            await release.wait()
            return arguments

        with runtime(tmp_path / "runs.db", handler) as engine:
            spec = GraphWorkflowSpec(
                "cancel",
                [
                    GraphNode("first", tool="business"),
                    GraphNode(
                        "next", tool="business", depends_on=("first",), input=Literal({"value": 99})
                    ),
                ],
            )
            handle = engine.submit(spec, {"value": 1}, command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await started.wait()
            engine.cancel(handle.run_id, command_id="cancel")
            release.set()
            assert (await task).state == "cancelled"
            assert calls == [1]
            action = engine.store.run(handle.run_id)["actions"][0]
            assert action["status"] == "completed" and action["result"] == {"value": 1}

    asyncio.run(run())


def test_tool_plans_use_v2_and_v1_never_silently_accepts_tool():
    spec = graph()
    plan = StaticWorkflowCompiler().compile(spec)
    assert plan.to_dict()["schema_version"] == 2 and plan.identity["schema_version"] == 2
    old = plan.to_dict()
    old["schema_version"] = 1
    with pytest.raises(ValidationError):
        ExecutionPlan(old)
    legacy = StaticWorkflowCompiler().compile(
        GraphWorkflowSpec("old", [GraphNode("n", transform="identity")])
    )
    assert legacy.to_dict()["schema_version"] == 1
    assert "tool" not in legacy.to_dict()["nodes"][0]


@pytest.mark.parametrize(
    "options",
    [
        {"tool": "business", "transform": "identity"},
        {"tool": "business", "agent": AgentSpec("a", "x")},
        {"tool": ""},
        {"tool": "business", "config": {"hidden": "data"}},
    ],
)
def test_invalid_tool_node_declarations_reject(options):
    with pytest.raises(ValidationError):
        GraphNode("n", **options)


def test_crash_after_tool_receipt_reuses_confirmed_result(tmp_path):
    # A real installed interpreter exits after the independent receipt commit.
    fixture = Path(__file__).with_name("workflow_tool_crash_fixture.py")
    for mode, expected in [("crash", 77), ("resume", 0)]:
        child = subprocess.run(
            [sys.executable, str(fixture), str(tmp_path), mode], capture_output=True, text=True
        )
        assert child.returncode == expected, child.stderr
        if mode == "resume":
            assert json.loads(child.stdout) == {
                "state": "succeeded",
                "result": {"value": 3},
                "calls": 1,
            }


def test_forged_remote_effect_key_fails_before_approval_or_reservation(tmp_path):
    from ralf_agent import ToolDescriptor, ToolPolicy, register_tool_source

    calls = []

    class Source:
        identity = {"kind": "reserved-key", "version": "1"}

        async def list_tools(self):
            return (
                ToolDescriptor(
                    "write",
                    "Write",
                    {
                        "type": "object",
                        "properties": {"request_id": {"type": "string"}},
                        "required": ["request_id"],
                        "additionalProperties": True,
                    },
                ),
            )

        async def call_tool(self, descriptor, arguments, context):
            calls.append(arguments)
            return arguments

    registry = ToolRegistry()
    asyncio.run(
        register_tool_source(
            registry,
            Source(),
            policies={
                "write": ToolPolicy(
                    "1", effect="idempotent_write", effect_key_argument="request_id"
                )
            },
        )
    )
    with LocalEngine(SQLiteStore(tmp_path / "run.sqlite"), providers={}, tools=registry) as engine:
        flow = GraphWorkflowSpec("reserved", [GraphNode("write", tool="write")])
        handle = engine.submit(flow, {"request_id": "forged"}, command_id="forged")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed" and result.error["code"] == "validation_error"
        assert engine.store.run(handle.run_id)["actions"] == []
        assert engine.diagnostics(handle.run_id).budget["held"] == 0
        assert engine.diagnostics(handle.run_id).budget["spent"] == 0
        assert not calls
