"""Mechanical Worker ownership tracks real handlers; no History authority."""

import asyncio
import threading
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import InMemoryMemory, RecallQuery, Scope, ThreadedMemoryAdapter
from ralf_agent.errors import CloseIncomplete, DefinitionMismatch
from ralf_agent.temporal_assembly_lifecycle import WorkerExecutionOwner


def info(**changes):
    return SimpleNamespace(
        workflow_id="run",
        workflow_run_id="original-uuid",
        workflow_namespace="original",
        activity_id="model:0",
        attempt=1,
        **changes,
    )


def test_actual_delegated_thread_survives_activity_observer_cancel():
    started, release, stopped = (threading.Event() for _ in range(3))

    class Source(InMemoryMemory):
        def read_page(self, scope, address, query):
            started.set()
            try:
                assert release.wait(10)
                return super().read_page(scope, address, query)
            finally:
                stopped.set()

    async def run():
        reader = ThreadedMemoryAdapter(Source())
        owner = WorkerExecutionOwner(scope=Scope(), release={"fixed": "release"})

        async def operation():
            return await reader.read_page(Scope(), "s", RecallQuery())

        observer = asyncio.create_task(
            owner.execute(operation, info=info(), request={"scope": asdict(Scope())})
        )
        try:
            assert await asyncio.to_thread(started.wait, 3)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert not stopped.is_set()
            assert not await owner.wait(wait_timeout=0)
            with pytest.raises(CloseIncomplete):
                await owner.aclose(wait_timeout=0)
            release.set()
            assert await owner.wait(wait_timeout=3)
            assert stopped.is_set()
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)
            await owner.aclose(wait_timeout=3)

    asyncio.run(run())


def test_actual_async_call_stays_on_its_creation_loop():
    async def run():
        loop = asyncio.get_running_loop()
        started, release = asyncio.Event(), asyncio.Event()
        owner = WorkerExecutionOwner(scope=Scope(), release={"fixed": "release"})

        async def operation():
            assert asyncio.get_running_loop() is loop
            started.set()
            await release.wait()
            return "completed"

        observer = asyncio.create_task(
            owner.execute(operation, info=info(), request={"scope": asdict(Scope())})
        )
        try:
            await started.wait()
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            assert not await owner.wait(wait_timeout=0)
            release.set()
            assert await owner.wait(wait_timeout=3)
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)
            await owner.aclose(wait_timeout=3)

    asyncio.run(run())


def test_foreign_scope_refuses_before_operation():
    async def run():
        owner = WorkerExecutionOwner(scope=Scope(), release={"fixed": "release"})
        calls = []

        async def operation():
            calls.append("called")
            return None

        try:
            with pytest.raises(DefinitionMismatch):
                await owner.execute(
                    operation, info=info(), request={"scope": asdict(Scope("other", "tenant"))}
                )
            assert not calls and await owner.wait(wait_timeout=0)
        finally:
            await owner.aclose()

    asyncio.run(run())


def test_cancelled_tool_task_still_owns_tracker_explicit_run_group():
    from ralf_agent.tools import invoke

    started, release, stopped = (threading.Event() for _ in range(3))

    def handler(arguments, context):
        started.set()
        try:
            assert release.wait(10)
            return "done"
        finally:
            stopped.set()

    async def run():
        owner = WorkerExecutionOwner(scope=Scope(), release={"fixed": "release"})

        async def operation():
            return await invoke(handler, {}, SimpleNamespace(run_id="actual-business-run"))

        observer = asyncio.create_task(
            owner.execute(operation, info=info(), request={"scope": asdict(Scope())})
        )
        try:
            assert await asyncio.to_thread(started.wait, 3)
            # Cancel actual operation too, as whole-loop cancellation does.
            tasks = [entry["task"] for entry in owner._execution._entries.values()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(observer, return_exceptions=True)
            assert not await owner.wait(wait_timeout=0.05)
            assert not stopped.is_set()
            release.set()
            assert await owner.wait(wait_timeout=3)
            assert stopped.is_set()
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)
            await owner.aclose(wait_timeout=3)

    asyncio.run(run())
