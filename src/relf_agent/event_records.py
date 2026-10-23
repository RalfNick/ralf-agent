"""Scope-bound resume cursors and immutable durable-event wire snapshots."""

import base64
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .errors import ValidationError
from .model_protocol import json_object
from .types import RunEvent, RunSnapshot, Scope, _require_text, canonical


@dataclass(frozen=True)
class EventCursor:
    scope: Scope
    run_id: str
    after: int = 0

    def __post_init__(self):
        if not isinstance(self.scope, Scope):
            raise ValidationError("Event cursor requires a Scope")
        _require_text(self.run_id, "Event Run ID")
        if type(self.after) is not int or not 0 <= self.after <= 2**63 - 1:
            raise ValidationError("Event cursor requires a nonnegative sequence")
        object.__setattr__(self, "scope", Scope(self.scope.workspace, self.scope.principal))
        if len(canonical(self.to_dict()).encode("utf-8")) > 4096:
            raise ValidationError("Event cursor exceeds its bound")

    def to_dict(self):
        return {
            "version": "1",
            "scope": asdict(self.scope),
            "run_id": self.run_id,
            "after": self.after,
        }

    @property
    def token(self):
        return (
            base64.urlsafe_b64encode(canonical(self.to_dict()).encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )

    @classmethod
    def from_token(cls, token):
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 8192
            or re.fullmatch(r"[A-Za-z0-9_-]+", token) is None
        ):
            raise ValidationError("Invalid event cursor token")
        try:
            raw = base64.b64decode(token + "=" * ((-len(token)) % 4), altchars=b"-_", validate=True)
            if len(raw) > 4096:
                raise ValueError("Cursor exceeds bound")
            value = json_object(raw.decode("utf-8"))
            if (
                set(value) != {"version", "scope", "run_id", "after"}
                or value["version"] != "1"
                or not isinstance(value["scope"], dict)
                or set(value["scope"]) != {"workspace", "principal"}
            ):
                raise ValueError("Unsupported cursor fields")
            cursor = cls(Scope(**value["scope"]), value["run_id"], value["after"])
            if cursor.token != token:
                raise ValueError("Noncanonical cursor token")
            return cursor
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ValidationError("Invalid event cursor token") from exc


@dataclass(frozen=True, init=False)
class EventEnvelope:
    cursor: EventCursor
    _event_json: str = field(repr=False)

    def __init__(self, scope, event):
        if (
            not isinstance(event, RunEvent)
            or type(event.seq) is not int
            or event.seq < 1
            or not isinstance(event.kind, str)
            or not event.kind.strip()
            or len(event.kind) > 128
            or not isinstance(event.data, dict)
        ):
            raise ValidationError("Invalid durable event")
        object.__setattr__(self, "cursor", EventCursor(scope, event.run_id, event.seq))
        object.__setattr__(self, "_event_json", canonical(asdict(event)))

    @property
    def event(self):
        return RunEvent(**json.loads(self._event_json))

    def to_dict(self):
        return {
            "event": json.loads(self._event_json),
            "cursor": self.cursor.to_dict(),
            "cursor_token": self.cursor.token,
        }

    def to_sse(self):
        return (
            "id: "
            + self.cursor.token
            + "\nevent: ralf.run\ndata: "
            + canonical(self.to_dict())
            + "\n\n"
        )


class SyncRunEventSource(Protocol):
    scope: Scope

    def status(self, run_id: str) -> RunSnapshot: ...
    def events(self, run_id: str, *, after=0, limit=1000) -> list[RunEvent]: ...


class AsyncRunEventSource(Protocol):
    scope: Scope

    async def status(self, run_id: str) -> RunSnapshot: ...
    async def events(self, run_id: str, *, after=0, limit=1000) -> list[RunEvent]: ...
