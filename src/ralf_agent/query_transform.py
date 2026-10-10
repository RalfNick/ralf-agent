"""Explicit bounded query proposals; no model, source or execution authority."""

import json
import re
from typing import Protocol

from .errors import ValidationError
from .retrieval_pipeline import _lazy
from .types import canonical


def query_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise ValidationError("Query transform requires nonblank text of at most4096 characters")
    try:
        text.encode("utf-8")
    except UnicodeError:
        raise ValidationError("Query requires valid Unicode scalars") from None
    return text


def query_proposal(value):
    if type(value) is not tuple or not 1 <= len(value) <= 4:
        _lazy(value)
        raise ValidationError("Query transform must return1..4 completed text queries")
    result = tuple(query_text(text) for text in value)
    if len(set(result)) != len(result) or sum(map(len, result)) > 16384:
        raise ValidationError("Query proposal repeats or exceeds its finite budget")
    return result


class QueryTransform(Protocol):
    identity: dict

    def transform(self, text: str) -> tuple[str, ...]: ...


class AsyncQueryTransform(Protocol):
    identity: dict

    async def transform(self, text: str) -> tuple[str, ...]: ...


class IdentityQueryTransform:
    @property
    def identity(self):
        return {"kind": "identity-query-transform", "version": "1"}

    def transform(self, text):
        return (query_text(text),)


class AliasQueryTransform:
    def __init__(self, aliases, *, include_original=True):
        if type(aliases) is not dict or len(aliases) > 128 or type(include_original) is not bool:
            raise ValidationError(
                "Query aliases require at most128 literal pairs and boolean policy"
            )
        normalized = {}
        for key, value in aliases.items():
            key, value = query_text(key), query_text(value)
            if len(key) > 256 or len(value) > 1024:
                raise ValidationError("Query alias pair exceeds text limits")
            normalized[key] = value
        self._config_json = canonical(
            dict(
                kind="alias-query-transform",
                version="1",
                aliases=normalized,
                include_original=include_original,
            )
        )

    @property
    def identity(self):
        return json.loads(self._config_json)

    def transform(self, text):
        text = " ".join(query_text(text).split())
        config = self.identity
        aliases = config["aliases"]
        if not aliases:
            return (text,)
        pattern = "|".join(re.escape(key) for key in sorted(aliases, key=lambda k: (-len(k), k)))
        rewritten = re.sub(pattern, lambda match: aliases[match[0]], text)
        rewritten = " ".join(rewritten.split())
        values = (
            (text, rewritten) if config["include_original"] and rewritten != text else (rewritten,)
        )
        return query_proposal(values)
