"""Persistent business deadlines retain original work and effect obligations."""

import asyncio
import copy
import threading
import time
from dataclasses import FrozenInstanceError

import pytest

from ralf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from ralf_agent.errors import (
    CoordinatorBusy,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from ralf_agent.governance import LocalExecutionPolicy
from ralf_agent.orchestration_types import DynamicWorkflowSpec, TeamSpec
from ralf_agent.types import submission_request

from .helpers import ScriptedProvider, tool_response


def make_engine(path, provider=None, tools=None, **options):
    return LocalEngine(
        SQLiteStore(path),
        providers={"default": provider or ScriptedProvider([])},
        tools=ToolRegistry() if tools is None else tools,
        **options,
    )


def write_tools(handler, *, approval=False):
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change",
            "Change a business value",
            {"type": "object"},
            effect="unqueryable_write",
            requires_approval=approval,
        ),
        handler,
    )
    return tools


async def eventually(predicate, *, max_wait_seconds=3):
    expires = asyncio.get_running_loop().time() + max_wait_seconds
    while not predicate():
        if asyncio.get_running_loop().time() >= expires:
            pytest.fail("Original authority did not reach the expected deadline checkpoint")
        await asyncio.sleep(0.002)


@pytest.mark.parametrize("field", ["run_timeout_seconds", "approval_timeout_seconds"])
@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), 86401, "1"])
def test_deadline_policy_rejects_invalid_relative_times(field, value):
    with pytest.raises(ValidationError):
        LocalExecutionPolicy(**{field: value})


def test_deadline_policy_is_immutable_and_identity_is_detached():
    policy = LocalExecutionPolicy(run_timeout_seconds=1, approval_timeout_seconds=2)
    with pytest.raises(FrozenInstanceError):
        policy.run_timeout_seconds = 3
    original = copy.deepcopy(policy.identity)
    identity = policy.identity
    identity["run_timeout_seconds"] = 99
    assert policy.identity == original
    assert policy.identity["kind"] == "local-execution-policy"


def test_omitted_deadlines_preserve_request_manifest_and_original_schema(tmp_path):
    spec = AgentSpec("agent", "Answer")
    request = submission_request(spec, "task")
    assert set(request) == {"definition", "input", "budget", "session_id"}
    with make_engine(tmp_path / "default.sqlite") as engine:
        handle = engine.submit(spec, "task", command_id="submit")
        run = engine.store.run(handle.run_id)
        assert "local_deadlines" not in run
        assert "local_deadline_protocol" not in run["manifest"]
        assert "execution_policy" not in run["manifest"]
        assert (
            engine.store.conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()[0]
            == "1"
        )


@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), "1"])
def test_invalid_explicit_deadline_is_refused_before_acceptance(tmp_path, value):
    provider = ScriptedProvider([])
    with make_engine(tmp_path / "invalid.sqlite", provider) as engine:
        with pytest.raises(ValidationError):
            engine.submit(AgentSpec("agent", "Answer"), "task", command_id="s", deadline_at=value)
        assert provider.calls == 0
        assert engine.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_submission_retry_keeps_original_time_and_receipt_after_policy_moves(tmp_path):
    path = tmp_path / "dedupe.sqlite"
    spec = AgentSpec("agent", "Answer")
    deadline = time.time() + 60
    with make_engine(path, execution_policy=LocalExecutionPolicy(run_timeout_seconds=30)) as engine:
        original = engine.submit(spec, "task", command_id="s", deadline_at=deadline)
        accepted = copy.deepcopy(engine.store.run(original.run_id))
    with make_engine(path, execution_policy=LocalExecutionPolicy(run_timeout_seconds=50)) as engine:
        assert engine.submit(spec, "task", command_id="s", deadline_at=deadline) == original
        restored = engine.store.run(original.run_id)
        assert restored["local_deadlines"] == accepted["local_deadlines"]
        assert restored["manifest"] == accepted["manifest"]
        assert len(engine.events(original.run_id)) == 1
        with pytest.raises(IdempotencyConflict):
            engine.submit(spec, "task", command_id="s", deadline_at=deadline + 1)
        with pytest.raises(IdempotencyConflict):
            engine.submit(spec, "task", command_id="s")


