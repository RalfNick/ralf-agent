"""Independent final-review regressions, reproduced before the unified fix pass."""

import asyncio
import inspect

import pytest

import relf_agent as r
from relf_agent.errors import CloseIncomplete
from relf_agent.temporal_activities import TemporalRuntime

from .test_temporal_tool_execution import admission, proof
from .test_temporal_tool_execution import state_for as claimed_state_for


def state_for():
    runtime, state, action, request = claimed_state_for()
    state.tool_executions[action["id"]].pop("invocation_id", None)
    state.tool_executions[action["id"]].pop("grant_allowed", None)
    return runtime, state, action, request


def test_capacity_no_start_end_survives_transient_rpc_and_close_retries():
    runtime, state, _, request = state_for()

    async def run():
        owner = runtime.tool_execution
        release = asyncio.Event()
        calls = []

        async def held():
            await release.wait()

        holds = [
            asyncio.create_task(
                owner.execute(
                    held,
                    proof={
                        key: value
                        for key, value in {**proof(request), "action_id": f"held-{index}"}.items()
                        if key != "invocation_id"
                    },
                )
            )
            for index in range(8)
        ]
        await asyncio.sleep(0.01)

        async def guard(value, *, invocation_id):
            return state.admit_tool_dispatch(admission(value, invocation_id))

        async def ended(value):
            calls.append(value)
            if len(calls) == 1:
                raise ConnectionError("one lost no-start acknowledgement")
            state.tool_execution_ended(value)

        response = await runtime.execute_tool(request, dispatch_guard=guard, on_end=ended)
        state.accept_tool(request["action_id"], response)
        release.set()
        await asyncio.gather(*holds)
        await runtime.close_context_execution(wait_timeout=2)
        assert state.tool_executions[request["action_id"]]["execution_stopped"] is True
        assert len(calls) >= 2 and state.quiescent is True
        await owner.aclose()

    asyncio.run(run())


def test_independent_default_owners_cannot_execute_same_original_request_twice():
    runtime, state, _, request = state_for()
    other = TemporalRuntime(
        providers=runtime.providers,
        tools=runtime.tools,
        tool_execution=r.ToolExecutionOwner(version="1"),
    )
    assert runtime.manifest == other.manifest

    async def run():
        async def guard(value, *, invocation_id):
            return state.admit_tool_dispatch(admission(value, invocation_id))

        async def ended(value):
            state.tool_execution_ended(value)

        responses = await asyncio.gather(
            runtime.execute_tool(request, dispatch_guard=guard, on_end=ended),
            other.execute_tool(request, dispatch_guard=guard, on_end=ended),
        )
        assert sum(value.get("ok") is True for value in responses) == 1
        await runtime.close_context_execution()
        await other.close_context_execution()
        await runtime.tool_execution.aclose()
        await other.tool_execution.aclose()

    asyncio.run(run())


def test_custom_owner_lazy_execute_is_rejected_and_disposed_before_return():
    runtime, _, _, request = state_for()

    class Lazy(r.ToolExecutionOwner):
        async def execute(self, operation, *, proof, on_end=None):
            return operation()

    owner = Lazy(version="1")
    runtime = TemporalRuntime(
        providers=runtime.providers, tools=runtime.tools, tool_execution=owner
    )

    async def run():
        async def guard(value, *, invocation_id):
            return {
                "allowed": True,
                "invocation_id": invocation_id,
                "claimed": True,
                **{k: value[k] for k in ("run_id", "action_id", "release_digest")},
            }

        async def ended(value):
            return None

        request["runtime_manifest"] = runtime.manifest
        response = await runtime.execute_tool(request, dispatch_guard=guard, on_end=ended)
        if inspect.iscoroutine(response):
            response.close()  # Avoid a warning hiding the observed missing boundary.
        assert type(response) is dict and response["ok"] is False
        await runtime.close_context_execution(wait_timeout=0)
        await owner.aclose()

    asyncio.run(run())


def test_foreign_claim_cannot_confirm_actual_stop_of_admitted_owner():
    from relf_agent.errors import RalfError

    _, state, action, request = state_for()
    first = state.admit_tool_dispatch(admission(request, "a" * 32))
    second = state.admit_tool_dispatch(admission(request, "b" * 32))
    assert first["allowed"] is True and second["allowed"] is False
    with pytest.raises(RalfError):
        state.tool_execution_ended(proof(request, "b" * 32))
    assert state.tool_executions[action["id"]]["execution_stopped"] is False
    state.tool_execution_ended(proof(request, "a" * 32))
    assert state.tool_executions[action["id"]]["execution_stopped"] is True


def test_custom_wait_lazy_value_is_disposed_and_close_refuses():
    from relf_agent.errors import RalfError

    original, *_ = state_for()
    calls = []

    class Lazy(r.ToolExecutionOwner):
        async def wait(self, *, wait_timeout=30):
            async def lazy():
                calls.append(True)

            return lazy()

    runtime = TemporalRuntime(
        providers=original.providers,
        tools=original.tools,
        tool_execution=Lazy(version="1"),
    )

    async def run():
        with pytest.raises(RalfError):
            await runtime.close_context_execution()
        assert runtime._tool_execution_closing is True

    asyncio.run(run())
    assert calls == []


def test_cancelled_no_start_notification_observer_remains_owned_until_ack():
    runtime, state, _, request = state_for()

    async def run():
        release = asyncio.Event()
        entered = asyncio.Event()
        attempts = []
        state.command("cancel", {"kind": "cancel", "scope": state.scope})

        async def guard(value, *, invocation_id):
            return state.admit_tool_dispatch(admission(value, invocation_id))

        async def ended(value):
            attempts.append(value)
            entered.set()
            await release.wait()
            state.tool_execution_ended(value)

        response = await runtime.execute_tool(request, dispatch_guard=guard, on_end=ended)
        state.accept_tool(request["action_id"], response)
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(CloseIncomplete):
            await runtime.close_context_execution(wait_timeout=0)
        entry = next(iter(runtime._tool_notifications._entries.values()))
        entry["notification"].cancel()
        await asyncio.gather(entry["notification"], return_exceptions=True)
        release.set()
        await runtime.close_context_execution(wait_timeout=2)
        assert state.quiescent is True and len(attempts) >= 2
        await runtime.tool_execution.aclose()

    asyncio.run(run())
