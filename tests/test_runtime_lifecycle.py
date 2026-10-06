import asyncio
import threading

import pytest

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    ModelResponse,
    ProfiledEngine,
    RuntimeBuilder,
    RuntimeCatalog,
    RuntimeProfile,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from ralf_agent.errors import CoordinatorBusy, ValidationError


def test_cancelled_tasks_cannot_switch_profiles_while_a_real_handler_thread_is_alive(tmp_path):
    started, release = threading.Event(), threading.Event()
    closed = []

    class Client:
        def close(self):
            closed.append("closed")

    class Provider:
        identity = {"kind": "thread-profile-fixture", "version": "1"}

        async def complete(self, messages, tools):
            if any(message["role"] == "tool" for message in messages):
                return ModelResponse(output="done")
            return ModelResponse(tool_calls=(ToolCall("slow", {}),))

    def tools_factory(config, context):
        context.own(Client())

        def handler(arguments, invocation):
            started.set()
            assert release.wait(5)
            return {"effect": "confirmed"}

        tools = ToolRegistry()
        tools.register(
            ToolSpec("slow", "Local slow fixture", {"type": "object"}, effect="idempotent_write"),
            handler,
        )
        return tools

    registry = ComponentRegistry()
    registry.register("provider", "slow", lambda c, ctx: Provider())
    registry.register("tools", "slow", tools_factory)
    catalog = RuntimeCatalog()
    catalog.register(
        RuntimeProfile(
            "app", "1", {"default": {"adapter": "slow"}}, {"tools": {"adapter": "slow"}}
        ),
        default=True,
    )
    catalog.register(RuntimeProfile("app", "2", {"default": {"adapter": "offline-echo"}}))
    path = tmp_path / "thread.sqlite"
    runtime = ProfiledEngine(catalog, path, builder=RuntimeBuilder(registry))

    async def scenario():
        first = runtime.submit(AgentSpec("a", "Run", ("slow",)), "q", command_id="s")
        driving = asyncio.create_task(runtime.drive(first.run_id))
        assert await asyncio.to_thread(started.wait, 2)
        victims = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in victims:
            task.cancel()
        await asyncio.gather(*victims, return_exceptions=True)
        assert driving.done()
        catalog.set_default("app", "2")
        with pytest.raises(ValidationError):
            runtime.submit(AgentSpec("b", "Answer"), "q", command_id="new")
        assert closed == []
        with SQLiteStore(path) as store:
            with pytest.raises(CoordinatorBusy):
                store.create_coordinator().acquire()
        release.set()
        await runtime.wait_for_threads()
        second = runtime.submit(AgentSpec("b", "Answer"), "q", command_id="new")
        assert (await runtime.drive(second.run_id)).state == "succeeded"
        assert closed == ["closed"]

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        asyncio.run(runtime.wait_for_threads())
        runtime.close()
