"""Bounded Codex App Server stdio correlation and POSIX process ownership.

This layer never retries business requests or interprets turn stop evidence.
Killing the owned process group is not a sandbox or an escaped-child guarantee.
"""

import asyncio
import json
import math
import os
import signal
import subprocess
from collections import deque

_METHODS = frozenset(
    {"initialize", "thread/start", "thread/read", "thread/resume", "turn/start", "turn/interrupt"}
)
_MAX_ID = 2**53 - 1


class CodexRPCError(RuntimeError):
    """Transport operation failed; effects of sent requests may be unknown."""


class CodexRPCProtocolError(CodexRPCError):
    """Malformed, oversized, overflowing, or uncorrelated peer traffic."""


class CodexRPCClosed(CodexRPCError):
    """The transport is not open for communication."""


class CodexRPCRemoteError(CodexRPCError):
    """A correlated JSON-RPC error, with the original error object."""

    def __init__(self, error: dict):
        super().__init__("Codex App Server rejected the request")
        self.error = error


class CodexRPCCloseIncomplete(CodexRPCError):
    """Cleanup retains its owner; aclose can be awaited again in the same loop."""


def _positive_number(value, name):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a positive finite number")


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError("nonfinite JSON number")


def _check_json(value, *, depth=0, budget=None):
    # Bound recursive validation independently of the interpreter recursion limit.
    if depth > 64:
        raise ValueError("JSON nesting exceeds transport limit")
    if budget is not None:
        budget[0] -= len(value) if type(value) is str else 1
        if budget[0] < 0:
            raise ValueError("outgoing JSON exceeds transport size budget")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON object keys must be strings")
            if budget is not None:
                budget[0] -= len(key)
                if budget[0] < 0:
                    raise ValueError("outgoing JSON key exceeds transport size budget")
            _check_json(item, depth=depth + 1, budget=budget)
        return
    if type(value) is list:
        for item in value:
            _check_json(item, depth=depth + 1, budget=budget)
        return
    raise ValueError("payload must contain only finite JSON values")


def _valid_id(value):
    return type(value) is int and -_MAX_ID <= value <= _MAX_ID or type(value) is str and bool(value)


