"""Independent admission regression probes over real selected SDK paths."""

import asyncio
import threading

import pytest

from relf_agent import (
    AgentSpec,
    DeploymentAdmissionPolicy,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    TeamSpec,
    ToolRegistry,
)
from relf_agent.errors import CapacityExceeded, CoordinatorBusy, ValidationError
from relf_agent.executors import PythonToolExecutor
from relf_agent.parent_completion import ParentCompletionPolicy, ParentCompletionVerdict
from relf_agent.parent_verification_stage import ModelParentVerificationStage
from relf_agent.runtime_builder import EchoProvider

from .helpers import ScriptedProvider, tool_response
from .test_local_admission import tools_with


def policy():
    return DeploymentAdmissionPolicy("review-deployment", max_active_root_runs=1)


def make_engine(store, provider=None, tools=None, **options):
    return LocalEngine(
        store,
        providers={"default": provider or EchoProvider("review")},
        tools=ToolRegistry() if tools is None else tools,
        admission_policy=policy(),
        **options,
    )


def test_rejected_but_received_and_settled_model_decision_does_not_leak_root_capacity(tmp_path):
    with make_engine(
        SQLiteStore(tmp_path / "rejected.sqlite"), ScriptedProvider([ModelResponse()])
    ) as engine:
        handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        result = asyncio.run(engine.drive(handle.run_id))
        assert result.state == "failed"
        assert result.actions[0]["status"] == "rejected"
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 1}
        assert not engine._operation_active(handle.run_id)
        assert engine.store.local_capacity_holders(engine.scope) == ()
        engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")


def test_parallel_cancelled_undispatched_approval_does_not_leak_root_capacity(tmp_path):
    effects = []
    tools = tools_with(lambda args, ctx: effects.append(ctx.effect_key), approval=True)
    with make_engine(
        SQLiteStore(tmp_path / "parallel-approval.sqlite"),
        ScriptedProvider([tool_response()]),
        tools,
    ) as engine:
        definition = GraphWorkflowSpec(
            "parallel",
            [GraphNode("worker", agent=AgentSpec("a", "Change", ("change",)))],
            max_concurrency=2,
        )
        handle = engine.submit(definition, "q", command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).state == "waiting_approval"
        engine.cancel(handle.run_id, command_id="cancel")
        assert asyncio.run(engine.drive(handle.run_id)).state == "cancelled"
        action = next(
            action for action in engine.status(handle.run_id).actions if action["kind"] == "tool"
        )
        assert action["status"] == "cancelled" and not action["attempts"]
        assert effects == []
        assert engine.store.budget(handle.run_id)["held"] == 0
        assert engine.store.run(handle.run_id)["workflow"]["quiescent"] is True
        assert engine.store.local_capacity_holders(engine.scope) == ()
        engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")


def test_terminal_pure_parent_completion_gate_error_has_no_unfinished_external_obligation(tmp_path):
    class FailingGate:
        identity = {"kind": "review-pure-parent-gate", "version": "1"}

        def verify(self, request):
            raise ValidationError("Pure gate rejected invalid business evidence")

    with make_engine(
        SQLiteStore(tmp_path / "pure-gate.sqlite"),
        parent_completion_policies={"gate": ParentCompletionPolicy(FailingGate())},
    ) as engine:
        handle = engine.submit(
            TeamSpec(
                "team",
                {"worker": AgentSpec("worker", "Answer")},
                completion_policy="gate",
                child_budget=4,
            ),
            "q",
            command_id="s",
            budget=8,
        )
        snapshot = asyncio.run(engine.drive(handle.run_id))
        assert snapshot.state == "failed"
        record = engine.store.run(handle.run_id)
        stage = record["parent_completion_stages"]["r0"]
        assert stage["child_run_id"] is None and stage["received_proposal"] is None
        assert stage["policy_registration"]["effective_agent_release"] is None
        assert all(child["settled"] for child in record["orchestration"]["children"])
        assert engine.store.budget(handle.run_id)["held"] == 0
        assert (
            not engine._active
            and not engine._drive_users
            and not engine._operation_active(handle.run_id)
        )
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        assert engine.store.local_capacity_holders(engine.scope) == ()
        engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")


