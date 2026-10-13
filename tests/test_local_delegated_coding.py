"""Local original-action delegation lifecycle contracts (not native model coverage)."""

import asyncio
import importlib.util

import pytest

from ralf_agent import AgentSpec, LocalEngine, ToolRegistry
from ralf_agent.errors import ValidationError
from ralf_agent.storage import SQLiteStore

from .helpers import ScriptedProvider


def test_delegated_authority_is_available():
    assert importlib.util.find_spec("ralf_agent.local_delegated_coding") is not None


def test_schema14_activation_is_atomic_and_keeps_native_history(tmp_path):
    store = SQLiteStore(tmp_path / "runs.db")
    assert getattr(store, "delegated_execution_version", None) == 1
    assert (
        store.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        == "1"
    )
    with pytest.raises(ValidationError):
        store.prepare_delegated_execution()
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.prepare_delegated_execution()
            raise RuntimeError("rollback")
    assert (
        store.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        == "1"
    )
    with store.transaction():
        store.prepare_delegated_execution()
        store.publish_native_history(__import__("ralf_agent").Scope(), "s", "m", {"x": 1})
    assert (
        store.conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        == "14"
    )
    assert store.native_history_publications(__import__("ralf_agent").Scope(), "s") == [{"x": 1}]
    assert store.create_session_admission()._enabled()
    store.close()
    SQLiteStore(tmp_path / "runs.db", readonly=True).close()


def test_pending_native_work_keeps_engine_coordinator(tmp_path):
    runtime = LocalEngine(
        SQLiteStore(tmp_path / "runs.db"),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
    )
    handle = runtime.submit(AgentSpec("a", "x"), "x", command_id="s")
    with runtime.store.transaction():
        run = runtime.store.run(handle.run_id)
        run["actions"].append(
            {
                "id": "a",
                "kind": "tool",
                "status": "outcome_unknown",
                "delegated_execution": {"version": 1, "pending_stop": True, "fenced": False},
            }
        )
        runtime.store.save_run(run)
    with pytest.raises(ValidationError, match="delegated"):
        runtime.close()
    with runtime.store.transaction():
        run = runtime.store.run(handle.run_id)
        run["actions"].clear()
        runtime.store.save_run(run)
    runtime.close()


class LifecycleRunner:
    """Finite lifecycle fixture. No native process or G7/G8 claim."""

    identity = {
        "kind": "lifecycle-fixture",
        "version": "1",
        "profile": {"recovery_modes": ["none"]},
    }

    def __init__(self, *, fail_stop=False, crash=False, wait=False):
        self.active_operations = 0
        self.fail_stop, self.crash, self.wait = fail_stop, crash, wait
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.calls, self.envelope, self.authority = [], None, None
        self.state = None

    async def execute(self, envelope, authority):
        from ralf_agent.executors import EffectObservation
        from ralf_agent.types import digest

        self.envelope, self.authority = envelope, authority
        self.calls.append("execute")
        self.active_operations += 1
        intent = authority.check(envelope, self.identity)
        env = {
            "kind": "environment-fixture",
            "expected_generation": digest(
                {"dispatch": intent["dispatch"], "runner": self.identity}
            )[:32],
        }
        binding = {
            "request": intent,
            "runner": self.identity,
            "dispatch": intent["dispatch"],
            "environment": env,
        }
        grant = authority.authorize("prepare", {}, binding)
        assert grant["execute"]
        assert not authority.authorize("prepare", {}, binding)["execute"]
        self.state = {
            "identity": env,
            "container_id": "a" * 64,
            "generation": env["expected_generation"],
            "fenced": False,
            "running": False,
            "stopped": True,
            "retired": False,
            "container_present": True,
        }
        authority.adopt("prepared", self.state)
        binding["environment"] = {
            k: self.state[k] for k in ("identity", "container_id", "generation")
        }
        params = {
            "cwd": "/workspace",
            "approvalPolicy": "never",
            "approvalsReviewer": "user",
            "ephemeral": False,
        }
        assert authority.authorize("thread/start", params, binding)["execute"]
        authority.adopt("thread", {"thread_id": "thread"})
        params = {
            "threadId": "thread",
            "cwd": "/workspace",
            "approvalPolicy": "never",
            "approvalsReviewer": "user",
            "input": [{"type": "text", "text": envelope.arguments["task"], "text_elements": []}],
        }
        assert authority.authorize("turn/start", params, binding)["execute"]
        authority.adopt("turn", {"thread_id": "thread", "turn_id": "turn"})
        self.entered.set()
        if self.wait:
            await self.release.wait()
        if self.crash or authority.cancelled():
            raise RuntimeError("native outcome unavailable")
        authority.adopt(
            "observation",
            {
                "thread_id": "thread",
                "turn_id": "turn",
                "native_status": "completed",
                "final_thread_read": True,
            },
        )
        await self.stop_existing(envelope, authority)
        result = {
            "text": "done",
            "artifacts": [],
            "native": {"thread_id": "thread", "turn_id": "turn", "status": "completed"},
            "usage": {"status": "unknown"},
            "stop": {k: self.state[k] for k in ("container_id", "generation", "fenced")},
        }
        authority.adopt("result_candidate", {"result": result})
        return EffectObservation(result, "coding-fixture")

    async def reconcile(self, envelope, authority):
        self.calls.append("reconcile")
        await self.stop_existing(envelope, authority)
        return None

    async def stop_existing(self, envelope, authority):
        self.calls.append("stop_existing")
        authority.check(envelope, self.identity)
        if self.fail_stop:
            raise RuntimeError("daemon unavailable")
        self.state.update(
            fenced=True,
            stopped=True,
            running=False,
            retired=True,
            container_present=False,
            transport_closed=True,
        )
        authority.adopt("stop", self.state)
        self.active_operations = 0
        return self.state

    async def aclose(self, *, wait_timeout=30):
        assert self.active_operations == 0


