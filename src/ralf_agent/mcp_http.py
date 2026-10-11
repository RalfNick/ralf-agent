"""Fixed HTTP MCP transport with original actual-thread ownership."""

import copy
import threading

from . import mcp_http_session
from .errors import DefinitionMismatch, ValidationError
from .http_tools import _configuration
from .tool_sources import ToolDescriptor, ToolSourceError
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import canonical, digest


class MCPHTTPTransport:
    def __init__(
        self,
        url,
        *,
        version,
        headers=None,
        timeout=30,
        max_message_bytes=1048576,
        max_operation_bytes=8388608,
    ):
        values = _configuration(
            url, version, headers, timeout, max_message_bytes, max_message_bytes
        )
        if (
            type(max_operation_bytes) is not int
            or not max_message_bytes <= max_operation_bytes <= 67108864
        ):
            raise ValidationError(
                "MCP HTTP operation byte limit must cover messages and be at most64 MiB"
            )
        if set(values) & {"accept", "mcp-session-id", "mcp-protocol-version", "last-event-id"}:
            raise ValidationError("MCP HTTP headers conflict with negotiated protocol framing")
        self._url, self._version, self._headers = url, version, values
        self._timeout, self._message_limit, self._operation_limit = (
            timeout,
            max_message_bytes,
            max_operation_bytes,
        )
        self._tracker = ThreadExecutionTracker()
        self._lock, self._stops, self._closing = threading.Lock(), set(), False
        self._identity = canonical(self.identity)

    @property
    def identity(self):
        return {
            "kind": "mcp-http",
            "version": "1",
            "behavior_version": self._version,
            "url": self._url,
            "header_names": sorted(self._headers),
            "header_fingerprint": digest(self._headers),
            "timeout": self._timeout,
            "max_message_bytes": self._message_limit,
            "max_operation_bytes": self._operation_limit,
        }

    def _check(self):
        if canonical(self.identity) != self._identity:
            raise DefinitionMismatch("Original MCP HTTP configuration changed")
        if self._closing:
            raise ToolSourceError("MCP HTTP transport is closing or closed")

    def _execute(self, token, method, params, expected, stopped):
        if token is not None and not self._tracker._begin(token):
            return None
        try:
            return mcp_http_session.execute(
                self._url,
                self._headers,
                self._timeout,
                self._message_limit,
                self._operation_limit,
                method,
                params,
                expected,
                stopped,
            )
        finally:
            if token is not None:
                self._tracker._finish(token)

    async def request(self, method, params, *, expected_tool=None):
        if method not in {"tools/list", "tools/call"} or type(params) is not dict:
            raise ValidationError("MCP HTTP supports tools/list and pinned tools/call")
        if method == "tools/list" and params:
            raise ValidationError("MCP HTTP discovery starts with empty parameters")
        if method == "tools/call":
            if (
                set(params) != {"name", "arguments"}
                or type(expected_tool) is not dict
                or params["name"] != expected_tool.get("name")
                or type(params["arguments"]) is not dict
            ):
                raise ValidationError("MCP HTTP call requires pinned tool and JSON arguments")
            try:
                ToolDescriptor(**expected_tool)
            except TypeError:
                raise ValidationError("MCP HTTP pinned descriptor is incomplete") from None
        try:
            canonical(params).encode("utf-8")
            canonical(expected_tool).encode("utf-8")
        except (ValueError, RecursionError):
            raise ValidationError("MCP HTTP requests require finite UTF-8 JSON") from None
        stopped = threading.Event()
        ambient = current_thread_tracker.get()
        tracker = ambient or self._tracker
        with self._lock:
            self._check()
            self._stops.add(stopped)
            token = (
                self._tracker._register(current_thread_group.get()) if ambient is not None else None
            )
        try:
            result = await tracker.run(
                self._execute,
                token,
                method,
                copy.deepcopy(params),
                copy.deepcopy(expected_tool),
                stopped,
                group=current_thread_group.get(),
            )
            self._check()
            return copy.deepcopy(result)
        except BaseException:
            stopped.set()
            if token is not None:
                self._tracker._withdraw_pending(token)
            raise
        finally:
            with self._lock:
                self._stops.discard(stopped)

    async def wait_for_calls(self):
        await self._tracker.drain()

    async def aclose(self):
        with self._lock:
            self._closing = True
            for stopped in self._stops:
                stopped.set()
        await self.wait_for_calls()