def test_failed_release_callback_keeps_claim_and_is_visible_in_original_public_diagnostics(
    tmp_path,
):
    class ReleaseUnavailableStore(SQLiteStore):
        release_unavailable = True

        def local_capacity_release(self, scope, root_run_id):
            if self.release_unavailable:
                raise ConnectionError("Capacity store temporarily unavailable")
            return super().local_capacity_release(scope, root_run_id)

    store = ReleaseUnavailableStore(tmp_path / "callback.sqlite")
    engine = make_engine(store)
    try:
        handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        assert asyncio.run(engine.drive(handle.run_id)).state == "succeeded"
        assert store.local_capacity_holders(engine.scope) == (handle.run_id,)
        assert engine._admission_failures[handle.run_id] == "admission_host_failed"
        info = engine.diagnostics(handle.run_id)
        assert (info.workflow or {}).get("local_admission", {}).get(
            "host_failure"
        ) == "admission_host_failed"
        store.release_unavailable = False
        engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")
        assert (engine.diagnostics(handle.run_id).workflow or {}).get("local_admission", {}).get(
            "host_failure"
        ) is None
    finally:
        store.release_unavailable = False
        engine.close()


def held_thread_executor(loop):
    ready = {}
    release = threading.Event()
    effects = []

    def change(arguments, context):
        effects.append(context.effect_key)
        loop.call_soon_threadsafe(ready[context.action_id].set)
        assert release.wait(10), "Original handler barrier was not released"
        return {"changed": True}

    tools = tools_with(change, cost=0)

    class LostAcknowledgementExecutor(PythonToolExecutor):
        @property
        def identity(self):
            return {"kind": "review-lost-thread-acknowledgement", "version": "1"}

        async def execute(self, envelope):
            entered = ready.setdefault(envelope.context.action_id, asyncio.Event())
            operation = asyncio.create_task(super().execute(envelope))
            await entered.wait()
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
            raise ConnectionError("The acknowledgement transport ended before the handler")

    return tools, LostAcknowledgementExecutor(tools), release, effects


def test_parallel_confirmed_effects_do_not_release_root_before_both_real_handlers_end(tmp_path):
    async def scenario():
        tools, executor, release, effects = held_thread_executor(asyncio.get_running_loop())
        engine = make_engine(
            SQLiteStore(tmp_path / "real-parallel.sqlite"),
            ScriptedProvider(
                [tool_response(arguments={"value": 1}), tool_response(arguments={"value": 2})]
            ),
            tools,
            tool_executor=executor,
        )
        try:
            worker = AgentSpec("worker", "Change", ("change",), model_credits=0)
            handle = engine.submit(
                GraphWorkflowSpec(
                    "parallel",
                    [GraphNode("one", agent=worker), GraphNode("two", agent=worker)],
                    max_concurrency=2,
                ),
                "q",
                command_id="s",
                budget=0,
            )
            assert (await engine.drive(handle.run_id)).state == "waiting_reconciliation"
            assert len(effects) == 2 and engine._threads.active_count == 2
            engine.cancel(handle.run_id, command_id="cancel")
            actions = [
                action
                for action in engine.status(handle.run_id).actions
                if action["kind"] == "tool"
            ]
            for action in actions:
                assert action["status"] == "outcome_unknown"
                engine.reconcile(
                    handle.run_id,
                    action["id"],
                    {"changed": True},
                    command_id="verify-" + action["id"],
                )
            assert engine.store.budget(handle.run_id) == {"limit": 0, "held": 0, "spent": 0}
            assert engine._threads.active_count == 2
            assert engine.store.local_capacity_holders(engine.scope) == (handle.run_id,)
            with pytest.raises(CapacityExceeded):
                engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")
            with pytest.raises(ValidationError):
                engine.close()
            release.set()
            await engine.wait_for_threads()
            assert (await engine.drive(handle.run_id)).state == "cancelled"
            assert engine.store.local_capacity_holders(engine.scope) == ()
            engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")
        finally:
            release.set()
            await engine.wait_for_threads()
            engine.close()

    asyncio.run(scenario())