def coding_engine(tmp_path, runner, responses=None):
    from ralf_agent import ModelResponse
    from ralf_agent.delegated_coding import register_coding_tool

    from .helpers import tool_response

    tools = ToolRegistry()
    register_coding_tool(tools, runner)
    provider = ScriptedProvider(
        responses
        or [tool_response("coding", {"task": "write answer"}), ModelResponse(output="finished")]
    )
    runtime = LocalEngine(
        SQLiteStore(tmp_path / "coding.db"), providers={"default": provider}, tools=tools
    )
    return runtime, provider


def test_original_approval_one_attempt_and_grants(tmp_path):
    async def exercise():
        runner = LifecycleRunner()
        runtime, provider = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        assert runtime.store.run(handle.run_id)["manifest"]["kernel"] == "local-10"
        await runtime.drive(handle.run_id)
        assert runner.calls == []
        action = runtime.store.run(handle.run_id)["actions"][-1]
        assert action["status"] == "waiting_approval"
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        run = runtime.store.run(handle.run_id)
        action = next(a for a in run["actions"] if a["kind"] == "tool")
        assert run["state"] == "succeeded"
        assert len(action["attempts"]) == 1
        assert set(action["delegated_execution"]["grants"]) == {
            "prepare",
            "thread/start",
            "turn/start",
        }
        assert action["delegated_execution"]["effect_case"] == "confirmed"
        assert len([m for m in run["messages"] if m["role"] == "tool"]) == 1
        assert provider.calls == 2
        assert runtime.store.budget(handle.run_id)["held"] == 0
        runtime.close()

    asyncio.run(exercise())


def test_cancel_requires_real_fence_and_preserves_unknown_effect(tmp_path):
    async def exercise():
        runner = LifecycleRunner(fail_stop=True, wait=True)
        runtime, _ = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        drive = asyncio.create_task(runtime.drive(handle.run_id))
        await runner.entered.wait()
        runtime.cancel(handle.run_id, command_id="cancel")
        runner.release.set()
        await drive
        assert runtime.status(handle.run_id).state == "cancelling"
        with pytest.raises(ValidationError, match="delegated"):
            runtime.close()
        runner.fail_stop = False
        await runtime.drive(handle.run_id)
        run = runtime.store.run(handle.run_id)
        action = next(a for a in run["actions"] if a["kind"] == "tool")
        assert run["state"] == "cancelled"
        assert action["status"] == "outcome_unknown"
        assert action["delegated_execution"]["effect_case"] == "unknown"
        assert runtime.store.unresolved_effect(
            runtime.scope, "coding", {"task": "write answer"}, "another"
        ) == {"run_id": run["id"], "action_id": action["id"]}
        assert len(action["attempts"]) == 1
        runtime.close()

    asyncio.run(exercise())


