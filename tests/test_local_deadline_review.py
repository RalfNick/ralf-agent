"""Focused regressions found by independent review of Local deadline admission."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    Runtime,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.dag_planning import DAGNode, DAGProposal
from relf_agent.errors import ExecutionHostFailed
from relf_agent.governance import LocalExecutionPolicy
from relf_agent.orchestration_types import ChildCall, DynamicWorkflowSpec, TeamSelection, TeamSpec
from relf_agent.planning import PlanProposal

from .helpers import ScriptedProvider, tool_response


def test_expired_team_selection_cannot_admit_a_new_child_run(tmp_path, monkeypatch):
    import relf_agent.local_deadlines as deadlines

    clock = [1000000000.0]
    monkeypatch.setattr(deadlines, "time", SimpleNamespace(time=lambda: clock[0]))

    class SlowSelection:
        identity = {"kind": "selection-across-original-deadline", "version": "1"}

        def select(self, request):
            # A valid synchronous strategy can take time while no timer Task
            # gets a chance to run. Its result must pass the original cutoff.
            clock[0] += 31
            return TeamSelection([ChildCall("worker", "worker", request.task)])

    provider = ScriptedProvider([ModelResponse(output="must not dispatch")])
    with LocalEngine(
        SQLiteStore(tmp_path / "selection.sqlite"),
        providers={"default": provider},
        tools=ToolRegistry(),
        team_strategies={"slow": SlowSelection()},
        execution_policy=LocalExecutionPolicy(run_timeout_seconds=30),
    ) as engine:
        handle = engine.submit(
            TeamSpec("team", {"worker": AgentSpec("worker", "Answer")}, strategy="slow"),
            "task",
            command_id="original",
        )
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "cancelled"
        assert snapshot.error["code"] == "deadline_exceeded"
        assert provider.calls == 0
        assert engine.store.run(handle.run_id)["orchestration"]["children"] == []
        assert not any(event.kind == "child_submitted" for event in engine.events(handle.run_id))
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}


@pytest.mark.parametrize("mode", ["flat", "dag"])
def test_expired_planner_result_cannot_adopt_a_revision_or_admit_a_child(
    tmp_path, monkeypatch, mode
):
    import relf_agent.local_deadlines as deadlines

    clock = [1000000000.0]
    monkeypatch.setattr(deadlines, "time", SimpleNamespace(time=lambda: clock[0]))

    class SlowPlanner:
        identity = {"kind": "planning-across-original-deadline", "version": "1"}

        async def plan(self, request, caller):
            clock[0] += 31
            if mode == "dag":
                return DAGProposal([DAGNode("work", "worker")])
            return PlanProposal([ChildCall("work", "worker", request.task)])

    provider = ScriptedProvider([ModelResponse(output="must not dispatch")])
    with LocalEngine(
        SQLiteStore(tmp_path / "planning.sqlite"),
        providers={"default": provider},
        tools=ToolRegistry(),
        planners={"slow": SlowPlanner()},
        execution_policy=LocalExecutionPolicy(run_timeout_seconds=30),
    ) as engine:
        handle = engine.submit(
            DynamicWorkflowSpec(
                "plan", {"worker": AgentSpec("worker", "Answer")}, planner="slow", plan_mode=mode
            ),
            "task",
            command_id="original",
        )
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "cancelled"
        assert snapshot.error["code"] == "deadline_exceeded"
        assert provider.calls == 0
        assert engine.store.run(handle.run_id)["orchestration"]["children"] == []
        assert not any(
            event.kind in {"child_submitted", "plan_revision_adopted", "dag_revision_adopted"}
            for event in engine.events(handle.run_id)
        )
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}


def test_child_admission_rechecks_cutoff_after_the_store_transaction_is_acquired(
    tmp_path, monkeypatch
):
    import relf_agent.local_deadlines as deadlines

    clock = [1000000000.0]
    monkeypatch.setattr(deadlines, "time", SimpleNamespace(time=lambda: clock[0]))

    class DelayedTransactionStore(SQLiteStore):
        delay_next_transaction = False

        @contextmanager
        def transaction(self):
            if not self.conn.in_transaction and self.delay_next_transaction:
                # Acquiring a synchronous Store transaction can wait for
                # another writer while the event loop and timer are blocked.
                clock[0] += 31
                self.delay_next_transaction = False
            with super().transaction():
                yield

    store = DelayedTransactionStore(tmp_path / "transaction.sqlite")

    class Planner:
        identity = {"kind": "planning-before-transaction-delay", "version": "1"}
        agent = AgentSpec("planner", "Plan the task")

        async def plan(self, request, caller):
            store.delay_next_transaction = True
            await caller.call("plan", "@planner", request.task)
            return None

    provider = ScriptedProvider([ModelResponse(output="must not dispatch")])
    with LocalEngine(
        store,
        providers={"default": provider},
        tools=ToolRegistry(),
        planners={"selected": Planner()},
        execution_policy=LocalExecutionPolicy(run_timeout_seconds=30),
    ) as engine:
        handle = engine.submit(
            DynamicWorkflowSpec(
                "dynamic", {"worker": AgentSpec("worker", "Answer")}, planner="selected"
            ),
            "task",
            command_id="original",
        )
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "cancelled"
        assert snapshot.error["code"] == "deadline_exceeded"
        assert provider.calls == 0
        assert engine.store.run(handle.run_id)["orchestration"]["children"] == []
        assert not any(event.kind == "child_submitted" for event in engine.events(handle.run_id))


def test_cancelled_deadline_host_is_reported_while_the_engine_is_still_open(tmp_path):
    async def scenario():
        effects = []
        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "change",
                "Change",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            lambda arguments, context: effects.append(context.effect_key),
        )
        raw = LocalEngine(
            SQLiteStore(tmp_path / "host-cancel.sqlite"),
            providers={"default": ScriptedProvider([tool_response()])},
            tools=tools,
            execution_policy=LocalExecutionPolicy(approval_timeout_seconds=60),
        )
        runtime = Runtime(raw, owned=True)
        try:
            run = await runtime.create_agent(AgentSpec("agent", "Change", ("change",))).submit(
                "task", command_id="original"
            )
            assert (await run.wait(wait_timeout=1)).snapshot.state == "waiting_approval"
            original = raw.store.run(run.ref.run_id)
            observer = raw._deadline_tasks[run.ref.run_id][0]
            # Host-wide cancellation can cancel an observer while no business
            # drive is active. This is not the Engine's intentional close path.
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
            await asyncio.sleep(0)
            assert raw._lifecycle == "open"
            with pytest.raises(ExecutionHostFailed):
                await run.wait(wait_timeout=0, terminal_only=True)
            assert (await run.diagnostics()).workflow["local_deadlines"]["host_failure"]
            assert raw.store.run(run.ref.run_id)["local_deadlines"] == original["local_deadlines"]
            assert effects == []
        finally:
            await runtime.aclose(close_timeout=2)

    asyncio.run(scenario())
