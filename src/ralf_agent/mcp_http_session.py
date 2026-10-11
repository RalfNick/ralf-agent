"""One HTTP MCP session; wire evidence only, no business retry authority."""

import time

import httpx

from .errors import DefinitionMismatch, ValidationError
from .mcp import mcp_descriptor
from .mcp_http_events import iter_sse_messages
from .tool_json import decode_output
from .tool_sources import ToolSourceError
from .types import canonical, digest

VERSIONS = frozenset({"2025-11-25", "2025-06-18", "2025-03-26"})


def _local_schema_references(schema):
    # A remote catalog cannot grant another network destination to jsonschema.
    # Keep fragment references, including $defs/anchors, within admitted data.
    pending = [schema]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    type(item) is not str or not item.startswith("#")
                ):
                    raise ToolSourceError("MCP HTTP tool schemas require local references")
                pending.append(item)
        elif isinstance(value, list):
            pending.extend(value)


class Session:
    def __init__(self, client, url, headers, timeout, message_limit, operation_limit, stopped):
        self.client, self.url, self.headers = client, url, headers
        self.deadline, self.stopped = time.monotonic() + timeout, stopped
        self.message_limit, self.operation_limit = message_limit, operation_limit
        self.used, self.counter, self.unsolicited = 0, 0, 0
        self.identifier, self.protocol = None, None

    def check(self):
        if self.stopped.is_set() or time.monotonic() >= self.deadline:
            raise ToolSourceError("MCP HTTP operation stopped or timed out")

    def charge(self, size):
        self.used += size
        if self.used > self.operation_limit:
            raise ToolSourceError("MCP HTTP operation exceeds its byte limit")

    def wire_headers(self):
        result = {
            **self.headers,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Accept-Encoding": "identity",
        }
        if self.protocol is not None:
            result["MCP-Protocol-Version"] = self.protocol
        if self.identifier is not None:
            result["MCP-Session-Id"] = self.identifier
        return result

    def chunks(self, response):
        for chunk in response.iter_raw():
            self.check()
            self.charge(len(chunk))
            yield chunk
        self.check()

    def messages(self, response):
        kind = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if kind == "text/event-stream":
            yield from iter_sse_messages(self.chunks(response), limit=self.message_limit)
        elif kind == "application/json":
            output = bytearray()
            for chunk in self.chunks(response):
                if len(output) + len(chunk) > self.message_limit:
                    raise ToolSourceError("MCP HTTP message exceeds its byte limit")
                output.extend(chunk)
            yield bytes(output)
        else:
            raise ToolSourceError("MCP HTTP response requires JSON or SSE")

    def notification(self, message):
        self.post(message, notification=True)

    def post(self, message, *, notification=False):
        self.check()
        payload = canonical(message).encode("utf-8")
        if len(payload) > self.message_limit:
            raise ToolSourceError("MCP HTTP request exceeds its byte limit")
        self.charge(len(payload))
        with self.client.stream(
            "POST", self.url, content=payload, headers=self.wire_headers()
        ) as response:
            self.check()
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ToolSourceError("MCP HTTP response requires identity encoding")
            session = response.headers.get("MCP-Session-Id")
            if message.get("method") == "initialize":
                if session is not None:
                    if not 1 <= len(session) <= 256 or any(
                        not 33 <= ord(char) <= 126 for char in session
                    ):
                        raise ToolSourceError("MCP HTTP session identifier is invalid")
                    self.identifier = session
            elif session is not None and session != self.identifier:
                raise ToolSourceError("MCP HTTP response changed the original session")
            if notification:
                if response.status_code != 202 or any(self.chunks(response)):
                    raise ToolSourceError("MCP HTTP notification requires empty acceptance")
                return None
            if response.status_code != 200:
                raise ToolSourceError("MCP HTTP request returned an unsuccessful status")
            for raw in self.messages(response):
                self.check()
                result = decode_output(raw)
                if type(result) is not dict or result.get("jsonrpc") != "2.0":
                    raise ToolSourceError("MCP HTTP returned an invalid JSON-RPC object")
                if "method" in result:
                    self.unsolicited += 1
                    if self.unsolicited > 100 or type(result["method"]) is not str:
                        raise ToolSourceError(
                            "MCP HTTP unsolicited message is invalid or excessive"
                        )
                    if "id" in result:
                        if type(result["id"]) not in (str, int):
                            raise ToolSourceError("MCP HTTP server request identifier is invalid")
                        reply = {"jsonrpc": "2.0", "id": result["id"]}
                        if result["method"] == "ping":
                            reply["result"] = {}
                        else:
                            reply["error"] = {
                                "code": -32601,
                                "message": "Unsupported server request",
                            }
                        self.notification(reply)
                    continue
                if type(result.get("id")) is not int or result["id"] != message["id"]:
                    raise ToolSourceError("MCP HTTP response identity differs from its request")
                if ("error" in result) == ("result" in result) or "error" in result:
                    raise ToolSourceError("MCP HTTP returned an unsuccessful RPC response")
                if type(result["result"]) is not dict:
                    raise ToolSourceError("MCP HTTP result requires an object")
                return result["result"]
        raise ToolSourceError("MCP HTTP stream ended without its response")

    def request(self, method, params):
        self.counter += 1
        return self.post({"jsonrpc": "2.0", "id": self.counter, "method": method, "params": params})

    def initialize(self):
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "ralf-agent", "version": "mcp-http-1"},
            },
        )
        if (
            type(result.get("protocolVersion")) is not str
            or result["protocolVersion"] not in VERSIONS
            or type(result.get("capabilities")) is not dict
            or type(result["capabilities"].get("tools")) is not dict
        ):
            raise ToolSourceError("MCP HTTP peer has an unsupported protocol or tools capability")
        self.protocol = result["protocolVersion"]
        self.notification({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def discover(self):
        tools, names, seen, cursor = [], set(), set(), None
        for _ in range(32):
            page = self.request("tools/list", {} if cursor is None else {"cursor": cursor})
            if type(page.get("tools")) is not list:
                raise ToolSourceError("MCP HTTP discovery requires a tools page")
            for value in page["tools"]:
                if isinstance(value, dict):
                    _local_schema_references(value.get("inputSchema"))
                    _local_schema_references(value.get("outputSchema"))
                descriptor = mcp_descriptor(value)
                if descriptor.name in names or len(tools) == 256:
                    raise ToolSourceError("MCP HTTP discovery duplicates or exceeds tools")
                names.add(descriptor.name)
                tools.append(value)
            cursor = page.get("nextCursor")
            if cursor is None:
                return tools
            if type(cursor) is not str or not cursor or cursor in seen:
                raise ToolSourceError("MCP HTTP discovery cursor is invalid")
            seen.add(cursor)
        raise ToolSourceError("MCP HTTP discovery exceeded its page limit")

    def call(self, params, expected):
        descriptors = [mcp_descriptor(item) for item in self.discover()]
        selected = next((d for d in descriptors if d.name == expected["name"]), None)
        if selected is None or digest(selected.to_dict()) != digest(expected):
            raise DefinitionMismatch("MCP HTTP tool differs from its pinned descriptor")
        return self.request("tools/call", params)

    def close(self):
        if self.identifier is not None and self.protocol is not None:
            try:
                with self.client.stream("DELETE", self.url, headers=self.wire_headers()):
                    pass
            except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError):
                # This is session cleanup, never a resend of a business operation.
                pass


def execute(
    url, headers, timeout, message_limit, operation_limit, method, params, expected, stopped
):
    session = None
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            session = Session(
                client, url, headers, timeout, message_limit, operation_limit, stopped
            )
            try:
                session.check()
                session.initialize()
                return (
                    {"tools": session.discover()}
                    if method == "tools/list"
                    else session.call(params, expected)
                )
            finally:
                session.close()
    except (
        httpx.HTTPError,
        httpx.InvalidURL,
        OSError,
        ValueError,
        RecursionError,
        ValidationError,
    ):
        raise ToolSourceError("MCP HTTP transport or protocol validation failed") from None