def test_past_explicit_deadline_accepts_receipt_but_never_dispatches(tmp_path):
    provider = ScriptedProvider([ModelResponse(output="must not run")])
    with make_engine(tmp_path / "past.sqlite", provider) as engine:
        handle = engine.submit(
            AgentSpec("agent", "Answer"), "task", command_id="s", deadline_at=time.time() - 1
        )
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "cancelled"
        assert snapshot.error["code"] == "deadline_exceeded"
        assert provider.calls == 0
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}


@pytest.mark.parametrize("late_failure", [False, True])
def test_active_model_expires_without_cancelling_original_call_or_adopting_tools(
    tmp_path, late_failure
):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        effects = []

        class HeldProvider:
            identity = {"kind": "deadline-held-model", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                if late_failure:
                    raise ConnectionError("Lost response after the original deadline")
                return tool_response()

        engine = make_engine(
            tmp_path / "model.sqlite",
            HeldProvider(),
            write_tools(lambda args, ctx: effects.append(ctx.effect_key)),
            execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.15),
        )
        task = None
        try:
            handle = engine.submit(
                AgentSpec("agent", "Answer", ("change",)), "task", command_id="s"
            )
            task = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 2)
            await eventually(lambda: engine.status(handle.run_id).error is not None)
            snapshot = engine.status(handle.run_id)
            assert snapshot.state == "cancelling"
            assert snapshot.error["code"] == "deadline_exceeded"
            assert not task.done()
            assert engine.store.budget(handle.run_id)["held"] == 1
            with pytest.raises(ValidationError):
                engine.close()
            release.set()
            done = await asyncio.wait_for(asyncio.shield(task), 3)
            assert done.state == "cancelled"
            assert done.error["code"] == "deadline_exceeded"
            assert done.result is None
            assert effects == []
            assert not any(action["kind"] == "tool" for action in done.actions)
            budget = engine.store.budget(handle.run_id)
            assert budget["held"] == (1 if late_failure else 0)
            assert budget["spent"] == (0 if late_failure else 1)
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await engine.wait_for_threads()
            engine.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["team", "dynamic", "nested"])
def test_paused_child_approval_expiry_closes_parent_and_settles_original_escrow(tmp_path, kind):
    async def scenario():
        effects = []
        worker = AgentSpec("worker", "Change", ("change",))
        if kind == "team":
            definition = TeamSpec("team", {"worker": worker}, child_budget=4)
        elif kind == "dynamic":
            definition = DynamicWorkflowSpec("dynamic", {"worker": worker}, child_budget=4)
        else:
            definition = TeamSpec(
                "outer",
                {"inner": TeamSpec("inner", {"worker": worker}, child_budget=4)},
                child_budget=8,
            )
        engine = make_engine(
            tmp_path / f"approval-{kind}.sqlite",
            ScriptedProvider([tool_response()]),
            write_tools(lambda args, ctx: effects.append(ctx.effect_key), approval=True),
            execution_policy=LocalExecutionPolicy(approval_timeout_seconds=0.1),
        )
        try:
            handle = engine.submit(definition, "task", command_id="s", budget=16)
            assert (await engine.drive(handle.run_id)).state == "waiting_approval"
            assert engine.store.budget(handle.run_id)["held"] > 0
            await eventually(lambda: engine.status(handle.run_id).state == "failed")
            pending = [handle.run_id]
            while pending:
                current = engine.store.run(pending.pop())
                assert current["state"] == "failed"
                assert engine.store.budget(current["id"])["held"] == 0
                for child in current.get("orchestration", {}).get("children", []):
                    assert child["settled"] is True
                    pending.append(child["run_id"])
            assert effects == []
            assert engine.store.budget(handle.run_id)["spent"] == 1
        finally:
            engine.close()

    asyncio.run(scenario())


def test_changed_policy_refuses_resume_without_replacing_original_deadline(tmp_path):
    provider = ScriptedProvider([ModelResponse(output="must not run")])
    original = LocalExecutionPolicy(run_timeout_seconds=1)
    with make_engine(
        tmp_path / "policy-drift.sqlite", provider, execution_policy=original
    ) as engine:
        handle = engine.submit(AgentSpec("agent", "Answer"), "task", command_id="s")
        pinned = copy.deepcopy(engine.store.run(handle.run_id)["local_deadlines"])
        engine.execution_policy = LocalExecutionPolicy(run_timeout_seconds=2)
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(handle.run_id))
        assert provider.calls == 0
        assert engine.store.run(handle.run_id)["local_deadlines"] == pinned


