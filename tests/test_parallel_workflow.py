import asyncio
import threading

import pytest

from ralf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    InputMap,
    Literal,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
    ValueRef,
)
from ralf_agent.errors import CoordinatorBusy, ValidationError


def runtime(path, handler=None, *, effect="read_only", approval=False, provider=None, **options):
    tools = ToolRegistry()
    if handler is not None:
        tools.register(
            ToolSpec("work", "Work", {"type": "object"}, effect=effect, requires_approval=approval),
            handler,
        )
    return LocalEngine(
        SQLiteStore(path),
        providers={} if provider is None else {"default": provider},
        tools=tools,
        **options,
    )


def graph(count=2, **options):
    nodes = [GraphNode(f"n{i}", tool="work", input=Literal({"i": i})) for i in range(count)]
    return GraphWorkflowSpec(
        "parallel", nodes, max_concurrency=options.pop("max_concurrency", 2), **options
    )


@pytest.mark.parametrize("limit", [2, 3])
def test_two_workers_overlap_and_capacity_is_never_exceeded(tmp_path, limit):
    async def run():
        active, peak, started = 0, 0, []
        both, release = asyncio.Event(), asyncio.Event()

        async def handler(arguments, ctx):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            started.append(arguments["i"])
            if active == limit:
                both.set()
            await release.wait()
            active -= 1
            return arguments["i"]

        with runtime(tmp_path / "run.db", handler) as engine:
            handle = engine.submit(graph(5, max_concurrency=limit), {}, command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            try:
                await asyncio.wait_for(both.wait(), 2)
                assert started == list(range(limit))
            finally:
                release.set()
            result = await task
            assert result.state == "succeeded" and result.result == {f"n{i}": i for i in range(5)}
            assert peak == limit
            assert engine.diagnostics(handle.run_id).budget["spent"] == 5
            assert not engine._inflight and not engine._parallel_tasks and not engine._locks

    asyncio.run(run())


def test_agent_sessions_are_isolated_and_join_uses_explicit_results(tmp_path):
    class Provider:
        identity = {"kind": "isolated", "version": "1"}

        def __init__(self):
            self.messages = []

        async def complete(self, messages, tools):
            self.messages.append(messages)
            await asyncio.sleep(0)
            return ModelResponse(output=messages[1]["content"])

    provider = Provider()
    spec = GraphWorkflowSpec(
        "agents",
        [
            GraphNode("a", agent=AgentSpec("a", "A"), input=Literal("left")),
            GraphNode("b", agent=AgentSpec("b", "B"), input=Literal("right")),
            GraphNode(
                "join",
                transform="identity",
                depends_on=("a", "b"),
                input=InputMap({"a": ValueRef("a"), "b": ValueRef("b")}),
            ),
        ],
        max_concurrency=2,
        output=ValueRef("join"),
    )
    with runtime(tmp_path / "run.db", provider=provider) as engine:
        handle = engine.submit(spec, {}, command_id="s", session_id="conversation")
        assert asyncio.run(engine.drive(handle.run_id)).result == {"a": "left", "b": "right"}
        assert all(len(messages) == 2 for messages in provider.messages)
        assert engine.sessions.read(engine.scope, "conversation")[1] == []
        assert len(engine.sessions.read(engine.scope, "conversation:node:a")[1]) == 1
        assert len(engine.sessions.read(engine.scope, "conversation:node:b")[1]) == 1


def test_multiple_approvals_restart_and_replay_share_one_run(tmp_path):
    calls = []

    async def handler(arguments, ctx):
        calls.append((arguments["i"], ctx.effect_key))
        return arguments["i"]

    path = tmp_path / "run.db"
    with runtime(path, handler, effect="unqueryable_write", approval=True) as engine:
        handle = engine.submit(graph(), {}, command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "waiting_approval" and len(result.pending) == 2 and not calls
        for i, action in enumerate(result.pending):
            receipt = engine.approve(
                handle.run_id, action["action_id"], action["digest"], command_id=f"a{i}"
            )
            assert (
                engine.approve(
                    handle.run_id, action["action_id"], action["digest"], command_id=f"a{i}"
                )
                == receipt
            )
    with runtime(path, handler, effect="unqueryable_write", approval=True) as engine:
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "succeeded" and result.result == {"n0": 0, "n1": 1}
        assert asyncio.run(engine.drive(handle.run_id)) == result
    assert len(calls) == 2 and len({key for _, key in calls}) == 2


def test_unknown_branch_does_not_block_independent_branch_or_repeat_write(tmp_path):
    calls = []

    async def handler(arguments, ctx):
        calls.append(arguments["i"])
        if arguments["i"] == 0:
            raise RuntimeError("lost")
        return 1

    with runtime(tmp_path / "run.db", handler, effect="unqueryable_write") as engine:
        handle = engine.submit(graph(), {}, command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "waiting_reconciliation"
        nodes = engine.diagnostics(handle.run_id).workflow["nodes"]
        assert nodes["n1"]["state"] == "completed" and nodes["n1"]["result"] == 1
        asyncio.run(engine.drive(handle.run_id))
        assert calls == [0, 1]
        action = next(
            a
            for a in engine.store.run(handle.run_id)["actions"]
            if a["status"] == "outcome_unknown"
        )
        engine.reconcile(handle.run_id, action["id"], 0, command_id="r")
        assert asyncio.run(engine.drive(handle.run_id)).result == {"n0": 0, "n1": 1}


def test_failure_stops_new_work_and_keeps_started_effect_evidence(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def handler(arguments, ctx):
            calls.append(arguments["i"])
            if arguments["i"] == 0:
                await asyncio.wait_for(started.wait(), 2)
                return "bad"
            started.set()
            await release.wait()
            return 1

        with runtime(tmp_path / "run.db", handler) as engine:
            spec = GraphWorkflowSpec(
                "failure",
                [
                    GraphNode(
                        "n0",
                        tool="work",
                        input=Literal({"i": 0}),
                        output_schema={"type": "integer"},
                    ),
                    GraphNode("n1", tool="work", input=Literal({"i": 1})),
                    GraphNode("n2", tool="work", input=Literal({"i": 2})),
                ],
                max_concurrency=2,
            )
            handle = engine.submit(spec, {}, command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 3)
            for _ in range(20):
                await asyncio.sleep(0)
            assert not task.done()
            with pytest.raises(ValidationError):
                engine.close()
            release.set()
            result = await task
            assert result.state == "failed" and calls == [0, 1]
            actions = engine.store.run(handle.run_id)["actions"]
            assert any(a.get("result") == 1 and a["status"] == "completed" for a in actions)

    asyncio.run(run())


def test_parallel_budget_is_reserved_atomically(tmp_path):
    calls = []

    async def handler(arguments, ctx):
        calls.append(arguments["i"])
        await asyncio.sleep(0)
        return arguments["i"]

    with runtime(tmp_path / "run.db", handler) as engine:
        handle = engine.submit(graph(3), {}, command_id="s", budget=1)
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed" and result.error["code"] == "budget_exceeded"
        assert calls == [0]
        budget = engine.diagnostics(handle.run_id).budget
        assert budget["spent"] == 1 and budget["held"] == 0


def test_cancelled_caller_retains_workers_and_blocks_recovery(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        count = 0

        async def handler(arguments, ctx):
            nonlocal count
            count += 1
            if count == 2:
                started.set()
            await release.wait()
            return arguments["i"]

        with runtime(tmp_path / "run.db", handler) as engine:
            handle = engine.submit(graph(3), {}, command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(CoordinatorBusy):
                await engine.drive(handle.run_id)
            with pytest.raises(ValidationError):
                engine.close()
            supervisor = engine._inflight[handle.run_id]
            release.set()
            await asyncio.shield(supervisor)
            assert (await engine.drive(handle.run_id)).state == "cancelled" and count == 2
            assert all(
                a["status"] == "completed" for a in engine.store.run(handle.run_id)["actions"]
            )

    asyncio.run(run())


def test_bulk_task_cancel_still_tracks_real_sync_handler(tmp_path):
    started, release = threading.Event(), threading.Event()

    def handler(arguments, ctx):
        started.set()
        release.wait(5)
        return arguments

    engine = runtime(tmp_path / "run.db", handler)
    handle = engine.submit(graph(), {}, command_id="s")
    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(engine.drive(handle.run_id))
        loop.run_until_complete(asyncio.to_thread(started.wait, 2))
        assert started.is_set()
        for pending in asyncio.all_tasks(loop):
            pending.cancel()
        loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True))
        assert task.done()
        with pytest.raises(ValidationError):
            engine.close()
        with pytest.raises(CoordinatorBusy):
            loop.run_until_complete(engine.drive(handle.run_id))
    finally:
        release.set()
        loop.run_until_complete(engine.wait_for_threads())
        engine.close()
        loop.close()


@pytest.mark.parametrize("attack", ["wrong-input", "early-join", "oversized", "mutate-identity"])
def test_bad_scheduler_cannot_start_effects(tmp_path, attack):
    from ralf_agent import StaticWorkflowScheduler, WorkflowBatch, WorkflowSelection

    calls = []

    class Bad(StaticWorkflowScheduler):
        identity = {"kind": "bad", "version": "1"}

        def select(self, plan, input, states, limit):
            if attack == "mutate-identity":
                self.identity = {"kind": "bad", "version": "2"}
                return super().select(plan, input, states, limit)
            if attack == "oversized":
                return WorkflowBatch([WorkflowSelection(f"n{i}", {"i": i}) for i in range(3)])
            return WorkflowBatch(
                [WorkflowSelection("join" if attack == "early-join" else "n0", {})]
            )

    async def handler(arguments, ctx):
        calls.append(1)
        return arguments

    with runtime(tmp_path / "run.db", handler, workflow_scheduler=Bad()) as engine:
        handle = engine.submit(graph(3), {}, command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed" and not calls
        assert engine.store.run(handle.run_id)["actions"] == []


def test_manual_reconciliation_updates_agent_context_while_sibling_waits(tmp_path):
    from ralf_agent import ToolCall

    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        class Provider:
            identity = {"kind": "reconcile-context", "version": "1"}

            async def complete(self, messages, tools):
                if not any(m["role"] == "tool" for m in messages):
                    return ModelResponse(tool_calls=(ToolCall("work", {"i": 0}),))
                tool = next(m for m in messages if m["role"] == "tool")
                return ModelResponse(output=tool["content"])

        async def handler(arguments, ctx):
            calls.append(arguments["i"])
            if arguments["i"] == 0:
                raise RuntimeError("lost")
            started.set()
            await release.wait()
            return 1

        with runtime(
            tmp_path / "run.db", handler, effect="unqueryable_write", provider=Provider()
        ) as engine:
            spec = GraphWorkflowSpec(
                "context",
                [
                    GraphNode("agent", agent=AgentSpec("a", "A", tools=("work",))),
                    GraphNode("sibling", tool="work", input=Literal({"i": 1})),
                ],
                max_concurrency=2,
            )
            handle = engine.submit(spec, "task", command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 2)
            for _ in range(40):
                await asyncio.sleep(0)
                unknown = next(
                    (
                        a
                        for a in engine.store.run(handle.run_id)["actions"]
                        if a["status"] == "outcome_unknown"
                    ),
                    None,
                )
                if unknown:
                    break
            assert unknown is not None
            engine.reconcile(handle.run_id, unknown["id"], {"confirmed": True}, command_id="r")
            release.set()
            await task
            result = await engine.drive(handle.run_id)
            assert result.state == "succeeded" and result.result["agent"] == '{"confirmed":true}'
            assert sorted(calls) == [0, 1]

    asyncio.run(run())


def test_approved_branch_during_sibling_call_remains_resumable(tmp_path):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def slow(arguments, ctx):
            started.set()
            await release.wait()
            return 1

        tools = ToolRegistry()
        tools.register(ToolSpec("slow", "Slow", {"type": "object"}), slow)
        tools.register(
            ToolSpec(
                "write",
                "Write",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            lambda a, c: 2,
        )
        with LocalEngine(SQLiteStore(tmp_path / "run.db"), providers={}, tools=tools) as engine:
            spec = GraphWorkflowSpec(
                "control",
                [GraphNode("slow", tool="slow"), GraphNode("write", tool="write")],
                max_concurrency=2,
            )
            handle = engine.submit(spec, {}, command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 2)
            for _ in range(20):
                await asyncio.sleep(0)
                pending = engine.status(handle.run_id).pending
                if pending:
                    break
            action = pending[0]
            engine.approve(
                handle.run_id, action["action_id"], action["digest"], command_id="approve"
            )
            release.set()
            await task
            assert (await engine.drive(handle.run_id)).result == {"slow": 1, "write": 2}

    asyncio.run(run())


@pytest.mark.parametrize(
    "window",
    [
        "model_response_recorded",
        "tool_receipt_recorded",
        "workflow_node_completed",
        "session_append",
        "external_commit",
    ],
)
def test_parallel_real_process_crash_windows(window, tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    fixture = Path(__file__).with_name("parallel_crash_fixture.py")
    for mode, expected in [("crash", 77), ("resume", 0)]:
        child = subprocess.run(
            [sys.executable, str(fixture), str(tmp_path), window, mode],
            capture_output=True,
            text=True,
            env={"PATH": os.defpath},
            timeout=15,
        )
        assert child.returncode == expected, child.stderr
        if mode == "resume":
            data = json.loads(child.stdout)
            assert data["state"] == "succeeded" and data["effects"] == 2
            assert data["result"] == {"n0": {"i": 0}, "n1": {"i": 1}}
            assert data["model_calls"] == (5 if window == "model_response_recorded" else 4)


@pytest.mark.parametrize("parallel_first", [True, False])
def test_parallel_branch_sessions_are_reserved_on_acceptance(tmp_path, parallel_first):
    with runtime(tmp_path / "run.db", lambda a, c: a) as engine:
        parallel = graph()
        serial = GraphWorkflowSpec("serial", [GraphNode("a", transform="identity")])
        if parallel_first:
            engine.submit(parallel, {}, command_id="p", session_id="chat")
            with pytest.raises(ValidationError, match="Session"):
                engine.submit(serial, {}, command_id="s", session_id="chat:node:n0")
        else:
            engine.submit(serial, {}, command_id="s", session_id="chat:node:n0")
            with pytest.raises(ValidationError, match="Session"):
                engine.submit(parallel, {}, command_id="p", session_id="chat")


def test_parallel_agent_calls_really_overlap(tmp_path):
    async def run():
        count = 0
        both = asyncio.Event()

        class Provider:
            identity = {"kind": "parallel-barrier", "version": "1"}

            async def complete(self, messages, tools):
                nonlocal count
                count += 1
                if count == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 2)
                return ModelResponse(output=messages[1]["content"])

        with runtime(tmp_path / "run.db", provider=Provider()) as engine:
            spec = GraphWorkflowSpec(
                "overlap",
                [
                    GraphNode("a", agent=AgentSpec("a", "A")),
                    GraphNode("b", agent=AgentSpec("b", "B")),
                ],
                max_concurrency=2,
            )
            handle = engine.submit(spec, "task", command_id="s")
            assert (await engine.drive(handle.run_id)).state == "succeeded" and count == 2

    asyncio.run(run())


def test_rejected_parallel_approval_closes_other_branches(tmp_path):
    with runtime(
        tmp_path / "run.db", lambda a, c: a, effect="unqueryable_write", approval=True
    ) as engine:
        handle = engine.submit(graph(), {}, command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        action = result.pending[0]
        engine.approve(
            handle.run_id,
            action["action_id"],
            action["digest"],
            command_id="reject",
            approved=False,
        )
        states = engine.diagnostics(handle.run_id).workflow["nodes"]
        assert all(s["state"] in {"failed", "cancelled"} for s in states.values())
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"


def test_parallel_conditional_join_uses_skipped_default(tmp_path):
    from ralf_agent import BranchCondition

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
        max_concurrency=2,
        output=ValueRef("join"),
    )
    with runtime(tmp_path / "run.db") as engine:
        handle = engine.submit(spec, "right", command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).result == {"left": None, "right": "right"}
        assert engine.diagnostics(handle.run_id).workflow["nodes"]["left"]["state"] == "skipped"
