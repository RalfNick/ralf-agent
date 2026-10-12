"""Immutable reference instructions and replaceable, scoped catalog snapshots."""

import copy
import hashlib
import math
import re
import threading
from dataclasses import dataclass
from typing import Protocol

from .errors import RalfError, ValidationError
from .types import Scope, canonical, digest
from .workspace import DEFAULT_SCOPES, _authorize, _bound, _configuration, _scopes_json, _utf8

_NO_OFFSET = object()


class SkillError(RalfError):
    code = "skill_error"


def _plain(value, depth=0, ancestors=None):
    """Detach ordinary finite JSON without invoking custom copying hooks."""
    if depth > 64:
        raise SkillError("Skill data exceeds its nesting allowance")
    kind = type(value)
    if value is None or kind in (bool, int):
        return value
    if kind is str:
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise SkillError("Skill data requires ordinary UTF-8") from None
        return value
    if kind is float and math.isfinite(value):
        return value
    if kind not in (dict, list):
        raise SkillError("Skill data requires ordinary finite JSON types")
    ancestors = set() if ancestors is None else ancestors
    if id(value) in ancestors:
        raise SkillError("Skill data cannot contain a cycle")
    ancestors.add(id(value))
    try:
        if kind is list:
            return [_plain(item, depth + 1, ancestors) for item in value]
        if any(type(key) is not str for key in value):
            raise SkillError("Skill data requires ordinary string keys")
        return {_plain(key): _plain(item, depth + 1, ancestors) for key, item in value.items()}
    finally:
        ancestors.remove(id(value))


def _text(value, label, maximum):
    data = _utf8(value, label, max_bytes=maximum)
    if not value.strip() or b"\x00" in data:
        raise ValidationError(f"{label} requires nonblank ordinary text without NUL")
    return data


def _name(value):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 64
        or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) is None
    ):
        raise ValidationError("Skill name requires a lowercase ASCII slug of at most64 characters")
    return value


def _sha(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SkillError("Skill snapshot requires a plain SHA256 digest")


def _scope(scope):
    _configuration("1", [scope])
    return {"workspace": scope.workspace, "principal": scope.principal}


def _read_bounds(maximum, offset=_NO_OFFSET):
    _bound(maximum, 1000 if offset is not _NO_OFFSET else 16777216, "Skill read")
    if offset is not _NO_OFFSET and (type(offset) is not int or not 0 <= offset <= 1000):
        raise ValidationError("Skill offset requires an integer in [0,1000]")


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    instructions: str
    version: str = "1"

    def __post_init__(self):
        _name(self.name)
        _text(self.description, "Skill description", 4096)
        _text(self.instructions, "Skill instructions", 16777216)
        _text(self.version, "Skill version", 256)

    def to_dict(self):
        data = _text(self.instructions, "Skill instructions", 16777216)
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "version": self.version,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }


def skill_metadata(skill):
    if type(skill) is not SkillSpec:
        raise ValidationError("Skill catalog requires ordinary immutable SkillSpec entries")
    return {key: value for key, value in skill.to_dict().items() if key != "instructions"}


def _metadata(value):
    if type(value) is not dict or set(value) != {
        "name",
        "description",
        "version",
        "sha256",
        "bytes",
    }:
        raise SkillError("Skill snapshot metadata is invalid")
    _name(value["name"])
    _text(value["description"], "Skill description", 4096)
    _text(value["version"], "Skill version", 256)
    _sha(value["sha256"])
    if type(value["bytes"]) is not int or not 1 <= value["bytes"] <= 16777216:
        raise SkillError("Skill instruction size is invalid")


def _envelope(value, kind, scope, catalog_digest, fields):
    _sha(catalog_digest)
    if (
        type(value) is not dict
        or set(value) != {"kind", "version", "scope", "catalog_digest", *fields}
        or value["kind"] != kind
        or value["version"] != "1"
        or type(value["scope"]) is not dict
        or canonical(value["scope"]) != canonical(_scope(scope))
        or type(value["catalog_digest"]) is not str
        or value["catalog_digest"] != catalog_digest
    ):
        raise SkillError("Skill snapshot differs from its original Scope or catalog")


def validate_skill_list(value, scope, *, catalog_digest, max_entries, offset):
    try:
        value = _plain(value)
        _read_bounds(max_entries, offset)
        _envelope(value, "skill-list", scope, catalog_digest, {"skills", "total", "next_offset"})
        total, items, following = value["total"], value["skills"], value["next_offset"]
        if (
            type(total) is not int
            or not 0 <= total <= 1000
            or type(items) is not list
            or len(items) != max(0, min(max_entries, total - offset))
        ):
            raise SkillError("Skill catalog returned invalid page bounds")
        expected = offset + len(items) if offset + len(items) < total else None
        if following is not None and type(following) is not int or following != expected:
            raise SkillError("Skill catalog returned invalid next offset")
        for item in items:
            _metadata(item)
        names = [item["name"] for item in items]
        if names != sorted(set(names)):
            raise SkillError("Skill catalog page is not uniquely ordered")
        if offset == 0 and len(items) == total and digest(items) != catalog_digest:
            raise SkillError("Skill metadata differs from its immutable catalog digest")
        return value
    except (ValidationError, TypeError, KeyError, ValueError):
        raise SkillError("Skill catalog returned an invalid page snapshot") from None


