"""Independent review of source identity and received execution evidence."""

import asyncio

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.executors import EffectObservation

from .helpers import ScriptedProvider
from .receipt_runtime import ReceiptWindowStore


class SwitchingProvider:
    def __init__(self):
        self.version = "1"
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    @property
    def identity(self):
        return {"kind": "source-switch-review", "version": self.version}

    async def complete(self, messages, tools):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ModelResponse(output={"source_version": self.version}, usage={"input_tokens": 9})


def test_actual_provider_change_cannot_hide_behind_replacement_with_the_pinned_identity(tmp_path):
    async def scenario():
        provider = SwitchingProvider()
        replacement = SwitchingProvider()
        with LocalEngine(
            SQLiteStore(tmp_path / "provider.db"),
            providers={"default": provider},
            tools=ToolRegistry(),
        ) as engine:
            handle = engine.submit(
                AgentSpec("review", "Return the observed version"), {}, command_id="s"
            )
            drive = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(provider.started.wait(), 2)
            provider.version = "2"
            engine.providers["default"] = replacement
            provider.release.set()
            done = await asyncio.wait_for(drive, 2)
            assert provider.calls == 1 and replacement.calls == 0
            assert done.state == "failed" and done.error["code"] == "definition_mismatch"
            model = done.actions[0]
            assert model["received_response"]["output"] == {"source_version": "2"}
            assert model["attempts"][0]["status"] != "unknown"
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 1}

    asyncio.run(scenario())


def test_provider_change_after_dispatch_intent_is_rejected_before_a_paid_request(tmp_path):
    async def scenario():
        provider = SwitchingProvider()
        provider.release.set()
        store = ReceiptWindowStore(
            tmp_path / "model-intent.db", trigger_event="model_dispatched", trigger_mode="callback"
        )
        with LocalEngine(store, providers={"default": provider}, tools=ToolRegistry()) as engine:
            store.after_record = lambda run_id: setattr(provider, "version", "2")
            handle = engine.submit(
                AgentSpec("review", "Return the observed version"), {}, command_id="s"
            )
            done = await engine.drive(handle.run_id)
            assert provider.calls == 0
            assert done.state == "failed" and done.error["code"] == "definition_mismatch"
            assert done.actions[0]["attempts"][0]["status"] != "unknown"
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 0}

    asyncio.run(scenario())


class ReviewExecutor:
    def __init__(self):
        self.version = "1"
        self.execute_calls = []
        self.reconcile_calls = []
        self.reconcile_started = asyncio.Event()
        self.reconcile_release = asyncio.Event()
        self.reconcile_result = EffectObservation({"written": True}, "review-reconcile")
        self.fail_execute = False

    @property
    def identity(self):
        return {"kind": "executor-source-review", "version": self.version}

    async def execute(self, envelope):
        self.execute_calls.append(envelope)
        if self.fail_execute:
            raise TimeoutError("Response lost")
        return EffectObservation({"written": True}, "review-execute")

    async def reconcile(self, envelope):
        self.reconcile_calls.append(envelope)
        self.reconcile_started.set()
        await self.reconcile_release.wait()
        return self.reconcile_result


def review_tools(effect="queryable_write"):
    tools = ToolRegistry()

    def local_handler(arguments, context):
        pytest.fail("An injected executor owns dispatch; the descriptor handler must not run")

    tools.register(
        ToolSpec("write", "Write once", {"type": "object"}, effect=effect),
        local_handler,
    )
    return tools


def tool_provider():
    return ScriptedProvider(
        [ModelResponse(tool_calls=(ToolCall("write", {}),)), ModelResponse(output="done")]
    )


def test_definition_rejection_before_actual_dispatch_does_not_invent_unknown_effect(tmp_path):
    executor = ReviewExecutor()
    store = ReceiptWindowStore(
        tmp_path / "dispatch.db", trigger_event="tool_dispatch_intent", trigger_mode="callback"
    )
    with LocalEngine(
        store, providers={"default": tool_provider()}, tools=review_tools(), tool_executor=executor
    ) as engine:
        store.after_record = lambda run_id: setattr(executor, "version", "2")
        handle = engine.submit(AgentSpec("review", "Write once", ("write",)), {}, command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert executor.execute_calls == []
        assert done.state == "failed" and done.error["code"] == "definition_mismatch"
        action = next(action for action in done.actions if action["kind"] == "tool")
        assert action["status"] != "outcome_unknown"
        assert action["attempts"][0]["status"] != "unknown"
        assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 1}


