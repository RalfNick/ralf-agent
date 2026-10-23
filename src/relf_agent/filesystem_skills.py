"""Explicit JSON/Markdown skill catalogs pinned to original safe-file revisions."""

import json

from .errors import DefinitionMismatch, RalfError, ValidationError
from .filesystem_workspace import FileSystemWorkspace
from .skills import InMemorySkillCatalog, SkillSpec, _text
from .workspace import DEFAULT_SCOPES, _bound, _configuration, _path


class FileSystemSkillCatalog(InMemorySkillCatalog):
    def __init__(
        self,
        root,
        *,
        version,
        scopes=DEFAULT_SCOPES,
        manifest="skills.json",
        max_skills=100,
        max_bytes=1048576,
    ):
        _text(version, "Skill catalog version", 256)
        permitted = _configuration(version, scopes)
        _bound(max_skills, 1000, "Skill catalog entry")
        _bound(max_bytes, 16777216, "Skill catalog byte")
        _path(manifest)
        self._workspace = FileSystemWorkspace(root, version=version, scopes=permitted)
        try:
            scope = permitted[0]
            raw = self._workspace.read_text(scope, manifest, max_bytes=1048576)
            try:
                value = json.loads(raw["text"])
            except (ValueError, TypeError):
                raise ValidationError("Skill manifest requires ordinary JSON metadata") from None
            if (
                type(value) is not dict
                or set(value) != {"version", "skills"}
                or type(value["version"]) is not str
                or value["version"] != "1"
                or type(value["skills"]) is not list
                or len(value["skills"]) > max_skills
            ):
                raise ValidationError(
                    "Skill manifest requires version1 and bounded explicit entries"
                )
            skills, versions, names = [], [(manifest, raw["version"])], set()
            size = 0
            for entry in value["skills"]:
                if type(entry) is not dict or set(entry) != {
                    "name",
                    "description",
                    "version",
                    "path",
                }:
                    raise ValidationError("Skill manifest requires exact named instruction entries")
                _path(entry["path"])
                # Validate metadata before opening another user file.
                metadata = SkillSpec(
                    entry["name"], entry["description"], "Reference", entry["version"]
                )
                if metadata.name in names:
                    raise ValidationError("Skill manifest names must be unique")
                names.add(metadata.name)
                remaining = 67108864 - size
                if remaining <= 0:
                    raise ValidationError("Skill catalog exceeds its instruction capacity")
                body = self._workspace.read_text(
                    scope, entry["path"], max_bytes=min(max_bytes, remaining)
                )
                size += len(_text(body["text"], "Skill instructions", min(max_bytes, remaining)))
                skills.append(
                    SkillSpec(metadata.name, metadata.description, body["text"], metadata.version)
                )
                versions.append((entry["path"], body["version"]))
            super().__init__(
                skills,
                version=version,
                scopes=permitted,
                max_skills=max_skills,
                max_bytes=max_bytes,
            )
            self._versions = tuple(versions)
            self._identity = {
                **self._identity,
                "kind": "filesystem-skill-catalog",
                "workspace": self._workspace.identity,
                "manifest": {"path": manifest, "version": raw["version"]},
                "files": [{"path": path, "version": revision} for path, revision in versions[1:]],
            }
            with self._workspace._operation(scope):
                self._check(scope)
        except BaseException:
            self._workspace.close()
            raise

    def _check(self, scope):
        try:
            for path, revision in self._versions:
                if self._workspace.stat(scope, path)["version"] != revision:
                    raise DefinitionMismatch(
                        "Original skill catalog manifest or instructions changed"
                    )
        except RalfError:
            raise DefinitionMismatch(
                "Original skill catalog files are unavailable or changed"
            ) from None

    def list(self, scope, *, max_entries=100, offset=0):
        with self._workspace._operation(scope):
            self._check(scope)
            value = super().list(scope, max_entries=max_entries, offset=offset)
            self._check(scope)
            return value

    def get(self, scope, name, *, max_bytes=1048576):
        with self._workspace._operation(scope):
            self._check(scope)
            value = super().get(scope, name, max_bytes=max_bytes)
            self._check(scope)
            return value

    def close(self):
        # Root close refuses active real operations without waiting on the
        # catalog lock; failed close retains its original FD and closing state.
        self._workspace.close()
        if hasattr(self, "_lock"):
            super().close()
