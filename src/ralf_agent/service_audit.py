"""Bounded, redacted RPC observations, independent of execution evidence."""

import asyncio
import hashlib
import hmac
import secrets
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from .errors import ValidationError
from .ports import _complete_sync_none, is_sync_callable
from .types import Scope, canonical

_OPERATIONS = frozenset(
    {
        "message/send",
        "tasks/get",
        "tasks/cancel",
        "tasks/events",
        "tasks/approve",
        "tasks/reconcile",
        "tasks/resume",
        "unsupported",
    }
)
_OUTCOMES = frozenset(
    {
        "rpc_ok",
        "unauthorized",
        "not_found",
        "invalid_request",
        "rpc_error",
        "internal_error",
        "disconnected",
        "cancelled",
        "timeout",
    }
)


@dataclass(frozen=True)
class AuditRecord:
    """No raw identities, payloads, credentials, results or error details."""

    version: int
    event_id: str
    timestamp: float
    operation: str
    outcome: str
    scope_ref: str | None
    request_ref: str | None
    task_ref: str | None
    message_ref: str | None
    command_ref: str | None


class AuditSink(Protocol):
    """Borrowed host sink. Complete synchronously; never retry business work."""

    def emit(self, record: AuditRecord) -> None: ...


class InMemoryAuditSink:
    """Bounded default observation ring, not a durable compliance log."""

    def __init__(self, *, max_records=1000):
        if type(max_records) is not int or not 1 <= max_records <= 100000:
            raise ValidationError("Audit capacity must be an integer between 1 and 100000")
        self._records = deque(maxlen=max_records)
        self._dropped = 0

    @property
    def records(self):
        return tuple(self._records)

    @property
    def dropped(self):
        return self._dropped

    def emit(self, record: AuditRecord) -> None:
        if type(record) is not AuditRecord:
            raise ValidationError("Audit sink requires an AuditRecord")
        if len(self._records) == self._records.maxlen:
            self._dropped += 1
        self._records.append(record)


class ServiceAudit:
    """Best-effort observer with domain-separated keyed identity references.

    The random default key correlates only this instance. Hosts may supply a
    stable secret key for cross-restart correlation. Sink failures increment
    ``failures`` without exposing exception details or changing RPC outcomes.
    Sink ownership, persistence, access control and retention belong to the host.
    """

    def __init__(self, sink: AuditSink | None = None, *, key: bytes | None = None):
        if key is not None and (type(key) is not bytes or len(key) < 32):
            raise ValidationError("Audit key requires at least 32 secret bytes")
        self._sink = InMemoryAuditSink() if sink is None else sink
        if not is_sync_callable(getattr(self._sink, "emit", None)):
            raise ValidationError("AuditSink.emit must be synchronous")
        self._key = secrets.token_bytes(32) if key is None else key
        self._failures = 0

    @property
    def sink(self):
        return self._sink

    @property
    def failures(self):
        return self._failures

    def _ref(self, domain, value):
        if value is None:
            return None
        return hmac.new(
            self._key,
            canonical([domain, value]).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def record(
        self,
        *,
        scope,
        method,
        outcome,
        request_id=None,
        task_id=None,
        message_id=None,
        command_id=None,
    ):
        if outcome not in _OUTCOMES:
            raise ValidationError("Unsupported audit outcome")
        try:
            record = AuditRecord(
                version=1,
                event_id=uuid.uuid4().hex,
                timestamp=time.time(),
                operation=method if method in _OPERATIONS else "unsupported",
                outcome=outcome,
                scope_ref=self._ref("scope", [scope.workspace, scope.principal])
                if isinstance(scope, Scope)
                else None,
                request_ref=self._ref("request", request_id),
                task_ref=self._ref("task", task_id),
                message_ref=self._ref("message", message_id),
                command_ref=self._ref("command", command_id),
            )
            emit = getattr(self._sink, "emit", None)
            if not is_sync_callable(emit):
                raise ValidationError("AuditSink.emit must be synchronous")
            _complete_sync_none(emit(record), "AuditSink.emit")
        except (Exception, asyncio.CancelledError):
            self._failures += 1
