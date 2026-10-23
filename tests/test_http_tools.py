"""Host-fixed HTTP tool boundaries and retained actual request ownership."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

import relf_agent as api
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker

from .http_tool_fixture import endpoint
from .test_cli_tools import context, descriptor


def source(url, **options):
    assert hasattr(api, "HTTPToolSource"), "Missing HTTPToolSource API"
    return api.HTTPToolSource(descriptor(), url, version="http-fixture-v1", **options)


def test_fixed_post_discovery_headers_and_no_ambient_environment(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with endpoint() as (url, calls, _, _):

        async def run():
            headers = {"Authorization": "Bearer private-explicit"}
            remote = source(url + "/normal", headers=headers)
            identity = remote.identity
            headers["Authorization"] = "changed"
            assert await remote.list_tools() == (descriptor(),) and not calls
            assert "private-explicit" not in str(identity)
            try:
                assert await remote.call_tool(descriptor(), {"value": "中文"}, context()) == {
                    "value": "中文"
                }
            finally:
                await remote.aclose()
                await remote.aclose()

        asyncio.run(run())
        assert len(calls) == 1 and calls[0]["path"] == "/normal"
        assert calls[0]["body"] == '{"value":"中文"}'.encode()
        headers = {key.lower(): value for key, value in calls[0]["headers"].items()}
        assert headers["authorization"] == "Bearer private-explicit"
        assert calls[0]["headers"]["Content-Type"] == "application/json"
        assert calls[0]["headers"]["Accept-Encoding"] == "identity"


@pytest.mark.parametrize(
    "mode",
    [
        "redirect",
        "nonzero",
        "invalid",
        "unicode",
        "duplicate",
        "nan",
        "schema",
        "oversized",
        "compressed",
    ],
)
def test_response_refusal_is_sanitized_without_retry(mode):
    with endpoint() as (url, calls, _, _):

        async def run():
            remote = source(url + "/" + mode, max_output_bytes=256)
            try:
                with pytest.raises(api.ToolSourceError) as error:
                    await remote.call_tool(descriptor(), {"value": 1}, context())
                assert "private-" not in str(error.value) and url not in str(error.value)
            finally:
                await remote.aclose()

        asyncio.run(run())
        assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/a",
        "http://user:pass@localhost/a",
        "http://localhost/a?q=1",
        "http://localhost/a#f",
        "http://localhost:99999/a",
        " http://localhost/a",
        "http://localhost/a\n",
        "http://localhost/a\x7f",
        "http://[v1.private-endpoint]/",
        "http://☃.com/",
    ],
)
def test_invalid_destination_refuses_purely(url):
    with pytest.raises(ValidationError):
        source(url)


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": True},
        {"timeout": float("nan")},
        {"timeout": 301},
        {"max_input_bytes": 0},
        {"max_output_bytes": True},
        {"headers": {"Host": "elsewhere"}},
        {"headers": {"a": "x", "A": "y"}},
        {"headers": {"X-Input": "x\nsecret"}},
    ],
)
def test_invalid_options_refuse_purely(options):
    with pytest.raises(ValidationError):
        source("http://127.0.0.1/fixed", **options)


def test_input_identity_schema_and_bytes_refuse_before_request():
    with endpoint() as (url, calls, _, _):

        async def run():
            remote = source(url + "/normal", max_input_bytes=32)
            try:
                changed = api.ToolDescriptor("other", "Other", {"type": "object"})
                with pytest.raises(DefinitionMismatch):
                    await remote.call_tool(changed, {"value": 1}, context())
                for value in (
                    {"other": 1},
                    {"value": "\ud800"},
                    {"value": "x" * 100},
                    {"value": {1}},
                ):
                    with pytest.raises(ValidationError):
                        await remote.call_tool(descriptor(), value, context())
                assert not calls
            finally:
                await remote.aclose()

        asyncio.run(run())


def test_cancelled_wait_retains_actual_request_until_close_and_both_trackers_drain():
    with endpoint() as (url, calls, started, release):

        async def run():
            remote, tracker = source(url + "/hang", timeout=2), ThreadExecutionTracker()
            token = current_thread_tracker.set(tracker)
            group = current_thread_group.set("run")
            try:
                task = asyncio.create_task(remote.call_tool(descriptor(), {"value": 1}, context()))
            finally:
                current_thread_tracker.reset(token)
                current_thread_group.reset(group)
            try:
                assert await asyncio.to_thread(started.wait, 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                closing = asyncio.create_task(remote.aclose())
                await asyncio.sleep(0.03)
                assert not closing.done() and tracker.has_active_for("run")
            finally:
                release.set()
            await asyncio.wait_for(closing, 3)
            await tracker.drain("run")
            assert not tracker.has_active
            with pytest.raises(api.ToolSourceError):
                await remote.call_tool(descriptor(), {"value": 2}, context())

        asyncio.run(run())
        assert len(calls) == 1


def test_queued_cancelled_request_never_starts():
    with endpoint() as (url, calls, _, _):

        async def run():
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
            occupied, release = threading.Event(), threading.Event()

            def blocker():
                occupied.set()
                release.wait(3)

            blocker_task = loop.run_in_executor(None, blocker)
            while not occupied.is_set():  # noqa: ASYNC110 — actual worker starts outside loop
                await asyncio.sleep(0.001)
            remote = source(url + "/normal")
            try:
                task = asyncio.create_task(remote.call_tool(descriptor(), {"value": 1}, context()))
                await asyncio.sleep(0.03)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await asyncio.wait_for(remote.aclose(), 1)
            finally:
                release.set()
                await blocker_task
            assert not calls

        asyncio.run(run())


def test_socket_timeout_is_typed_and_original_request_drain_finishes():
    with endpoint() as (url, calls, _, release):

        async def run():
            remote = source(url + "/hang", timeout=0.1)
            try:
                with pytest.raises(api.ToolSourceError):
                    await remote.call_tool(descriptor(), {"value": 1}, context())
                await remote.wait_for_calls()
            finally:
                release.set()
                await remote.aclose()

        asyncio.run(run())
        assert len(calls) == 1


def test_closed_originating_loop_cannot_discard_actual_request_ownership():
    with endpoint() as (url, calls, started, release):
        remote, tracker = source(url + "/hang", timeout=2), ThreadExecutionTracker()
        loop = asyncio.new_event_loop()

        async def begin():
            token = current_thread_tracker.set(tracker)
            group = current_thread_group.set("original-loop")
            try:
                task = asyncio.create_task(remote.call_tool(descriptor(), {"value": 1}, context()))
            finally:
                current_thread_tracker.reset(token)
                current_thread_group.reset(group)
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        try:
            loop.run_until_complete(begin())
        finally:
            loop.close()

        async def close():
            task = asyncio.create_task(remote.aclose())
            try:
                await asyncio.sleep(0.03)
                assert not task.done() and tracker.has_active_for("original-loop")
            finally:
                release.set()
            await asyncio.wait_for(task, 3)
            await tracker.drain("original-loop")
            assert not tracker.has_active

        asyncio.run(close())
        assert len(calls) == 1


def test_both_trackers_wait_until_actual_http_client_resource_close(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = httpx.HTTPTransport.__exit__

    def blocked_close(transport, *args):
        entered.set()
        assert release.wait(5)
        return original(transport, *args)

    monkeypatch.setattr(httpx.HTTPTransport, "__exit__", blocked_close)
    with endpoint() as (url, calls, _, _):

        async def run():
            remote, tracker = source(url + "/normal"), ThreadExecutionTracker()
            token = current_thread_tracker.set(tracker)
            group = current_thread_group.set("actual-client-close")
            try:
                call = asyncio.create_task(remote.call_tool(descriptor(), {"value": 1}, context()))
            finally:
                current_thread_tracker.reset(token)
                current_thread_group.reset(group)
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                call.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await call
                closing = asyncio.create_task(remote.aclose())
                await asyncio.sleep(0.03)
                assert not closing.done() and tracker.has_active_for("actual-client-close")
            finally:
                release.set()
            await asyncio.wait_for(closing, 3)
            await tracker.drain("actual-client-close")
            assert not tracker.has_active

        asyncio.run(run())
        assert len(calls) == 1


def test_transport_defensively_sanitizes_actual_httpx_url_rejection():
    from relf_agent import http_tool_transport

    with pytest.raises(api.ToolSourceError) as error:
        http_tool_transport.execute(
            "http://[v1.private-endpoint]/", {}, b"{}", 0.1, 256, threading.Event()
        )
    assert "private-endpoint" not in str(error.value)
