import asyncio
import threading

import pytest

from relf_agent import (
    AgentSpec,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    ToolCall,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.errors import CoordinatorBusy, ValidationError
from relf_agent.handoff import SQLiteInbox


def test_owned_local_service_shutdown_retains_lease_until_real_handler_exit(tmp_path):
    from relf_agent.service_lifecycle import LocalA2AService

    async def run():
        started = asyncio.Event()
        finish = threading.Event()
        loop = asyncio.get_running_loop()

        class Provider:
            identity = {"kind": "service-thread", "version": "1"}

            async def complete(self, messages, tools):
                return ModelResponse(tool_calls=[ToolCall("wait", {})])

        def handler(arguments, context):
            loop.call_soon_threadsafe(started.set)
            finish.wait(5)
            return {"finished": True}

        tools = ToolRegistry()
        tools.register(ToolSpec("wait", "Wait", {"type": "object"}), handler)
        path = tmp_path / "runs.sqlite"
        engine = LocalEngine(SQLiteStore(path), providers={"default": Provider()}, tools=tools)
        inbox = SQLiteInbox(tmp_path / "inbox.sqlite")

        async def auth(headers):
            return Scope()

        service = LocalA2AService(
            engine=engine,
            inbox=inbox,
            spec=AgentSpec("a", "Wait", ("wait",)),
            authenticate=auth,
            url="http://test/rpc",
        )
        handle = engine.submit(AgentSpec("a", "Wait", ("wait",)), "input", command_id="first")
        closing = None
        try:
            await service.wakeup(Scope(), handle.run_id)
            await asyncio.wait_for(started.wait(), 2)
            closing = asyncio.create_task(service.aclose())
            await asyncio.sleep(0.02)
            assert not closing.done()
            with SQLiteStore(path) as contender:
                with pytest.raises(CoordinatorBusy):
                    contender.create_coordinator().acquire()
            with pytest.raises(ValidationError):
                await service.wakeup(Scope(), handle.run_id)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            finish.set()
            await asyncio.wait_for(service.aclose(), 2)
            assert service.closed
            with LocalEngine(SQLiteStore(path), providers={"default": Provider()}, tools=tools):
                pass
        finally:
            finish.set()
            await service.aclose()

    asyncio.run(run())


def test_inbox_close_failure_retries_without_reopening_engine(tmp_path):
    from relf_agent.runtime_builder import EchoProvider
    from relf_agent.service_lifecycle import LocalA2AService

    class Inbox(SQLiteInbox):
        fail = True

        def close(self):
            if self.fail:
                self.fail = False
                raise RuntimeError("close failure")
            super().close()

    async def run():
        engine = LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": EchoProvider("test")},
            tools=ToolRegistry(),
        )
        inbox = Inbox(tmp_path / "inbox.sqlite")

        async def auth(headers):
            return Scope()

        service = LocalA2AService(
            engine=engine,
            inbox=inbox,
            spec=AgentSpec("a", "Answer"),
            authenticate=auth,
            url="http://test/rpc",
        )
        with pytest.raises(RuntimeError):
            await service.aclose()
        with pytest.raises(ValidationError):
            engine.submit(AgentSpec("a", "Answer"), "task", command_id="unsafe")
        assert not service.closed
        await service.aclose()
        assert service.closed

    asyncio.run(run())
