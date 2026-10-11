"""Actual fixed-command JSON execution and retained process ownership."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

import ralf_agent as api
from ralf_agent import InvocationContext, Scope, ToolDescriptor
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker


def public():
    assert hasattr(api, "CLIToolSource"), "Missing CLI ToolSource API"
    return api


def descriptor():
    return ToolDescriptor(
        "read",
        "Read JSON",
        {
            "type": "object",
            "properties": {"value": {}},
            "required": ["value"],
            "additionalProperties": False,
        },
        {"type": "object"},
    )


def source(root, mode="normal", **options):
    return public().CLIToolSource(
        descriptor(),
        [sys.executable, str(Path(__file__).with_name("cli_tool_fixture.py")), mode, str(root)],
        version="fixture-v1",
        cwd=root,
        **options,
    )


def context():
    return InvocationContext(Scope(), "run", "action", "attempt", "stable-key", "epoch")


def gone(root):
    pid = int((root / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def started(root):
    async with asyncio.timeout(5):
        while not (root / "started").exists():  # noqa: ASYNC110 — external process evidence
            await asyncio.sleep(0.01)


def test_discovery_is_pure_and_business_input_never_changes_command(tmp_path):
    async def run():
        remote = source(tmp_path)
        tools = await remote.list_tools()
        assert tools == (descriptor(),) and not (tmp_path / "pid").exists()
        payload = "value; touch should-never-exist $(whoami)"
        assert await remote.call_tool(tools[0], {"value": payload}, context()) == {"value": payload}
        await remote.aclose()
        await remote.aclose()

    asyncio.run(run())
    gone(tmp_path)
    assert not (tmp_path / "should-never-exist").exists()


def test_environment_is_explicit_and_configuration_detached(tmp_path, monkeypatch):
    monkeypatch.setenv("RALF_TEST_CLI_PARENT", "parent-only")

    async def run():
        env = {"CLI_EXPLICIT": "explicit-only"}
        remote = source(tmp_path, "environment", env=env)
        before = remote.identity
        env["CLI_EXPLICIT"] = "changed"
        assert remote.identity == before and "explicit-only" not in str(before)
        result = await remote.call_tool(descriptor(), {"value": 1}, context())
        assert result == {
            "inherited": False,
            "explicit": "explicit-only",
            "cwd": str(tmp_path.resolve()),
            "argv": [],
        }
        await remote.aclose()

    asyncio.run(run())
    gone(tmp_path)


@pytest.mark.parametrize(
    "mode",
    [
        "nonzero",
        "invalid",
        "oversized",
        "nan",
        "duplicate",
        "schema",
        "surrogate-value",
        "surrogate-key",
    ],
)
def test_invalid_result_is_typed_and_process_reaped(tmp_path, mode):
    async def run():
        remote = source(tmp_path, mode, max_output_bytes=256)
        with pytest.raises(api.ToolSourceError) as error:
            await remote.call_tool(descriptor(), {"value": 1}, context())
        assert "private-" not in str(error.value)
        await remote.aclose()

    asyncio.run(run())
    gone(tmp_path)


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": 0},
        {"timeout": True},
        {"timeout": float("nan")},
        {"timeout": 301},
        {"max_input_bytes": 0},
        {"max_output_bytes": True},
        {"max_output_bytes": 16777217},
        {"env": {"BAD=KEY": "value"}},
    ],
)
def test_invalid_configuration_has_no_process(tmp_path, options):
    with pytest.raises(ValidationError):
        source(tmp_path, **options)
    assert not (tmp_path / "pid").exists()


def test_descriptor_and_input_limits_refuse_before_process(tmp_path):
    async def run():
        remote = source(tmp_path, max_input_bytes=32)
        changed = ToolDescriptor("other", "Other", {"type": "object"})
        with pytest.raises(DefinitionMismatch):
            await remote.call_tool(changed, {"value": 1}, context())
        with pytest.raises(ValidationError):
            await remote.call_tool(descriptor(), {"value": "x" * 64}, context())
        with pytest.raises(ValidationError):
            await remote.call_tool(descriptor(), {"other": 1}, context())
        assert not (tmp_path / "pid").exists()
        await remote.aclose()

    asyncio.run(run())


def test_large_input_exceeds_pipe_capacity_without_deadlock(tmp_path):
    async def run():
        remote = source(tmp_path)
        text = "中文" * 15000
        assert await remote.call_tool(descriptor(), {"value": text}, context()) == {"value": text}
        await remote.aclose()

    asyncio.run(run())
    gone(tmp_path)


def test_timeout_stops_and_waits_actual_process(tmp_path):
    async def run():
        remote = source(tmp_path, "hang", timeout=0.3)
        with pytest.raises(api.ToolSourceError):
            await remote.call_tool(descriptor(), {"value": 1}, context())
        await remote.wait_for_calls()
        await remote.aclose()

    asyncio.run(run())
    assert (tmp_path / "started").exists()
    gone(tmp_path)


@pytest.mark.parametrize("cancel_caller", [True, False])
def test_cancellation_or_source_close_drains_original_and_source_work(tmp_path, cancel_caller):
    async def run():
        remote = source(tmp_path, "hang", timeout=10)
        tracker = ThreadExecutionTracker()
        token = current_thread_tracker.set(tracker)
        group = current_thread_group.set("run")
        try:
            call = asyncio.create_task(remote.call_tool(descriptor(), {"value": 1}, context()))
        finally:
            current_thread_tracker.reset(token)
            current_thread_group.reset(group)
        await started(tmp_path)
        assert tracker.has_active_for("run")
        if cancel_caller:
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
        await asyncio.wait_for(remote.aclose(), 3)
        if not cancel_caller:
            with pytest.raises(api.ToolSourceError):
                await call
        await remote.wait_for_calls()
        await tracker.drain("run")
        assert not tracker.has_active
        with pytest.raises(api.ToolSourceError):
            await remote.call_tool(descriptor(), {"value": 2}, context())

    asyncio.run(run())
    gone(tmp_path)


def test_invalid_unicode_input_is_refused_before_launch(tmp_path):
    async def run():
        remote = source(tmp_path)
        with pytest.raises(ValidationError):
            await remote.call_tool(descriptor(), {"value": "\ud800"}, context())
        assert not (tmp_path / "pid").exists()
        await remote.aclose()

    asyncio.run(run())


def test_both_trackers_keep_cancelled_handler_until_actual_cleanup(tmp_path, monkeypatch):
    import threading

    from ralf_agent import cli_process

    entered, release = threading.Event(), threading.Event()
    original = cli_process.stop_process

    def blocked_stop(process):
        entered.set()
        assert release.wait(5)
        original(process)

    monkeypatch.setattr(cli_process, "stop_process", blocked_stop)

    async def run():
        remote = source(tmp_path, "hang", timeout=10)
        tracker = ThreadExecutionTracker()
        token = current_thread_tracker.set(tracker)
        group = current_thread_group.set("original-run")
        try:
            call = asyncio.create_task(remote.call_tool(descriptor(), {"value": 1}, context()))
        finally:
            current_thread_tracker.reset(token)
            current_thread_group.reset(group)
        try:
            await started(tmp_path)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            assert await asyncio.to_thread(entered.wait, 2)
            closing = asyncio.create_task(remote.aclose())
            await asyncio.sleep(0.03)
            assert not closing.done() and tracker.has_active_for("original-run")
            release.set()
            await closing
            await tracker.drain("original-run")
            assert not tracker.has_active
        finally:
            release.set()
            await remote.aclose()

    asyncio.run(run())
    gone(tmp_path)


@pytest.mark.parametrize("ambient", [True, False])
def test_cancelled_queued_handler_never_launches_after_source_close(tmp_path, ambient):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    release, entered = threading.Event(), threading.Event()

    def occupy():
        entered.set()
        assert release.wait(5)

    async def run():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        busy = asyncio.create_task(asyncio.to_thread(occupy))
        async with asyncio.timeout(2):
            while not entered.is_set():  # noqa: ASYNC110 — independent worker evidence
                await asyncio.sleep(0.01)
        tracker = ThreadExecutionTracker()
        token = current_thread_tracker.set(tracker if ambient else None)
        remote = source(tmp_path)
        try:
            call = asyncio.create_task(remote.call_tool(descriptor(), {"value": 1}, context()))
            await asyncio.sleep(0.03)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            await asyncio.wait_for(remote.aclose(), 1)
            assert not tracker.has_active and not (tmp_path / "pid").exists()
        finally:
            current_thread_tracker.reset(token)
            release.set()
            await busy
        assert not (tmp_path / "pid").exists()

    asyncio.run(run())


def test_same_group_descendant_stops_after_parent_success(tmp_path):
    async def run():
        remote = source(tmp_path, "descendant")
        assert await remote.call_tool(descriptor(), {"value": 1}, context()) == {"value": 1}
        await remote.aclose()
        previous = (tmp_path / "child-audit").read_text()
        await asyncio.sleep(0.1)
        assert (tmp_path / "child-audit").read_text() == previous

    asyncio.run(run())
    gone(tmp_path)
