"""Actual MCP HTTP protocol and client/handler ownership."""

import asyncio
import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

import ralf_agent as api
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.tools import ThreadExecutionTracker, current_thread_tracker

from .mcp_http_fixture import descriptor, peer
from .test_cli_tools import context


def transport(url, **options):
    assert hasattr(api, "MCPHTTPTransport"), "Missing MCPHTTPTransport"
    return api.MCPHTTPTransport(url, version="peer-v1", **options)


def business_calls(calls):
    return [
        c for c in calls if c["message"] is not None and c["message"].get("method") == "tools/call"
    ]


@pytest.mark.parametrize(
    "mode",
    ["json", "sse", "pagination", "ping", "elicitation", "delete-405", "2025-06-18", "2025-03-26"],
)
def test_actual_handshake_pinned_call_headers_and_client_cleanup(mode):
    with peer(mode) as (url, calls, _, _):

        async def run():
            wire = transport(url)
            source = api.MCPToolSource(wire)
            assert await source.list_tools() == (descriptor(),)
            result = await source.call_tool(descriptor(), {"value": 7}, context())
            assert result["structuredContent"] == {"value": 7}
            await wire.aclose()
            with pytest.raises(api.ToolSourceError):
                await source.list_tools()

        asyncio.run(run())
        assert len(business_calls(calls)) == 1
        initialized = [
            c
            for c in calls
            if c["message"] is not None and c["message"].get("method") == "initialize"
        ]
        assert len(initialized) == 2
        for request in initialized:
            assert "MCP-Session-Id" not in request["headers"]
            assert "application/json" in request["headers"]["Accept"]
            assert "text/event-stream" in request["headers"]["Accept"]
        assert len([c for c in calls if c["verb"] == "DELETE"]) == 2
        if mode in {"ping", "elicitation"}:
            replies = [
                c["message"]
                for c in calls
                if c["message"] is not None and c["message"].get("id") == "server-1"
            ]
            assert len(replies) == 1
            assert (
                (replies[0].get("result") == {})
                if mode == "ping"
                else (replies[0]["error"]["code"] == -32601)
            )


@pytest.mark.parametrize(
    "mode",
    [
        "version",
        "no-tools",
        "bad-session",
        "rotate",
        "wrong-id",
        "bool-id",
        "both",
        "error",
        "array",
        "invalid",
        "duplicate",
        "nan",
        "surrogate",
        "oversized",
        "compressed",
        "sse-eof",
    ],
)
def test_actual_protocol_failures_are_sanitized_and_never_business_success(mode):
    with peer(mode) as (url, calls, _, _):

        async def run():
            wire = transport(url, max_message_bytes=4096)
            try:
                with pytest.raises(api.ToolSourceError) as error:
                    await wire.request("tools/list", {})
                assert "private" not in str(error.value) and url not in str(error.value)
            finally:
                await wire.aclose()

        asyncio.run(run())
        assert not business_calls(calls)


def test_pinned_descriptor_drift_refuses_before_actual_tool_call():
    with peer("drift") as (url, calls, _, _):

        async def run():
            wire = transport(url)
            try:
                with pytest.raises(DefinitionMismatch):
                    await wire.request(
                        "tools/call",
                        {"name": "read", "arguments": {"value": 1}},
                        expected_tool=descriptor().to_dict(),
                    )
            finally:
                await wire.aclose()

        asyncio.run(run())
        assert not business_calls(calls)


def test_http404_never_reinitializes_or_resends_the_same_call():
    with peer("404") as (url, calls, _, _):

        async def run():
            wire = transport(url)
            try:
                with pytest.raises(api.ToolSourceError):
                    await wire.request(
                        "tools/call",
                        {"name": "read", "arguments": {"value": 1}},
                        expected_tool=descriptor().to_dict(),
                    )
            finally:
                await wire.aclose()

        asyncio.run(run())
        assert len(business_calls(calls)) == 1
        assert (
            sum(
                c["message"] is not None and c["message"].get("method") == "initialize"
                for c in calls
            )
            == 1
        )