def validate_skill_get(value, scope, name, *, catalog_digest, max_bytes):
    try:
        value = _plain(value)
        _name(name)
        _read_bounds(max_bytes)
        _envelope(value, "skill-instructions", scope, catalog_digest, {"skill"})
        item = value["skill"]
        if type(item) is not dict or set(item) != {
            "name",
            "description",
            "version",
            "sha256",
            "bytes",
            "instructions",
        }:
            raise SkillError("Skill instruction snapshot is invalid")
        _metadata({k: v for k, v in item.items() if k != "instructions"})
        data = _text(item["instructions"], "Skill instructions", max_bytes)
        if (
            item["name"] != name
            or len(data) != item["bytes"]
            or hashlib.sha256(data).hexdigest() != item["sha256"]
        ):
            raise SkillError(
                "Skill instructions differ from their name, content hash or byte count"
            )
        return value
    except (ValidationError, TypeError, KeyError, ValueError):
        raise SkillError("Skill catalog returned an invalid instruction snapshot") from None


class SkillCatalogPort(Protocol):
    identity: dict

    def list(self, scope: Scope, *, max_entries: int = 100, offset: int = 0) -> dict: ...
    def get(self, scope: Scope, name: str, *, max_bytes: int = 1048576) -> dict: ...
    def close(self) -> None: ...


class InMemorySkillCatalog:
    def __init__(
        self, skills=(), *, version, scopes=DEFAULT_SCOPES, max_skills=100, max_bytes=1048576
    ):
        _text(version, "Skill catalog version", 256)
        self._scopes = _configuration(version, scopes)
        _bound(max_skills, 1000, "Skill catalog entry")
        _bound(max_bytes, 16777216, "Skill catalog byte")
        if type(skills) not in (list, tuple) or len(skills) > max_skills:
            raise ValidationError("Skill catalog requires a bounded ordinary entry sequence")
        entries, size = {}, 0
        for skill in skills:
            metadata = skill_metadata(skill)
            if metadata["name"] in entries:
                raise ValidationError("Skill catalog names must be unique")
            size += metadata["bytes"]
            if metadata["bytes"] > max_bytes or size > 67108864:
                raise ValidationError("Skill catalog exceeds its instruction capacity")
            entries[skill.name] = skill.to_dict()
        self._entries = dict(sorted(entries.items()))
        self._metadata = [
            {k: v for k, v in item.items() if k != "instructions"}
            for item in self._entries.values()
        ]
        self._identity = {
            "kind": "memory-skill-catalog",
            "version": "1",
            "behavior_version": version,
            "scopes": _scopes_json(self._scopes),
            "max_skills": max_skills,
            "max_bytes": max_bytes,
            "catalog_digest": digest(self._metadata),
        }
        self._lock, self._closed = threading.RLock(), False

    @property
    def identity(self):
        return copy.deepcopy(self._identity)

    def _open(self, scope):
        _authorize(scope, self._scopes)
        if self._closed:
            raise SkillError("Skill catalog is closed")

    def list(self, scope, *, max_entries=100, offset=0):
        with self._lock:
            self._open(scope)
            _read_bounds(max_entries, offset)
            items = self._metadata[offset : offset + max_entries]
            total = len(self._metadata)
            value = {
                "kind": "skill-list",
                "version": "1",
                "scope": _scope(scope),
                "catalog_digest": self._identity["catalog_digest"],
                "skills": items,
                "total": total,
                "next_offset": offset + len(items) if offset + len(items) < total else None,
            }
            return validate_skill_list(
                value,
                scope,
                catalog_digest=self._identity["catalog_digest"],
                max_entries=max_entries,
                offset=offset,
            )

    def get(self, scope, name, *, max_bytes=1048576):
        with self._lock:
            self._open(scope)
            _name(name)
            _read_bounds(max_bytes)
            if name not in self._entries:
                raise SkillError("Skill is outside this catalog")
            value = {
                "kind": "skill-instructions",
                "version": "1",
                "scope": _scope(scope),
                "catalog_digest": self._identity["catalog_digest"],
                "skill": self._entries[name],
            }
            return validate_skill_get(
                value,
                scope,
                name,
                catalog_digest=self._identity["catalog_digest"],
                max_bytes=max_bytes,
            )

    def close(self):
        with self._lock:
            self._closed = True
