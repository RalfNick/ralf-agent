"""Temporal-only actual Tool owner with original assembly resource ownership."""

from .errors import ValidationError
from .tool_execution import ToolExecutionOwner


def register_tool_execution(registry):
    def validate(config):
        if type(config) is not dict or set(config) - {"version", "max_calls"}:
            raise ValidationError("Tracked Tool execution requires declared version/capacity")
        if "version" not in config:
            raise ValidationError("Tracked Tool execution requires its behavior version")
        ToolExecutionOwner(**config)

    async def build(config, context):
        return context.own_async(ToolExecutionOwner(**config))

    registry.register_async("tool_execution", "tracked", build, validator=validate)
