"""Fixed HTTP JSON declarations through the original async ownership ledger."""

from .errors import ValidationError
from .http_tools import HTTPToolSource
from .tool_sources import ToolDescriptor, ToolPolicy, _caller_schema, register_tool_source
from .tools import ToolRegistry, ToolSpec

SOURCE_FIELDS = frozenset({"headers", "timeout", "max_input_bytes", "max_output_bytes"})
POLICY_FIELDS = frozenset({"version", "effect", "requires_approval", "cost", "effect_key_argument"})


def _entry(value):
    if (
        type(value) is not dict
        or set(value) - SOURCE_FIELDS - {"descriptor", "url", "version", "policy", "prefix"}
        or not {"descriptor", "url", "version", "policy"}.issubset(value)
    ):
        raise ValidationError("HTTP declaration requires descriptor, url, version and policy")
    if (
        type(value["descriptor"]) is not dict
        or type(value["policy"]) is not dict
        or set(value["policy"]) - POLICY_FIELDS
    ):
        raise ValidationError("HTTP declaration requires explicit descriptor and policy fields")
    prefix = value.get("prefix", "")
    if type(prefix) is not str:
        raise ValidationError("HTTP tool prefix must be a string")
    try:
        descriptor, policy = ToolDescriptor(**value["descriptor"]), ToolPolicy(**value["policy"])
    except (TypeError, KeyError):
        raise ValidationError("HTTP descriptor or policy fields are incomplete") from None
    options = {field: value[field] for field in SOURCE_FIELDS if field in value}
    HTTPToolSource(descriptor, value["url"], version=value["version"], **options)
    ToolSpec(
        prefix + descriptor.name,
        descriptor.description,
        _caller_schema(descriptor, policy),
        policy.version,
        policy.effect,
        policy.requires_approval,
        policy.cost,
    )
    return descriptor, policy, prefix, options


def validate(config):
    if (
        type(config) is not dict
        or set(config) != {"tools"}
        or type(config["tools"]) is not list
        or not 1 <= len(config["tools"]) <= 256
    ):
        raise ValidationError("HTTP tools config requires one to256 explicit declarations")
    names = set()
    for value in config["tools"]:
        descriptor, _, prefix, _ = _entry(value)
        name = prefix + descriptor.name
        if name in names:
            raise ValidationError("HTTP declarations duplicate a local tool name")
        names.add(name)


async def build(config, context):
    registry = ToolRegistry()
    for value in config["tools"]:
        descriptor, policy, prefix, options = _entry(value)
        source = context.own_async(
            HTTPToolSource(descriptor, value["url"], version=value["version"], **options)
        )
        await register_tool_source(
            registry, source, policies={descriptor.name: policy}, prefix=prefix
        )
    return registry


def register_http_tools(registry):
    registry.register_async("tools", "http-json", build, validator=validate)
