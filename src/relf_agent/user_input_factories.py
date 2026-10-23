"""Bounded input declarations; factories compose into the existing tool registry."""

from .errors import ValidationError
from .tools import ToolRegistry


def _name(value, label, maximum):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{label} requires a bounded stable name")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValidationError(f"{label} requires valid UTF-8") from None


def _configured(config):
    from .user_input import UserInputPolicy

    if type(config) is not dict or set(config) - {"policies", "tools"} or "policies" not in config:
        raise ValidationError("User input config requires policies and optional tools")
    declarations, tools = config["policies"], config.get("tools", {})
    if type(declarations) is not dict or not 1 <= len(declarations) <= 32:
        raise ValidationError("Register 1 to 32 named user input policies")
    if type(tools) is not dict or len(tools) > 32:
        raise ValidationError("Configure at most 32 user input tools")
    policies = {}
    for name, options in declarations.items():
        _name(name, "User input policy", 256)
        if type(options) is not dict or set(options) - {
            "version",
            "reply_schema",
            "max_requests",
            "max_prompt_chars",
            "max_reply_bytes",
        }:
            raise ValidationError("Unknown user input policy options")
        policies[name] = UserInputPolicy(**options)
    for name, selection in tools.items():
        _name(name, "User input tool", 128)
        if (
            type(selection) is not dict
            or set(selection) != {"policy"}
            or type(selection["policy"]) is not str
            or selection["policy"] not in policies
        ):
            raise ValidationError("Input tool requires an available named policy")
    return policies, tools


def user_input_config(config):
    _configured(config)


def configured_user_input(config, context):
    from .user_input import register_user_input

    policies, selections = _configured(config)
    if not isinstance(context.tools, ToolRegistry):
        raise ValidationError("User input tools require the existing ToolRegistry")
    staged = ToolRegistry()
    for name, selection in selections.items():
        register_user_input(staged, name=name, policy=policies[selection["policy"]])
    # register_many checks all collisions before publishing any marker. Custom
    # factories stay opaque during pure preflight and retain their tools here.
    context.tools.register_many(
        [(entry.spec, entry.handler, entry.reconciler) for entry in staged._tools.values()]
    )
    return policies


def preflight_user_input(profile):
    declaration = profile.components.get("user_input_policies")
    if declaration is None or declaration["adapter"] != "configured":
        return
    _, selections = _configured(declaration["config"])
    tools = profile.components.get("tools")
    if tools is None:
        return
    # Known source adapters declare tool names. No custom factory is invoked
    # merely to discover names before resource construction.
    config = tools["config"]
    known = set()
    declarations = config.get("tools", []) if tools["adapter"] in {"http-json", "cli-json"} else []
    for item in declarations if type(declarations) is list else []:
        if type(item) is dict:
            name = item.get("name")
            descriptor = item.get("descriptor")
            if name is None and type(descriptor) is dict:
                name = descriptor.get("name")
            if type(name) is str:
                prefix = item.get("prefix", "")
                if type(prefix) is str:
                    known.add(prefix + name)
    if known & selections.keys():
        raise ValidationError("User input tool collides with a declared tool")


def validate_user_input_controls(engine, tools, *, policies_selected=False):
    """Selected Local assemblies require the optional synchronous control port."""
    from .ports import is_sync_callable
    from .user_input import input_tool_policy

    marker_selected = isinstance(tools, ToolRegistry) and any(
        input_tool_policy(entry) is not None for entry in tools._tools.values()
    )
    if (policies_selected or marker_selected) and not is_sync_callable(
        getattr(engine, "send_input", None)
    ):
        raise ValidationError("Selected user input requires synchronous send_input controls")


def register_user_input_factories(registry):
    registry.register(
        "user_input_policies",
        "configured",
        configured_user_input,
        validator=user_input_config,
    )
