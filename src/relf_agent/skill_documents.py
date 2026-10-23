"""Bounded pure standard-frontmatter values and replaceable optional YAML parsing."""

import json
from dataclasses import dataclass
from typing import Protocol

from .errors import ValidationError
from .skills import SkillSpec, _name, _plain, _text
from .types import canonical
from .workspace import _utf8


def _bounded_header(value):
    """Bound expanded alias work before ordinary JSON detachment."""
    count, size, ancestors = 0, 0, set()

    def visit(item):
        nonlocal count, size
        count += 1
        if count > 4096:
            raise ValidationError("Expanded Skill YAML exceeds its value allowance")
        kind = type(item)
        if kind is str:
            size += len(_utf8(item, "Skill YAML value", max_bytes=65536))
            if size > 65536:
                raise ValidationError("Expanded Skill YAML exceeds its byte allowance")
        elif kind in (dict, list):
            if id(item) in ancestors:
                raise ValidationError("Skill YAML cannot contain alias cycles")
            ancestors.add(id(item))
            try:
                if kind is dict:
                    for key, child in item.items():
                        visit(key)
                        visit(child)
                else:
                    for child in item:
                        visit(child)
            finally:
                ancestors.remove(id(item))

    visit(value)
    return _plain(value)


def _metadata(value):
    value = {} if value is None else value
    allowed = {"license", "compatibility", "metadata", "allowed-tools"}
    if (
        type(value) is not dict
        or len(value) > 4
        or any(type(key) is not str or key not in allowed for key in value)
    ):
        raise ValidationError("Skill document requires known informational metadata fields")
    result = {}
    for key in ("license", "allowed-tools"):
        if key in value:
            _text(value[key], "Skill " + key, 4096)
            result[key] = value[key]
    if "compatibility" in value:
        _text(value["compatibility"], "Skill compatibility", 2000)
        if len(value["compatibility"]) > 500:
            raise ValidationError("Skill compatibility exceeds500 characters")
        result["compatibility"] = value["compatibility"]
    if "metadata" in value:
        values = value["metadata"]
        if type(values) is not dict or len(values) > 64:
            raise ValidationError("Skill metadata requires at most64 string pairs")
        for key, item in values.items():
            _utf8(key, "Skill metadata key", max_bytes=1024)
            if not 1 <= len(key) <= 256:
                raise ValidationError("Skill metadata key exceeds its allowance")
            _utf8(item, "Skill metadata value", max_bytes=4096)
        result["metadata"] = dict(values)
    if len(canonical(result).encode("utf-8")) > 65536:
        raise ValidationError("Skill informational metadata exceeds its aggregate allowance")
    return result


def _checked_skill(skill):
    if type(skill) is not SkillSpec:
        raise ValidationError("Skill document requires an ordinary immutable SkillSpec")
    try:
        return SkillSpec(skill.name, skill.description, skill.instructions, skill.version)
    except AttributeError:
        raise ValidationError("Skill document requires all existing SkillSpec fields") from None


def _decode_metadata(value):
    _text(value, "Serialized Skill metadata", 65536)
    try:
        metadata = json.loads(value)
    except (ValueError, TypeError, RecursionError):
        raise ValidationError("Skill document requires bounded serialized metadata") from None
    return _metadata(metadata)


@dataclass(frozen=True, init=False)
class ParsedSkillDocument:
    skill: SkillSpec
    _metadata_json: str

    def __init__(self, skill, metadata=None):
        object.__setattr__(self, "skill", _checked_skill(skill))
        object.__setattr__(self, "_metadata_json", canonical(_metadata(metadata)))

    @property
    def metadata(self):
        return _decode_metadata(self._metadata_json)

    def to_dict(self):
        return {"skill": _checked_skill(self.skill).to_dict(), "metadata": self.metadata}


def _adopt_document(value, maximum):
    skill = getattr(value, "skill", None)
    if type(skill) is not SkillSpec:
        raise ValidationError("Parsed Skill document requires an ordinary nested SkillSpec")
    _text(getattr(skill, "instructions", None), "Parsed Skill instructions", maximum)
    metadata = _decode_metadata(getattr(value, "_metadata_json", None))
    return ParsedSkillDocument(skill, metadata)