def test_changed_store_preparation_binding_refuses_resume_before_dispatch(tmp_path):
    provider = ScriptedProvider([ModelResponse(output="must not run")])
    with make_engine(
        tmp_path / "store-drift.sqlite",
        provider,
        execution_policy=LocalExecutionPolicy(run_timeout_seconds=1),
    ) as engine:
        handle = engine.submit(AgentSpec("agent", "Answer"), "task", command_id="s")
        pinned = copy.deepcopy(engine.store.run(handle.run_id)["local_deadlines"])
        engine.store.prepare_local_deadlines = lambda: None
        with pytest.raises(DefinitionMismatch):
            asyncio.run(engine.drive(handle.run_id))
        assert provider.calls == 0
        assert engine.store.run(handle.run_id)["local_deadlines"] == pinned


@pytest.mark.parametrize("capability", ["missing", "lazy"])
def test_explicit_deadlines_reject_unavailable_or_lazy_store_capability(tmp_path, capability):
    class StoreProxy:
        def __init__(self, original):
            self.original = original

        def __getattr__(self, name):
            if name in {"local_deadline_version", "prepare_local_deadlines"}:
                raise AttributeError(name)
            return getattr(self.original, name)

    class LazyStoreProxy(StoreProxy):
        local_deadline_version = 1

        def prepare_local_deadlines(self):
            yield None

    with SQLiteStore(tmp_path / "unsupported.sqlite") as store:
        proxy = StoreProxy(store) if capability == "missing" else LazyStoreProxy(store)
        with pytest.raises(ValidationError):
            LocalEngine(
                proxy,
                providers={},
                tools=ToolRegistry(),
                execution_policy=LocalExecutionPolicy(run_timeout_seconds=1),
            )
        assert store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize("late_failure", [False, True])
def test_expired_sync_handler_retains_actual_thread_and_coordinator(tmp_path, late_failure):
    async def scenario():
        started, release, ended = threading.Event(), threading.Event(), threading.Event()

        def change(arguments, context):
            started.set()
            try:
                assert release.wait(5), "Test barrier was not released"
                if late_failure:
                    raise ConnectionError("Write acknowledgement unavailable")
                return {"changed": True}
            finally:
                ended.set()

        path = tmp_path / "thread.sqlite"
        engine = make_engine(
            path,
            ScriptedProvider([tool_response()]),
            write_tools(change),
            execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.2),
        )
        task = None
        try:
            handle = engine.submit(
                AgentSpec("agent", "Change", ("change",)), "task", command_id="s"
            )
            task = asyncio.create_task(engine.drive(handle.run_id))
            await eventually(started.is_set)
            await eventually(lambda: engine.status(handle.run_id).error is not None)
            assert engine.status(handle.run_id).state == "cancelling"
            assert not ended.is_set() and not task.done()
            assert engine._threads.has_active_for(handle.run_id)
            assert engine.store.budget(handle.run_id)["held"] == 1
            with pytest.raises(ValidationError):
                engine.close()
            with SQLiteStore(path) as contender_store:
                with pytest.raises(CoordinatorBusy):
                    LocalEngine(contender_store, providers={}, tools=ToolRegistry())
            release.set()
            done = await asyncio.wait_for(asyncio.shield(task), 3)
            assert ended.is_set() and not engine._threads.has_active_for(handle.run_id)
            assert done.state == "cancelled" and done.error["code"] == "deadline_exceeded"
            assert done.result is None
            assert engine.store.budget(handle.run_id)["held"] == (1 if late_failure else 0)
            assert done.actions[-1]["status"] == (
                "outcome_unknown" if late_failure else "completed"
            )
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await engine.wait_for_threads()
            engine.close()
        with make_engine(path) as successor:
            assert successor.status(handle.run_id).state == "cancelled"

    asyncio.run(scenario())


