"""Borrowed Provider wrapper; observations never replace model decisions."""

import copy
import inspect
from contextlib import aclosing
from dataclasses import asdict

from .errors import DefinitionMismatch, ValidationError
from .harness import ModelRequest
from .middleware import MiddlewarePipeline, _entry, _identity, observe_after
from .model_protocol import ModelStreamEvent
from .ports import _complete_sync_none, is_async_callable, is_sync_callable
from .types import ModelResponse, canonical


def _response(value):
    if not isinstance(value, ModelResponse):
        raise ValidationError("Middleware Provider requires a completed ModelResponse")
    canonical(asdict(value))
    return copy.deepcopy(value)


class MiddlewareProvider:
    def __init__(self, provider, middleware=(), *, max_bytes=4_000_000):
        self.provider = provider
        self.pipeline = MiddlewarePipeline(middleware, max_bytes=max_bytes)
        self._pinned = canonical(self.identity)

    @property
    def identity(self):
        optional = {}
        for name in ("validate_request", "stream"):
            method = getattr(self.provider, name, None)
            if method is None:
                optional[name] = None
            else:
                predicate = (
                    is_sync_callable
                    if name == "validate_request"
                    else lambda m: inspect.isasyncgenfunction(m) or is_sync_callable(m)
                )
                if not predicate(method):
                    raise ValidationError("Optional Provider method has an invalid mode")
                optional[name] = {
                    "mode": "async_iterator"
                    if inspect.isasyncgenfunction(method)
                    else "synchronous",
                    "entry": _entry(method),
                }
        return {
            "kind": "middleware-provider",
            "version": "1",
            "provider": _identity(self.provider, ("complete",), is_async_callable),
            "optional_methods": optional,
            "pipeline": self.pipeline.identity,
            "entry_points": {
                name: _entry(getattr(self, name))
                for name in ("complete", "_stream", "validate_request", "_prepare", "_verify")
            },
        }

    @property
    def capabilities(self):
        return getattr(self.provider, "capabilities", None)

    @property
    def continuation_identity(self):
        from .model_continuation import provider_continuation_identity

        return provider_continuation_identity(self.provider)

    def _verify(self):
        if canonical(self.identity) != self._pinned:
            raise DefinitionMismatch("Middleware Provider registration changed")

    def validate_request(self, messages, tools):
        self._verify()
        request = ModelRequest(messages, tools)
        method = getattr(self.provider, "validate_request", None)
        if method is not None:
            if not is_sync_callable(method):
                raise ValidationError("Provider preflight must be synchronous")
            _complete_sync_none(method(request.messages, request.tools), "Provider preflight")
        self._verify()

    def _prepare(self, messages, tools):
        self.validate_request(messages, tools)
        request = ModelRequest(messages, tools)
        self.pipeline.before("model", asdict(request))
        self._verify()
        return request

    async def complete(self, messages, tools):
        request = self._prepare(messages, tools)
        value = _response(await self.provider.complete(request.messages, request.tools))
        observe_after(self.pipeline, "model", {"response": asdict(value)})
        return value

    @property
    def stream(self):
        if not callable(getattr(self.provider, "stream", None)):
            raise AttributeError("Underlying Provider has no stream port")
        return self._stream

    async def _stream(self, messages, tools):
        request = self._prepare(messages, tools)
        stream = self.provider.stream(request.messages, request.tools)
        if not callable(getattr(stream, "aclose", None)):
            raise ValidationError("Middleware streaming requires a closable iterator")
        complete, size = None, 0
        async with aclosing(stream):
            async for event in stream:
                if not isinstance(event, ModelStreamEvent) or complete is not None:
                    raise ValidationError("Malformed or extra complete stream event")
                size += len(canonical(asdict(event)).encode("utf-8"))
                if size > 4_000_000:
                    raise ValidationError("Middleware stream exceeds bound")
                if event.kind == "response":
                    complete = _response(event.response)
                else:
                    yield copy.deepcopy(event)
        if complete is None:
            raise ValidationError("Middleware stream requires a complete response")
        observe_after(self.pipeline, "model", {"response": asdict(complete)})
        yield ModelStreamEvent("response", response=complete)
