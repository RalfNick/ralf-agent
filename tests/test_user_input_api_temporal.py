"""Network-only doubles exercise original Temporal state through the public Facade."""

import asyncio
from dataclasses import replace
from types import MethodType

import pytest

from relf_agent import AgentSpec, Runtime
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.tools import ToolRegistry
from relf_agent.user_input import register_user_input

from .temporal_agent_fixture import StateClient, engine
from .test_temporal_memory_bindings import grant
from .test_temporal_user_input import QuestionProvider


class InputClient(StateClient):
    def __init__(self):
        super().__init__()
        tools = ToolRegistry()
        register_user_input(tools)
        self.worker_runtime = TemporalRuntime(
            providers={"default": QuestionProvider()}, tools=tools
        )

    async def advance(self, run_id):
        state = self.states[run_id]
        for _ in range(20):
            operation = state.next_operation()
            if operation is None:
                return
            action, request = operation
            if action["kind"] == "model":
                state.accept_model(
                    action["id"],
                    await self.worker_runtime.complete_model(
                        request,
                        dispatch_guard=lambda value: grant(state, value),
                    ),
                )
            elif action["kind"] == "model_adoption":
                state.accept_model_adoption(
                    action["id"], await self.worker_runtime.adopt_model(request)
                )
            else:
                assert action["kind"] == "context"
                state.accept_context(
                    action["id"],
                    await self.worker_runtime.prepare_context(
                        request,
                        dispatch_guard=lambda value: grant(state, value),
                    ),
                )
        raise AssertionError("Unbounded fixture execution")


@pytest.mark.parametrize("control", [None, lambda *arguments, **options: None])
def test_selected_temporal_facade_requires_async_optional_control_before_acceptance(
    monkeypatch, control
):
    async def run():
        client = StateClient()
        legacy = engine(monkeypatch, client=client)
        monkeypatch.setattr(legacy, "send_input", control)
        async with Runtime.from_temporal(legacy):
            pass
        selected_client = InputClient()
        selected = engine(
            monkeypatch, client=selected_client, release=selected_client.worker_runtime.manifest
        )
        monkeypatch.setattr(selected, "send_input", control)
        with pytest.raises(ValidationError, match="user input"):
            Runtime.from_temporal(selected)
        assert selected_client.states == {} and selected_client.registries == {}
        assert not selected_client.closed  # Failed transfer retains the caller's client.

    asyncio.run(run())


def test_temporal_facade_exposes_question_and_returns_schema_rejection_receipt(monkeypatch):
    async def run():
        client = InputClient()
        raw = engine(monkeypatch, client=client, release=client.worker_runtime.manifest)
        async with Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(AgentSpec("a", "Ask", ("request_input",))).submit(
                "Choose",
                command_id="start",
            )
            question = (await run.pending())[0]
            assert question["kind"] == "input" and question["ref"] == run.ref.to_dict()
            rejected = await run.send_input(
                question["pending_id"], question["target_digest"], {}, command_id="bad"
            )
            assert rejected.apply_state == "rejected"
            assert rejected.outcome["reason"] == "invalid_input"
            assert (await run.status()).state == "waiting_input"
            receipt = await run.send_input(
                question["pending_id"], question["target_digest"], "wire", command_id="answer"
            )
            assert (await run.wait(wait_timeout=1)).snapshot.result == "Selected wire"
            assert await run.pending() == []
            assert (
                await run.send_input(
                    question["pending_id"], question["target_digest"], "wire", command_id="answer"
                )
                == receipt
            )

    asyncio.run(run())


def test_native_temporal_question_with_foreign_owner_is_rejected_not_hidden(monkeypatch):
    async def run():
        client = InputClient()
        raw = engine(monkeypatch, client=client, release=client.worker_runtime.manifest)
        async with Runtime.from_temporal(raw) as runtime:
            run = await runtime.create_agent(AgentSpec("a", "Ask", ("request_input",))).submit(
                "Choose",
                command_id="start",
            )
            observe = runtime._observe_with

            async def foreign(self, view, ref, kind, **options):
                info = await observe(view, ref, kind, **options)
                if kind == "diagnostics":
                    item = dict(info.snapshot.pending[0])
                    item["owner"] = {**item["owner"], "run_id": "foreign"}
                    info = replace(info, snapshot=replace(info.snapshot, pending=(item,)))
                return info

            runtime._observe_with = MethodType(foreign, runtime)
            with pytest.raises((DefinitionMismatch, ValidationError)):
                await run.pending()

    asyncio.run(run())