def test_approval_expiry_is_written_once_and_runs_while_paused(tmp_path):
    async def scenario():
        effects = []
        engine = make_engine(
            tmp_path / "approval.sqlite",
            ScriptedProvider([tool_response()]),
            write_tools(lambda args, ctx: effects.append(ctx.effect_key), approval=True),
            execution_policy=LocalExecutionPolicy(approval_timeout_seconds=0.2),
        )
        try:
            handle = engine.submit(
                AgentSpec("agent", "Change", ("change",)), "task", command_id="s"
            )
            waiting = await engine.drive(handle.run_id)
            assert waiting.state == "waiting_approval"
            action = engine.store.run(handle.run_id)["actions"][-1]
            requested, expires = action["approval_requested_at"], action["approval_expires_at"]
            assert expires == pytest.approx(requested + 0.2)
            await asyncio.sleep(0.02)
            await engine.drive(handle.run_id)
            assert engine.store.run(handle.run_id)["actions"][-1]["approval_expires_at"] == expires
            await eventually(lambda: engine.status(handle.run_id).state == "failed")
            assert engine.status(handle.run_id).error["code"] == "approval_expired"
            receipt = engine.approve(
                handle.run_id, action["id"], action["digest"], command_id="late"
            )
            assert receipt.apply_state == "rejected"
            assert (
                engine.approve(handle.run_id, action["id"], action["digest"], command_id="late")
                == receipt
            )
            assert effects == []
        finally:
            engine.close()

    asyncio.run(scenario())


def test_cold_approval_expiry_retains_original_times_and_rejects_late_command(tmp_path):
    path = tmp_path / "cold.sqlite"
    policy = LocalExecutionPolicy(approval_timeout_seconds=0.05)
    tools = write_tools(lambda args, ctx: args, approval=True)
    with make_engine(
        path, ScriptedProvider([tool_response()]), tools, execution_policy=policy
    ) as engine:
        handle = engine.submit(AgentSpec("agent", "Change", ("change",)), "task", command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).state == "waiting_approval"
        original = copy.deepcopy(engine.store.run(handle.run_id)["actions"][-1])
    time.sleep(0.08)
    with make_engine(path, ScriptedProvider([]), tools, execution_policy=policy) as engine:
        receipt = engine.approve(
            handle.run_id, original["id"], original["digest"], command_id="late"
        )
        assert receipt.apply_state == "rejected"
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "failed" and snapshot.error["code"] == "approval_expired"
        restored = engine.store.run(handle.run_id)["actions"][-1]
        assert restored["approval_requested_at"] == original["approval_requested_at"]
        assert restored["approval_expires_at"] == original["approval_expires_at"]
        assert not restored["attempts"]


def test_old_approved_command_receipt_is_not_reinterpreted_after_expiry_time(tmp_path):
    path = tmp_path / "approved.sqlite"
    policy = LocalExecutionPolicy(approval_timeout_seconds=0.05)
    tools = write_tools(lambda args, ctx: args, approval=True)
    with make_engine(
        path, ScriptedProvider([tool_response()]), tools, execution_policy=policy
    ) as engine:
        handle = engine.submit(AgentSpec("agent", "Change", ("change",)), "task", command_id="s")
        pending = asyncio.run(engine.drive(handle.run_id)).pending[0]
        receipt = engine.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
        )
        assert receipt.apply_state == "applied"
    time.sleep(0.08)
    with make_engine(path, ScriptedProvider([]), tools, execution_policy=policy) as engine:
        assert (
            engine.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            == receipt
        )
        assert engine.status(handle.run_id).state == "running"
        assert engine.store.run(handle.run_id)["actions"][-1]["status"] == "ready"


def selected_definition(kind):
    first, second = AgentSpec("first", "First"), AgentSpec("second", "Second")
    if kind == "sequence":
        return WorkflowSpec("sequence", (first, second))
    if kind in {"graph", "parallel"}:
        return GraphWorkflowSpec(
            kind,
            [
                GraphNode("first", agent=first),
                GraphNode("second", agent=second, depends_on=("first",)),
            ],
            max_concurrency=2 if kind == "parallel" else 1,
        )
    if kind == "team":
        return TeamSpec("team", {"first": first, "second": second}, child_budget=4)
    if kind == "dynamic":
        return DynamicWorkflowSpec("dynamic", {"first": first, "second": second}, child_budget=4)
    assert kind == "nested"
    return TeamSpec(
        "outer",
        {
            "inner": TeamSpec(
                "inner", {"sequence": WorkflowSpec("sequence", (first, second))}, child_budget=4
            )
        },
        child_budget=8,
    )


