"""Actual Context readers and end notifications, never a business scheduler."""

import asyncio
import inspect
import json
import math
import re
from typing import Protocol

from .errors import CloseIncomplete, MemoryBackendError, ValidationError
from .ports import is_async_callable
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import canonical, digest


class ContextExecutionPort(Protocol):
    """Borrowed fixed owner port; callbacks acknowledge original-History end evidence."""

    @property
    def identity(self) -> dict: ...

    async def execute(self, operation, *, proof, on_end=None): ...

    async def wait(self, *, wait_timeout=30) -> bool: ...

    async def aclose(self, *, wait_timeout=30) -> None: ...


class ContextExecutionRejected(MemoryBackendError):
    """A fixed owner reports whether this refusal started no actual handler."""

    def __init__(self, *, handler_not_started):
        super().__init__("Context execution owner is closed, full, or owns this Action")
        if type(handler_not_started) is not bool:
            raise ValidationError("Context start refusal requires an exact boolean")
        self.handler_not_started = handler_not_started


def _proof(value):
    fields = {"scope", "action_id", "release_digest", "request_digest", "execution_epoch"}
    if type(value) is not dict or set(value) != fields:
        raise ValidationError("Context reader requires its original complete end identity")
    scope = value["scope"]
    if type(scope) is not dict or set(scope) != {"workspace", "principal"}:
        raise ValidationError("Context reader requires its original Scope")
    for text in [*scope.values(), value["action_id"], value["execution_epoch"]]:
        if type(text) is not str or not text.strip() or len(text) > 1024:
            raise ValidationError("Context reader identity requires bounded nonempty text")
    for name in ("release_digest", "request_digest"):
        if type(value[name]) is not str or re.fullmatch(r"[a-f0-9]{64}", value[name]) is None:
            raise ValidationError("Context reader requires fixed original digests")
    return json.loads(canonical(value))


class _ContextThreads(ThreadExecutionTracker):
    def __init__(self, finished):
        super().__init__()
        self._finished = finished

    def _register(self, group):
        # Delegators may supply their logical Run ID. This tracker belongs to
        # the actual owning invocation, whose end callback must see that work.
        return super()._register(current_thread_group.get() or group)

    def _finish(self, token):
        with self._lock:
            call = self._calls.get(token)
        super()._finish(token)
        if call is not None:
            self._finished(call[0])


class ContextExecutionOwner:
    """Keep the actual async operation, delegated threads and end ACK owned."""

    def __init__(self, *, max_calls=8):
        if type(max_calls) is not int or not 1 <= max_calls <= 256:
            raise ValidationError("Context reader capacity requires 1 to 256 calls")
        self.max_calls = max_calls
        self._threads = _ContextThreads(self._thread_finished)
        self._entries = {}
        self._closed = False

    @property
    def identity(self):
        return {"kind": "context-execution-owner", "version": "1", "max_calls": self.max_calls}

    @property
    def active_count(self):
        return sum(self._active(entry) for entry in list(self._entries.values()))

    def _active(self, entry):
        foreign = entry.get("foreign")
        return (
            not entry["task"].done()
            or self._threads.has_active_for(entry["group"])
            or (foreign is not None and (not foreign.done() or foreign.cancelled()))
        )

    @staticmethod
    def _key(proof):
        return digest([proof["scope"], proof["execution_epoch"], proof["action_id"]])

    async def execute(self, operation, *, proof, on_end=None):
        if not is_async_callable(operation) or (on_end is not None and not callable(on_end)):
            raise ValidationError(
                "Context reader requires an async operation and completed end callback"
            )
        proof = _proof(proof)
        key = self._key(proof)
        if self._closed or key in self._entries or len(self._entries) >= self.max_calls:
            raise ContextExecutionRejected(handler_not_started=key not in self._entries)

        async def invoke():
            tracker = current_thread_tracker.set(self._threads)
            group = current_thread_group.set(key)
            try:
                value = await operation()
                if inspect.isawaitable(value):
                    if isinstance(value, asyncio.Future):
                        if value.get_loop() is not asyncio.get_running_loop():
                            self._entries[key]["foreign"] = value
                            value.add_done_callback(lambda done: self._thread_finished(key))
                            raise ValidationError(
                                "Context operation returned a foreign-loop future"
                            )
                        value.cancel()
                        await asyncio.gather(value, return_exceptions=True)
                    elif inspect.iscoroutine(value):
                        value.close()
                    raise ValidationError("Context operation returned an unfinished awaitable")
                if inspect.isasyncgen(value):
                    await value.aclose()
                    raise ValidationError(
                        "Context operation returned an unfinished async generator"
                    )
                if inspect.isgenerator(value):
                    value.close()
                    raise ValidationError("Context operation returned an unfinished generator")
                return value
            finally:
                current_thread_group.reset(group)
                current_thread_tracker.reset(tracker)

        task = asyncio.create_task(invoke())
        entry = {"task": task, "proof": proof, "group": key, "on_end": on_end, "notification": None}
        self._entries[key] = entry

        def finished(done):
            if not done.cancelled():
                done.exception()
            if not done.cancelling():
                self._schedule_end(key)

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    def _thread_finished(self, key):
        entry = self._entries.get(key)
        if entry is None or entry["task"].cancelling():
            return
        try:
            entry["task"].get_loop().call_soon_threadsafe(self._schedule_end, key)
        except RuntimeError:
            pass  # Keep the fixed proof for explicit waiting on a live loop.

    def _schedule_end(self, key):
        entry = self._entries.get(key)
        if entry is None or entry["notification"] is not None or self._active(entry):
            return

        async def notify():
            delay = 0.05
            while True:
                try:
                    await self._threads.drain(entry["group"])
                    if entry["on_end"] is not None:
                        result = entry["on_end"](json.loads(canonical(entry["proof"])))
                        if inspect.isawaitable(result):
                            result = await result
                        if result is not None:
                            if inspect.iscoroutine(result):
                                result.close()
                            raise ValidationError(
                                "Context execution end must return completed None"
                            )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Keep the original completed invocation and end proof owned.
                    # A temporary ACK failure must recover without a second
                    # handler invocation or a caller driving wait/close.
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 1)
                else:
                    self._entries.pop(key, None)
                    return

        entry["notification"] = asyncio.create_task(notify())

    async def wait(self, *, wait_timeout=30):
        if (
            type(wait_timeout) not in (int, float)
            or not math.isfinite(wait_timeout)
            or wait_timeout < 0
        ):
            raise ValidationError("Context wait timeout must be finite and nonnegative")
        deadline = asyncio.get_running_loop().time() + wait_timeout
        while self._entries:
            for key, entry in list(self._entries.items()):
                if entry["task"].done():
                    notification = entry["notification"]
                    if notification is None or notification.done():
                        entry["notification"] = None
                        self._schedule_end(key)
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(min(0.01, max(0, deadline - asyncio.get_running_loop().time())))
        return True

    async def aclose(self, *, wait_timeout=30):
        if not await self.wait(wait_timeout=wait_timeout):
            raise CloseIncomplete("Original Context readers or end notifications remain owned")
        self._closed = True
