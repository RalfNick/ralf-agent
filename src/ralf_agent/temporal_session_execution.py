"""Worker ownership of real Session handlers; observations go to original History."""

import asyncio
import concurrent.futures
import math

from .errors import CloseIncomplete, MemoryBackendError, ValidationError
from .memory import ThreadedMemoryAdapter
from .types import canonical


class SessionExecutionOwner:
    def __init__(self, *, max_calls=8):
        if type(max_calls) is not int or not 1 <= max_calls <= 256:
            raise ValidationError("Session handler capacity requires 1 to 256 calls")
        self.max_calls = max_calls
        self._executor = None
        self._entries = {}
        self._closed = False

    @property
    def identity(self):
        return {"kind": "session-execution-owner", "version": "1", "max_calls": self.max_calls}

    @property
    def active_count(self):
        # A cancelled async task is not proof that delegated I/O stopped.
        return sum(
            not e["future"].done() or e["future"].cancelled() for e in list(self._entries.values())
        )

    async def append(
        self, source, scope, address, message, *, expected_revision, message_id, proof, on_end=None
    ):
        if self._closed or len(self._entries) >= self.max_calls:
            raise MemoryBackendError("Session execution owner is closed or at capacity")
        key = proof["action_id"]
        if key in self._entries:
            raise MemoryBackendError("Original Session handler is already owned")
        loop = asyncio.get_running_loop()
        import json

        proof = json.loads(canonical(proof))

        async def invoke(role):
            return await source.fixed.call(
                role,
                "append",
                scope,
                address,
                message,
                expected_revision=expected_revision,
                message_id=message_id,
            )

        if isinstance(source.backend, ThreadedMemoryAdapter):
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self.max_calls, thread_name_prefix="ralf-session"
                )
            # Keep the actual concurrent Future, even if every asyncio task is cancelled.
            future = self._executor.submit(lambda: asyncio.run(invoke("session-source")))
            waiter = asyncio.wrap_future(future)
            waiter.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        else:
            future = waiter = asyncio.create_task(invoke("session"))
        entry = {"future": future, "proof": proof, "on_end": on_end, "notification": None}
        self._entries[key] = entry

        def finished(done):
            if done.cancelled():
                return
            done.exception()  # Consume errors even after observation cancellation.
            if on_end is None:
                self._entries.pop(key, None)
                return
            try:
                loop.call_soon_threadsafe(self._schedule_end, key)
            except RuntimeError:
                pass  # Keep proof queued; a closed loop cannot deliver it.

        future.add_done_callback(finished)
        return await asyncio.shield(waiter)

    def _schedule_end(self, key):
        entry = self._entries.get(key)
        if entry is None or entry["notification"] is not None:
            return

        async def notify():
            try:
                if entry["on_end"] is not None:
                    await entry["on_end"](entry["proof"])
            except asyncio.CancelledError:
                raise
            except Exception:
                return  # Retain the end proof for explicit retry, never fabricate ACK.
            self._entries.pop(key, None)

        entry["notification"] = asyncio.create_task(notify())

    async def wait(self, *, wait_timeout=30):
        if (
            type(wait_timeout) not in (int, float)
            or not math.isfinite(wait_timeout)
            or wait_timeout < 0
        ):
            raise ValidationError("Session handler wait timeout must be finite and nonnegative")
        deadline = asyncio.get_running_loop().time() + wait_timeout
        while self._entries:
            for key, entry in list(self._entries.items()):
                future = entry["future"]
                if future.done() and not future.cancelled():
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
            raise CloseIncomplete("Original Session handlers or end notifications remain owned")
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(wait=False)