@pytest.mark.parametrize("kind", ["sequence", "graph", "parallel", "team", "dynamic", "nested"])
def test_original_parent_deadline_stops_successors_and_is_inherited(tmp_path, kind):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class HeldProvider:
            identity = {"kind": "deadline-orchestration-model", "version": "1"}
            calls = 0

            async def complete(self, messages, tools):
                self.calls += 1
                started.set()
                await release.wait()
                return ModelResponse(output="late")

        provider = HeldProvider()
        engine = make_engine(
            tmp_path / f"{kind}.sqlite",
            provider,
            execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.2),
        )
        task = None
        try:
            handle = engine.submit(selected_definition(kind), "task", command_id="s", budget=16)
            root_expiry = engine.store.run(handle.run_id)["local_deadlines"]["run_expires_at"]
            task = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 2)
            await eventually(lambda: engine.status(handle.run_id).error is not None)
            assert engine.status(handle.run_id).error["code"] == "deadline_exceeded"
            assert not task.done()
            pending = [handle.run_id]
            while pending:
                current = engine.store.run(pending.pop())
                for child in current.get("orchestration", {}).get("children", []):
                    record = engine.store.run(child["run_id"])
                    assert record["local_deadlines"]["parent_run_expires_at"] == root_expiry
                    assert record["local_deadlines"]["run_expires_at"] <= root_expiry
                    pending.append(child["run_id"])
            release.set()
            done = await asyncio.wait_for(asyncio.shield(task), 3)
            assert done.state == "cancelled" and done.error["code"] == "deadline_exceeded"
            assert done.result is None
            assert provider.calls == 1
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await engine.wait_for_threads()
            engine.close()

    asyncio.run(scenario())


def test_parallel_deadline_retains_both_active_branches_and_never_starts_join(tmp_path):
    async def scenario():
        both_started, release = asyncio.Event(), asyncio.Event()

        class HeldProvider:
            identity = {"kind": "deadline-parallel-branches", "version": "1"}
            calls = []

            async def complete(self, messages, tools):
                self.calls.append(messages[0]["content"])
                if len(self.calls) == 2:
                    both_started.set()
                await release.wait()
                return ModelResponse(output="late")

        definition = GraphWorkflowSpec(
            "parallel",
            [
                GraphNode("left", agent=AgentSpec("left", "Left")),
                GraphNode("right", agent=AgentSpec("right", "Right")),
                GraphNode("join", agent=AgentSpec("join", "Join"), depends_on=("left", "right")),
            ],
            max_concurrency=2,
        )
        provider = HeldProvider()
        engine = make_engine(
            tmp_path / "parallel-two.sqlite",
            provider,
            execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.2),
        )
        task = None
        try:
            handle = engine.submit(definition, "task", command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(both_started.wait(), 2)
            await eventually(lambda: engine.status(handle.run_id).error is not None)
            assert engine.status(handle.run_id).state == "cancelling"
            assert engine.store.budget(handle.run_id)["held"] == 2
            assert not task.done()
            with pytest.raises(ValidationError):
                engine.close()
            release.set()
            done = await asyncio.wait_for(asyncio.shield(task), 3)
            assert done.state == "cancelled" and done.error["code"] == "deadline_exceeded"
            assert sorted(provider.calls) == ["Left", "Right"]
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 2}
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await engine.wait_for_threads()
            engine.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["graph", "parallel", "team", "dynamic"])