def test_store_close_failure_keeps_original_lease_and_unknown_capacity_after_handler_exit(tmp_path):
    class CloseUnavailableStore(SQLiteStore):
        close_unavailable = False

        def close(self):
            if self.close_unavailable:
                raise ConnectionError("Execution store close remains incomplete")
            return super().close()

    async def scenario():
        path = tmp_path / "close-failure.sqlite"
        store = CloseUnavailableStore(path)
        tools, executor, release, effects = held_thread_executor(asyncio.get_running_loop())
        engine = make_engine(
            store, ScriptedProvider([tool_response()]), tools, tool_executor=executor
        )
        try:
            handle = engine.submit(
                AgentSpec("worker", "Change", ("change",), model_credits=0),
                "q",
                command_id="s",
                budget=0,
            )
            assert (await engine.drive(handle.run_id)).state == "waiting_reconciliation"
            assert len(effects) == 1 and engine._threads.has_active
            release.set()
            await engine.wait_for_threads()
            engine.cancel(handle.run_id, command_id="cancel")
            assert not engine._threads.has_active
            assert engine.status(handle.run_id).actions[-1]["status"] == "outcome_unknown"
            store.close_unavailable = True
            with pytest.raises(ConnectionError):
                engine.close()
            assert store.local_capacity_holders(Scope()) == (handle.run_id,)
            with pytest.raises(ValidationError):
                engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")
            with SQLiteStore(path) as contender:
                with pytest.raises(CoordinatorBusy):
                    make_engine(contender)
            store.close_unavailable = False
            engine.close()
            with make_engine(SQLiteStore(path), tools=tools, tool_executor=executor) as restored:
                assert restored.store.local_capacity_holders(restored.scope) == (handle.run_id,)
                with pytest.raises(CapacityExceeded):
                    restored.submit(AgentSpec("next", "Answer"), "q", command_id="next")
        finally:
            release.set()
            if engine._lifecycle == "open":
                await engine.wait_for_threads()
            store.close_unavailable = False
            engine.close()

    asyncio.run(scenario())


def test_failed_but_fully_received_verifier_child_cannot_leave_parent_capacity_forever(tmp_path):
    class AcceptGate:
        identity = {"kind": "review-verifier-child-gate", "version": "1"}

        def verify(self, request):
            return ParentCompletionVerdict("accept")

    class Provider:
        identity = {"kind": "review-verifier-rejected-response", "version": "1"}

        async def complete(self, messages, tools):
            return (
                ModelResponse()
                if messages[0]["content"] == "judge"
                else ModelResponse(output="done")
            )

    with make_engine(
        SQLiteStore(tmp_path / "verifier-failed.sqlite"),
        Provider(),
        parent_completion_policies={
            "gate": ParentCompletionPolicy(
                AcceptGate(), model_stage=ModelParentVerificationStage(instructions="judge")
            )
        },
    ) as engine:
        handle = engine.submit(
            TeamSpec(
                "team",
                {"worker": AgentSpec("worker", "Answer")},
                completion_policy="gate",
                child_budget=4,
            ),
            "q",
            command_id="s",
            budget=8,
        )
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        record = engine.store.run(handle.run_id)
        stage = record["parent_completion_stages"]["r0"]
        verifier = engine.store.run(stage["child_run_id"])
        assert verifier["state"] == "failed" and verifier["actions"][0]["status"] == "rejected"
        assert all(child["settled"] for child in record["orchestration"]["children"])
        assert engine.store.budget(handle.run_id) == {"limit": 8, "held": 0, "spent": 2}
        assert not engine._active and not engine._drive_users and not engine._threads.has_active
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        assert engine.store.local_capacity_holders(engine.scope) == ()
        engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")