@pytest.mark.parametrize("kind", ["model", "tool"])
def test_cancel_after_dispatch_intent_prevents_the_actual_component_call(tmp_path, kind):
    executor = ReviewExecutor()
    provider = tool_provider()
    store = ReceiptWindowStore(
        tmp_path / "cancel-intent.db",
        trigger_event="model_dispatched" if kind == "model" else "tool_dispatch_intent",
        trigger_mode="callback",
    )
    with LocalEngine(
        store,
        providers={"default": provider},
        tools=review_tools(),
        tool_executor=executor,
    ) as engine:
        store.after_record = lambda run_id: engine.cancel(run_id, command_id="cancel-before-call")
        handle = engine.submit(AgentSpec("review", "Write once", ("write",)), {}, command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "cancelled" and done.result is None
        assert executor.execute_calls == []
        assert provider.calls == (0 if kind == "model" else 1)
        last_action = done.actions[-1]
        assert last_action["status"] != "outcome_unknown"
        assert last_action["attempts"][-1]["status"] != "unknown"
        assert engine.store.budget(handle.run_id) == {
            "limit": 32,
            "held": 0,
            "spent": 0 if kind == "model" else 1,
        }


@pytest.mark.parametrize("rejection", ["definition_mismatch", "cancelled"])
def test_rejected_retry_releases_only_its_own_reservation_and_keeps_the_previous_unknown(
    tmp_path, rejection
):
    class NextIntentStore(SQLiteStore):
        after_next_intent = None

        def emit(self, run_id, kind, data=None):
            super().emit(run_id, kind, data)
            if kind == "tool_dispatch_intent" and self.after_next_intent is not None:
                callback, self.after_next_intent = self.after_next_intent, None
                callback()

    async def scenario():
        executor = ReviewExecutor()
        executor.fail_execute = True
        executor.reconcile_result = None
        executor.reconcile_release.set()
        store = NextIntentStore(tmp_path / "retry-not-dispatched.db")
        with LocalEngine(
            store,
            providers={"default": tool_provider()},
            tools=review_tools(effect="idempotent_write"),
            tool_executor=executor,
        ) as engine:
            handle = engine.submit(
                AgentSpec("review", "Write once", ("write",)), {}, command_id="s"
            )
            assert (await engine.drive(handle.run_id)).state == "waiting_reconciliation"
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 1, "spent": 1}
            store.after_next_intent = (
                (lambda: setattr(executor, "version", "2"))
                if rejection == "definition_mismatch"
                else (lambda: engine.cancel(handle.run_id, command_id="cancel-retry"))
            )
            done = await engine.drive(handle.run_id)
            if rejection == "definition_mismatch":
                assert done.state == "failed" and done.error["code"] == "definition_mismatch"
            else:
                assert done.state == "cancelled"
            assert len(executor.execute_calls) == len(executor.reconcile_calls) == 1
            action = next(action for action in done.actions if action["kind"] == "tool")
            assert len(action["attempts"]) == 2
            assert action["attempts"][0]["status"] == "unknown"
            assert action["attempts"][1]["status"] != "unknown"
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 1, "spent": 1}
            assert action["status"] == "outcome_unknown"
            assert engine.store.unresolved_effect(engine.scope, "write", {}, "new-action") == {
                "run_id": handle.run_id,
                "action_id": action["id"],
            }
            engine.providers["default"] = tool_provider()
            second = engine.submit(
                AgentSpec("other-review", "Write once", ("write",)), {}, command_id="other-run"
            )
            blocked = await engine.drive(second.run_id)
            assert blocked.state == "waiting_reconciliation"
            assert blocked.error == {
                "code": "prior_effect_unknown",
                "run_id": handle.run_id,
                "action_id": action["id"],
            }
            assert len(executor.execute_calls) == 1
            engine.reconcile(
                handle.run_id, action["id"], {"written": True}, command_id="confirm-original-effect"
            )
            confirmed = engine.status(handle.run_id)
            assert confirmed.state == (
                "failed" if rejection == "definition_mismatch" else "cancelled"
            )
            tool = next(action for action in confirmed.actions if action["kind"] == "tool")
            assert tool["status"] == "completed" and tool["result"] == {"written": True}
            assert tool["attempts"][0]["status"] == "completed"
            assert tool["attempts"][1]["status"] == "not_dispatched"
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 0, "spent": 2}
            assert engine.store.unresolved_effect(engine.scope, "write", {}, "new-action") is None

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", [{"written": True}, False, "confirmed"])
def test_invalid_reconcile_result_is_a_typed_error_without_fabricating_evidence(tmp_path, invalid):
    async def scenario():
        executor = ReviewExecutor()
        executor.fail_execute = True
        executor.reconcile_result = invalid
        executor.reconcile_release.set()
        with LocalEngine(
            SQLiteStore(tmp_path / "invalid-reconcile.db"),
            providers={"default": tool_provider()},
            tools=review_tools(),
            tool_executor=executor,
        ) as engine:
            handle = engine.submit(
                AgentSpec("review", "Write once", ("write",)), {}, command_id="s"
            )
            assert (await engine.drive(handle.run_id)).state == "waiting_reconciliation"
            done = await engine.drive(handle.run_id)
            assert done.state == "failed" and done.error["code"] == "validation_error"
            assert len(executor.execute_calls) == len(executor.reconcile_calls) == 1
            action = next(action for action in done.actions if action["kind"] == "tool")
            assert action["status"] == "outcome_unknown"
            assert "effect_observation" not in action
            assert not any(
                event.kind == "tool_receipt_recorded" for event in engine.events(handle.run_id)
            )
            assert engine.store.budget(handle.run_id) == {"limit": 32, "held": 1, "spent": 1}

    asyncio.run(scenario())


