"""A pending child question is observable before another real handler exits."""

import asyncio
import threading

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    Runtime,
    SQLiteStore,
    TeamSpec,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import CloseIncomplete, CoordinatorBusy
from relf_agent.user_input import register_user_input


def test_default_wait_surfaces_child_question_while_real_sibling_is_active(tmp_path):
    async def run():
        started, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        class Provider:
            identity = {"kind": "active-sibling-user-input", "version": "1"}

            async def complete(self, messages, tools):
                if any(item["role"] == "tool" for item in messages) or not tools:
                    return ModelResponse(output="completed")
                name = tools[0]["function"]["name"]
                return ModelResponse(
                    tool_calls=(
                        ToolCall(
                            name,
                            {"prompt": "Which environment?"} if name == "request_input" else {},
                        ),
                    )
                )

        def busy(arguments, context):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5), "test must release its actual handler"
            return {"completed": True}

        path = tmp_path / "siblings.sqlite"
        tools = ToolRegistry()
        register_user_input(tools)
        tools.register(ToolSpec("busy", "A real blocking read", {"type": "object"}), busy)
        raw = LocalEngine(SQLiteStore(path), providers={"default": Provider()}, tools=tools)
        runtime = Runtime(raw, owned=True)
        try:
            root = await runtime.create_agent(
                TeamSpec(
                    "team",
                    {
                        "ask": AgentSpec("ask", "Ask", ("request_input",)),
                        "busy": AgentSpec("busy", "Read", ("busy",)),
                        "finish": AgentSpec("finish", "Summarize"),
                    },
                    strategy="supervisor",
                    strategy_config={"supervisor": "finish"},
                    max_concurrency=2,
                )
            ).submit("Choose", command_id="start", budget=64)
            await asyncio.wait_for(started.wait(), 1)
            observed = await root.wait(wait_timeout=0.2)
            assert observed.wait_reason == "control_available"
            assert observed.snapshot.state == "running"
            question = (await root.pending())[0]
            assert question["kind"] == "input" and question["ref"]["run_id"] != root.ref.run_id
            assert not release.is_set()
            terminal = await root.wait(wait_timeout=0.02, terminal_only=True)
            assert terminal.wait_reason == "observation_timeout"
            observer = asyncio.create_task(root.wait(terminal_only=True))
            await asyncio.sleep(0)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert (await root.pending())[0] == question
            with pytest.raises(CloseIncomplete):
                await runtime.aclose(close_timeout=0.01)
            with SQLiteStore(path) as contender:
                with pytest.raises(CoordinatorBusy):
                    contender.create_coordinator().acquire()
            release.set()
            report = await runtime.aclose(close_timeout=2)
            assert report.state == "closed" and root.ref in report.parked
        finally:
            release.set()
            await runtime.aclose(close_timeout=2)

    asyncio.run(run())
