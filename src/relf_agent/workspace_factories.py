"""Pure Workspace read declarations through original async resource assembly."""

from pathlib import Path

from .binding_workspace import WorkspaceBindingResource, _names
from .errors import ValidationError
from .filesystem_workspace import FileSystemWorkspace, _root_text
from .tool_sources import ToolPolicy, register_tool_source
from .tools import ToolRegistry
from .types import Scope, credits
from .workspace import _authorize, _bound, _configuration, _utf8
from .workspace_tools import WorkspaceToolSource


def _options(config):
    if (
        type(config) is not dict
        or set(config)
        - {
            "root",
            "version",
            "scopes",
            "max_entries",
            "max_bytes",
            "prefix",
            "requires_approval",
            "cost",
        }
        or not {"root", "version"}.issubset(config)
    ):
        raise ValidationError("Workspace declaration requires fixed root and version")
    if type(config["root"]) is not str:
        raise ValidationError("Workspace declaration root requires a string")
    _root_text(config["root"])
    scopes = None
    if "scopes" in config:
        values = config["scopes"]
        if (
            type(values) is not list
            or not 1 <= len(values) <= 256
            or any(
                type(item) is not dict
                or set(item) != {"workspace", "principal"}
                or any(type(value) is not str for value in item.values())
                for item in values
            )
        ):
            raise ValidationError("Workspace declaration requires explicit Scope objects")
        scopes = _configuration(config["version"], [Scope(**item) for item in values])
    else:
        _configuration(config["version"], [Scope()])
    _bound(config.get("max_entries", 100), 1000, "entry")
    _bound(config.get("max_bytes", 1048576), 16777216, "byte")
    _utf8(config.get("prefix", ""), "Workspace prefix")
    if type(config.get("requires_approval", False)) is not bool:
        raise ValidationError("Workspace approval option requires a boolean")
    credits(config.get("cost", 1))
    return scopes


def validate(config):
    _options(config)


async def build(config, context):
    scopes = _options(config)
    _authorize(context.scope, scopes or (context.scope,))
    root = Path(config["root"])
    if not root.is_absolute():
        root = context.base_dir / root
    port = context.own(
        FileSystemWorkspace(root, version=config["version"], scopes=scopes or (context.scope,))
    )
    source = context.own_async(
        WorkspaceToolSource(
            port,
            version=config["version"],
            max_entries=config.get("max_entries", 100),
            max_bytes=config.get("max_bytes", 1048576),
        )
    )
    registry = ToolRegistry()
    policies = {
        name: ToolPolicy(
            config["version"],
            effect="read_only",
            requires_approval=config.get("requires_approval", False),
            cost=config.get("cost", 1),
        )
        for name in ("workspace_stat", "workspace_list", "workspace_read_text")
    }
    await register_tool_source(registry, source, policies=policies, prefix=config.get("prefix", ""))
    return registry


def register_workspace_tools(registry):
    from .workspace_write_factories import build as write_build
    from .workspace_write_factories import validate as write_validate

    registry.register_async("tools", "workspace-read", build, validator=validate)
    registry.register_async("tools", "workspace-read-write", write_build, validator=write_validate)
    registry.register("workspace", "registered-tools", binding, validator=validate_binding)


def validate_binding(config):
    if type(config) is not dict or set(config) != {"names"}:
        raise ValidationError("Workspace binding declaration requires existing tool names")
    _names(config["names"])


def binding(config, context):
    validate_binding(config)
    return WorkspaceBindingResource(context.tools, names=config["names"])