def test_unknown_verifier_cannot_be_retired_or_free_root_after_parent_cancellation(tmp_path):
    class AcceptGate:
        identity = {"kind": "review-unknown-verifier-gate", "version": "1"}

        def verify(self, request):
            return ParentCompletionVerdict("accept")

    class UnknownVerifierProvider:
        identity = {"kind": "review-unknown-verifier-provider", "version": "1"}

        async def complete(self, messages, tools):
            if messages[0]["content"] == "judge":
                raise ConnectionError("The verifier response was not acknowledged")
            return ModelResponse(output="done")

    selected = ParentCompletionPolicy(
        AcceptGate(), model_stage=ModelParentVerificationStage(instructions="judge")
    )
    provider = UnknownVerifierProvider()
    path = tmp_path / "unknown-verifier.sqlite"
    with make_engine(
        SQLiteStore(path), provider, parent_completion_policies={"gate": selected}
    ) as engine:
        handle = engine.submit(
            TeamSpec(
                "team",
                {"worker": AgentSpec("worker", "Answer")},
                completion_policy="gate",
                child_budget=4,
            ),
            "q",
            command_id="s",
            budget=8,
        )
        asyncio.run(engine.drive(handle.run_id))
        original_stage = engine.store.run(handle.run_id)["parent_completion_stages"]["r0"]
        verifier_id = original_stage["child_run_id"]
        assert engine.status(verifier_id).actions[0]["status"] == "outcome_unknown"
        engine.cancel(handle.run_id, command_id="cancel")
        assert asyncio.run(engine.drive(handle.run_id)).state == "cancelled"
        assert (
            engine.store.run(handle.run_id)["parent_completion_stages"]["r0"]["status"]
            == "child_pending"
        )
        assert engine.store.budget(verifier_id)["held"] == 1
        assert engine.store.local_capacity_holders(engine.scope) == (handle.run_id,)
    with make_engine(
        SQLiteStore(path), provider, parent_completion_policies={"gate": selected}
    ) as engine:
        assert asyncio.run(engine.drive(handle.run_id)).state == "cancelled"
        stage = engine.store.run(handle.run_id)["parent_completion_stages"]["r0"]
        assert stage["status"] == "child_pending" and stage["adopted_verdict"] is None
        assert stage["source"] == original_stage["source"]
        assert engine.store.budget(verifier_id)["held"] == 1
        assert engine.store.local_capacity_holders(engine.scope) == (handle.run_id,)
        with pytest.raises(CapacityExceeded):
            engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")