@pytest.mark.parametrize(
    "options",
    [
        {"headers": {"MCP-Session-Id": "override"}},
        {"headers": {"Accept": "text/plain"}},
        {"timeout": True},
        {"max_message_bytes": 0},
        {"max_operation_bytes": 1},
        {"max_operation_bytes": 67108865},
    ],
)
def test_invalid_configuration_refuses_without_connecting(options):
    with pytest.raises(ValidationError):
        transport("http://127.0.0.1:1/mcp", **options)


@pytest.mark.parametrize(
    "url",
    [
        "http://[v1.secret]/",
        "http://☃.com/",
        "http://user:secret@host/mcp",
        "http://host/mcp?token=secret",
    ],
)
def test_invalid_fixed_url_is_pure(url):
    with pytest.raises(ValidationError):
        transport(url)


def test_actual_cancel_retains_source_and_ambient_worker_until_socket_and_client_close():
    with peer("hang") as (url, calls, started, release):

        async def run():
            wire = transport(url, timeout=2)
            tracker = ThreadExecutionTracker()
            token = current_thread_tracker.set(tracker)
            task = asyncio.create_task(
                wire.request(
                    "tools/call",
                    {"name": "read", "arguments": {"value": 1}},
                    expected_tool=descriptor().to_dict(),
                )
            )
            try:
                assert await asyncio.to_thread(started.wait, 3)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert tracker.active_count == 1
                draining = asyncio.create_task(wire.aclose())
                await asyncio.sleep(0.05)
                assert not draining.done()
                release.set()
                await draining
                await tracker.drain()
                assert tracker.active_count == 0
            finally:
                current_thread_tracker.reset(token)
                release.set()

        asyncio.run(run())
        assert len(business_calls(calls)) == 1


def test_header_identity_is_copied_and_redacted():
    headers = {"Authorization": "private-token"}
    wire = transport("http://127.0.0.1:1/mcp", headers=headers)
    original = copy.deepcopy(wire.identity)
    headers["Authorization"] = "changed"
    assert wire.identity == original and "private-token" not in str(original)
    asyncio.run(wire.aclose())


@pytest.mark.parametrize("value", [{"value": "\ud800"}, {"value": float("nan")}])
def test_non_utf8_or_nonfinite_input_refuses_purely(value):
    wire = transport("http://127.0.0.1:1/mcp")

    async def run():
        try:
            with pytest.raises(ValidationError):
                await wire.request(
                    "tools/call",
                    {"name": "read", "arguments": value},
                    expected_tool=descriptor().to_dict(),
                )
        finally:
            await wire.aclose()

    asyncio.run(run())


def test_cancelled_queued_request_never_initializes_peer():
    with peer() as (url, calls, _, _):

        async def run():
            loop = asyncio.get_running_loop()
            loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
            entered, release = threading.Event(), threading.Event()

            def block():
                entered.set()
                release.wait(5)

            blocker = loop.run_in_executor(None, block)
            wire = transport(url)
            try:
                while not entered.is_set():  # noqa: ASYNC110 — actual worker starts outside loop
                    await asyncio.sleep(0.001)
                call = asyncio.create_task(wire.request("tools/list", {}))
                await asyncio.sleep(0.03)
                call.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await call
                await asyncio.wait_for(wire.aclose(), 1)
                assert not calls
            finally:
                release.set()
                await blocker

        asyncio.run(run())


def test_closed_original_loop_retains_actual_mcp_http_handler():
    with peer("hang") as (url, calls, started, release):
        wire, tracker = transport(url, timeout=2), ThreadExecutionTracker()
        loop = asyncio.new_event_loop()

        async def begin():
            token = current_thread_tracker.set(tracker)
            try:
                call = asyncio.create_task(
                    wire.request(
                        "tools/call",
                        {"name": "read", "arguments": {"value": 1}},
                        expected_tool=descriptor().to_dict(),
                    )
                )
            finally:
                current_thread_tracker.reset(token)
            assert await asyncio.to_thread(started.wait, 2)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call

        try:
            loop.run_until_complete(begin())
        finally:
            loop.close()

        async def close():
            task = asyncio.create_task(wire.aclose())
            try:
                await asyncio.sleep(0.03)
                assert not task.done() and tracker.has_active
            finally:
                release.set()
            await asyncio.wait_for(task, 3)
            await tracker.drain()
            assert not tracker.has_active

        asyncio.run(close())
        assert len(business_calls(calls)) == 1


