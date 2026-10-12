"""Explicit owned Skill catalogs with borrowed native KnowledgeContext assembly."""

from pathlib import Path

from .errors import ValidationError
from .filesystem_skill_documents import FileSkillDocumentCatalog
from .filesystem_skills import FileSystemSkillCatalog
from .retrieval import KnowledgeContext
from .skill_document_factories import _parse as document_options
from .skill_factories import _parse as file_options
from .skill_retrieval import SkillDirectoryRetriever
from .skill_selection import LexicalSkillSelector
from .skills import _bound, _name, _text
from .workspace import _authorize

EXTRA = {"names", "namespace", "limit", "max_chars", "selector"}


def options(config, *, markdown=False):
    if type(config) is not dict:
        raise ValidationError("Skill directory declaration requires ordinary configuration")
    allowed = {
        "root",
        "version",
        "scopes",
        "max_entries",
        "max_bytes",
        "max_skills",
        "paths" if markdown else "manifest",
    } | EXTRA
    if set(config) - allowed:
        raise ValidationError("Unknown Skill directory declaration fields")
    base = {key: value for key, value in config.items() if key not in EXTRA}
    scopes = (document_options if markdown else file_options)(base)
    names = config.get("names")
    if names is not None:
        if type(names) not in (list, tuple) or not 1 <= len(names) <= 1000:
            raise ValidationError("Skill directory names require a bounded allowlist")
        for name in names:
            _name(name)
        if len(set(names)) != len(names):
            raise ValidationError("Skill directory names must be unique")
    _text(config.get("namespace", "skills"), "Skill directory namespace", 128)
    _bound(config.get("limit", 5), 100, "Skill directory selection")
    maximum = config.get("max_chars", 8000)
    if type(maximum) is not int or not 2 <= maximum <= 65536:
        raise ValidationError("Skill directory character allowance requires 2 to 65536")
    selector = config.get("selector", {"adapter": "lexical", "config": {}})
    if (
        type(selector) is not dict
        or set(selector) - {"adapter", "config"}
        or selector.get("adapter") != "lexical"
    ):
        raise ValidationError("Skill directory declares an explicit lexical selector")
    settings = selector.get("config", {})
    if type(settings) is not dict or set(settings) - {"version"}:
        raise ValidationError("Lexical selector declaration requires version only")
    LexicalSkillSelector(**settings)
    return base, scopes, settings


async def build(config, context, *, markdown=False):
    base, scopes, settings = options(config, markdown=markdown)
    _authorize(context.scope, scopes or (context.scope,))
    root = Path(base["root"])
    if not root.is_absolute():
        root = context.base_dir / root
    cls = FileSkillDocumentCatalog if markdown else FileSystemSkillCatalog
    extra = (
        {"paths": base.get("paths", ("SKILL.md",))}
        if markdown
        else {"manifest": base.get("manifest", "skills.json")}
    )
    catalog = context.own(
        cls(
            root,
            version=base["version"],
            scopes=scopes or (context.scope,),
            max_skills=base.get("max_skills", 100),
            max_bytes=base.get("max_bytes", 1048576),
            **extra,
        )
    )
    retriever = SkillDirectoryRetriever(
        catalog,
        version=base["version"],
        names=config.get("names"),
        selector=LexicalSkillSelector(**settings),
        max_entries=base.get("max_entries", 1000),
    )
    return KnowledgeContext(
        retriever,
        namespace=config.get("namespace", "skills"),
        limit=config.get("limit", 5),
        max_chars=config.get("max_chars", 8000),
    )


def register_skill_discovery(registry):
    def file_validate(config):
        options(config)

    def markdown_validate(config):
        options(config, markdown=True)

    async def file_build(config, context):
        return await build(config, context)

    async def markdown_build(config, context):
        return await build(config, context, markdown=True)

    registry.register_async(
        "knowledge", "skills-directory-file", file_build, validator=file_validate
    )
    registry.register_async(
        "knowledge",
        "skills-directory-markdown",
        markdown_build,
        validator=markdown_validate,
    )
