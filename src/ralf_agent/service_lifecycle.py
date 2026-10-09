"""Explicit owned lifecycle for a single local A2A execution authority."""

import asyncio
import uuid
from collections import deque

from .a2a import A2AApplication
from .errors import RalfError, ValidationError
from .handoff import _completed, validate_inbox
from .ports import _complete_sync_none, close_engine, is_async_callable, validate_engine
from .task_controls import TaskControlBridge


class LocalA2AService:
    """Own a local Engine/Inbox only after successful construction.

    Host callbacks supply trusted authentication. Queued/recovering Runs are
    driven on this Engine's coordinator loop; shutdown stops dispatch, waits for
    actual drives/threads and closes resources in stages with retry. This class
    does not host async remote authorities or start an ASGI server implicitly.
    """

    def __init__(self, *, engine, inbox, **application_options):
        validate_engine(engine)
        validate_inbox(inbox)
        self._engine, self._inbox = engine, inbox
        self._controls = TaskControlBridge(engine, engine.scope)
        self._active = {}
        self._errors = deque(maxlen=100)
        self._closing, self._closed = False, False
        self._engine_closed, self._inbox_closed = False, False
        self._close_task = None
        self._loop = None
        self._stop_nonce = uuid.uuid4().hex
        self.application = A2AApplication(
            engine_for_scope=lambda scope: engine,
            inbox=inbox,
            wakeup=self.wakeup,
            **application_options,
        )

    @property
    def closed(self):
        return self._closed

    @property
    def errors(self):
        return tuple(dict(item) for item in self._errors)

    def _check_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ValidationError("Local service lifecycle must use its coordinator loop")

    async def wakeup(self, scope, run_id):
        self._check_loop()
        if self._closing:
            raise ValidationError("Local service is closing")
        if scope != self._controls.scope:
            raise ValidationError("Local service wakeup Scope mismatch")
        self._controls.verify()
        if run_id in self._active or (await self._controls.status(run_id)).state not in {
            "queued",
            "running",
        }:
            return
        task = asyncio.create_task(self._engine.drive(run_id))
        self._active[run_id] = task

        def finished(value):
            if self._active.get(run_id) is value:
                self._active.pop(run_id)
            if not value.cancelled():
                error = value.exception()
                if error is not None:
                    self._errors.append(
                        {
                            "run_id": run_id,
                            "code": error.code if isinstance(error, RalfError) else "drive_failed",
                        }
                    )

        task.add_done_callback(finished)

    async def _close(self):
        if not self._engine_closed:
            active = tuple(self._active.items())
            for run_id, _ in active:
                await self._controls.cancel(
                    run_id, command_id=f"a2a-host-stop:{self._stop_nonce}:{run_id}"
                )
            # Cancellation requests do not prove real provider/tool calls ended.
            await asyncio.gather(*(task for _, task in active), return_exceptions=True)
            _complete_sync_none(await self._engine.wait_for_threads(), "Engine thread drain")
            close_engine(self._engine)
            self._engine_closed = True
        if not self._inbox_closed:
            operation = (
                self._inbox.aclose
                if is_async_callable(getattr(self._inbox, "aclose", None))
                else self._inbox.close
            )
            value = await operation() if is_async_callable(operation) else operation()
            _complete_sync_none(await _completed(value, "Inbox close"), "Inbox close")
            self._inbox_closed = True
        self._closed = True

    async def aclose(self):
        self._check_loop()
        if asyncio.current_task() is self._close_task:
            raise ValidationError("Local service close cannot reenter itself")
        if self._closed:
            return
        self._closing = True
        if self._close_task is None or self._close_task.done():
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def __call__(self, scope, receive, send):
        self._check_loop()
        if scope["type"] == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    try:
                        await self.aclose()
                    except Exception:
                        await send(
                            {"type": "lifespan.shutdown.failed", "message": "Resource close failed"}
                        )
                    else:
                        await send({"type": "lifespan.shutdown.complete"})
                    return
        elif self._closing and scope["type"] == "http":
            await self.application._reply(send, 503, {"error": "service_closing"})
        else:
            await self.application(scope, receive, send)
