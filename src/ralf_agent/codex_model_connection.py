"""Fixed, nonsecret Responses connection data; credentials are never resolved here."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import ValidationError

_FIELDS = frozenset({"base_url", "model", "credential_env", "credential_id", "generation"})


def _text(value, pattern, limit):
    return (
        type(value) is str and 0 < len(value) <= limit and re.fullmatch(pattern, value) is not None
    )


def _endpoint(value):
    if not _text(value, r"https://[A-Za-z0-9./:_\[\]-]+", 2048):
        return False
    try:
        url = urlsplit(value)
        port = url.port
        host = url.hostname
        return (
            url.scheme == "https"
            and host is not None
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and (port is None or 0 < port <= 65535)
            and _text(host, r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", 253)
            and all(part not in (".", "..") for part in url.path.split("/"))
        )
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class CodexModelConnection:
    """A credential reference and public provider choice, never a bearer token."""

    base_url: str
    model: str
    credential_env: str
    credential_id: str
    generation: str
    reasoning_effort: str = "low"

    def __post_init__(self):
        if not (
            _endpoint(self.base_url)
            and _text(self.model, r"[A-Za-z0-9][A-Za-z0-9._:/-]*", 128)
            and _text(self.credential_env, r"[A-Za-z_][A-Za-z0-9_]*", 128)
            and _text(self.credential_id, r"[A-Za-z0-9][A-Za-z0-9._:-]*", 128)
            and _text(self.generation, r"[A-Za-z0-9][A-Za-z0-9._:-]*", 128)
            and type(self.reasoning_effort) is str
            and self.reasoning_effort in {"none", "minimal", "low", "medium", "high", "xhigh"}
        ):
            raise ValidationError(
                "Codex model connection requires bounded nonsecret Responses data"
            )

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in sorted(_FIELDS | {"reasoning_effort"})}

    @classmethod
    def from_dict(cls, value: dict):
        if type(value) is not dict or not (
            _FIELDS <= value.keys() <= _FIELDS | {"reasoning_effort"}
        ):
            raise ValidationError("Codex model connection declaration has invalid fields")
        return cls(**value)

    @property
    def identity(self) -> dict:
        return {"kind": "codex-model-connection", "version": "1", **self.to_dict()}
