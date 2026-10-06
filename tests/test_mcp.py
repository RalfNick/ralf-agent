import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

import ralf_agent as api
from ralf_agent import InvocationContext, Scope
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker


def public():
    for name in ("MCPTransport", "MCPToolSource", "MCPStdioTransport"):
        assert hasattr(api, name), f"Missing MCP API: {name}"
    return api


def source(a, root, mode="normal", **options):
    return a.MCPToolSource(
        a.MCPStdioTransport(
            [sys.executable, str(Path(__file__).with_name("mcp_fixture.py")), mode, str(root)],
            version="fixture-v1",
            **options,
        )
    )


def context():
    return InvocationContext(Scope(), "run", "action", "attempt", "stable-key", "epoch")


def gone(root):
    pid = int((root / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_real_stdio_protocol_and_structured_result(tmp_path):
    a = public()

    async def run():
        remote = source(a, tmp_path)
        descriptors = await remote.list_tools()
        assert [d.name for d in descriptors] == ["read"]
        assert descriptors[0].input_schema["properties"]["value"] == {"type": "integer"}
        result = await remote.call_tool(descriptors[0], {"value": 7}, context())
        assert result == {
            "content": [{"type": "text", "text": "result"}],
            "structuredContent": {"value": 7},
            "isError": False,
        }

    asyncio.run(run())
    assert (tmp_path / "calls").read_text() == "1"
    gone(tmp_path)


def test_real_pagination_returns_all_named_tools(tmp_path):
    a = public()
    descriptors = asyncio.run(source(a, tmp_path, "pagination").list_tools())
    assert [item.name for item in descriptors] == ["read", "second"]
    gone(tmp_path)


def test_repeated_cursor_rejected_without_infinite_discovery(tmp_path):
    a = public()
    with pytest.raises(ValidationError):
        asyncio.run(source(a, tmp_path, "cursor").list_tools())
    gone(tmp_path)


@pytest.mark.parametrize("mode", ["malformed", "oversized", "version"])
def test_bad_protocol_rejected_and_process_reaped(tmp_path, mode):
    a = public()
    with pytest.raises(a.ToolSourceError):
        asyncio.run(source(a, tmp_path, mode).list_tools())
    gone(tmp_path)


@pytest.mark.parametrize("mode", ["tool_error", "rpc_error", "bad_output"])
def test_remote_errors_are_not_successful_results(tmp_path, mode):
    a = public()
    remote = source(a, tmp_path, mode)

    async def run():
        tool = (await remote.list_tools())[0]
        with pytest.raises(a.ToolSourceError):
            await remote.call_tool(tool, {"value": 1}, context())

    asyncio.run(run())
    assert (tmp_path / "calls").read_text() == "1"
    gone(tmp_path)


def test_changed_descriptor_refused_before_remote_call(tmp_path):
    a = public()

    async def run():
        original = (await source(a, tmp_path).list_tools())[0]
        with pytest.raises(DefinitionMismatch):
            await source(a, tmp_path, "drift").call_tool(original, {"value": 1}, context())

    asyncio.run(run())
    assert not (tmp_path / "calls").exists()
    gone(tmp_path)


def test_timeout_stops_and_reaps_real_process(tmp_path):
    a = public()
    remote = source(a, tmp_path, "hang", timeout=0.3)

    async def run():
        tool = (await remote.list_tools())[0]
        with pytest.raises(a.ToolSourceError):
            await remote.call_tool(tool, {"value": 1}, context())

    asyncio.run(run())
    assert (tmp_path / "started").exists()
    gone(tmp_path)


def test_subprocess_environment_is_explicit(tmp_path, monkeypatch):
    a = public()
    monkeypatch.setenv("RALF_TEST_MCP_SECRET", "fixture-parent-only")
    remote = source(a, tmp_path, "environment", env={"EXPLICIT": "fixture-only"})

    async def run():
        tool = (await remote.list_tools())[0]
        result = await remote.call_tool(tool, {"value": 1}, context())
        assert result["structuredContent"]["inherited_secret"] is False
        assert result["structuredContent"]["explicit"] is True

    asyncio.run(run())
    assert "fixture-only" not in str(remote.identity)
    gone(tmp_path)


def test_cancelled_task_retains_actual_worker_ownership_until_reaped(tmp_path):
    a = public()

    async def run():
        remote = source(a, tmp_path, "hang", timeout=5)
        tool = (await remote.list_tools())[0]
        tracker = ThreadExecutionTracker()
        token = current_thread_tracker.set(tracker)
        group = current_thread_group.set("run")
        try:
            task = asyncio.create_task(remote.call_tool(tool, {"value": 1}, context()))
        finally:
            current_thread_tracker.reset(token)
            current_thread_group.reset(group)
        deadline = time.monotonic() + 3
        while not (tmp_path / "started").exists():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        assert tracker.has_active_for("run")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await tracker.drain("run")
        assert not tracker.has_active
        gone(tmp_path)

    asyncio.run(run())


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, 301])
def test_invalid_timeout_rejected_before_start(tmp_path, timeout):
    a = public()
    with pytest.raises(ValidationError):
        source(a, tmp_path, timeout=timeout)
    assert not (tmp_path / "pid").exists()


def test_custom_transport_can_replace_stdio_without_changing_tool_source():
    a = public()

    class MemoryTransport:
        identity = {"kind": "in-memory-mcp-fixture", "version": "1"}

        async def request(self, method, params, *, expected_tool=None):
            if method == "tools/list":
                return {
                    "tools": [
                        {"name": "read", "description": "Read", "inputSchema": {"type": "object"}}
                    ]
                }
            assert expected_tool["name"] == "read" and params == {"name": "read", "arguments": {}}
            return {"content": [{"type": "text", "text": "custom transport"}]}

    async def run():
        remote = a.MCPToolSource(MemoryTransport())
        tool = (await remote.list_tools())[0]
        assert await remote.call_tool(tool, {}, context()) == {
            "content": [{"type": "text", "text": "custom transport"}]
        }

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["wrongid", "flood", "manypages", "too_many_tools"])
def test_protocol_identity_and_discovery_limits_reject(tmp_path, mode):
    a = public()
    with pytest.raises((a.ToolSourceError, ValidationError)):
        asyncio.run(source(a, tmp_path, mode).list_tools())
    gone(tmp_path)


def test_server_ping_does_not_replace_initialize_response(tmp_path):
    a = public()
    assert asyncio.run(source(a, tmp_path, "ping").list_tools())[0].name == "read"
    gone(tmp_path)
