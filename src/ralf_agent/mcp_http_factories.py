"""Explicit MCP HTTP discovery through the original async ownership ledger."""

from .errors import ValidationError
from .mcp import MCPToolSource
from .mcp_http import MCPHTTPTransport
from .tool_sources import ToolPolicy, register_tool_source

OPTIONS = frozenset({"headers", "timeout", "max_message_bytes", "max_operation_bytes"})
POLICY_FIELDS = frozenset({"version", "effect", "requires_approval", "cost", "effect_key_argument"})


def _entry(value):
    if (
        type(value) is not dict
        or set(value) - OPTIONS - {"url", "version", "policies", "prefix"}
        or not {"url", "version", "policies"}.issubset(value)
    ):
        raise ValidationError("MCP HTTP declaration requires fixed URL, version and policies")
    prefix = value.get("prefix", "")
    if type(prefix) is not str:
        raise ValidationError("MCP HTTP prefix requires a string")
    selected = value["policies"]
    if (
        type(selected) is not dict
        or not 1 <= len(selected) <= 256
        or any(type(name) is not str or not name.strip() for name in selected)
    ):
        raise ValidationError("MCP HTTP requires one to256 explicitly selected tool policies")
    policies = {}
    for name, fields in selected.items():
        if type(fields) is not dict or set(fields) - POLICY_FIELDS:
            raise ValidationError("MCP HTTP policies require basic declarative fields")
        try:
            policies[name] = ToolPolicy(**fields)
        except TypeError:
            raise ValidationError("MCP HTTP tool policy is incomplete") from None
    options = {field: value[field] for field in OPTIONS if field in value}
    MCPHTTPTransport(value["url"], version=value["version"], **options)
    return policies, prefix, options


def validate(config):
    if (
        type(config) is not dict
        or set(config) != {"servers"}
        or type(config["servers"]) is not list
        or not 1 <= len(config["servers"]) <= 32
    ):
        raise ValidationError("MCP HTTP config requires one to32 explicit servers")
    names = set()
    for value in config["servers"]:
        policies, prefix, _ = _entry(value)
        local = {prefix + name for name in policies}
        if names & local:
            raise ValidationError("MCP HTTP declarations duplicate a local tool name")
        names.update(local)


async def build(config, context):
    from .tools import ToolRegistry

    registry = ToolRegistry()
    for value in config["servers"]:
        policies, prefix, options = _entry(value)
        wire = context.own_async(
            MCPHTTPTransport(value["url"], version=value["version"], **options)
        )
        await register_tool_source(registry, MCPToolSource(wire), policies=policies, prefix=prefix)
    return registry


def register_mcp_http(registry):
    registry.register_async("tools", "mcp-http", build, validator=validate)