class CodexRPCTransport:
    """One explicitly started, non-reconnecting stdio connection.

    max_events also bounds outstanding local requests. Request IDs are local
    correlation IDs, never business idempotence keys. Params admission belongs
    to the caller's frozen capability profile, not this framing layer.
    """

    def __init__(
        self,
        argv: tuple[str, ...],
        *,
        env: dict[str, str],
        max_message_bytes: int = 1048576,
        max_events: int = 256,
        request_timeout: float = 30.0,
    ):
        if os.name != "posix":
            raise ValueError("CodexRPCTransport requires POSIX process groups")
        if (
            type(argv) is not tuple
            or not argv
            or any(type(arg) is not str or not arg or "\0" in arg for arg in argv)
        ):
            raise ValueError("argv must be a nonempty tuple of nonempty NUL-free strings")
        if type(env) is not dict or any(
            type(key) is not str
            or not key
            or "=" in key
            or "\0" in key
            or type(value) is not str
            or "\0" in value
            for key, value in env.items()
        ):
            raise ValueError("env must contain valid string environment names and values")
        for value, name, upper in (
            (max_message_bytes, "max_message_bytes", 16 * 1024 * 1024),
            (max_events, "max_events", 65536),
        ):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be an integer between 1 and {upper}")
        _positive_number(request_timeout, "request_timeout")
        self._argv = argv
        self._env = dict(env)
        self._max_message_bytes = max_message_bytes
        self._max_events = max_events
        self._request_timeout = request_timeout
        self._state = "new"
        self._failure = None
        self._process = None
        self._stdin = None
        self._stdout = None
        self._read_transport = None
        self._write_transport = None
        self._launch_task = None
        self._launch_settled = False
        self._reader_task = None
        self._close_task = None
        self._pending = {}
        self._events = deque()
        self._event_ready = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._last_id = 0
        self._notifications = 0

    @property
    def pid(self) -> int | None:
        """Owned local process identity, without any native task identity claim."""
        return self._process.pid if self._process is not None else None

    async def start(self):
        if self._state != "new":
            raise CodexRPCClosed("transport cannot be started again")
        self._state = "starting"
        self._launch_task = asyncio.create_task(self._launch())
        try:
            await asyncio.shield(self._launch_task)
        except asyncio.CancelledError:
            self._begin_close()
            await self._complete_close()
            raise
        self._require_open()

    async def _launch(self):
        if self._state != "starting":
            return
        try:
            # Popen owns the real PID and raw pipes synchronously, before pipe
            # attachment can suspend. create_subprocess_exec only returns its
            # Process after that cancellable setup, leaving an ownership gap.
            self._process = subprocess.Popen(  # noqa: ASYNC220 - own PID before every await
                self._argv,
                env=self._env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                bufsize=0,
            )
            loop = asyncio.get_running_loop()
            self._stdout = asyncio.StreamReader(limit=self._max_message_bytes + 1)
            self._read_transport, _ = await loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(self._stdout),
                self._process.stdout,
            )
            # StreamReaderProtocol supplies the public StreamWriter flow-control
            # and close-waiter contract. This write-side reader receives no data.
            write_protocol = asyncio.StreamReaderProtocol(asyncio.StreamReader())
            self._write_transport, _ = await loop.connect_write_pipe(
                lambda: write_protocol,
                self._process.stdin,
            )
            self._stdin = asyncio.StreamWriter(self._write_transport, write_protocol, None, loop)
            if self._state == "starting":
                self._state = "open"
                self._reader_task = asyncio.create_task(self._read())
        except asyncio.CancelledError:
            # Pipe attachment has unwound. Cleanup must not wait for this task
            # while this original shutdown task keeps its cleanup owner alive.
            self._launch_settled = True
            self._begin_close()
            await self._complete_close()
        except (OSError, ValueError, RuntimeError):
            self._fail(CodexRPCError("Codex App Server launch failed"))
        finally:
            self._launch_settled = True

    def _require_open(self):
        if self._failure is not None:
            raise self._failure
        if self._state != "open":
            raise CodexRPCClosed("transport is not open")

    def _encode(self, message):
        # Before iterencode can allocate an escaped string/key, bound its input
        # characters and total nodes. The final encoder enforces actual bytes.
        _check_json(message, budget=[self._max_message_bytes])
        # iterencode avoids allocating the whole encoded object before the byte bound.
        output = bytearray()
        try:
            for part in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(
                message
            ):
                if len(part) > self._max_message_bytes:
                    raise ValueError("outgoing message exceeds byte limit")
                encoded = part.encode("utf-8")
                if len(output) + len(encoded) > self._max_message_bytes:
                    raise ValueError("outgoing message exceeds byte limit")
                output.extend(encoded)
        except (RecursionError, UnicodeError, OverflowError):
            raise ValueError("outgoing message is not bounded valid JSON") from None
        output.append(10)
        return bytes(output)

    async def _send(self, payload):
        async with self._write_lock:
            self._require_open()
            try:
                # A timed-out/cancelled previous drain may leave one frame in
                # the pipe transport. Respect its backpressure before appending
                # another frame, so repeated timeouts cannot grow that buffer.
                await self._stdin.drain()
                self._require_open()
                self._stdin.write(payload)
                await self._stdin.drain()
            except (OSError, RuntimeError):
                error = CodexRPCError("Codex App Server write failed; request effects are unknown")
                self._fail(error)
                raise error from None

    async def request(self, method: str, params: dict) -> dict:
        self._require_open()
        if type(method) is not str or method not in _METHODS or type(params) is not dict:
            raise ValueError("request method or params are outside the stable transport subset")
        if len(self._pending) >= self._max_events:
            raise CodexRPCError("outstanding request limit reached")
        if self._last_id == _MAX_ID:
            raise CodexRPCError("local request ID space exhausted")
        request_id = self._last_id + 1
        payload = self._encode({"id": request_id, "method": method, "params": params})
        self._last_id = request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        async def exchange():
            await self._send(payload)
            return await future

        try:
            return await asyncio.wait_for(exchange(), timeout=self._request_timeout)
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def notify(self, method: str, params: dict | None = None):
        self._require_open()
        if (
            type(method) is not str
            or method != "initialized"
            or (params is not None and type(params) is not dict)
        ):
            raise ValueError("only initialized notifications are allowed")
        if self._notifications >= self._max_events:
            raise CodexRPCError("outstanding notification limit reached")
        self._notifications += 1
        try:
            message = {"method": method}
            if params is not None:
                message["params"] = params
            payload = self._encode(message)
            await asyncio.wait_for(self._send(payload), timeout=self._request_timeout)
        finally:
            self._notifications -= 1

    async def next_event(self) -> dict:
        while True:
            if self._events:
                return self._events.popleft()
            self._require_open()
            self._event_ready.clear()
            await self._event_ready.wait()

    async def _read(self):
        try:
            while True:
                wire = await self._stdout.readuntil(b"\n")
                if len(wire) - 1 > self._max_message_bytes:
                    raise ValueError("frame exceeds byte limit")
                message = json.loads(
                    wire.decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_constant=_invalid_constant,
                )
                _check_json(message)
                self._route(message)
        except asyncio.CancelledError:
            raise
        except asyncio.IncompleteReadError as error:
            if error.partial:
                self._fail(CodexRPCProtocolError("unterminated JSON frame"))
            else:
                self._fail(CodexRPCClosed("Codex App Server stdout closed"))
        except (ValueError, UnicodeError, RecursionError, asyncio.LimitOverrunError):
            self._fail(CodexRPCProtocolError("invalid or overflowing Codex JSON frame"))
        except OSError:
            self._fail(CodexRPCError("Codex App Server read failed"))

    def _route(self, message):
        if type(message) is not dict or message.get("jsonrpc", "2.0") != "2.0":
            raise ValueError("invalid JSON-RPC object")
        if "method" in message:
            if (
                type(message["method"]) is not str
                or not message["method"]
                or "result" in message
                or "error" in message
                or ("params" in message and type(message["params"]) is not dict)
                or ("id" in message and not _valid_id(message["id"]))
            ):
                raise ValueError("invalid peer request or notification")
            if len(self._events) == self._max_events:
                raise ValueError("event inbox overflow")
            self._events.append(message)
            self._event_ready.set()
            return
        request_id = message.get("id")
        if type(request_id) is not int or not 1 <= request_id <= self._last_id:
            raise ValueError("uncorrelated response ID")
        if ("result" in message) == ("error" in message):
            raise ValueError("response must have exactly one result or error")
        if "result" in message and type(message["result"]) is not dict:
            raise ValueError("response result must be an object")
        if "error" in message:
            error = message["error"]
            if (
                type(error) is not dict
                or type(error.get("code")) is not int
                or type(error.get("message")) is not str
            ):
                raise ValueError("invalid JSON-RPC error")
        future = self._pending.get(request_id)
        # Old IDs are never reused, so late responses require no unbounded tombstone set.
        if future is None or future.done():
            return
        if "error" in message:
            future.set_exception(CodexRPCRemoteError(message["error"]))
        else:
            future.set_result(message["result"])

    def _fail(self, error):
        if self._failure is None:
            self._failure = error
        self._begin_close()

    def _begin_close(self):
        if self._state != "closed":
            self._state = "closing"
        error = self._failure or CodexRPCClosed("transport is closing")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._event_ready.set()
        if self._close_task is None or (
            self._close_task.done()
            and (self._close_task.cancelled() or self._close_task.exception() is not None)
        ):
            self._close_task = asyncio.create_task(self._cleanup())

    async def _cleanup(self):
        # No await precedes the process identity read or the signal. A launch
        # that has not executed yet sees closing and never creates a process.
        if (
            self._launch_task is not None
            and not self._launch_task.done()
            and not self._launch_settled
        ):
            self._launch_task.cancel()
        process = self._process
        if process is not None:
            if self._reader_task is not None:
                self._reader_task.cancel()
            process.poll()
            try:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except OSError:
                    # The final SIGKILL still has to be attempted. A denied
                    # graceful signal cannot be interpreted as a stopped group.
                    pass
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                # Event-loop shutdown can cancel the owner itself. Skip grace,
                # but retain ownership through kill, pipe close, and reap.
                pass
            finally:
                # Kill the original group even if its leader has already exited.
                # Reap an exited leader before signalling again: an unreaped
                # zombie can make POSIX sandbox signal checks report EPERM.
                process.poll()
                signal_failure = None
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    signal_failure = CodexRPCCloseIncomplete(
                        "process-group stop could not be confirmed; PID retained for close retry"
                    )
                # A cancelled launch keeps this owner alive until cleanup ends.
                # Wait for pipe setup to unwind, not for that supervisor to exit.
                while (
                    self._launch_task is not None
                    and not self._launch_task.done()
                    and not self._launch_settled
                ):
                    try:
                        await asyncio.sleep(0)
                    except asyncio.CancelledError:
                        pass
                # Pipe setup has settled, so it cannot attach another transport
                # after these owned pipes are closed. Escaped fds cannot hold up
                # local pipe close or the direct child's reap.
                if self._read_transport is not None:
                    self._read_transport.close()
                else:
                    process.stdout.close()
                if self._write_transport is not None:
                    self._write_transport.close()
                else:
                    process.stdin.close()
                if signal_failure is not None:
                    process.poll()
                    raise signal_failure
                while process.poll() is None:
                    try:
                        await asyncio.sleep(0.005)
                    except asyncio.CancelledError:
                        pass
            if self._reader_task is not None:
                await self._settle_task(self._reader_task)
        elif self._launch_task is not None:
            await self._settle_task(self._launch_task)
        self._state = "closed"
        self._events.clear()
        self._event_ready.set()

    @staticmethod
    async def _settle_task(task):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Shutdown may cancel both the cleanup owner and the task it is
                # draining. Neither cancellation discards the owned PID/pipes.
                pass
        if not task.cancelled():
            task.exception()

    async def _complete_close(self):
        while True:
            self._begin_close()
            try:
                await asyncio.shield(self._close_task)
                return
            except asyncio.CancelledError:
                # If shutdown cancelled an owner before its first instruction,
                # recreate it while the already-running supervisor remains alive.
                pass

    async def aclose(self, *, wait_timeout: float = 30) -> None:
        _positive_number(wait_timeout, "wait_timeout")
        self._begin_close()
        try:
            await asyncio.wait_for(asyncio.shield(self._close_task), timeout=wait_timeout)
        except TimeoutError:
            raise CodexRPCCloseIncomplete(
                "cleanup still owned; retry aclose in the same loop"
            ) from None
