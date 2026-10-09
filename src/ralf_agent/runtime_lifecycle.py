"""Owned client lifetime, separate from local execution authority and factories."""

import asyncio
from dataclasses import dataclass
from functools import wraps
from pathlib import Path

from .errors import ValidationError
from .ports import _complete_sync_none, _invoke_sync_none, is_async_callable, is_sync_callable


@dataclass
class _OwnedResource:
    resource: object
    asynchronous: bool
    task: asyncio.Task | None = None


def _observe(task):
    if not task.cancelled():
        task.exception()


async def _close_async(method):
    _complete_sync_none(await method(), "Resource aclose")


class BuildContext:
    def __init__(self, store, db_path, scope, base_dir, *, allow_async=False):
        self.store, self.db_path, self.scope = store, str(db_path), scope
        self.base_dir = Path(base_dir).resolve()
        self.tools = None
        self._resources = []
        self._allow_async = allow_async
        self._loop = None

    def own(self, resource):
        if resource is self.store:
            return resource
        return self._own(resource, asynchronous=False)

    def own_async(self, resource):
        if not self._allow_async:
            raise ValidationError("Async resources require RuntimeBuilder.abuild")
        if resource is self.store:
            raise ValidationError("Execution authority remains synchronously owned by the Engine")
        return self._own(resource, asynchronous=True)

    def _own(self, resource, *, asynchronous):
        method = getattr(resource, "aclose" if asynchronous else "close", None)
        if not (is_async_callable(method) if asynchronous else is_sync_callable(method)):
            raise ValidationError(
                "Owned async resources require async aclose"
                if asynchronous
                else "Owned resources require synchronous close"
            )
        for owned in self._resources:
            if owned.resource is resource:
                if owned.asynchronous != asynchronous:
                    raise ValidationError("An owned resource cannot change its close mode")
                return resource
        if asynchronous:
            loop = asyncio.get_running_loop()
            if self._loop is not None and self._loop is not loop:
                raise ValidationError("Async resources must share their creation loop")
            self._loop = loop
        self._resources.append(_OwnedResource(resource, asynchronous))
        return resource

    def path(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Resource path must be a non-empty string")
        path = Path(value)
        return str((path if path.is_absolute() else self.base_dir / path).resolve())

    @property
    def has_async_resources(self):
        return any(owned.asynchronous for owned in self._resources)

    def _check_loop(self):
        if self.has_async_resources and asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Async cleanup must use the resource creation loop")

    def _require_sync_cleanup(self):
        if self.has_async_resources:
            raise ValidationError("Async resources require await runtime.aclose() or async with")

    def _check_cleanup_origin(self):
        current = asyncio.current_task()
        if any(owned.task is current for owned in self._resources):
            raise ValidationError("Resource cleanup cannot reenter its owning runtime cleanup")

    def cleanup(self):
        self._require_sync_cleanup()
        while self._resources:
            owned = self._resources[-1]
            _invoke_sync_none(getattr(owned.resource, "close", None), "Resource close")
            self._resources.pop()

    async def cleanup_async(self):
        self._check_loop()
        self._check_cleanup_origin()
        while self._resources:
            owned = self._resources[-1]
            if not owned.asynchronous:
                _invoke_sync_none(getattr(owned.resource, "close", None), "Resource close")
            else:
                if owned.task is None:
                    method = getattr(owned.resource, "aclose", None)
                    if not is_async_callable(method):
                        raise ValidationError("Owned resources require async aclose")
                    owned.task = asyncio.create_task(_close_async(method))
                    owned.task.add_done_callback(_observe)
                try:
                    await asyncio.shield(owned.task)
                except asyncio.CancelledError:
                    if owned.task.cancelled():
                        owned.task = None
                    raise
                except BaseException:
                    owned.task = None
                    raise
            self._resources.pop()


_GUARDED_METHODS = {
    "submit",
    "drive",
    "status",
    "events",
    "approve",
    "cancel",
    "reconcile",
    "diagnostics",
}


class RuntimeInstance:
    """Close execution first; cleanup failures leave a retriable, stopped instance."""

    def __init__(self, engine, context, *, drain_engine=True):
        self._engine, self._context = engine, context
        self._drain_engine = drain_engine
        self._engine_closed = False
        self._async_shutdown = False
        self._aclosing = False

    def _ensure_open(self):
        if self._engine_closed or self._async_shutdown:
            raise ValidationError("Runtime is closing or closed; retry resource cleanup only")

    def __getattr__(self, name):
        self._ensure_open()
        value = getattr(self._engine, name)
        if name not in _GUARDED_METHODS or not callable(value):
            return value
        if is_async_callable(value):

            @wraps(value)
            async def operation(*args, **kwargs):
                self._ensure_open()
                self._context._check_loop()
                return await value(*args, **kwargs)
        else:

            @wraps(value)
            def operation(*args, **kwargs):
                self._ensure_open()
                return value(*args, **kwargs)

        return operation

    def __enter__(self):
        self._ensure_open()
        self._context._require_sync_cleanup()
        return self

    def __exit__(self, *args):
        self.close()

    async def __aenter__(self):
        self._ensure_open()
        self._context._check_loop()
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    def _close_engine(self):
        if not self._engine_closed:
            owner = self._engine if self._engine is not None else self._context.store
            _invoke_sync_none(getattr(owner, "close", None), "Engine close")
            self._engine_closed = True

    def close(self):
        if self._aclosing or (self._async_shutdown and not self._engine_closed):
            raise ValidationError("Async shutdown is in progress; retry await runtime.aclose()")
        self._context._require_sync_cleanup()
        self._close_engine()
        self._context.cleanup()

    async def aclose(self):
        self._context._check_cleanup_origin()
        if self._aclosing:
            raise ValidationError("Runtime is already closing")
        if self._engine_closed and not self._context._resources:
            return
        self._context._check_loop()
        self._aclosing = True
        self._async_shutdown = True
        try:
            if self._drain_engine and self._engine is not None and not self._engine_closed:
                wait = getattr(self._engine, "wait_for_threads", None)
                if not is_async_callable(wait):
                    raise ValidationError("Engine wait_for_threads must be async")
                _complete_sync_none(await wait(), "Engine wait_for_threads")
            self._close_engine()
            await self._context.cleanup_async()
        finally:
            self._aclosing = False

    async def wait_for_threads(self):
        if self._engine is not None and not self._engine_closed:
            self._context._check_loop()
            _complete_sync_none(await self._engine.wait_for_threads(), "Engine wait_for_threads")