def test_reconcile_has_its_own_backend_even_without_a_descriptor_reconciler(tmp_path):
    async def scenario():
        executor = ReviewExecutor()
        executor.fail_execute = True
        executor.reconcile_release.set()
        with LocalEngine(
            SQLiteStore(tmp_path / "reconcile.db"),
            providers={"default": tool_provider()},
            tools=review_tools(),
            tool_executor=executor,
        ) as engine:
            handle = engine.submit(
                AgentSpec("review", "Write once", ("write",)), {}, command_id="s"
            )
            waiting = await engine.drive(handle.run_id)
            assert waiting.state == "waiting_reconciliation"
            done = await engine.drive(handle.run_id)
            assert done.state == "succeeded"
            assert len(executor.execute_calls) == len(executor.reconcile_calls) == 1
            action = next(action for action in done.actions if action["kind"] == "tool")
            assert action["result"] == {"written": True}
            assert (
                executor.reconcile_calls[0].tool_manifest
                == engine.store.run(handle.run_id)["manifest"]["tools"]["write"]
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("known_result", [None, {"written": True}])
def test_reconcile_component_change_never_retries_and_keeps_received_evidence(
    tmp_path, known_result
):
    async def scenario():
        executor = ReviewExecutor()
        executor.fail_execute = True
        executor.reconcile_result = (
            None if known_result is None else EffectObservation(known_result)
        )
        replacement = ReviewExecutor()
        with LocalEngine(
            SQLiteStore(tmp_path / "reconcile-change.db"),
            providers={"default": tool_provider()},
            tools=review_tools(),
            tool_executor=executor,
        ) as engine:
            handle = engine.submit(
                AgentSpec("review", "Write once", ("write",)), {}, command_id="s"
            )
            assert (await engine.drive(handle.run_id)).state == "waiting_reconciliation"
            drive = asyncio.create_task(engine.drive(handle.run_id))
            await asyncio.wait_for(executor.reconcile_started.wait(), 2)
            executor.version = "2"
            engine.tool_executor = replacement
            executor.reconcile_release.set()
            done = await asyncio.wait_for(drive, 2)
            assert done.state == "failed" and done.error["code"] == "definition_mismatch"
            assert len(executor.execute_calls) == 1
            assert replacement.execute_calls == replacement.reconcile_calls == []
            action = next(action for action in done.actions if action["kind"] == "tool")
            if known_result is not None:
                assert action["status"] == "receipt_received"
                assert action["effect_observation"]["result"] == known_result
                assert action["attempts"][0]["status"] != "unknown"

    asyncio.run(scenario())
