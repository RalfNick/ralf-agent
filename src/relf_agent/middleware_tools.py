"""Borrowed ToolExecutor wrapper, forwarding the original approved envelope."""

from dataclasses import asdict

from .errors import DefinitionMismatch, ValidationError
from .executors import DispatchEnvelope, EffectObservation
from .middleware import MiddlewarePipeline, _entry, _identity, observe_after
from .ports import is_async_callable
from .types import canonical


def _envelope(value):
    if not isinstance(value, DispatchEnvelope):
        raise ValidationError("Middleware ToolExecutor requires a DispatchEnvelope")
    return {
        "context": asdict(value.context),
        "tool_manifest": value.tool_manifest,
        "arguments": value.arguments,
        "operation_digest": value.operation_digest,
    }


class MiddlewareToolExecutor:
    def __init__(self, executor, middleware=(), *, max_bytes=4_000_000):
        self.executor = executor
        self.pipeline = MiddlewarePipeline(middleware, max_bytes=max_bytes)
        self._pinned = canonical(self.identity)

    @property
    def identity(self):
        return {
            "kind": "middleware-tool-executor",
            "version": "1",
            "executor": _identity(self.executor, ("execute", "reconcile"), is_async_callable),
            "pipeline": self.pipeline.identity,
            "entry_points": {
                name: _entry(getattr(self, name))
                for name in ("execute", "reconcile", "_call", "_verify")
            },
        }

    def _verify(self):
        if canonical(self.identity) != self._pinned:
            raise DefinitionMismatch("Middleware ToolExecutor registration changed")

    async def _call(self, operation, envelope):
        self._verify()
        payload = _envelope(envelope)
        self.pipeline.before(operation, {"envelope": payload})
        self._verify()
        method = self.executor.execute if operation == "tool" else self.executor.reconcile
        value = await method(envelope)
        if (value is None and operation != "reconcile") or (
            value is not None and not isinstance(value, EffectObservation)
        ):
            raise ValidationError("Middleware executor requires a completed observation")
        observation = None if value is None else EffectObservation(value.result, value.source)
        observe_after(
            self.pipeline,
            operation,
            {
                "envelope": payload,
                "observation": None
                if observation is None
                else {"result": observation.result, "source": observation.source},
            },
        )
        return observation

    async def execute(self, envelope):
        return await self._call("tool", envelope)

    async def reconcile(self, envelope):
        return await self._call("reconcile", envelope)
