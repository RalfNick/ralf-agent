"""Pure explicit catalog declarations and original owned read-tool assembly."""

from pathlib import Path

from .errors import ValidationError
from .filesystem_skills import FileSystemSkillCatalog
from .skill_tools import SkillToolSource
from .skills import _text
from .tool_sources import ToolPolicy, register_tool_source
from .tools import ToolRegistry
from .workspace import _authorize, _bound, _path
from .workspace_factories import _options


def _parse(config):
    if type(config) is not dict:
        raise ValidationError("Skill declaration requires an ordinary configuration object")
    _text(config.get("version"), "Skill catalog version", 256)
    scopes = _options(
        {key: value for key, value in config.items() if key not in {"manifest", "max_skills"}}
    )
    _path(config.get("manifest", "skills.json"))
    _bound(config.get("max_skills", 100), 1000, "Skill catalog entry")
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
        FileSystemSkillCatalog(
            root,
            version=config["version"],
            scopes=scopes or (context.scope,),
            manifest=config.get("manifest", "skills.json"),
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


def register_skill_tools(registry):
    from .skill_document_factories import build as document_build
    from .skill_document_factories import validate as document_validate

    registry.register_async("tools", "skills-file", build, validator=validate)
    registry.register_async("tools", "skills-markdown", document_build, validator=document_validate)
    registry.register("skills", "registered-tools", binding, validator=validate_binding)


def validate_binding(config):
    from .binding_workspace import _names

    if type(config) is not dict or set(config) != {"names"}:
        raise ValidationError("Skills binding declaration requires existing tool names")
    _names(config["names"])


def binding(config, context):
    from .binding_skills import SkillBindingResource

    validate_binding(config)
    return SkillBindingResource(context.tools, names=config["names"])
