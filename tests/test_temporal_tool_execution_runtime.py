"""Fixed borrowed owner and original admission/end callbacks before Tool I/O."""

import asyncio

import pytest

import ralf_agent as r
from ralf_agent.errors import RalfError
from ralf_agent.temporal_tool_execution import ToolExecutionRegistration

from .test_temporal_tool_execution import admission, proof, state_for


@pytest.mark.parametrize("kind", ["tuple", "dict-subclass", "nan", "depth", "values"])
def test_owner_identity_is_bounded_ordinary_json_before_copy(kind):
    class Unsafe(dict):
        def __deepcopy__(self, memo):
            raise AssertionError("copy hook must not run")

    value = {
        "tuple": {"value": ()},
        "dict-subclass": Unsafe(value="unsafe"),
        "nan": {"value": float("nan")},
        "values": {"value": [0] * 4097},
    }.get(kind)
    if kind == "depth":
        value = {}
        for _ in range(18):
            value = {"child": value}

    class Owner(r.ToolExecutionOwner):
        @property
        def identity(self):
            return value

    with pytest.raises(RalfError):
        ToolExecutionRegistration(Owner(version="1"))


def test_owner_configuration_drift_refuses_before_tool_or_end_notification():
    runtime, state, _, request = state_for()
    runtime.tool_execution._version = "changed"
    callbacks = []

    async def guard(value):
        callbacks.append("guard")
        return state.admit_tool_dispatch(admission(value))

    async def ended(value):
        callbacks.append("end")

    async def run():
        response = await runtime.execute_tool(request, dispatch_guard=guard, on_end=ended)
        assert response["ok"] is False and response["dispatched"] is False

    asyncio.run(run())
    assert callbacks == []


def test_cancel_before_real_admission_has_original_end_without_business_dispatch():
    runtime, state, _, request = state_for()
    state.command("cancel", {"kind": "cancel", "scope": state.scope})
    ends = []

    async def guard(value):
        return state.admit_tool_dispatch(admission(value))

    async def ended(value):
        ends.append(value)
        state.tool_execution_ended(value)

    async def run():
        response = await runtime.execute_tool(request, dispatch_guard=guard, on_end=ended)
        assert response["ok"] is False and response["dispatched"] is False
        assert await runtime.wait_context_executions(wait_timeout=2)
        assert ends == [proof(request)]
        state.accept_tool(request["action_id"], response)
        assert state.quiescent is True and state.state == "cancelled"
        await runtime.close_context_execution()
        assert runtime.tool_execution._closing is False
        await runtime.tool_execution.aclose()

    asyncio.run(run())


def test_true_operation_has_one_fixed_end_and_duplicate_refuses_without_dispatch():
    runtime, state, _, request = state_for()
    ends = []

    async def guard(value):
        return state.admit_tool_dispatch(admission(value))

    async def ended(value):
        ends.append(value)
        state.tool_execution_ended(value)

    async def run():
        first = await runtime.execute_tool(request, dispatch_guard=guard, on_end=ended)
        assert first == {"ok": True, "result": {}, "source": "tool-handler"}
        assert await runtime.wait_context_executions(wait_timeout=2)
        second = await runtime.execute_tool(request, dispatch_guard=guard, on_end=ended)
        assert second["ok"] is False and second["dispatched"] is False
        assert ends[0] == proof(request)
        await runtime.close_context_execution()
        await runtime.tool_execution.aclose()

    asyncio.run(run())


def test_tool_and_context_owner_protocols_compose_without_changing_context_version():
    from ralf_agent.temporal_activities import TemporalRuntime

    from .test_temporal_engine import Provider, registry

    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=registry(),
        context_reads=True,
        tool_execution=r.ToolExecutionOwner(version="1"),
    )
    assert runtime.manifest["binding_protocol"] == 3
    assert runtime.manifest["context_read_protocol"]["version"] == 1
    assert runtime.manifest["tool_execution_protocol"]["version"] == 1
    asyncio.run(runtime.close_context_execution())


@pytest.mark.parametrize("kind", ["sync", "generator", "async-generator"])
def test_lazy_owner_methods_refuse_at_construction(kind):
    class Owner(r.ToolExecutionOwner):
        pass

    def sync(self, operation, **options):
        return None

    def generator(self, operation, **options):
        yield None

    async def async_generator(self, operation, **options):
        yield None

    Owner.execute = {"sync": sync, "generator": generator, "async-generator": async_generator}[kind]
    with pytest.raises(RalfError):
        ToolExecutionRegistration(Owner(version="1"))


def test_callback_pins_original_handle_and_refuses_namespace_drift():
    from types import SimpleNamespace

    from ralf_agent.temporal_tool_execution_activities import callbacks

    _, _, _, request = state_for()
    calls = []

    class Handle:
        async def execute_update(self, name, value, **options):
            calls.append((name, value))
            if name == "tool_execution_ended":
                return {"action_id": request["action_id"], "recorded": True}
            return {
                "run_id": request["run_id"],
                "action_id": request["action_id"],
                "release_digest": request["release_digest"],
                "allowed": True,
            }

    class Client:
        namespace = "original"

        def get_workflow_handle(self, name, *, run_id):
            assert name == request["run_id"] and run_id == request["execution_epoch"]
            return Handle()

    client = Client()
    guard, ended = callbacks(
        client,
        request,
        SimpleNamespace(
            workflow_id=request["run_id"],
            workflow_run_id=request["execution_epoch"],
            workflow_namespace="original",
        ),
    )

    async def run():
        assert (await guard(request))["allowed"] is True
        await ended(proof(request))
        client.namespace = "foreign"
        with pytest.raises(RalfError):
            await guard(request)
        with pytest.raises(RalfError):
            await ended(proof(request))

    asyncio.run(run())
    assert [name for name, _ in calls] == ["admit_tool_dispatch", "tool_execution_ended"]
