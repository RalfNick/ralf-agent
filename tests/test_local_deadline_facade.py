"""Facade observers cannot cancel business work or fake deadline ownership release."""

import asyncio
import time
from contextlib import contextmanager

import pytest

import ralf_agent as r
from ralf_agent.errors import (
    CoordinatorBusy,
    DefinitionMismatch,
    ExecutionHostFailed,
    ValidationError,
)
from ralf_agent.governance import LocalExecutionPolicy


async def eventually(predicate):
    deadline = asyncio.get_running_loop().time() + 3
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail("The original Local deadline authority did not advance")
        await asyncio.sleep(0.002)


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_default_wait_reports_failed_deadline_host_after_transient_store_recovery(tmp_path, kind):
    class TransientStore(r.SQLiteStore):
        fail_transactions = False

        @contextmanager
        def transaction(self):
            if self.fail_transactions:
                raise OSError("Transient offline transaction failure")
            with super().transaction():
                yield

    async def scenario():
        writes = []

        class Provider:
            identity = {"kind": "transient-deadline-test", "version": "1"}

            async def complete(self, messages, tools):
                return r.ModelResponse(tool_calls=(r.ToolCall("change", {}),))

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec(
                "change",
                "Change",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            lambda arguments, context: writes.append(context.effect_key),
        )
        store = TransientStore(tmp_path / "transient.sqlite")
        engine = r.LocalEngine(
            store,
            providers={"default": Provider()},
            tools=tools,
            execution_policy=LocalExecutionPolicy(approval_timeout_seconds=0.15),
        )
        runtime = r.Runtime(engine, owned=True)
        root = None
        try:
            definition = r.AgentSpec("writer", "Change", ("change",))
            if kind == "team":
                definition = r.TeamSpec("team", {"worker": definition})
            root = await runtime.create_agent(definition).submit("q", command_id="s")
            assert (await root.wait(wait_timeout=1)).snapshot.state == "waiting_approval"
            targets = [root]
            if kind == "team":
                targets.append(runtime.attach(r.RunRef.from_dict((await root.pending())[0]["ref"])))
            store.fail_transactions = True
            await eventually(lambda: root.ref.run_id in engine._deadline_failures)
            store.fail_transactions = False
            for target in targets:
                assert (await target.status()).state == "waiting_approval"
                with pytest.raises(ExecutionHostFailed):
                    await target.wait(wait_timeout=0)
            assert writes == []
            await runtime.resume(root.ref)
            await eventually(lambda: engine.status(root.ref.run_id).state == "failed")
            result = await root.wait(wait_timeout=1)
            assert result.snapshot.error["code"] == "approval_expired" and writes == []
        finally:
            store.fail_transactions = False
            if root is not None and engine._deadline_failures:
                await runtime.resume(root.ref)
            await runtime.aclose(close_timeout=2)

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_observer", [False, True], ids=["timeout", "cancel-wait"])
def test_facade_observation_ends_without_business_cancel_then_original_deadline_wins(
    tmp_path, cancel_observer
):
    async def scenario():
        started, release, ended = asyncio.Event(), asyncio.Event(), asyncio.Event()
        cancelled = []

        class Provider:
            identity = {"kind": "facade-original-deadline-provider", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                try:
                    await release.wait()
                    return r.ModelResponse(output="late answer")
                except asyncio.CancelledError:
                    cancelled.append(True)
                    raise
                finally:
                    ended.set()

        raw = r.LocalEngine(
            r.SQLiteStore(tmp_path / "wait.sqlite"),
            providers={"default": Provider()},
            tools=r.ToolRegistry(),
            execution_policy=LocalExecutionPolicy(run_timeout_seconds=0.25),
        )
        runtime = r.Runtime(raw, owned=True)
        run = None
        try:
            run = await runtime.create_agent(r.AgentSpec("a", "Answer")).submit("q", command_id="s")
            await asyncio.wait_for(started.wait(), 2)
            if cancel_observer:
                observer = asyncio.create_task(run.wait())
                await asyncio.sleep(0)
                observer.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await observer
            else:
                observed = await run.wait(wait_timeout=0)
                assert observed.wait_reason == "observation_timeout"
            assert (await run.status()).state == "running"
            assert not cancelled and not ended.is_set()
            assert not any(event.kind == "run_cancelled" for event in await run.events())
            await eventually(lambda: raw.status(run.ref.run_id).error is not None)
            snapshot = await run.status()
            assert snapshot.state == "cancelling" and snapshot.error["code"] == "deadline_exceeded"
            assert not cancelled and not ended.is_set()
            assert raw.store.budget(run.ref.run_id)["held"] == 1
            release.set()
            finished = await run.wait(wait_timeout=2, terminal_only=True)
            assert finished.snapshot.state == "cancelled"
            assert finished.snapshot.error["code"] == "deadline_exceeded"
            assert finished.snapshot.result is None and ended.is_set() and not cancelled
            assert raw.store.budget(run.ref.run_id) == {"limit": 32, "held": 0, "spent": 1}
        finally:
            release.set()
            if run is not None:
                await run.wait(wait_timeout=2, terminal_only=True)
            await runtime.aclose(close_timeout=2)

    asyncio.run(scenario())


def test_explicit_facade_deadline_preserves_owned_close_until_original_model_ends(tmp_path):
    async def scenario():
        started, release, ended = asyncio.Event(), asyncio.Event(), asyncio.Event()
        cancelled = []

        class Provider:
            identity = {"kind": "facade-owned-deadline-provider", "version": "1"}

            async def complete(self, messages, tools):
                started.set()
                try:
                    await release.wait()
                    return r.ModelResponse(output="late answer")
                except asyncio.CancelledError:
                    cancelled.append(True)
                    raise
                finally:
                    ended.set()

        path = tmp_path / "owned.sqlite"
        raw = r.LocalEngine(
            r.SQLiteStore(path), providers={"default": Provider()}, tools=r.ToolRegistry()
        )
        runtime = r.Runtime(raw, owned=True, close_policy="drain")
        try:
            requested = time.time() + 0.25
            run = await runtime.create_agent(r.AgentSpec("a", "Answer")).submit(
                "q",
                command_id="s",
                deadline_at=requested,
            )
            await asyncio.wait_for(started.wait(), 2)
            original = raw.store.run(run.ref.run_id)
            assert original["local_deadlines"]["requested_deadline_at"] == requested
            assert original["local_deadlines"]["run_expires_at"] == requested
            assert original["manifest"]["execution_policy"] is None
            await eventually(lambda: raw.status(run.ref.run_id).error is not None)
            assert raw.status(run.ref.run_id).error["code"] == "deadline_exceeded"
            with pytest.raises(r.CloseIncomplete):
                await runtime.aclose(close_timeout=0.01)
            assert runtime.state == "quiescing"
            assert not ended.is_set() and not cancelled
            assert raw.store.budget(run.ref.run_id)["held"] == 1
            with r.SQLiteStore(path) as contender:
                with pytest.raises(CoordinatorBusy):
                    r.LocalEngine(contender, providers={}, tools=r.ToolRegistry())
            release.set()
            closed = await runtime.aclose(close_timeout=2)
            assert closed.state == "closed"
            assert ended.is_set() and not cancelled
        finally:
            release.set()
            await runtime.aclose(close_timeout=2)
        with r.LocalEngine(
            r.SQLiteStore(path), providers={"default": Provider()}, tools=r.ToolRegistry()
        ) as successor:
            snapshot = successor.status(run.ref.run_id)
            assert snapshot.state == "cancelled" and snapshot.error["code"] == "deadline_exceeded"
            assert snapshot.result is None
            assert successor.store.budget(run.ref.run_id) == {"limit": 32, "held": 0, "spent": 1}

    asyncio.run(scenario())


def test_paused_deadline_actor_failure_is_observable_and_original_binding_resume_recovers(
    tmp_path,
):
    async def scenario():
        effects = []

        class Provider:
            identity = {"kind": "facade-deadline-host-failure-provider", "version": "1"}

            async def complete(self, messages, tools):
                return r.ModelResponse(tool_calls=(r.ToolCall("change", {}, "original-call"),))

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec(
                "change",
                "Change a business value",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            lambda arguments, context: effects.append(context.effect_key),
        )
        raw = r.LocalEngine(
            r.SQLiteStore(tmp_path / "host-failure.sqlite"),
            providers={"default": Provider()},
            tools=tools,
            execution_policy=LocalExecutionPolicy(approval_timeout_seconds=0.15),
        )
        runtime = r.Runtime(raw, owned=True)
        original_prepare = raw.store.prepare_local_deadlines
        try:
            run = await runtime.create_agent(r.AgentSpec("a", "Change", ("change",))).submit(
                "q", command_id="s"
            )
            waiting = await run.wait(wait_timeout=1)
            assert waiting.snapshot.state == "waiting_approval"
            original = raw.store.run(run.ref.run_id)
            pending = next(action for action in original["actions"] if action["kind"] == "tool")
            original_expiry = pending["approval_expires_at"]
            raw.store.prepare_local_deadlines = lambda: None
            with pytest.raises(ExecutionHostFailed):
                await run.wait(wait_timeout=1, terminal_only=True)
            diagnostic = await run.diagnostics()
            assert diagnostic.snapshot.state == "waiting_approval"
            assert diagnostic.workflow["local_deadlines"]["host_failure"] == "definition_mismatch"
            assert time.time() >= original_expiry and effects == []
            raw.store.prepare_local_deadlines = original_prepare
            recovered = await runtime.resume(run.ref)
            result = await recovered.wait(wait_timeout=1, terminal_only=True)
            assert result.snapshot.state == "failed"
            assert result.snapshot.error["code"] == "approval_expired"
            restored = raw.store.run(run.ref.run_id)
            action = next(action for action in restored["actions"] if action["id"] == pending["id"])
            assert restored["local_deadlines"] == original["local_deadlines"]
            assert action["approval_requested_at"] == pending["approval_requested_at"]
            assert action["approval_expires_at"] == original_expiry
            assert not action["attempts"] and effects == []
            assert (await recovered.diagnostics()).workflow["local_deadlines"].get(
                "host_failure"
            ) is None
        finally:
            raw.store.prepare_local_deadlines = original_prepare
            await runtime.aclose(close_timeout=2)

    asyncio.run(scenario())


def test_team_root_reports_original_child_approval_timer_host_failure_and_recovers(tmp_path):
    async def scenario():
        effects = []

        class Provider:
            identity = {"kind": "facade-team-deadline-host-failure-provider", "version": "1"}

            async def complete(self, messages, tools):
                return r.ModelResponse(tool_calls=(r.ToolCall("change", {}, "original-call"),))

        tools = r.ToolRegistry()
        tools.register(
            r.ToolSpec(
                "change",
                "Change a business value",
                {"type": "object"},
                effect="unqueryable_write",
                requires_approval=True,
            ),
            lambda arguments, context: effects.append(context.effect_key),
        )
        raw = r.LocalEngine(
            r.SQLiteStore(tmp_path / "team-host-failure.sqlite"),
            providers={"default": Provider()},
            tools=tools,
            execution_policy=LocalExecutionPolicy(approval_timeout_seconds=0.15),
        )
        runtime = r.Runtime(raw, owned=True)
        original_prepare = raw.store.prepare_local_deadlines
        try:
            definition = r.TeamSpec("team", {"worker": r.AgentSpec("a", "Change", ("change",))})
            root = await runtime.create_agent(definition).submit("q", command_id="s")
            assert (await root.wait(wait_timeout=1)).snapshot.state == "waiting_approval"
            pending = await root.pending()
            assert len(pending) == 1 and pending[0]["kind"] == "approval"
            child_ref = r.RunRef.from_dict(pending[0]["ref"])
            child = runtime.attach(child_ref)
            assert child_ref.run_id != root.ref.run_id
            original_root = raw.store.run(root.ref.run_id)
            original_child = raw.store.run(child_ref.run_id)
            links = original_root["orchestration"]["children"]
            assert any(
                link["run_id"] == child_ref.run_id and link["id"] == original_child["call_id"]
                for link in links
            )
            approval = next(
                action
                for action in original_child["actions"]
                if action["id"] == pending[0]["action_id"]
            )
            original_expiry = approval["approval_expires_at"]
            raw.store.prepare_local_deadlines = lambda: None
            with pytest.raises(ExecutionHostFailed):
                await root.wait(wait_timeout=1, terminal_only=True)
            assert (await root.diagnostics()).workflow["local_deadlines"][
                "host_failure"
            ] == "definition_mismatch"
            assert (await child.diagnostics()).workflow["local_deadlines"][
                "host_failure"
            ] == "definition_mismatch"
            assert time.time() >= original_expiry and effects == []
            assert (await root.status()).state == "waiting_approval"
            assert (await child.status()).state == "waiting_approval"
            raw.store.prepare_local_deadlines = original_prepare
            recovered = await runtime.resume(root.ref)
            result = await recovered.wait(wait_timeout=1, terminal_only=True)
            assert (
                result.snapshot.state == "failed"
                and result.snapshot.error["code"] == "approval_expired"
            )
            restored = raw.store.run(child_ref.run_id)
            restored_approval = next(
                action for action in restored["actions"] if action["id"] == approval["id"]
            )
            assert restored["local_deadlines"] == original_child["local_deadlines"]
            assert restored_approval["approval_expires_at"] == original_expiry
            assert not restored_approval["attempts"] and effects == []
            assert (await recovered.diagnostics()).workflow["local_deadlines"].get(
                "host_failure"
            ) is None
            assert (await child.diagnostics()).workflow["local_deadlines"].get(
                "host_failure"
            ) is None
        finally:
            raw.store.prepare_local_deadlines = original_prepare
            await runtime.aclose(close_timeout=2)

    asyncio.run(scenario())


@pytest.mark.parametrize("deadline_capable", [True, False], ids=["deadline-store", "legacy-store"])
def test_facade_reports_actual_store_deadline_capability_and_refuses_unsupported_submit(
    tmp_path, deadline_capable
):
    async def scenario():
        class LegacyStore:
            local_deadline_version = None

            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                if name in {"prepare_local_deadlines", "conn"}:
                    raise AttributeError(name)
                return getattr(self.inner, name)

        class Provider:
            identity = {"kind": "facade-deadline-capability-provider", "version": "1"}
            calls = 0

            async def complete(self, messages, tools):
                self.calls += 1
                return r.ModelResponse(output="completed")

        provider = Provider()
        inner = r.SQLiteStore(tmp_path / "capability.sqlite")
        store = inner if deadline_capable else LegacyStore(inner)
        raw = r.LocalEngine(store, providers={"default": provider}, tools=r.ToolRegistry())
        async with r.Runtime(raw, owned=True) as runtime:
            assert runtime.capabilities["deadline"] is deadline_capable
            agent = runtime.create_agent(r.AgentSpec("a", "Answer"))
            requested = time.time() + 60
            if deadline_capable:
                run = await agent.submit("q", command_id="deadline-submit", deadline_at=requested)
                result = await run.wait(wait_timeout=1, terminal_only=True)
                assert result.snapshot.state == "succeeded"
                accepted = store.run(run.ref.run_id)
                assert accepted["local_deadlines"]["requested_deadline_at"] == requested
                assert accepted["local_deadlines"]["run_expires_at"] == requested
                assert accepted["manifest"]["local_deadline_protocol"] == 1
            else:
                with pytest.raises((ValidationError, DefinitionMismatch)):
                    await agent.submit("q", command_id="deadline-submit", deadline_at=requested)
                assert provider.calls == 0
                assert inner.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
                plain = await agent.submit("q", command_id="plain-submit")
                result = await plain.wait(wait_timeout=1, terminal_only=True)
                assert result.snapshot.state == "succeeded"
                accepted = store.run(plain.ref.run_id)
                assert "local_deadlines" not in accepted
                assert "local_deadline_protocol" not in accepted["manifest"]
                assert provider.calls == 1

    asyncio.run(scenario())
