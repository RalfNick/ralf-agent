"""Native write proposals reuse original registration, receipts and thread owners."""

import asyncio
import copy
import os
import threading

import pytest

import ralf_agent as r
from ralf_agent.errors import CoordinatorBusy, DefinitionMismatch, ValidationError
from ralf_agent.tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from ralf_agent.types import InvocationContext
from ralf_agent.workspace import WorkspaceError

from .test_thread_execution import wait_until_started


def source(port, **options):
    cls = getattr(r, "WritableWorkspaceToolSource", None)
    assert cls is not None, "public WritableWorkspaceToolSource missing"
    return cls(port, version="1", **options)


def context():
    return InvocationContext(r.Scope(), "run", "action", "attempt", "original-effect", "epoch")


def policies(src):
    return {
        "workspace_write_text": r.ToolPolicy(
            "1",
            effect="idempotent_write",
            effect_key_argument="effect_key",
            reconciler=src.reconcile,
        )
    }


def test_original_registry_injects_reserved_effect_and_native_reconciler_reuses_receipt():
    port = r.InMemoryWritableWorkspace(version="1")
    src = source(port)

    async def run():
        registry = r.ToolRegistry()
        await r.register_tool_source(registry, src, policies=policies(src))
        tool = registry.get("workspace_write_text")
        arguments = {"path": "note", "text": "A", "expected_version": None}
        value = await tool.handler(arguments, context())
        assert value["effect_key"] == context().effect_key
        assert value == port.query_write(r.Scope(), context().effect_key)
        assert tool.spec.requires_approval and tool.spec.effect == "idempotent_write"
        assert "effect_key" not in tool.spec.input_schema["properties"]
        assert await tool.reconciler(arguments, context()) == value
        with pytest.raises(ValidationError):
            await tool.handler({**arguments, "effect_key": "forged"}, context())
        await src.aclose()
        assert port.read_text(r.Scope(), "note")["text"] == "A"

    try:
        asyncio.run(run())
    finally:
        port.close()


@pytest.mark.parametrize(
    "options",
    [
        {"effect": "read_only"},
        {"effect": "unqueryable_write"},
        {"effect": "idempotent_write", "effect_key_argument": "wrong"},
    ],
)
def test_native_write_policy_cannot_hide_effect_or_reserved_key(options):
    port = r.InMemoryWritableWorkspace(version="1")
    src = source(port)

    async def run():
        registry = r.ToolRegistry()
        with pytest.raises(ValidationError):
            await r.register_tool_source(
                registry, src, policies={"workspace_write_text": r.ToolPolicy("1", **options)}
            )
        with pytest.raises(DefinitionMismatch):
            registry.get("workspace_write_text")
        await src.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_source_publishes_three_original_reads_and_one_explicit_write():
    port = r.InMemoryWritableWorkspace({"seed": "old"}, version="1")
    src = source(port)

    async def run():
        names = [d.name for d in await src.list_tools()]
        assert names == [
            "workspace_stat",
            "workspace_list",
            "workspace_read_text",
            "workspace_write_text",
        ]
        identity = src.identity
        assert identity["kind"] == "workspace-tool-source" and identity["version"] == "2"
        registry = r.ToolRegistry()
        await r.register_tool_source(
            registry,
            src,
            policies={
                "workspace_read_text": r.ToolPolicy(
                    "1", effect="read_only", requires_approval=False
                ),
                **policies(src),
            },
        )
        assert (await registry.get("workspace_read_text").handler({"path": "seed"}, context()))[
            "text"
        ] == "old"
        await src.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_native_source_refuses_a_readonly_port_before_registration():
    port = r.InMemoryWorkspace(version="1")
    try:
        with pytest.raises(ValidationError):
            source(port)
    finally:
        port.close()


def test_reconciler_refuses_a_receipt_for_another_request():
    class Invalid(r.InMemoryWritableWorkspace):
        def query_write(self, scope, key):
            value = copy.deepcopy(super().query_write(scope, key))
            if value is not None:
                value["request_digest"] = "0" * 64
            return value

    port = Invalid(version="1")
    src = source(port)

    async def run():
        registry = r.ToolRegistry()
        await r.register_tool_source(registry, src, policies=policies(src))
        tool = registry.get("workspace_write_text")
        arguments = {"path": "note", "text": "A", "expected_version": None}
        await tool.handler(arguments, context())
        with pytest.raises((ValidationError, WorkspaceError)):
            await tool.reconciler(arguments, context())
        await src.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_global_loop_cancel_keeps_real_write_thread_and_root_lease(tmp_path, monkeypatch):
    port = r.FileSystemWritableWorkspace(tmp_path, version="1")
    src = source(port)
    entered, release, ended = threading.Event(), threading.Event(), threading.Event()
    original = os.replace
    ambient = ThreadExecutionTracker()
    loop = asyncio.new_event_loop()

    def blocked(*args, **kwargs):
        entered.set()
        try:
            assert release.wait(5)
            return original(*args, **kwargs)
        finally:
            ended.set()

    monkeypatch.setattr(os, "replace", blocked)

    async def cancel():
        descriptor = next(d for d in await src.list_tools() if d.name == "workspace_write_text")
        token = current_thread_tracker.set(ambient)
        group = current_thread_group.set("run")
        try:
            task = asyncio.create_task(
                src.call_tool(
                    descriptor,
                    {"path": "note", "text": "A", "expected_version": None, "effect_key": "k"},
                    context(),
                )
            )
            await wait_until_started(entered)
            for pending in asyncio.all_tasks():
                if pending is not asyncio.current_task():
                    pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            current_thread_group.reset(group)
            current_thread_tracker.reset(token)

    async def close_after_exit():
        closing = asyncio.create_task(src.aclose())
        await asyncio.sleep(0)
        assert not closing.done() and ambient.has_active_for("run")
        with pytest.raises(WorkspaceError):
            port.close()
        with pytest.raises(CoordinatorBusy):
            r.FileSystemWritableWorkspace(tmp_path, version="1")
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
            loop.close()
        port.close()
