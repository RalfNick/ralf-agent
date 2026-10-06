import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ralf_agent import (
    AgentSpec,
    InMemoryMemory,
    LocalEngine,
    ModelResponse,
    SQLiteStore,
    ThreadedMemoryAdapter,
    ToolRegistry,
)
from ralf_agent.errors import CoordinatorBusy, ValidationError
from ralf_agent.memory import MemoryRecallPolicy

from .helpers import ScriptedProvider
from .test_review_shutdown import cancel_all_tasks


@pytest.mark.parametrize("operation", ["read", "append", "read_page", "recall", "validate_facts"])
def test_threaded_memory_retains_ownership_after_service_loop_closes(tmp_path, operation):
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.new_event_loop()
    loop.set_default_executor(executor)

    class BlockingMemory(InMemoryMemory):
        def blocked(self):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5)

        def read(self, *args):
            if operation == "read":
                try:
                    self.blocked()
                    return super().read(*args)
                finally:
                    finished.set()
            return super().read(*args)

        def append(self, *args, **kwargs):
            try:
                self.blocked()
                return super().append(*args, **kwargs)
            finally:
                finished.set()

        def read_page(self, *args):
            if operation == "read_page":
                try:
                    self.blocked()
                    return super().read_page(*args)
                finally:
                    finished.set()
            return super().read_page(*args)

        def recall(self, *args):
            if operation == "recall":
                try:
                    self.blocked()
                    return super().recall(*args)
                finally:
                    finished.set()
            return super().recall(*args)

        def validate_facts(self, *args):
            try:
                self.blocked()
                return super().validate_facts(*args)
            finally:
                finished.set()

    path = tmp_path / "runs.db"
    memory = BlockingMemory()
    if operation == "validate_facts":
        from ralf_agent import Scope

        memory.put_fact(Scope(), "a", "fixture", "active", expected_version=0)
    runtime = LocalEngine(
        SQLiteStore(path),
        providers={"default": ScriptedProvider([ModelResponse(output="done")])},
        tools=ToolRegistry(),
        session_store=ThreadedMemoryAdapter(memory),
        memory_store=ThreadedMemoryAdapter(memory),
        recall_policy=MemoryRecallPolicy()
        if operation in {"read_page", "recall", "validate_facts"}
        else None,
    )
    try:
        run = runtime.submit(AgentSpec("a", "Answer"), "question", command_id="start")

        async def begin():
            asyncio.create_task(runtime.drive(run.run_id))
            await asyncio.wait_for(started.wait(), 2)

        loop.run_until_complete(begin())
        cancel_all_tasks(loop)
        loop.close()
        assert not finished.is_set()
        with pytest.raises(ValidationError):
            runtime.close()
        with SQLiteStore(path) as contender:
            with pytest.raises(CoordinatorBusy):
                LocalEngine(contender, providers={}, tools=ToolRegistry())

        async def finish_owned_threads():
            waiting = asyncio.create_task(runtime.wait_for_threads())
            await asyncio.sleep(0)
            assert not waiting.done()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            with pytest.raises(ValidationError):
                runtime.close()
            release.set()
            await runtime.wait_for_threads()

        asyncio.run(finish_owned_threads())
        executor.shutdown(wait=True)
        assert finished.is_set()
        runtime.close()
    finally:
        release.set()
        executor.shutdown(wait=True)
        if not loop.is_closed():
            cancel_all_tasks(loop)
            loop.close()
        runtime.close()
