"""Pure, replaceable selection over passive scoped Skill metadata."""

import math
import re
from typing import Protocol

from .errors import ValidationError
from .skills import _metadata, _plain, _text
from .types import canonical


def fixed_identity(value):
    count, size = 0, 0

    def visit(item, depth):
        nonlocal count, size
        count += 1
        if count > 4096 or depth > 16:
            raise ValidationError("Skill identity exceeds its structural allowance")
        kind = type(item)
        if kind is str:
            size += len(item.encode("utf-8"))
        elif kind is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValidationError("Skill identities require ordinary string keys")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif kind is list:
            for child in item:
                visit(child, depth + 1)
        elif kind not in (int, float, bool, type(None)) or (
            kind is float and not math.isfinite(item)
        ):
            raise ValidationError("Skill identities require finite ordinary JSON")
        if size > 65536:
            raise ValidationError("Skill identity exceeds its byte allowance")

    try:
        visit(value, 0)
        if type(value) is not dict or not value or len(canonical(value).encode("utf-8")) > 65536:
            raise ValidationError("Skill identity requires bounded ordinary JSON object")
        return _plain(value)
    except (UnicodeError, ValueError, RecursionError):
        raise ValidationError("Skill identity requires bounded ordinary UTF-8 JSON") from None


class SkillSelector(Protocol):
    identity: dict

    def select(self, query, entries, *, limit) -> list[str]: ...


def selection_input(query, entries, limit):
    if type(query) is not str or len(query) > 32768:
        raise ValidationError("Skill selection query requires bounded ordinary text")
    try:
        query.encode("utf-8")
    except UnicodeError:
        raise ValidationError("Skill selection query requires valid UTF-8") from None
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError("Skill selection limit requires 1 to 100 entries")
    if type(entries) is not list or len(entries) > 1000:
        raise ValidationError("Skill selection requires bounded ordinary metadata")
    for item in entries:
        _metadata(item)
    if len({item["name"] for item in entries}) != len(entries):
        raise ValidationError("Skill selection metadata names must be unique")
    return _plain(entries)


def tokens(text):
    result = set()
    for token in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text.lower()):
        if "\u3400" <= token[0] <= "\u9fff":
            result.update(token[index : index + 2] for index in range(max(1, len(token) - 1)))
        else:
            result.add(token)
    return result


class LexicalSkillSelector:
    def __init__(self, *, version="1"):
        _text(version, "Skill selector version", 256)
        self.version = version

    @property
    def identity(self):
        return {"kind": "lexical-skill-selector", "version": "1", "behavior_version": self.version}

    def select(self, query, entries, *, limit):
        entries = selection_input(query, entries, limit)
        query_tokens = tokens(query)
        ranked = []
        for item in entries:
            score = len(query_tokens & tokens(item["name"] + " " + item["description"]))
            if not query.strip() or score:
                ranked.append((-score, item["name"]))
        return [name for _, name in sorted(ranked)[:limit]]