def test_cold_recovery_retires_persisted_child_pending_only_after_known_verifier_closure(tmp_path):
    class RetainedClaimStore(SQLiteStore):
        allow_release = False

        def local_capacity_release(self, scope, root_run_id):
            return (
                super().local_capacity_release(scope, root_run_id) if self.allow_release else False
            )

    class AcceptGate:
        identity = {"kind": "review-cold-verifier-gate", "version": "1"}

        def verify(self, request):
            return ParentCompletionVerdict("accept")

    class Provider:
        identity = {"kind": "review-cold-verifier-provider", "version": "1"}
        calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            return (
                ModelResponse()
                if messages[0]["content"] == "judge"
                else ModelResponse(output="done")
            )

    selected = ParentCompletionPolicy(
        AcceptGate(), model_stage=ModelParentVerificationStage(instructions="judge")
    )
    provider = Provider()
    path = tmp_path / "cold-child-pending.sqlite"
    with make_engine(
        RetainedClaimStore(path), provider, parent_completion_policies={"gate": selected}
    ) as engine:
        handle = engine.submit(
            TeamSpec(
                "team",
                {"worker": AgentSpec("worker", "Answer")},
                completion_policy="gate",
                child_budget=4,
            ),
            "q",
            command_id="s",
            budget=8,
        )
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        with engine.store.transaction():
            record = engine.store.run(handle.run_id)
            stage = record["parent_completion_stages"]["r0"]
            assert stage["status"] == "closed"
            # Recreate the valid durable window from before retirement committed.
            # This is a persisted crash-window simulation, not an actual SIGKILL.
            stage["status"] = "child_pending"
            original_source = stage["source"]
            original_release = record["release_digest"]
            engine.store.save_run(record)
        assert engine.store.local_capacity_holders(engine.scope) == (handle.run_id,)
        assert provider.calls == 2
    restored_store = RetainedClaimStore(path)
    restored_store.allow_release = True
    with make_engine(
        restored_store, provider, parent_completion_policies={"gate": selected}
    ) as engine:
        assert engine.store.local_capacity_holders(engine.scope) == (handle.run_id,)
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        record = engine.store.run(handle.run_id)
        stage = record["parent_completion_stages"]["r0"]
        assert stage["status"] == "closed" and stage["adopted_verdict"] is None
        assert stage["source"] == original_source and record["release_digest"] == original_release
        assert provider.calls == 2  # Terminal recovery does not re-dispatch either model.
        assert engine.store.budget(handle.run_id) == {"limit": 8, "held": 0, "spent": 2}
        assert engine.store.local_capacity_holders(engine.scope) == ()
        engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")


def test_received_verifier_with_invalid_evidence_reference_does_not_leak_capacity(tmp_path):
    class AcceptGate:
        identity = {"kind": "review-received-verdict-gate", "version": "1"}

        def verify(self, request):
            return ParentCompletionVerdict("accept")

    class InvalidEvidenceProvider:
        identity = {"kind": "review-received-verdict-provider", "version": "1"}

        async def complete(self, messages, tools):
            if messages[0]["content"] == "judge":
                # Valid bounded output Schema, but this evidence is not in the frozen source.
                return ModelResponse(
                    output={
                        "status": "accept",
                        "feedback": None,
                        "evidence_ids": ["child:" + "0" * 64],
                    }
                )
            return ModelResponse(output="done")

    with make_engine(
        SQLiteStore(tmp_path / "received-verdict.sqlite"),
        InvalidEvidenceProvider(),
        parent_completion_policies={
            "gate": ParentCompletionPolicy(
                AcceptGate(), model_stage=ModelParentVerificationStage(instructions="judge")
            )
        },
    ) as engine:
        handle = engine.submit(
            TeamSpec(
                "team",
                {"worker": AgentSpec("worker", "Answer")},
                completion_policy="gate",
                child_budget=4,
            ),
            "q",
            command_id="s",
            budget=8,
        )
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        record = engine.store.run(handle.run_id)
        stage = record["parent_completion_stages"]["r0"]
        original_proposal = stage["received_proposal"]
        assert original_proposal == {
            "status": "accept",
            "feedback": None,
            "evidence_ids": ["child:" + "0" * 64],
        }
        assert engine.status(stage["child_run_id"]).state == "succeeded"
        assert all(child["settled"] for child in record["orchestration"]["children"])
        assert engine.store.budget(handle.run_id) == {"limit": 8, "held": 0, "spent": 2}
        assert asyncio.run(engine.drive(handle.run_id)).state == "failed"
        assert (
            engine.store.run(handle.run_id)["parent_completion_stages"]["r0"]["received_proposal"]
            == original_proposal
        )
        assert (
            engine.store.run(handle.run_id)["parent_completion_stages"]["r0"]["adopted_verdict"]
            is None
        )
        assert engine.store.local_capacity_holders(engine.scope) == ()
        engine.submit(AgentSpec("next", "Answer"), "q", command_id="next")