class SkillDocumentParser(Protocol):
    identity: dict

    def parse(self, text: str, *, parent_name: str) -> ParsedSkillDocument: ...


class YamlSkillDocumentParser:
    def __init__(self, *, version):
        _text(version, "Skill parser version", 256)
        try:
            import yaml
        except ImportError:
            raise ValidationError(
                "YAML Skill documents require the optional skills/PyYAML extra"
            ) from None
        self._yaml, self._version = yaml, version
        self._identity = {
            "kind": "yaml-skill-document-parser",
            "version": "1",
            "behavior_version": version,
            "yaml_version": yaml.__version__,
            "max_document_bytes": 16777216,
            "max_header_bytes": 65536,
            "max_depth": 16,
            "max_aliases": 32,
            "max_events": 4096,
            "max_expanded_values": 4096,
            "max_expanded_bytes": 65536,
            "name_profile": "ralf-ascii-slug-1",
            "permissions": "informational-only",
        }

    @property
    def identity(self):
        return _plain(self._identity)

    def _header(self, header):
        yaml = self._yaml
        aliases, count, depth = 0, 0, 0
        containers = []
        try:
            for event in yaml.parse(header, Loader=yaml.SafeLoader):
                count += 1
                if isinstance(event, yaml.events.AliasEvent):
                    aliases += 1
                    if event.anchor in containers:
                        raise ValidationError("Skill YAML cannot contain alias cycles")
                if isinstance(
                    event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)
                ):
                    depth += 1
                    containers.append(event.anchor)
                elif isinstance(event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)):
                    depth -= 1
                    containers.pop()
                if count > 4096 or aliases > 32 or depth > 16:
                    raise ValidationError("Skill YAML work exceeds its parsing allowance")

            class UniqueLoader(yaml.SafeLoader):
                pass

            def mapping(loader, node, deep=False):
                if type(node) is not yaml.nodes.MappingNode:
                    raise ValidationError("Skill YAML requires an ordinary metadata mapping")
                result = {}
                for key_node, value_node in node.value:
                    key = loader.construct_object(key_node, deep=deep)
                    if type(key) is not str or key in result:
                        raise ValidationError(
                            "Skill YAML mapping keys must be unique ordinary strings"
                        )
                    result[key] = loader.construct_object(value_node, deep=deep)
                return result

            UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
            return _bounded_header(yaml.load(header, Loader=UniqueLoader))
        except yaml.YAMLError:
            raise ValidationError("Skill document requires bounded safe YAML frontmatter") from None

    def parse(self, text, *, parent_name):
        _name(parent_name)
        _utf8(text, "Skill document", max_bytes=16777216)
        content = text[1:] if text.startswith("\ufeff") else text
        lines = content.splitlines(keepends=True)
        if not lines or lines[0].rstrip("\r\n") != "---":
            raise ValidationError("Skill document must start with YAML frontmatter")
        closing = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
        if closing is None:
            raise ValidationError("Skill document frontmatter requires a closing delimiter")
        header = "".join(lines[1:closing])
        _utf8(header, "Skill frontmatter", max_bytes=65536)
        data = self._header(header)
        if (
            type(data) is not dict
            or not {"name", "description"} <= set(data)
            or set(data)
            - {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
        ):
            raise ValidationError("Skill document requires exact standard frontmatter fields")
        name, description = data["name"], data["description"]
        _name(name)
        _text(description, "Skill description", 4096)
        if name != parent_name or len(description) > 1024:
            raise ValidationError(
                "Skill name must match parent and description must fit1024 characters"
            )
        metadata = _metadata(
            {key: value for key, value in data.items() if key not in {"name", "description"}}
        )
        version = metadata.get("metadata", {}).get("version", "1")
        skill = SkillSpec(name, description, "".join(lines[closing + 1 :]), version)
        return ParsedSkillDocument(skill, metadata)