def test_composite_final_adoption_rechecks_after_a_synchronous_policy(tmp_path, kind):
    from ralf_agent.planning import CompleteVerifier
    from ralf_agent.teams import SequentialTeam
    from ralf_agent.workflow import StaticWorkflowInterpreter
    from ralf_agent.workflow_scheduler import StaticWorkflowScheduler

    class SlowFinalInterpreter(StaticWorkflowInterpreter):
        identity = {"kind": "slow-final-interpreter", "version": "1"}

        def select(self, plan, input, states):
            result = super().select(plan, input, states)
            if result.done:
                time.sleep(0.08)
            return result

    class SlowFinalScheduler(StaticWorkflowScheduler):
        identity = {"kind": "slow-final-scheduler", "version": "1"}

        def select(self, plan, input, states, limit):
            result = super().select(plan, input, states, limit)
            if result.done:
                time.sleep(0.08)
            return result

    class SlowFinalTeam(SequentialTeam):
        identity = {"kind": "slow-final-team", "version": "1"}

        def select(self, request):
            result = super().select(request)
            if result.done:
                time.sleep(0.08)
            return result

    class SlowFinalVerifier(CompleteVerifier):
        identity = {"kind": "slow-final-verifier", "version": "1"}

        def verify(self, request):
            time.sleep(0.08)
            return super().verify(request)

    worker = AgentSpec("worker", "Answer")
    if kind in {"graph", "parallel"}:
        definition = GraphWorkflowSpec(
            kind,
            [GraphNode("worker", agent=worker)],
            max_concurrency=2 if kind == "parallel" else 1,
        )
        options = (
            {"workflow_interpreter": SlowFinalInterpreter()}
            if kind == "graph"
            else {"workflow_scheduler": SlowFinalScheduler()}
        )
    elif kind == "team":
        definition = TeamSpec("team", {"worker": worker}, strategy="slow", child_budget=4)
        options = {"team_strategies": {"slow": SlowFinalTeam()}}
    else:
        definition = DynamicWorkflowSpec(
            "dynamic", {"worker": worker}, verifier="slow", child_budget=4
        )
        options = {"plan_verifiers": {"slow": SlowFinalVerifier()}}
    with make_engine(
        tmp_path / f"final-{kind}.sqlite",
        ScriptedProvider([ModelResponse(output="done")]),
        execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.05),
        **options,
    ) as engine:
        handle = engine.submit(definition, "task", command_id="s")
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "cancelled" and snapshot.error["code"] == "deadline_exceeded"
        assert snapshot.result is None
        assert not any(event.kind == "run_succeeded" for event in engine.events(handle.run_id))


def test_run_expiry_wins_when_approval_is_capped_to_the_same_absolute_time(tmp_path):
    async def scenario():
        engine = make_engine(
            tmp_path / "same-time.sqlite",
            ScriptedProvider([tool_response()]),
            write_tools(lambda args, ctx: args, approval=True),
            execution_policy=LocalExecutionPolicy(
                run_timeout_seconds=0.1, approval_timeout_seconds=5
            ),
        )
        try:
            handle = engine.submit(
                AgentSpec("agent", "Change", ("change",)), "task", command_id="s"
            )
            assert (await engine.drive(handle.run_id)).state == "waiting_approval"
            run = engine.store.run(handle.run_id)
            assert (
                run["actions"][-1]["approval_expires_at"]
                == run["local_deadlines"]["run_expires_at"]
            )
            await eventually(lambda: engine.status(handle.run_id).state in {"failed", "cancelled"})
            snapshot = engine.status(handle.run_id)
            assert snapshot.state == "cancelled"
            assert snapshot.error["code"] == "deadline_exceeded"
        finally:
            engine.close()

    asyncio.run(scenario())


def test_late_response_cannot_adopt_tools_when_the_model_blocked_the_event_loop(tmp_path):
    class BlockingProvider:
        identity = {"kind": "blocking-model-deadline", "version": "1"}

        async def complete(self, messages, tools):
            time.sleep(0.08)  # noqa: ASYNC251 — deliberately block the observer timer.
            return tool_response()

    engine = make_engine(
        tmp_path / "blocked-model.sqlite",
        BlockingProvider(),
        write_tools(lambda args, ctx: args),
        execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.05),
    )
    try:
        handle = engine.submit(AgentSpec("agent", "Change", ("change",)), "task", command_id="s")
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "cancelled" and snapshot.error["code"] == "deadline_exceeded"
        assert snapshot.result is None
        assert not any(action["kind"] == "tool" for action in snapshot.actions)
        assert snapshot.actions[0]["decision_skipped"] is True
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 1}
    finally:
        engine.close()