def test_cold_pending_cancel_only_stops_original_envelope(tmp_path):
    async def exercise():
        runner = LifecycleRunner(fail_stop=True, crash=True)
        runtime, provider = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        runtime.cancel(handle.run_id, command_id="cancel")
        saved = runner.envelope
        # Emulate process death; ordinary close deliberately cannot abandon work.
        runtime.store.close()
        runtime.coordinator.release()
        runner.fail_stop = False
        rebuilt = LocalEngine(
            SQLiteStore(tmp_path / "coding.db"),
            providers={"default": provider},
            tools=runtime.tools,
        )
        await rebuilt.drive(handle.run_id)
        run = rebuilt.store.run(handle.run_id)
        action = next(a for a in run["actions"] if a["kind"] == "tool")
        assert run["state"] == "cancelled"
        assert len(action["attempts"]) == 1
        assert (
            action["delegated_execution"]["request"]["dispatch"]["execution_epoch"]
            == saved.context.execution_epoch
        )
        assert runner.calls.count("execute") == 1
        assert "reconcile" not in runner.calls
        assert run["messages"][-1]["role"] == "assistant"
        rebuilt.close()

    asyncio.run(exercise())


def test_manual_unknown_confirmation_does_not_publish_after_cancel(tmp_path):
    async def exercise():
        runner = LifecycleRunner(crash=True)
        runtime, _ = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        runtime.cancel(handle.run_id, command_id="cancel")
        runtime.reconcile(
            handle.run_id, action["id"], {"operator": "confirmed"}, command_id="confirm"
        )
        run = runtime.store.run(handle.run_id)
        action = next(a for a in run["actions"] if a["kind"] == "tool")
        assert run["state"] == "cancelled"
        assert not any(m["role"] == "tool" for m in run["messages"])
        assert action["delegated_execution"]["effect_case"] == "confirmed"
        assert (
            runtime.store.unresolved_effect(
                runtime.scope, "coding", {"task": "write answer"}, "another"
            )
            is None
        )
        runtime.close()

    asyncio.run(exercise())


def test_completed_receipt_before_fence_cannot_commit_result(tmp_path):
    async def exercise():
        runner = LifecycleRunner(crash=True, fail_stop=True)
        runtime, _ = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        with pytest.raises(ValidationError, match="stop|fenc"):
            runtime.reconcile(
                handle.run_id, action["id"], {"fake": "completion"}, command_id="confirm"
            )
        run = runtime.store.run(handle.run_id)
        assert not any(m["role"] == "tool" for m in run["messages"])
        runtime.cancel(handle.run_id, command_id="cancel")
        runner.fail_stop = False
        await runtime.drive(handle.run_id)
        runtime.close()

    asyncio.run(exercise())


def test_native_grant_cannot_resume_after_original_owner_changes(tmp_path):
    async def exercise():
        runner = LifecycleRunner(crash=True, fail_stop=True)
        runtime, provider = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        runtime.store.close()
        runtime.coordinator.release()
        rebuilt = LocalEngine(
            SQLiteStore(tmp_path / "coding.db"),
            providers={"default": provider},
            tools=runtime.tools,
        )
        from ralf_agent.errors import AuthorizationDenied
        from ralf_agent.local_delegated_coding import LocalCodingAuthority

        authority = LocalCodingAuthority(rebuilt, handle.run_id, action["id"])
        saved = next(a for a in rebuilt.store.run(handle.run_id)["actions"] if a["kind"] == "tool")[
            "delegated_execution"
        ]
        grant = saved["grants"]["turn/start"]
        with pytest.raises(AuthorizationDenied):
            authority.authorize("turn/start", grant["params"], grant["binding"])
        rebuilt.cancel(handle.run_id, command_id="cancel")
        runner.fail_stop = False
        await rebuilt.drive(handle.run_id)
        rebuilt.close()

    asyncio.run(exercise())


