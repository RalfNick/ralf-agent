"""Frozen explicit Skill documents over the original safe-file catalog guard."""

import inspect
from pathlib import Path

from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, RalfError, ValidationError
from .filesystem_skills import FileSystemSkillCatalog
from .filesystem_workspace import FileSystemWorkspace
from .ports import is_sync_callable
from .skill_documents import ParsedSkillDocument, YamlSkillDocumentParser, _adopt_document
from .skills import InMemorySkillCatalog, _name, _plain, _text
from .types import canonical
from .workspace import DEFAULT_SCOPES, _bound, _configuration, _path


def _paths(paths, max_skills):
    if type(paths) not in (list, tuple) or not 1 <= len(paths) <= max_skills:
        raise ValidationError("Skill documents require a bounded explicit path sequence")
    checked = []
    for path in paths:
        parts = _path(path)
        if parts[-1] != "SKILL.md" or path in checked:
            raise ValidationError("Skill document paths must be unique and end in SKILL.md")
        if len(parts) > 1:
            _name(parts[-2])
        checked.append(path)
    return tuple(checked)


def _parser_identity(parser):
    identity = _plain(getattr(parser, "identity", None))
    method = getattr(parser, "parse", None)
    if type(identity) is not dict or not identity or not is_sync_callable(method):
        raise ValidationError("Skill parser requires a synchronous method and plain identity")
    return {"identity": identity, "implementation_digest": executable_digest(method)}


class FileSkillDocumentCatalog(FileSystemSkillCatalog):
    def __init__(
        self,
        root,
        *,
        version,
        paths=("SKILL.md",),
        parser=None,
        scopes=DEFAULT_SCOPES,
        max_skills=100,
        max_bytes=1048576,
    ):
        _text(version, "Skill catalog version", 256)
        permitted = _configuration(version, scopes)
        _bound(max_skills, 1000, "Skill catalog entry")
        _bound(max_bytes, 16777216, "Skill catalog byte")
        paths = _paths(paths, max_skills)
        self._parser = YamlSkillDocumentParser(version=version) if parser is None else parser
        parser_identity = _parser_identity(self._parser)
        self._parser_snapshot = canonical(parser_identity)
        self._workspace = FileSystemWorkspace(root, version=version, scopes=permitted)
        try:
            scope = permitted[0]
            skills, versions, documents, size, instruction_size = [], [], [], 0, 0
            for path in paths:
                remaining = 67108864 - size
                instruction_remaining = 67108864 - instruction_size
                if remaining <= 0 or instruction_remaining <= 0:
                    raise ValidationError("Skill catalog exceeds its raw or instruction capacity")
                raw = self._workspace.read_text(scope, path, max_bytes=min(max_bytes, remaining))
                size += len(_text(raw["text"], "Skill document", min(max_bytes, remaining)))
                parts = _path(path)
                parent = parts[-2] if len(parts) > 1 else Path(self._workspace._root).name
                _name(parent)
                value = self._parser.parse(raw["text"], parent_name=parent)
                if type(value) is not ParsedSkillDocument:
                    if inspect.iscoroutine(value) or inspect.isgenerator(value):
                        value.close()
                    raise ValidationError("Skill parser must complete with ParsedSkillDocument")
                value = _adopt_document(value, min(max_bytes, instruction_remaining))
                if value.skill.name != parent:
                    raise ValidationError("Parsed skill must match its original parent name")
                instruction_size += len(
                    _text(
                        value.skill.instructions,
                        "Parsed Skill instructions",
                        min(max_bytes, instruction_remaining),
                    )
                )
                skills.append(value.skill)
                versions.append((path, raw["version"]))
                documents.append(
                    {"path": path, "version": raw["version"], "metadata": value.metadata}
                )
            InMemorySkillCatalog.__init__(
                self,
                skills,
                version=version,
                scopes=permitted,
                max_skills=max_skills,
                max_bytes=max_bytes,
            )
            self._versions = tuple(versions)
            self._identity = {
                **self._identity,
                "kind": "file-skill-document-catalog",
                "workspace": self._workspace.identity,
                "parser": parser_identity,
                "documents": documents,
            }
            with self._workspace._operation(scope):
                self._check(scope)
        except BaseException:
            self._workspace.close()
            raise

    def _check(self, scope):
        super()._check(scope)
        try:
            current = canonical(_parser_identity(self._parser))
        except RalfError:
            raise DefinitionMismatch("Original Skill parser is unavailable or changed") from None
        if current != self._parser_snapshot:
            raise DefinitionMismatch("Original Skill parser configuration changed")