def test_final_completion_rechecks_after_a_synchronous_session_append(tmp_path):
    class BlockingSessions:
        backend_id = "deadline-blocking-session:1"
        messages = []

        def read(self, scope, session):
            return len(self.messages), list(self.messages)

        def append(self, scope, session, message, *, expected_revision, message_id):
            time.sleep(0.08)
            self.messages.append(message)
            return len(self.messages)

    sessions = BlockingSessions()
    engine = make_engine(
        tmp_path / "blocked-append.sqlite",
        ScriptedProvider([ModelResponse(output="late completion")]),
        session_store=sessions,
        execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.05),
    )
    try:
        handle = engine.submit(AgentSpec("agent", "Answer"), "task", command_id="s")
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert len(sessions.messages) == 1  # The already-started external write is retained.
        assert snapshot.state == "cancelled" and snapshot.error["code"] == "deadline_exceeded"
        assert snapshot.result is None
        assert not any(event.kind == "run_succeeded" for event in engine.events(handle.run_id))
    finally:
        engine.close()


@pytest.mark.parametrize("late_failure", [False, True])
def test_harness_adoption_rechecks_deadline_after_its_synchronous_proposal(tmp_path, late_failure):
    from ralf_agent.harness import NativeHarness

    class SlowHarness(NativeHarness):
        identity = {"kind": "slow-deadline-harness", "version": "1"}

        def propose(self, spec, response):
            time.sleep(0.08)
            if late_failure:
                raise ValidationError("Proposal validation finished after deadline")
            return super().propose(spec, response)

    with make_engine(
        tmp_path / "harness-adoption.sqlite",
        ScriptedProvider([tool_response()]),
        write_tools(lambda args, ctx: args),
        harness=SlowHarness(),
        execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.05),
    ) as engine:
        handle = engine.submit(AgentSpec("agent", "Change", ("change",)), "task", command_id="s")
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "cancelled" and snapshot.error["code"] == "deadline_exceeded"
        assert snapshot.result is None
        assert not any(action["kind"] == "tool" for action in snapshot.actions)


@pytest.mark.parametrize("corruption", ["extended", "missing", "boolean"])
def test_original_approval_time_corruption_is_rejected_before_granting_permission(
    tmp_path, corruption
):
    policy = LocalExecutionPolicy(approval_timeout_seconds=1)
    with make_engine(
        tmp_path / "corrupt-approval.sqlite",
        ScriptedProvider([tool_response()]),
        write_tools(lambda args, ctx: args, approval=True),
        execution_policy=policy,
    ) as engine:
        handle = engine.submit(AgentSpec("agent", "Change", ("change",)), "task", command_id="s")
        pending = asyncio.run(engine.drive(handle.run_id)).pending[0]
        with engine.store.transaction():
            record = engine.store.run(handle.run_id)
            action = record["actions"][-1]
            if corruption == "extended":
                action["approval_expires_at"] += 3600
            elif corruption == "missing":
                action.pop("approval_expires_at")
            else:
                action["approval_requested_at"] = True
            engine.store.save_run(record)
        with pytest.raises((DefinitionMismatch, ValidationError)):
            engine.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
        assert engine.store.run(handle.run_id)["actions"][-1]["approved"] is False


@pytest.mark.parametrize("late_failure", ["invalid_response", "provider_drift"])
def test_late_validation_failure_does_not_replace_the_original_deadline_cause(
    tmp_path, late_failure
):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class HeldProvider:
            identity = {"kind": "late-validation-model", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                await release.wait()
                return (
                    object() if late_failure == "invalid_response" else ModelResponse(output="late")
                )

        provider = HeldProvider()
        engine = make_engine(
            tmp_path / "validation.sqlite",
            provider,
            execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.1),
        )
        task = None
        try:
            handle = engine.submit(AgentSpec("agent", "Answer"), "task", command_id="s")
            task = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(started.wait(), 2)
            await eventually(lambda: engine.status(handle.run_id).error is not None)
            if late_failure == "provider_drift":
                provider.identity = {"kind": "changed-after-expiry", "version": "2"}
            release.set()
            snapshot = await asyncio.wait_for(asyncio.shield(task), 3)
            assert snapshot.state == "cancelled" and snapshot.error["code"] == "deadline_exceeded"
            assert snapshot.result is None
            assert engine.store.budget(handle.run_id)["held"] == (
                1 if late_failure == "invalid_response" else 0
            )
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await engine.wait_for_threads()
            engine.close()

    asyncio.run(scenario())