def test_corrupt_native_request_cannot_release_original_journal(tmp_path):
    async def exercise():
        from ralf_agent.errors import DefinitionMismatch

        runner = LifecycleRunner(crash=True, fail_stop=True)
        runtime, _ = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        saved = runtime.store.run(handle.run_id)
        with runtime.store.transaction():
            corrupt = runtime.store.run(handle.run_id)
            next(a for a in corrupt["actions"] if a["kind"] == "tool")["delegated_execution"][
                "request"
            ]["dispatch"]["effect_key"] = "other"
            runtime.store.save_run(corrupt)
        with pytest.raises(DefinitionMismatch):
            runtime._check_release(runtime.store.run(handle.run_id))
        with runtime.store.transaction():
            saved["revision"] = runtime.store.run(handle.run_id)["revision"]
            runtime.store.save_run(saved)
        runtime.cancel(handle.run_id, command_id="cancel")
        runner.fail_stop = False
        await runtime.drive(handle.run_id)
        runtime.close()

    asyncio.run(exercise())


def test_graph_direct_coding_tool_rejected_before_acceptance(tmp_path):
    from ralf_agent import GraphNode, GraphWorkflowSpec

    runner = LifecycleRunner()
    runtime, provider = coding_engine(tmp_path, runner)
    with pytest.raises(ValidationError, match="root unbound"):
        runtime.submit(
            GraphWorkflowSpec("graph", (GraphNode("coding", tool="coding"),)), "x", command_id="s"
        )
    assert provider.calls == 0
    assert runner.calls == []
    assert runtime.store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert (
        runtime.store.conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()[0]
        == "1"
    )
    runtime.close()


def test_unselected_runner_preserves_legacy_manifest_and_schema(tmp_path):
    from ralf_agent import ModelResponse

    runtime, _ = coding_engine(tmp_path, LifecycleRunner(), [ModelResponse(output="done")])
    handle = runtime.submit(AgentSpec("ordinary", "x"), "x", command_id="s")
    run = runtime.store.run(handle.run_id)
    assert run["manifest"]["kernel"] == "local-4"
    assert "delegated_execution_protocol" not in run["manifest"]
    assert (
        runtime.store.conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()[0]
        == "1"
    )
    runtime.close()


def test_queryable_unknown_case_is_independent_of_action_status(tmp_path):
    runtime, _ = coding_engine(tmp_path, LifecycleRunner())
    handle = runtime.submit(AgentSpec("ordinary", "x"), "x", command_id="s")
    with runtime.store.transaction():
        run = runtime.store.run(handle.run_id)
        run["state"] = "cancelled"
        run["actions"] = [
            {
                "id": "old",
                "kind": "tool",
                "tool": "coding",
                "arguments": {"task": "x"},
                "status": "completed",
                "delegated_execution": {
                    "effect_case": "unknown",
                    "pending_stop": False,
                    "fenced": True,
                },
            }
        ]
        runtime.store.save_run(run)
    assert runtime.store.unresolved_effect(runtime.scope, "coding", {"task": "x"}, "new") == {
        "run_id": handle.run_id,
        "action_id": "old",
    }
    runtime.close()


def test_stop_receipt_without_prepared_adoption_keeps_original_namespace(tmp_path):
    async def exercise():
        from ralf_agent.errors import DefinitionMismatch

        runner = LifecycleRunner(crash=True, fail_stop=True)
        runtime, _ = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        with runtime.store.transaction():
            run = runtime.store.run(handle.run_id)
            state = next(a for a in run["actions"] if a["kind"] == "tool")["delegated_execution"]
            original = state.pop("prepared")
            runtime.store.save_run(run)
        fake = {
            **original,
            "identity": {"kind": "different"},
            "fenced": True,
            "stopped": True,
            "running": False,
            "retired": True,
            "container_present": False,
        }
        with pytest.raises(DefinitionMismatch):
            runner.authority.adopt("stop", fake)
        run = runtime.store.run(handle.run_id)
        assert (
            next(a for a in run["actions"] if a["kind"] == "tool")["delegated_execution"][
                "pending_stop"
            ]
            is True
        )
        runtime.cancel(handle.run_id, command_id="cancel")
        runner.fail_stop = False
        await runtime.drive(handle.run_id)
        runtime.close()

    asyncio.run(exercise())


class PublicStoreProxy:
    """Optional public ports may forward; Engine must not reach private queries."""

    def __init__(self, store):
        self.store = store

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.store, name)


