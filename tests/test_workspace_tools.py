"""Workspace SDK injection and true managed handler lifetime."""

import asyncio
import copy
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from relf_agent import InMemoryWorkspace, Scope, ToolPolicy, ToolRegistry, register_tool_source
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from relf_agent.types import InvocationContext

from .test_thread_execution import wait_until_started
from .test_workspace import api


def context(scope=None):
    return InvocationContext(
        Scope() if scope is None else scope, "run", "action", "attempt", "effect", "epoch"
    )


def test_workspace_source_original_registry_and_borrowed_close():
    port = InMemoryWorkspace({"note": "hello"}, version="v1")
    source = api("WorkspaceToolSource")(port, version="tools-v1")

    async def run():
        registry = ToolRegistry()
        names = await register_tool_source(
            registry,
            source,
            policies={
                "workspace_read_text": ToolPolicy("1", effect="read_only", requires_approval=False)
            },
        )
        assert names == ("workspace_read_text",)
        handler = registry.get(names[0]).handler
        assert (await handler({"path": "note"}, context()))["text"] == "hello"
        await source.aclose()
        assert port.read_text(Scope(), "note")["text"] == "hello"
        with pytest.raises(api("WorkspaceError")):
            await source.list_tools()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_workspace_source_fixed_caps_and_scope_are_not_caller_overrides():
    scope = Scope("one", "owner")
    port = InMemoryWorkspace({"note": "你好"}, version="1", scopes=[scope])
    source = api("WorkspaceToolSource")(port, version="1", max_bytes=5)

    async def run():
        descriptor = next(
            item for item in await source.list_tools() if item.name == "workspace_read_text"
        )
        with pytest.raises(api("WorkspaceError")):
            await source.call_tool(descriptor, {"path": "note"}, context(scope))
        with pytest.raises(AuthorizationDenied):
            await source.call_tool(descriptor, {"path": "note"}, context())
        with pytest.raises(ValidationError):
            await source.call_tool(descriptor, {"path": "note", "max_bytes": 100}, context(scope))
        await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_workspace_source_adopts_all_three_fixed_results():
    port = InMemoryWorkspace({"docs/note": "hello"}, version="1")
    source = api("WorkspaceToolSource")(port, version="1")

    async def run():
        descriptors = {item.name: item for item in await source.list_tools()}
        args = {
            "workspace_stat": {"path": "docs/note"},
            "workspace_list": {"directory": "docs"},
            "workspace_read_text": {"path": "docs/note"},
        }
        output = {
            name: await source.call_tool(item, args[name], context())
            for name, item in descriptors.items()
        }
        assert output["workspace_stat"]["size"] == 5
        assert output["workspace_list"]["entries"][0]["path"] == "docs/note"
        assert output["workspace_read_text"]["text"] == "hello"
        await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_workspace_source_rejects_definition_changes():
    port = InMemoryWorkspace({"note": "hello"}, version="1")
    source = api("WorkspaceToolSource")(port, version="1")

    async def run():
        descriptor = (await source.list_tools())[0]
        port._identity["behavior_version"] = "changed"
        with pytest.raises(DefinitionMismatch):
            await source.call_tool(descriptor, {"path": "note"}, context())
        await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


@pytest.mark.parametrize(
    "bad",
    [
        {"path": "note", "text": "hello", "bytes": 1, "sha256": "bad", "version": "1"},
        {"path": "/outside", "text": "hello", "bytes": 5, "sha256": "bad", "version": "1"},
    ],
)
def test_workspace_source_custom_port_invalid_snapshot_refuses(bad):
    class InvalidPort(InMemoryWorkspace):
        def read_text(self, scope, path, *, max_bytes=1048576):
            return copy.deepcopy(bad)

    port = InvalidPort({}, version="1")
    source = api("WorkspaceToolSource")(port, version="1")

    async def run():
        descriptor = next(
            item for item in await source.list_tools() if item.name == "workspace_read_text"
        )
        with pytest.raises(api("WorkspaceError")):
            await source.call_tool(descriptor, {"path": "note"}, context())
        await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_workspace_source_cancel_and_closed_loop_retain_actual_file_read(tmp_path, monkeypatch):
    (tmp_path / "note").write_text("hello")
    port = api("FileSystemWorkspace")(tmp_path, version="1")
    source = api("WorkspaceToolSource")(port, version="1")
    started, release, ended = threading.Event(), threading.Event(), threading.Event()
    actual_read = os.read
    ambient = ThreadExecutionTracker()
    loop = asyncio.new_event_loop()

    def read(fd, count):
        started.set()
        try:
            assert release.wait(5)
            return actual_read(fd, count)
        finally:
            ended.set()

    monkeypatch.setattr(os, "read", read)

    async def cancel():
        descriptor = next(
            item for item in await source.list_tools() if item.name == "workspace_read_text"
        )
        token = current_thread_tracker.set(ambient)
        group = current_thread_group.set("run")
        try:
            task = asyncio.create_task(source.call_tool(descriptor, {"path": "note"}, context()))
            await wait_until_started(started)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            current_thread_group.reset(group)
            current_thread_tracker.reset(token)

    async def close_after_exit():
        closing = asyncio.create_task(source.aclose())
        await asyncio.sleep(0)
        assert not closing.done() and ambient.has_active_for("run")
        with pytest.raises(api("WorkspaceError")):
            port.close()
        release.set()
        await closing
        await ambient.drain()

    try:
        loop.run_until_complete(cancel())
        loop.close()
        assert not ended.is_set() and ambient.has_active_for("run")
        asyncio.run(close_after_exit())
        assert ended.is_set() and not ambient.has_active
    finally:
        release.set()
        if not loop.is_closed():
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
        asyncio.run(source.wait_for_calls())
        port.close()


def test_workspace_source_queued_cancel_does_not_dispatch_port():
    observed = []

    class CountingPort(InMemoryWorkspace):
        def read_text(self, scope, path, *, max_bytes=1048576):
            observed.append(path)
            return super().read_text(scope, path, max_bytes=max_bytes)

    port = CountingPort({"note": "hello"}, version="1")
    source = api("WorkspaceToolSource")(port, version="1")
    started, release = threading.Event(), threading.Event()
    pool = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.new_event_loop()
    loop.set_default_executor(pool)
    ambient = ThreadExecutionTracker()

    def occupy():
        started.set()
        assert release.wait(5)

    async def run():
        blocker = loop.run_in_executor(None, occupy)
        await wait_until_started(started)
        descriptor = next(
            item for item in await source.list_tools() if item.name == "workspace_read_text"
        )
        token = current_thread_tracker.set(ambient)
        try:
            task = asyncio.create_task(source.call_tool(descriptor, {"path": "note"}, context()))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            current_thread_tracker.reset(token)
        await source.aclose()
        assert not ambient.has_active
        release.set()
        await blocker
        await loop.shutdown_default_executor()

    try:
        loop.run_until_complete(run())
        assert observed == []
    finally:
        release.set()
        pool.shutdown(wait=True)
        loop.close()
        port.close()