def test_source_and_ambient_ownership_cover_actual_http_client_exit(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = httpx.HTTPTransport.__exit__

    def blocked_close(client, *args):
        entered.set()
        assert release.wait(5)
        return original(client, *args)

    monkeypatch.setattr(httpx.HTTPTransport, "__exit__", blocked_close)
    with peer() as (url, calls, _, _):

        async def run():
            wire, tracker = transport(url), ThreadExecutionTracker()
            token = current_thread_tracker.set(tracker)
            try:
                call = asyncio.create_task(wire.request("tools/list", {}))
            finally:
                current_thread_tracker.reset(token)
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                call.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await call
                task = asyncio.create_task(wire.aclose())
                await asyncio.sleep(0.03)
                assert not task.done() and tracker.has_active
            finally:
                release.set()
            await asyncio.wait_for(task, 3)
            await tracker.drain()
            assert not tracker.has_active

        asyncio.run(run())


def test_total_operation_limit_counts_across_all_requests_and_responses():
    with peer("pagination") as (url, calls, _, _):

        async def run():
            wire = transport(url, max_message_bytes=512, max_operation_bytes=512)
            try:
                with pytest.raises(api.ToolSourceError, match="operation.*limit"):
                    await wire.request("tools/list", {})
            finally:
                await wire.aclose()

        asyncio.run(run())
        assert not business_calls(calls)


def test_actual_socket_timeout_is_typed_without_business_resend():
    with peer("hang") as (url, calls, _, release):

        async def run():
            wire = transport(url, timeout=0.1)
            try:
                with pytest.raises(api.ToolSourceError):
                    await wire.request(
                        "tools/call",
                        {"name": "read", "arguments": {"value": 1}},
                        expected_tool=descriptor().to_dict(),
                    )
                await wire.wait_for_calls()
            finally:
                release.set()
                await wire.aclose()

        asyncio.run(run())
        assert len(business_calls(calls)) == 1


@pytest.mark.parametrize(
    "mode",
    [
        "external-input-ref",
        "external-output-ref",
        "external-input-dynamic",
        "external-output-dynamic",
    ],
)
def test_peer_schema_references_cannot_fetch_another_destination(mode, monkeypatch):
    import io
    import urllib.request
    import warnings

    external = []

    def fetch(request, *args, **options):
        external.append(request.full_url)
        return io.BytesIO(b'{"type":"object"}')

    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    with peer(mode) as (url, calls, _, _):

        async def run():
            wire = transport(url)
            source = api.MCPToolSource(wire)
            rejected = False
            try:
                descriptors = await source.list_tools()
                await source.call_tool(descriptors[0], {"value": 7}, context())
            except api.ToolSourceError:
                rejected = True
            finally:
                await wire.aclose()
            assert not external, "Peer schema fetched outside the fixed transport"
            assert rejected, "External peer schema must refuse at discovery"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.run(run())
        assert not business_calls(calls)


def test_safe_local_input_and_output_references_never_use_network(monkeypatch):
    import urllib.request

    def unexpected(*args, **options):
        raise AssertionError("Local references must stay offline")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected)
    with peer("local-ref") as (url, calls, _, _):

        async def run():
            wire = transport(url)
            try:
                source = api.MCPToolSource(wire)
                (selected,) = await source.list_tools()
                result = await source.call_tool(selected, {"value": 7}, context())
                assert result["structuredContent"] == {"value": 7}
            finally:
                await wire.aclose()

        asyncio.run(run())
        assert len(business_calls(calls)) == 1


def test_unsolicited_limit_is_shared_by_all_discovery_pages():
    with peer("unsolicited") as (url, calls, _, _):

        async def run():
            wire = transport(url)
            try:
                with pytest.raises(api.ToolSourceError, match="excessive"):
                    await wire.request("tools/list", {})
            finally:
                await wire.aclose()

        asyncio.run(run())
        replies = [
            c
            for c in calls
            if c["message"] is not None
            and type(c["message"].get("id")) is str
            and c["message"]["id"].startswith("server-")
        ]
        assert len(replies) == 100
        assert not business_calls(calls)
