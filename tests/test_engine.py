import asyncio

import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    ModelResponse,
    Scope,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from ralf_agent.errors import (
    AuthorizationDenied,
    CoordinatorBusy,
    DefinitionMismatch,
    ValidationError,
)
from ralf_agent.storage import SQLiteStore

from .helpers import ScriptedProvider, tool_response

SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}


def registry(handler, *, effect="unqueryable_write", approval=True, reconciler=None):
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "change", "Change a test value", SCHEMA, effect=effect, requires_approval=approval
        ),
        handler,
        reconciler=reconciler,
    )
    return tools


def engine(path, provider, tools, **kwargs):
    return LocalEngine(SQLiteStore(path), providers={"default": provider}, tools=tools, **kwargs)


def test_cancel_in_model_scheduling_window_prevents_provider_dispatch(tmp_path):
    async def exercise():
        provider = ScriptedProvider([ModelResponse(output="should not run")])
        with engine(tmp_path / "runs.db", provider, ToolRegistry()) as runtime:
            run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.sleep(0)
            runtime.cancel(run.run_id, command_id="cancel")
            await drive
            assert runtime.status(run.run_id).state == "cancelled"
            assert provider.calls == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("delay", range(6))
def test_cancel_cannot_be_overwritten_by_scheduled_approval_wait(tmp_path, delay):
    async def change(args, ctx):
        return args

    async def exercise():
        with engine(
            tmp_path / "runs.db", ScriptedProvider([tool_response()]), registry(change)
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            for _ in range(100):
                if any(e.kind == "decision_adopted" for e in runtime.events(run.run_id)):
                    break
                await asyncio.sleep(0)
            else:
                pytest.fail("Model decision was not adopted")
            for _ in range(delay):
                await asyncio.sleep(0)
            runtime.cancel(run.run_id, command_id="cancel")
            await drive
            assert runtime.status(run.run_id).state == "cancelled"

    asyncio.run(exercise())


@pytest.mark.parametrize("approval", [True, False])
def test_host_policy_cancellation_prevents_approval_or_dispatch(tmp_path, approval):
    effects = []

    def change(args, ctx):
        effects.append(ctx.effect_key)
        return args

    def policy(scope, spec, arguments):
        runtime.cancel(run.run_id, command_id="policy-cancel")

    with engine(
        tmp_path / "policy.db",
        ScriptedProvider([tool_response()]),
        registry(change, approval=approval),
        policy=policy,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "cancelled"
        assert snapshot.error is None
        assert not snapshot.pending
        assert effects == []


@pytest.mark.parametrize("stage", ["context", "result"])
def test_memory_callback_cancellation_cannot_be_overwritten(tmp_path, stage):
    class CancellingMemory(InMemoryMemory):
        def facts(self, scope, namespace):
            if stage == "context":
                runtime.cancel(run.run_id, command_id="memory-cancel")
            return super().facts(scope, namespace)

        def append(self, scope, session_id, message, **kwargs):
            if stage == "result":
                runtime.cancel(run.run_id, command_id="memory-cancel")
            return super().append(scope, session_id, message, **kwargs)

    memory = CancellingMemory(backend_id="test:cancel-memory")
    provider = ScriptedProvider([ModelResponse(output="completed")])
    with engine(
        tmp_path / "memory.db",
        provider,
        ToolRegistry(),
        session_store=memory,
        memory_store=memory,
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
        snapshot = asyncio.run(runtime.drive(run.run_id))
        assert snapshot.state == "cancelled"
        assert snapshot.result is None
        assert snapshot.error is None
        assert provider.calls == (0 if stage == "context" else 1)


def test_approval_and_adopted_decision_survive_restart(tmp_path):
    effects = []

    async def change(args, ctx):
        effects.append(ctx.effect_key)
        return {"changed": args["value"]}

    tools = registry(change)
    path = tmp_path / "runs.db"
    provider = ScriptedProvider([tool_response()])
    with engine(path, provider, tools) as runtime:
        handle = runtime.submit(
            AgentSpec("oncall", "Fix the test incident", ("change",)),
            "incident",
            command_id="start",
        )
        waiting = asyncio.run(runtime.drive(handle.run_id))
        assert waiting.state == "waiting_approval"
        pending = waiting.pending[0]
        assert effects == []
        assert provider.calls == 1

    continuation = ScriptedProvider([ModelResponse(output="verified")])
    with engine(path, continuation, tools) as runtime:
        receipt = runtime.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="approve-1"
        )
        assert receipt.apply_state == "applied"
        runtime.approve(
            handle.run_id, pending["action_id"], pending["digest"], command_id="approve-1"
        )
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded"
        assert done.result == "verified"
        assert len(effects) == 1
        assert continuation.calls == 1
        assert [event.seq for event in handle.events(runtime)] == list(
            range(1, len(handle.events(runtime)) + 1)
        )


def test_invalid_tool_arguments_never_execute(tmp_path):
    effects = []

    async def change(args, ctx):
        effects.append(args)

    provider = ScriptedProvider([tool_response(arguments={"value": "invalid"})])
    with engine(tmp_path / "runs.db", provider, registry(change)) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
        assert asyncio.run(runtime.drive(run.run_id)).state == "failed"
        assert effects == []


def test_unknown_write_is_not_blindly_retried(tmp_path):
    count = []

    async def uncertain(args, ctx):
        count.append(1)
        raise ConnectionError("response lost")

    provider = ScriptedProvider([tool_response()])
    tools = registry(uncertain, approval=False)
    path = tmp_path / "runs.db"
    with engine(path, provider, tools) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
        assert asyncio.run(runtime.drive(run.run_id)).state == "waiting_reconciliation"
        assert runtime.store.budget(run.run_id)["held"] == 1
    with engine(path, ScriptedProvider([]), tools) as runtime:
        assert asyncio.run(runtime.drive(run.run_id)).state == "waiting_reconciliation"
        assert count == [1]


def test_success_wins_over_late_cancel(tmp_path):
    with engine(
        tmp_path / "runs.db", ScriptedProvider([ModelResponse(output="ok")]), ToolRegistry()
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
        assert asyncio.run(runtime.drive(run.run_id)).state == "succeeded"
        receipt = runtime.cancel(run.run_id, command_id="cancel")
        assert receipt.apply_state == "rejected"
        assert receipt.outcome["reason"] == "too_late"
        assert runtime.status(run.run_id).state == "succeeded"


def test_cancel_before_result_prevents_success_and_keeps_effect(tmp_path):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()

        async def change(args, ctx):
            started.set()
            await release.wait()
            return {"changed": True}

        provider = ScriptedProvider([tool_response(), ModelResponse(output="must not happen")])
        with engine(tmp_path / "runs.db", provider, registry(change, approval=False)) as runtime:
            run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
            task = asyncio.create_task(runtime.drive(run.run_id))
            await started.wait()
            assert runtime.cancel(run.run_id, command_id="cancel").apply_state == "applied"
            assert runtime.status(run.run_id).state == "cancelling"
            release.set()
            assert (await task).state == "cancelled"
            assert provider.calls == 1
            assert runtime.status(run.run_id).actions[-1]["result"] == {"changed": True}

    asyncio.run(exercise())


def test_changed_tool_definition_rejects_recovery(tmp_path):
    async def change(args, ctx):
        return args

    path = tmp_path / "runs.db"
    tools = registry(change)
    with engine(path, ScriptedProvider([tool_response()]), tools) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
        asyncio.run(runtime.drive(run.run_id))
    changed = ToolRegistry()
    changed.register(ToolSpec("change", "Different operation", SCHEMA, version="2"), change)
    with engine(path, ScriptedProvider([]), changed) as runtime:
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(run.run_id))


def test_second_coordinator_cannot_open_execution_database(tmp_path):
    path = tmp_path / "runs.db"
    with engine(path, ScriptedProvider([]), ToolRegistry()):
        other = SQLiteStore(path)
        try:
            with pytest.raises(CoordinatorBusy):
                LocalEngine(other, providers={}, tools=ToolRegistry())
        finally:
            other.close()


def test_scope_is_enforced_for_run_queries(tmp_path):
    path = tmp_path / "runs.db"
    with engine(path, ScriptedProvider([]), ToolRegistry(), scope=Scope("one", "alice")) as runtime:
        run = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
    with engine(path, ScriptedProvider([]), ToolRegistry(), scope=Scope("two", "bob")) as runtime:
        with pytest.raises(AuthorizationDenied):
            runtime.status(run.run_id)


def test_sequential_workflow_passes_verified_result_to_next_agent(tmp_path):
    provider = ScriptedProvider(
        [ModelResponse(output={"diagnosis": "cache"}), ModelResponse(output="plan")]
    )
    flow = WorkflowSpec("incident", (AgentSpec("diagnose", "Diagnose"), AgentSpec("plan", "Plan")))
    with engine(tmp_path / "runs.db", provider, ToolRegistry()) as runtime:
        run = runtime.submit(flow, {"incident": 1}, command_id="s")
        done = asyncio.run(runtime.drive(run.run_id))
        assert done.state == "succeeded"
        assert done.result == "plan"
        assert '"diagnosis":"cache"' in provider.messages[1][1]["content"]


def test_output_validation_does_not_repeat_a_known_write(tmp_path):
    effects = []

    async def change(args, ctx):
        effects.append(1)
        return {"ok": True}

    provider = ScriptedProvider([tool_response(), ModelResponse(output="bad output")])
    spec = AgentSpec("a", "x", ("change",), output_schema={"type": "object"})
    with engine(tmp_path / "runs.db", provider, registry(change, approval=False)) as runtime:
        run = runtime.submit(spec, "x", command_id="s")
        assert asyncio.run(runtime.drive(run.run_id)).state == "failed"
        assert asyncio.run(runtime.drive(run.run_id)).state == "failed"
        assert effects == [1]


def test_approval_digest_must_match_pending_operation(tmp_path):
    async def change(args, ctx):
        return args

    with engine(
        tmp_path / "runs.db", ScriptedProvider([tool_response()]), registry(change)
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
        waiting = asyncio.run(runtime.drive(run.run_id))
        with pytest.raises(ValidationError):
            runtime.approve(
                run.run_id, waiting.pending[0]["action_id"], "wrong", command_id="approve"
            )
        assert runtime.status(run.run_id).state == "waiting_approval"


def test_new_run_cannot_repeat_an_unresolved_write(tmp_path):
    effects = []

    async def uncertain(args, ctx):
        effects.append(1)
        raise ConnectionError("response lost")

    provider = ScriptedProvider([tool_response(), tool_response()])
    with engine(tmp_path / "runs.db", provider, registry(uncertain, approval=False)) as runtime:
        spec = AgentSpec("a", "x", ("change",))
        first = runtime.submit(spec, "x", command_id="first")
        assert asyncio.run(runtime.drive(first.run_id)).state == "waiting_reconciliation"
        second = runtime.submit(spec, "x", command_id="second")
        assert asyncio.run(runtime.drive(second.run_id)).state == "waiting_reconciliation"
        assert effects == [1]


def test_cancelling_drive_cannot_release_coordinator_while_tool_is_running(tmp_path):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()

        async def change(args, ctx):
            started.set()
            await release.wait()
            return {"ok": True}

        runtime = engine(
            tmp_path / "runs.db",
            ScriptedProvider([tool_response()]),
            registry(change, approval=False),
        )
        try:
            run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
            drive = asyncio.create_task(runtime.drive(run.run_id))
            await started.wait()
            drive.cancel()
            with pytest.raises(asyncio.CancelledError):
                await drive
            with pytest.raises(ValidationError):
                runtime.close()
            with pytest.raises(CoordinatorBusy):
                await runtime.drive(run.run_id)
            release.set()
            for _ in range(20):
                await asyncio.sleep(0)
            assert (await runtime.drive(run.run_id)).state == "cancelled"
            assert runtime.status(run.run_id).actions[-1]["result"] == {"ok": True}
        finally:
            release.set()
            runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("late_failure", [False, True])
def test_queued_driver_rechecks_live_attempt_after_acquiring_run_lock(tmp_path, late_failure):
    async def exercise():
        model_completed, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class NotifyingProvider(ScriptedProvider):
            async def complete(self, messages, tools):
                model_completed.set()
                return await super().complete(messages, tools)

        async def change(args, ctx):
            started.set()
            await release.wait()
            if late_failure:
                raise ConnectionError("Response was lost after cancellation")
            return {"ok": True}

        with engine(
            tmp_path / "queued.db",
            NotifyingProvider([tool_response()]),
            registry(change, approval=False),
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")

            async def queued_driver():
                await model_completed.wait()
                return await runtime.drive(run.run_id)

            queued = asyncio.create_task(queued_driver())
            first = asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            try:
                with pytest.raises(CoordinatorBusy):
                    await queued
                snapshot = runtime.status(run.run_id)
                assert snapshot.state == "cancelling"
                assert snapshot.actions[-1]["status"] == "executing"
            finally:
                release.set()
                for _ in range(100):
                    if runtime._inflight[run.run_id].done():
                        break
                    await asyncio.sleep(0)
                else:
                    pytest.fail("Cancelled tool did not finish")
            assert (await runtime.drive(run.run_id)).state == "cancelled"

    asyncio.run(exercise())


@pytest.mark.parametrize("automatic_result", [{"source": "automatic"}, None])
def test_manual_reconciliation_wins_over_late_automatic_evidence(tmp_path, automatic_result):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()

        async def uncertain(args, ctx):
            raise ConnectionError("Response was lost")

        async def reconcile(args, ctx):
            started.set()
            await release.wait()
            return automatic_result

        provider = ScriptedProvider([tool_response(), ModelResponse(output="done")])
        with engine(
            tmp_path / "reconciliation.db",
            provider,
            registry(uncertain, approval=False, effect="queryable_write", reconciler=reconcile),
        ) as runtime:
            run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
            assert (await runtime.drive(run.run_id)).state == "waiting_reconciliation"
            action = runtime.status(run.run_id).actions[-1]
            drive = asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 2)
            runtime.reconcile(
                run.run_id, action["id"], {"source": "manual"}, command_id="manual-confirm"
            )
            release.set()
            snapshot = await drive
            assert snapshot.state == "succeeded"
            assert snapshot.actions[1]["result"] == {"source": "manual"}
            tool_messages = [m for m in provider.messages[-1] if m["role"] == "tool"]
            assert len(tool_messages) == 1
            assert tool_messages[0]["content"] == '{"source":"manual"}'

    asyncio.run(exercise())


@pytest.mark.parametrize("current_cost", [2, None])
def test_manual_reconciliation_settles_pinned_cost_without_current_tool(tmp_path, current_cost):
    async def uncertain(args, ctx):
        raise ConnectionError("Response was lost")

    path = tmp_path / "pinned-cost.db"
    with engine(
        path, ScriptedProvider([tool_response()]), registry(uncertain, approval=False)
    ) as runtime:
        run = runtime.submit(AgentSpec("a", "x", ("change",)), "x", command_id="s")
        assert asyncio.run(runtime.drive(run.run_id)).state == "waiting_reconciliation"
        action = runtime.status(run.run_id).actions[-1]
    current = ToolRegistry()
    if current_cost is not None:
        current.register(
            ToolSpec("change", "Changed configuration", SCHEMA, cost=current_cost), uncertain
        )
    with engine(path, ScriptedProvider([]), current) as runtime:
        runtime.reconcile(run.run_id, action["id"], {"confirmed": True}, command_id="confirm")
        assert runtime.status(run.run_id).actions[-1]["status"] == "completed"
        assert runtime.store.budget(run.run_id) == {"limit": 32, "held": 0, "spent": 2}