def test_custom_store_close_queries_public_persisted_native_work(tmp_path):
    async def exercise():
        runner = LifecycleRunner(crash=True, fail_stop=True)
        runtime, provider = coding_engine(tmp_path, runner)
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        runtime.store.close()
        runtime.coordinator.release()
        runner.active_operations = 0
        public = PublicStoreProxy(SQLiteStore(tmp_path / "coding.db"))
        rebuilt = LocalEngine(public, providers={"default": provider}, tools=runtime.tools)
        with pytest.raises(ValidationError, match="delegated"):
            rebuilt.close()
        assert rebuilt.store.run(handle.run_id)["state"] == "waiting_reconciliation"
        rebuilt.cancel(handle.run_id, command_id="cancel")
        runner.fail_stop = False
        await rebuilt.drive(handle.run_id)
        rebuilt.close()

    asyncio.run(exercise())


def test_explicit_optional_store_rejects_missing_public_pending_capability(tmp_path):
    class MissingPending(PublicStoreProxy):
        def __getattr__(self, name):
            if name == "delegated_pending":
                raise AttributeError(name)
            return super().__getattr__(name)

    store = SQLiteStore(tmp_path / "runs.db")
    with pytest.raises(ValidationError, match="delegated|Delegated"):
        LocalEngine(
            MissingPending(store), providers={"default": ScriptedProvider([])}, tools=ToolRegistry()
        )
    store.close()


def test_lazy_optional_pending_query_cannot_release_coordinator(tmp_path):
    class LazyPendingStore(SQLiteStore):
        lazy = False

        def delegated_pending(self, scope):
            value = super().delegated_pending(scope)
            return iter(value) if self.lazy else value

    store = LazyPendingStore(tmp_path / "runs.db")
    runtime = LocalEngine(store, providers={"default": ScriptedProvider([])}, tools=ToolRegistry())
    store.lazy = True
    with pytest.raises(ValidationError, match="completed finite"):
        runtime.close()
    assert runtime._lifecycle == "open"
    store.lazy = False
    runtime.close()


def test_optional_reservation_facts_require_exact_typed_original_identity(tmp_path):
    async def exercise():
        class MalformedReservationStore(SQLiteStore):
            malformed = False

            def delegated_execution_reservation(self, run_id, reservation_id):
                value = super().delegated_execution_reservation(run_id, reservation_id)
                if self.malformed and value is not None:
                    return {**value, "id": "different", "amount": True}
                return value

        runner = LifecycleRunner(crash=True, fail_stop=True)
        runtime, _ = coding_engine(tmp_path, runner)
        runtime.store.close()
        runtime.coordinator.release()
        runtime = LocalEngine(
            MalformedReservationStore(tmp_path / "coding.db"),
            providers=runtime.providers,
            tools=runtime.tools,
        )
        handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
        await runtime.drive(handle.run_id)
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        await runtime.drive(handle.run_id)
        runtime.store.malformed = True
        from ralf_agent.errors import AuthorizationDenied

        with pytest.raises(AuthorizationDenied, match="reservation"):
            runner.authority.check(runner.envelope, runner.identity)
        runtime.store.malformed = False
        runtime.cancel(handle.run_id, command_id="cancel")
        runner.fail_stop = False
        await runtime.drive(handle.run_id)
        runtime.close()

    asyncio.run(exercise())


def test_cold_selected_coding_release_requires_public_store_capability_before_model(tmp_path):
    class LegacyStore(PublicStoreProxy):
        def __getattr__(self, name):
            if name == "delegated_execution_version":
                raise AttributeError(name)
            return super().__getattr__(name)

    runner = LifecycleRunner()
    runtime, provider = coding_engine(tmp_path, runner)
    handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
    assert runtime.store.run(handle.run_id)["actions"] == []
    tools = runtime.tools
    runtime.close()
    reopened = LocalEngine(
        LegacyStore(SQLiteStore(tmp_path / "coding.db")),
        providers={"default": provider},
        tools=tools,
    )
    with pytest.raises(ValidationError, match="Delegated|delegated"):
        asyncio.run(reopened.drive(handle.run_id))
    assert provider.calls == 0
    assert runner.calls == []
    reopened.close()


def test_cold_selected_coding_release_rejects_lazy_public_query_before_model(tmp_path):
    class LazyStore(SQLiteStore):
        lazy = False

        def delegated_pending(self, scope):
            value = super().delegated_pending(scope)
            return iter(value) if self.lazy else value

    runner = LifecycleRunner()
    runtime, provider = coding_engine(tmp_path, runner)
    handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
    tools = runtime.tools
    runtime.close()
    store = LazyStore(tmp_path / "coding.db")
    reopened = LocalEngine(store, providers={"default": provider}, tools=tools)
    store.lazy = True
    with pytest.raises(ValidationError, match="completed finite"):
        asyncio.run(reopened.drive(handle.run_id))
    assert provider.calls == 0
    assert runner.calls == []
    store.lazy = False
    reopened.close()


