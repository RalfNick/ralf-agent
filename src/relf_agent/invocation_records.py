"""Immutable observation snapshots, never an execution or authorization token."""

import json
from dataclasses import dataclass, field
from typing import Protocol

from .errors import ValidationError
from .types import canonical, digest


@dataclass(frozen=True, init=False)
class InvocationRecord:
    operation: str
    phase: str
    _payload_json: str = field(repr=False)

    def __init__(self, operation, phase, payload, *, max_bytes=4_000_000):
        if operation not in {"model", "tool", "reconcile"} or phase not in {"before", "after"}:
            raise ValidationError("Unsupported invocation observation")
        if not isinstance(payload, dict):
            raise ValidationError("Invocation payload must be a JSON object")
        text = canonical(payload)
        if len(text.encode("utf-8")) > max_bytes:
            raise ValidationError("Invocation observation exceeds its bound")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "_payload_json", text)

    @property
    def payload(self):
        return json.loads(self._payload_json)

    @property
    def payload_digest(self):
        return digest(self.payload)


class InvocationMiddleware(Protocol):
    identity: dict

    def before(self, record: InvocationRecord) -> None: ...
    def after(self, record: InvocationRecord) -> None: ...
