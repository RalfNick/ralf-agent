"""Synchronous observation pipelines preserve known response/effect receipts."""

import asyncio
import copy
import inspect
import logging

from .component_fingerprint import _code
from .errors import DefinitionMismatch, ValidationError
from .invocation_records import InvocationRecord
from .ports import _complete_sync_none, is_sync_callable
from .types import canonical, digest

_LOG = logging.getLogger("relf_agent.middleware")


def _diagnostic(operation, code):
    try:
        _LOG.error("Invocation observer failed phase=after operation=%s code=%s", operation, code)
    except (Exception, asyncio.CancelledError):
        # A broken diagnostic sink must not turn an observed result into an
        # unknown external effect. This path contains no user values or errors.
        pass


def observe_after(pipeline, operation, payload):
    """Preserve a known receipt even if the dispatcher's registration drifts."""
    try:
        pipeline.after(operation, payload)
    except (Exception, asyncio.CancelledError):
        _diagnostic(operation, "observer_dispatch_error")


def _entry(method):
    target = getattr(method, "__func__", method)
    if not inspect.isfunction(target):
        raise ValidationError("Middleware delegates/hooks require Python entry points")
    return {
        "module": target.__module__,
        "name": target.__qualname__,
        "code": digest(_code(target.__code__)),
    }


def _identity(component, methods, predicate):
    value = getattr(component, "identity", None)
    if not isinstance(value, dict) or not value:
        raise ValidationError("Middleware components require explicit JSON identity")
    canonical(value)
    if any(not predicate(getattr(component, name, None)) for name in methods):
        raise ValidationError("Middleware component has an unsupported method mode")
    return {
        "configuration": copy.deepcopy(value),
        "entry_points": {name: _entry(getattr(component, name)) for name in methods},
    }


class NoopMiddleware:
    identity = {"kind": "noop-middleware", "version": "1"}

    def before(self, record):
        return None

    def after(self, record):
        return None


class LoggingMiddleware(NoopMiddleware):
    identity = {"kind": "logging-middleware", "version": "1"}

    def before(self, record):
        _LOG.info(
            "Invocation phase=%s operation=%s payload_sha256=%s",
            record.phase,
            record.operation,
            record.payload_digest,
        )

    def after(self, record):
        _LOG.info(
            "Invocation phase=%s operation=%s payload_sha256=%s",
            record.phase,
            record.operation,
            record.payload_digest,
        )


class MiddlewarePipeline:
    def __init__(self, middleware=(), *, max_bytes=4_000_000):
        if not isinstance(middleware, (tuple, list)) or len(middleware) > 16:
            raise ValidationError("Middleware must be a bounded list or tuple")
        if type(max_bytes) is not int or not 256 <= max_bytes <= 4_000_000:
            raise ValidationError("Middleware payload bound must be from256 to4000000bytes")
        self.middleware, self.max_bytes = tuple(middleware), max_bytes
        self._pinned = canonical(self.identity)

    @property
    def identity(self):
        return {
            "kind": "invocation-middleware-pipeline",
            "version": "1",
            "max_bytes": self.max_bytes,
            "entry_points": {
                name: _entry(getattr(self, name)) for name in ("before", "after", "verify")
            },
            "middleware": [
                _identity(h, ("before", "after"), is_sync_callable) for h in self.middleware
            ],
        }

    def verify(self):
        if canonical(self.identity) != self._pinned:
            raise DefinitionMismatch("Middleware registration changed")

    def before(self, operation, payload):
        self.verify()
        record = InvocationRecord(operation, "before", payload, max_bytes=self.max_bytes)
        for hook in self.middleware:
            _complete_sync_none(hook.before(record), "Middleware.before")
            self.verify()

    def after(self, operation, payload):
        try:
            record = InvocationRecord(operation, "after", payload, max_bytes=self.max_bytes)
        except Exception:
            _diagnostic(operation, "invalid_observation")
            return
        for hook in reversed(self.middleware):
            try:
                self.verify()
                _complete_sync_none(hook.after(record), "Middleware.after")
            except (Exception, asyncio.CancelledError):
                # Receipt preservation is mandatory. Never log user exception
                # text, traceback, hook metadata or raw observed business values.
                _diagnostic(operation, "observer_error")
