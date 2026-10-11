"""Explicit JSON CLI declarations in the original async construction ledger."""

from .cli_tools import CLIToolSource
from .errors import ValidationError
from .tool_sources import ToolDescriptor, ToolPolicy, _caller_schema, register_tool_source
from .tools import ToolRegistry, ToolSpec

SOURCE_FIELDS = frozenset({"cwd", "env", "timeout", "max_input_bytes", "max_output_bytes"})
POLICY_FIELDS = frozenset({"version", "effect", "requires_approval", "cost", "effect_key_argument"})


def _entry(value):
    if (
        type(value) is not dict
        or set(value) - SOURCE_FIELDS - {"descriptor", "command", "version", "policy", "prefix"}
        or not {"descriptor", "command", "version", "policy"}.issubset(value)
    ):
        raise ValidationError("CLI declaration requires descriptor, command, version and policy")
    if (
        type(value["descriptor"]) is not dict
        or type(value["policy"]) is not dict
        or set(value["policy"]) - POLICY_FIELDS
    ):
        raise ValidationError(
            "CLI declarations require explicit descriptor and basic policy fields"
        )
    prefix = value.get("prefix", "")
    if type(prefix) is not str:
        raise ValidationError("CLI tool prefix must be a string")
    try:
        descriptor = ToolDescriptor(**value["descriptor"])
        policy = ToolPolicy(**value["policy"])
    except (TypeError, KeyError):
        raise ValidationError("CLI descriptor or policy fields are incomplete") from None
    options = {field: value[field] for field in SOURCE_FIELDS if field in value}
    CLIToolSource(descriptor, value["command"], version=value["version"], **options)
    # Preserve the existing flat-Schema reserved effect-key contract in preflight.
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
        raise ValidationError("CLI tools config requires one to256 explicit declarations")
    names = set()
    for value in config["tools"]:
        descriptor, _, prefix, _ = _entry(value)
        name = prefix + descriptor.name
        if name in names:
            raise ValidationError("CLI declarations duplicate a local tool name")
        names.add(name)


async def build(config, context):
    registry = ToolRegistry()
    for value in config["tools"]:
        descriptor, policy, prefix, options = _entry(value)
        options["cwd"] = context.path(options["cwd"]) if "cwd" in options else str(context.base_dir)
        source = context.own_async(
            CLIToolSource(descriptor, value["command"], version=value["version"], **options)
        )
        await register_tool_source(
            registry, source, policies={descriptor.name: policy}, prefix=prefix
        )
    return registry


def register_cli_tools(registry):
    registry.register_async("tools", "cli-json", build, validator=validate)