@pytest.mark.parametrize("change", ["method", "version"])
def test_cold_selected_coding_release_rejects_changed_capability_before_model(tmp_path, change):
    runner = LifecycleRunner()
    runtime, provider = coding_engine(tmp_path, runner)
    handle = runtime.submit(AgentSpec("a", "x", ("coding",)), "x", command_id="s")
    tools = runtime.tools
    runtime.close()
    store = SQLiteStore(tmp_path / "coding.db")
    reopened = LocalEngine(store, providers={"default": provider}, tools=tools)
    if change == "method":
        store.delegated_pending = lambda scope: ()
    else:
        store.delegated_execution_version = True
    with pytest.raises(ValidationError, match="Delegated|delegated"):
        asyncio.run(reopened.drive(handle.run_id))
    assert provider.calls == 0
    assert runner.calls == []
    delattr(store, "delegated_pending" if change == "method" else "delegated_execution_version")
    reopened.close()


def test_ordinary_output_schema_tool_defaults_are_not_declarations(tmp_path):
    schema = {
        "type": "object",
        "properties": {"tool": {"type": "string"}},
        "default": {"tool": "not_registered"},
    }
    runtime = LocalEngine(
        SQLiteStore(tmp_path / "ordinary.db"),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
    )
    handle = runtime.submit(AgentSpec("a", "x", output_schema=schema), "x", command_id="s")
    run = runtime.store.run(handle.run_id)
    assert run["manifest"]["kernel"] == "local-4"
    assert run["definition"]["steps"][0]["output_schema"] == schema
    runtime.close()


def test_graph_argument_and_schema_tool_values_do_not_select_coding(tmp_path):
    from ralf_agent import GraphNode, GraphWorkflowSpec, Literal, ToolSpec

    async def read(arguments, context):
        return arguments

    runtime, provider = coding_engine(tmp_path, LifecycleRunner())
    runtime.tools.register(
        ToolSpec(
            "read",
            "ordinary",
            {
                "type": "object",
                "properties": {"tool": {"type": "string"}},
                "additionalProperties": False,
            },
        ),
        read,
    )
    graph = GraphWorkflowSpec(
        "graph",
        (GraphNode("read", tool="read", input=Literal({"tool": "coding"})),),
        output_schema={"type": "object", "default": {"tool": "coding"}},
    )
    handle = runtime.submit(graph, {"tool": "coding"}, command_id="s")
    assert "delegated_coding_tools" not in runtime.store.run(handle.run_id)["manifest"]
    assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"
    assert runtime.status(handle.run_id).result == {"read": {"tool": "coding"}}
    assert provider.calls == 0
    runtime.close()


def test_nested_graph_actual_coding_selection_remains_unsupported(tmp_path):
    from ralf_agent import GraphNode, GraphWorkflowSpec, TeamSpec

    runtime, provider = coding_engine(tmp_path, LifecycleRunner())
    graph = GraphWorkflowSpec("graph", (GraphNode("coding", tool="coding"),))
    with pytest.raises(ValidationError, match="root unbound"):
        runtime.submit(TeamSpec("team", {"member": graph}), "x", command_id="s")
    assert provider.calls == 0
    runtime.close()


@pytest.mark.parametrize("kind", ["team", "dynamic", "bound_agent"])
def test_actual_composite_coding_selections_remain_unsupported(tmp_path, kind):
    from ralf_agent import AgentDefinition, DynamicWorkflowSpec, TeamSpec

    runtime, provider = coding_engine(tmp_path, LifecycleRunner())
    agent = AgentSpec("a", "x", ("coding",))
    definition = (
        AgentDefinition(agent)
        if kind == "bound_agent"
        else (TeamSpec if kind == "team" else DynamicWorkflowSpec)("parent", {"member": agent})
    )
    with pytest.raises(ValidationError, match="root unbound"):
        runtime.submit(definition, "x", command_id="s")
    assert provider.calls == 0
    runtime.close()
