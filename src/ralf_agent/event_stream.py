"""Pull-only observation of committed Run events; never drive/cancel authority."""

import asyncio
import math
from collections import deque
from dataclasses import asdict

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .event_records import EventCursor, EventEnvelope
from .handoff import _completed
from .ports import is_async_callable, is_sync_callable
from .task_controls import _binding
from .types import RunEvent, RunSnapshot, Scope, canonical

_STATES = {
    "queued",
    "running",
    "waiting_approval",
    "waiting_reconciliation",
    "outcome_unknown",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
}
_TERMINAL = {"succeeded", "failed", "cancelled"}


class _Reader:
    def __init__(self, source, scope):
        self.source, self.scope = source, scope
        self.asynchronous = is_async_callable(getattr(source, "events", None))
        self.predicate = is_async_callable if self.asynchronous else is_sync_callable
        if not all(self.predicate(getattr(source, n, None)) for n in ("events", "status")):
            raise ValidationError("Event sources need one synchronous or native async mode")
        self.bindings = {n: _binding(getattr(source, n)) for n in ("events", "status")}
        self.verify()

    def verify(self):
        if getattr(self.source, "scope", None) != self.scope:
            raise AuthorizationDenied("Event source Scope changed or mismatched")
        for name, binding in self.bindings.items():
            method = getattr(self.source, name, None)
            if not self.predicate(method) or _binding(method) != binding:
                raise DefinitionMismatch("Event source binding changed")

    async def call(self, name, *args, **kwargs):
        self.verify()
        method = getattr(self.source, name)
        value = await method(*args, **kwargs) if self.asynchronous else method(*args, **kwargs)
        value = await _completed(value, "Event source " + name)
        self.verify()
        return value


def _seconds(value, name, lower, upper):
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValidationError(name + " is outside its finite supported range")
    return value


class RunEventSubscription:
    def __init__(
        self,
        source,
        run_id,
        *,
        scope=None,
        after=0,
        page_size=100,
        follow=True,
        poll_interval=0.1,
        read_timeout=30,
        max_events=None,
    ):
        scope = getattr(source, "scope", None) if scope is None else scope
        if not isinstance(scope, Scope):
            raise AuthorizationDenied("Event source requires a trusted Scope")
        cursor = after if isinstance(after, EventCursor) else EventCursor(scope, run_id, after)
        if cursor.scope != scope or cursor.run_id != run_id:
            raise AuthorizationDenied("Event cursor belongs to another Scope or Run")
        if type(page_size) is not int or not 1 <= page_size <= 1000 or type(follow) is not bool:
            raise ValidationError("Invalid event page size/follow mode")
        if max_events is not None and (
            type(max_events) is not int or not 1 <= max_events <= 1_000_000
        ):
            raise ValidationError("Invalid event emission allowance")
        self.poll_interval = _seconds(poll_interval, "Event polling interval", 0.01, 60)
        self.read_timeout = _seconds(read_timeout, "Event read timeout", 0.001, 300)
        self.source, self.run_id, self.scope = source, run_id, cursor.scope
        self._reader = _Reader(source, self.scope)
        self.page_size, self.follow, self.max_events = page_size, follow, max_events
        self._cursor, self._emitted = cursor, 0
        self._buffer = deque()
        self._loop = self._wake = self._read_task = None
        self._cancel_read_requested = False
        self._closed = self._reading = False

    @property
    def cursor(self):
        return self._cursor

    def __aiter__(self):
        return self

    def _bind_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop, self._wake = loop, asyncio.Event()
        elif self._loop is not loop:
            raise ValidationError("Event subscription belongs to another event loop")

    async def _call(self, name, **kwargs):
        if self._closed:
            raise StopAsyncIteration
        task = asyncio.create_task(
            self._reader.call(name, self.run_id, **kwargs), name="ralf:event-read"
        )
        self._read_task = task
        self._cancel_read_requested = False
        try:
            done, _ = await asyncio.wait({task}, timeout=self.read_timeout)
            if not done:
                await self._stop_read(task)
                raise TimeoutError("Event source read timed out")
            value = task.result()
            if self._closed:
                raise StopAsyncIteration
            return value
        except asyncio.CancelledError:
            await self._stop_read(task)
            if self._closed:
                raise StopAsyncIteration from None
            raise
        finally:
            if task.done() and self._read_task is task:
                self._read_task = None

    async def _stop_read(self, task):
        if not task.done() and not self._cancel_read_requested:
            self._cancel_read_requested = True
            task.cancel()
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done():
                raise
        except Exception:
            pass
        if task.done() and self._read_task is task:
            self._read_task = None

    async def _page(self):
        page = await self._call("events", after=self.cursor.after, limit=self.page_size)
        if (
            not isinstance(page, list)
            or len(page) > self.page_size
            or any(not isinstance(event, RunEvent) for event in page)
        ):
            raise ValidationError("Event source returned an invalid page")
        if len(canonical([asdict(e) for e in page]).encode("utf-8")) > 4_000_000:
            raise ValidationError("Event page exceeds its bound")
        records = []
        for offset, event in enumerate(page, 1):
            record = EventEnvelope(self.scope, event)
            if (
                record.cursor.run_id != self.run_id
                or record.cursor.after != self.cursor.after + offset
            ):
                raise ValidationError("Event sequence contains a gap or foreign Run")
            records.append(record)
        self._buffer.extend(records)
        return bool(records)

    async def __anext__(self):
        if self._closed:
            raise StopAsyncIteration
        self._bind_loop()
        if self._reading:
            raise ValidationError("Event subscription allows one consumer")
        self._reading = True
        try:
            while not self._closed:
                self._reader.verify()
                if self.max_events is not None and self._emitted >= self.max_events:
                    break
                if self._buffer:
                    record = self._buffer.popleft()
                    self._cursor = record.cursor
                    self._emitted += 1
                    return record
                if await self._page():
                    continue
                if not self.follow:
                    break
                status = await self._call("status")
                if (
                    not isinstance(status, RunSnapshot)
                    or status.run_id != self.run_id
                    or status.state not in _STATES
                    or type(status.state_revision) is not int
                    or status.state_revision < 0
                ):
                    raise ValidationError("Event source returned an invalid status")
                canonical(asdict(status))
                if status.state in _TERMINAL:
                    if await self._page():
                        continue
                    break
                try:
                    await asyncio.wait_for(self._wake.wait(), self.poll_interval)
                except TimeoutError:
                    pass
            await self.aclose()
            raise StopAsyncIteration
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._reading = False

    async def aclose(self):
        task = self._read_task
        if self._closed and (task is None or task.done()):
            return
        if (
            self._loop is not None
            and self._loop is not asyncio.get_running_loop()
            and self._read_task is not None
        ):
            raise ValidationError("Active event subscription belongs to another loop")
        self._closed = True
        self._buffer.clear()
        if self._wake is not None:
            self._wake.set()
        if task is not None and not task.done():
            await self._stop_read(task)
