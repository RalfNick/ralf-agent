"""Pure default write declarations and original owned Source/port assembly."""

from pathlib import Path

from .filesystem_workspace_writes import FileSystemWritableWorkspace
from .tool_sources import ToolPolicy, register_tool_source
from .tools import ToolRegistry
from .workspace import _authorize, _bound
from .workspace_factories import _options
from .workspace_write_tools import WritableWorkspaceToolSource


def validate(config):
    scopes = _options({k: v for k, v in config.items() if k != "capacity"})
    _bound(config.get("capacity", 1024), 100000, "write receipt capacity")
    return scopes


async def build(config, context):
    scopes = validate(config)
    _authorize(context.scope, scopes or (context.scope,))
    root = Path(config["root"])
    if not root.is_absolute():
        root = context.base_dir / root
    port = context.own(
        FileSystemWritableWorkspace(
            root,
            version=config["version"],
            scopes=scopes or (context.scope,),
            max_bytes=config.get("max_bytes", 1048576),
            capacity=config.get("capacity", 1024),
        )
    )
    source = context.own_async(
        WritableWorkspaceToolSource(
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
    policies["workspace_write_text"] = ToolPolicy(
        config["version"],
        effect="idempotent_write",
        effect_key_argument="effect_key",
        requires_approval=True,
        cost=config.get("cost", 1),
        reconciler=source.reconcile,
    )
    await register_tool_source(registry, source, policies=policies, prefix=config.get("prefix", ""))
    return registry
