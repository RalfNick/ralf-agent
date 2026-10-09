"""Explicit profile defaults; custom observers use registered host factories."""

from .errors import ValidationError
from .executors import PythonToolExecutor
from .middleware import LoggingMiddleware, MiddlewarePipeline
from .middleware_models import MiddlewareProvider
from .middleware_tools import MiddlewareToolExecutor
from .ports import is_sync_callable
from .runtime_config import component_declaration


def _options(config, *, provider=False):
    allowed = {"logging", "max_bytes"} | ({"provider"} if provider else set())
    if set(config) - allowed or type(config.get("logging", False)) is not bool:
        raise ValidationError("Invalid middleware adapter fields")
    MiddlewarePipeline(max_bytes=config.get("max_bytes", 4_000_000))
    return {
        "middleware": [LoggingMiddleware()] if config.get("logging", False) else [],
        "max_bytes": config.get("max_bytes", 4_000_000),
    }


def register_middleware_factories(registry):
    from .runtime_builder import _completed

    def nested(config):
        _options(config, provider=True)
        declaration = component_declaration(config.get("provider"))
        if declaration["adapter"] == "middleware":
            raise ValidationError("Nested middleware adapters are not supported")
        factory, prepared = registry.prepare("provider", declaration)
        if not is_sync_callable(factory):
            raise ValidationError("Wrap async Provider factories explicitly with abuild")
        return factory, prepared

    def validate_provider(config):
        nested(config)

    def provider(config, context):
        factory, prepared = nested(config)
        delegate = _completed(factory(prepared, context), "Nested middleware Provider factory")
        return MiddlewareProvider(delegate, **_options(config, provider=True))

    def validate_executor(config):
        _options(config)

    def executor(config, context):
        return MiddlewareToolExecutor(PythonToolExecutor(context.tools), **_options(config))

    registry.register("provider", "middleware", provider, validator=validate_provider)
    registry.register("tool_executor", "middleware-python", executor, validator=validate_executor)
