"""Replaceable actual Tool call ownership; business authority stays in Engine."""

from typing import Protocol

from .errors import ValidationError
from .temporal_context_execution import ContextExecutionOwner, ContextExecutionRejected
from .workspace import _utf8


class ToolExecutionPort(Protocol):
    identity: dict

    async def execute(self, operation, *, proof, on_end=None): ...

    async def wait(self, *, wait_timeout=30) -> bool: ...

    async def aclose(self, *, wait_timeout=30) -> None: ...


class ToolExecutionOwner:
    def __init__(self, *, version, max_calls=8):
        data = _utf8(version, "Tool execution version", max_bytes=256)
        if not version.strip() or b"\x00" in data:
            raise ValidationError("Tool execution requires a nonblank behavior version")
        self._version = version
        self._execution = ContextExecutionOwner(max_calls=max_calls)
        self._closing = False

    @property
    def identity(self):
        return {
            "kind": "tool-execution-owner",
            "version": "1",
            "behavior_version": self._version,
            "max_calls": self._execution.max_calls,
        }

    async def execute(self, operation, *, proof, on_end=None):
        if self._closing:
            raise ContextExecutionRejected(handler_not_started=True)
        return await self._execution.execute(operation, proof=proof, on_end=on_end)

    async def wait(self, *, wait_timeout=30):
        return await self._execution.wait(wait_timeout=wait_timeout)

    async def aclose(self, *, wait_timeout=30):
        self._closing = True
        await self._execution.aclose(wait_timeout=wait_timeout)
