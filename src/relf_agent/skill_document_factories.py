"""Opt-in standard Skill documents through the existing owned tool assembly."""

from pathlib import Path

from .errors import ValidationError
from .filesystem_skill_documents import FileSkillDocumentCatalog, _paths
from .skill_tools import SkillToolSource
from .skills import _text
from .tool_sources import ToolPolicy, register_tool_source
from .tools import ToolRegistry
from .workspace import _authorize, _bound
from .workspace_factories import _options


def _parse(config):
    if type(config) is not dict:
        raise ValidationError("Skill declaration requires an ordinary configuration object")
    _text(config.get("version"), "Skill catalog version", 256)
    scopes = _options(
        {key: value for key, value in config.items() if key not in {"paths", "max_skills"}}
    )
    maximum = config.get("max_skills", 100)
    _bound(maximum, 1000, "Skill catalog entry")
    _paths(config.get("paths", ("SKILL.md",)), maximum)
    return scopes


def validate(config):
    _parse(config)


async def build(config, context):
    scopes = _parse(config)
    _authorize(context.scope, scopes or (context.scope,))
    root = Path(config["root"])
    if not root.is_absolute():
        root = context.base_dir / root
    catalog = context.own(
        FileSkillDocumentCatalog(
            root,
            version=config["version"],
            paths=config.get("paths", ("SKILL.md",)),
            scopes=scopes or (context.scope,),
            max_skills=config.get("max_skills", 100),
            max_bytes=config.get("max_bytes", 1048576),
        )
    )
    source = context.own_async(
        SkillToolSource(
            catalog,
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
        for name in ("skill_list", "skill_get")
    }
    await register_tool_source(registry, source, policies=policies, prefix=config.get("prefix", ""))
    return registry
