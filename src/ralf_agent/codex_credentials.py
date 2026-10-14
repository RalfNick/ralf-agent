"""Lazy trusted-host credentials; identity and diagnostics contain no key material.

Custom sources are borrowed. Their owner manages clients and closure. Resolution
is awaited only after the original Action admits native resource preparation.
"""

import inspect
import json
import os
import re
from typing import Protocol

from .component_fingerprint import executable_digest
from .errors import ValidationError
from .ports import is_async_callable
from .runner_journal_state import _json


class CodingCredentialSource(Protocol):
    @property
    def identity(self) -> dict: ...

    async def resolve(self, connection: dict) -> str: ...


def validate_credential(value):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 8192
        or any(not 33 <= ord(char) <= 126 for char in value)
    ):
        if inspect.iscoroutine(value):
            value.close()
        raise ValidationError("Coding credential is unavailable")
    return value


class EnvironmentCodingCredentials:
    """Stateless default; an environment name is resolved once per admitted owner."""

    @property
    def identity(self):
        return {"kind": "coding-environment-credentials", "version": "1"}

    async def resolve(self, connection):
        name = connection.get("credential_env") if type(connection) is dict else None
        if type(name) is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
            raise ValidationError("Coding credential is unavailable")
        return validate_credential(os.environ.get(name))


def source_registration(source):
    """Fix a nonsecret source identity and its verifiable async implementation."""
    if not is_async_callable(getattr(source, "resolve", None)):
        raise ValidationError("Coding credentials require an async source")
    identity = json.loads(_json(source.identity, "Coding credential source identity"))
    return {"identity": identity, "resolve": executable_digest(source.resolve)}
