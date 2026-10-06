"""Bounded POSIX MCP stdio sessions with actual worker/process ownership."""

import copy
import json
import math
import os
import selectors
import signal
import subprocess
import threading
import time
from pathlib import Path

from .errors import DefinitionMismatch, ValidationError
from .mcp import mcp_descriptor
from .tool_sources import ToolSourceError
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import canonical, digest

VERSIONS = {"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}
LIMIT = 1048576


class _Session:
    def __init__(self, process, deadline, stopped):
        self.process, self.deadline, self.stopped = process, deadline, stopped
        self.buffer, self.counter = bytearray(), 0
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)

    def _check(self):
        if self.stopped.is_set() or time.monotonic() >= self.deadline:
            raise ToolSourceError("MCP operation cancelled or timed out")

    def _write(self, message):
        data = (canonical(message) + "\n").encode()
        if len(data) > LIMIT:
            raise ToolSourceError("MCP request exceeds 1 MiB")
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdin, selectors.EVENT_WRITE)
            while data:
                self._check()
                if selector.select(0.02):
                    try:
                        data = data[os.write(self.process.stdin.fileno(), data) :]
                    except BlockingIOError:
                        continue

    def _read(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                self._check()
                end = self.buffer.find(b"\n")
                if end >= 0:
                    if end + 1 > LIMIT:
                        raise ToolSourceError("MCP message exceeds 1 MiB")
                    line = bytes(self.buffer[:end])
                    del self.buffer[: end + 1]
                    try:
                        message = json.loads(line.decode("utf-8"))
                        canonical(message)
                    except (ValueError, ValidationError) as exc:
                        raise ToolSourceError("MCP peer returned invalid UTF-8 JSON") from exc
                    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                        raise ToolSourceError("MCP peer returned an invalid JSON-RPC message")
                    return message
                if len(self.buffer) >= LIMIT:
                    raise ToolSourceError("MCP message exceeds 1 MiB")
                if selector.select(0.02):
                    try:
                        chunk = os.read(self.process.stdout.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        raise ToolSourceError("MCP peer closed before completing its response")
                    self.buffer.extend(chunk)

    def notify(self, method):
        self._write({"jsonrpc": "2.0", "method": method})

    def request(self, method, params):
        self.counter += 1
        identifier = self.counter
        self._write({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        for _ in range(101):
            message = self._read()
            if "method" in message:
                if not isinstance(message["method"], str):
                    raise ToolSourceError("MCP peer returned an invalid method")
                if "id" in message:
                    response = {"jsonrpc": "2.0", "id": message["id"]}
                    if message["method"] == "ping":
                        response["result"] = {}
                    else:
                        response["error"] = {
                            "code": -32601,
                            "message": "Unsupported server request",
                        }
                    self._write(response)
                continue
            if type(message.get("id")) is not int or message["id"] != identifier:
                raise ToolSourceError("MCP response identity does not match the request")
            if ("error" in message) == ("result" in message):
                raise ToolSourceError("MCP response requires one result or error")
            if "error" in message:
                raise ToolSourceError("MCP peer reported a JSON-RPC error")
            if not isinstance(message["result"], dict):
                raise ToolSourceError("MCP response result must be an object")
            return message["result"]
        raise ToolSourceError("MCP peer exceeded the unsolicited message limit")

    def matching_tool(self, expected):
        descriptors, cursor, seen = [], None, set()
        for _ in range(32):
            page = self.request("tools/list", {} if cursor is None else {"cursor": cursor})
            if not isinstance(page.get("tools"), list):
                raise ToolSourceError("MCP discovery page is invalid")
            descriptors.extend(mcp_descriptor(item) for item in page["tools"])
            if len(descriptors) > 256 or len({item.name for item in descriptors}) != len(
                descriptors
            ):
                raise ToolSourceError("MCP discovery has excessive or duplicated tools")
            cursor = page.get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise ToolSourceError("MCP discovery cursor is invalid")
            seen.add(cursor)
        else:
            raise ToolSourceError("MCP discovery exceeded 32 pages")
        match = next((item for item in descriptors if item.name == expected["name"]), None)
        if match is None or digest(match.to_dict()) != digest(expected):
            raise DefinitionMismatch("MCP peer tool differs from the pinned descriptor")


class MCPStdioTransport:
    def __init__(self, command, *, version, cwd=None, env=None, timeout=30):
        if os.name != "posix":
            raise ValidationError("Default MCP stdio transport requires POSIX")
        if (
            not isinstance(command, (tuple, list))
            or not command
            or any(not isinstance(value, str) or not value or "\x00" in value for value in command)
        ):
            raise ValidationError("MCP command must be an explicit non-empty argv")
        if not isinstance(version, str) or not version.strip():
            raise ValidationError("MCP transport requires an explicit behavior version")
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 300
        ):
            raise ValidationError("MCP timeout must be finite and between 0 and 300 seconds")
        values = {"PATH": os.environ.get("PATH", "")} if env is None else dict(env)
        if any(
            not isinstance(k, str)
            or not k
            or "=" in k
            or "\x00" in k
            or not isinstance(v, str)
            or "\x00" in v
            for k, v in values.items()
        ):
            raise ValidationError("MCP environment must contain explicit string fields")
        self._command, self._version = tuple(command), version
        self._cwd, self._env, self._timeout = (
            str(Path(cwd or Path.cwd()).resolve()),
            values,
            timeout,
        )
        self._tracker = ThreadExecutionTracker()

    @property
    def identity(self):
        return {
            "kind": "mcp-stdio",
            "version": "1",
            "behavior_version": self._version,
            "command": list(self._command),
            "cwd": self._cwd,
            "environment_keys": sorted(self._env),
            "timeout": self._timeout,
        }

    async def request(self, method, params, *, expected_tool=None):
        if method not in {"tools/list", "tools/call"} or not isinstance(params, dict):
            raise ValidationError("MCP stdio supports tools/list and tools/call")
        canonical(params)
        canonical(expected_tool)
        if method == "tools/call" and (
            not isinstance(expected_tool, dict) or expected_tool.get("name") != params.get("name")
        ):
            raise ValidationError("MCP calls require their pinned descriptor")
        stopped = threading.Event()
        tracker = current_thread_tracker.get() or self._tracker
        try:
            return await tracker.run(
                self._request,
                method,
                copy.deepcopy(params),
                copy.deepcopy(expected_tool),
                stopped,
                group=current_thread_group.get(),
            )
        except BaseException:
            stopped.set()
            raise

    async def wait_for_calls(self):
        await self._tracker.drain()

    def _request(self, method, params, expected, stopped):
        process = None
        try:
            if stopped.is_set():
                raise ToolSourceError("MCP request cancelled before start")
            process = subprocess.Popen(
                self._command,
                cwd=self._cwd,
                env=self._env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            session = _Session(process, time.monotonic() + self._timeout, stopped)
            initialized = session.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "ralf-agent", "version": "0.1.0.dev11"},
                },
            )
            if (
                initialized.get("protocolVersion") not in VERSIONS
                or not isinstance(initialized.get("capabilities"), dict)
                or not isinstance(initialized["capabilities"].get("tools"), dict)
            ):
                raise ToolSourceError("MCP peer has an unsupported protocol or tool capability")
            session.notify("notifications/initialized")
            if expected is not None:
                session.matching_tool(expected)
            return session.request(method, params)
        except (OSError, ValueError) as exc:
            raise ToolSourceError("MCP stdio operation failed") from exc
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
                # Descendants remain our responsibility even if their parent exits.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                process.stdin.close()
                process.stdout.close()
