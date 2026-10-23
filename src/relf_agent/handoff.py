"""Durable bounded SQLite inbox/outbox and explicit engine command adapters.

These stores own handoff receipts, never Run state. A crash between engine
acceptance and inbox completion is resolved by the engine's own command_id.
The dispatcher accepts commands but never drives a Run; a host wakeup can
schedule drive on its existing coordinator after acceptance.
"""

import asyncio
import inspect
import json
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .errors import IdempotencyConflict, RalfError, ValidationError
from .messaging import MessageEnvelope, _delivery, _inputs, _integer, _json, _text
from .ports import is_async_callable, is_sync_callable
from .types import Scope, canonical


class HandoffError(RalfError):
    code = "handoff_error"


@runtime_checkable
class Inbox(Protocol):
    """Synchronous durable receipt storage, borrowed by handoff consumers.

    accept commits reception before returning None or the original result.
    complete commits the immutable result and returns None after completion.
    Methods must finish synchronously; a lazy return is never durability evidence.
    The host owns close, including when consumers or A2A borrow this port.
    """

    def accept(self, scope: Scope, message: MessageEnvelope) -> dict | None: ...
    def complete(self, scope: Scope, message: MessageEnvelope, result: dict) -> None: ...
    def result(self, scope: Scope, message_id: str) -> dict | None: ...
    def pending(self, scope: Scope, *, limit=100) -> list[MessageEnvelope]: ...
    def close(self) -> None: ...


@runtime_checkable
class AsyncInbox(Protocol):
    """Native async equivalent of Inbox with host-owned async lifecycle."""

    async def accept(self, scope: Scope, message: MessageEnvelope) -> dict | None: ...
    async def complete(self, scope: Scope, message: MessageEnvelope, result: dict) -> None: ...
    async def result(self, scope: Scope, message_id: str) -> dict | None: ...
    async def pending(self, scope: Scope, *, limit=100) -> list[MessageEnvelope]: ...
    async def aclose(self) -> None: ...


@runtime_checkable
class Outbox(Protocol):
    """Synchronous durable enqueue/read with explicit async broker delivery.

    enqueue retains stable message identity before returning it. flush only
    marks publication after the broker returns its stable identity. The host
    owns close. SQLiteOutbox is the default implementation.
    """

    def enqueue(self, scope: Scope, message: MessageEnvelope) -> str: ...
    def result(self, scope: Scope, message_id: str) -> dict | None: ...
    def pending(self, scope: Scope, *, limit=100) -> list[MessageEnvelope]: ...
    async def flush(self, bus, scope: Scope, *, limit=100) -> int: ...
    def close(self) -> None: ...


@runtime_checkable
class AsyncOutbox(Protocol):
    """Native async durable enqueue/read/publication with host-owned lifecycle."""

    async def enqueue(self, scope: Scope, message: MessageEnvelope) -> str: ...
    async def result(self, scope: Scope, message_id: str) -> dict | None: ...
    async def pending(self, scope: Scope, *, limit=100) -> list[MessageEnvelope]: ...
    async def flush(self, bus, scope: Scope, *, limit=100) -> int: ...
    async def aclose(self) -> None: ...


@runtime_checkable
class CommandAdapter(Protocol):
    """Trusted scoped async invocation bridge; execution authority owns dedup.

    invoke receives a validated control kind, positional args and keyword args
    including stable command_id. It returns a completed finite JSON receipt.
    This borrowed port neither transfers engine ownership nor drives a Run.
    """

    scope: Scope

    async def invoke(self, kind: str, args: tuple, kwargs: dict) -> dict: ...


def _validate_storage_port(value, methods, label):
    asynchronous = is_async_callable(getattr(value, methods[0], None))
    predicate = is_async_callable if asynchronous else is_sync_callable
    lifecycle = "aclose" if asynchronous else "close"
    for name in (*methods, lifecycle):
        if not predicate(getattr(value, name, None)):
            kind = "async" if asynchronous else "synchronous"
            raise ValidationError(
                f"{label}.{name} must be {kind}; storage methods cannot mix modes"
            )
    return value


def validate_inbox(inbox):
    """Accept a structural synchronous or native async Inbox, without inheritance."""
    return _validate_storage_port(inbox, ("accept", "complete", "result", "pending"), "Inbox")


def validate_outbox(outbox):
    """Validate durable storage mode plus an explicitly async delivery operation."""
    _validate_storage_port(outbox, ("enqueue", "result", "pending"), "Outbox")
    if not is_async_callable(getattr(outbox, "flush", None)):
        raise ValidationError("Outbox.flush must be native async")
    return outbox


def validate_command_adapter(adapter):
    if not isinstance(getattr(adapter, "scope", None), Scope):
        raise ValidationError("CommandAdapter requires an explicit trusted Scope")
    if not is_async_callable(getattr(adapter, "invoke", None)):
        raise ValidationError("CommandAdapter.invoke must be native async")
    return adapter


async def _completed(value, label):
    """Dispose unexpected lazy returns without entering their execution."""
    lazy = inspect.isawaitable(value) or inspect.isgenerator(value) or inspect.isasyncgen(value)
    if lazy:
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        elif inspect.isasyncgen(value):
            await value.aclose()
        raise ValidationError(f"{label} must return a completed value, not lazy work")
    return value


async def call_inbox(inbox, method, *args, **kwargs):
    """Invoke a borrowed Inbox safely; only native async methods are awaited.

    A synchronous function returning a coroutine is invalid and never entered.
    complete must return exactly None before a consumer may acknowledge.
    """
    validate_inbox(inbox)
    if method not in {"accept", "complete", "result", "pending"}:
        raise ValidationError("Unknown Inbox operation")
    operation = getattr(inbox, method)
    result = (
        await operation(*args, **kwargs)
        if is_async_callable(operation)
        else operation(*args, **kwargs)
    )
    result = await _completed(result, f"Inbox.{method}")
    if method == "complete":
        if result is not None:
            raise ValidationError("Inbox.complete must return None after durable completion")
        return None
    if method == "pending":
        if (
            not isinstance(result, list)
            or len(result) > kwargs.get("limit", 100)
            or any(not isinstance(item, MessageEnvelope) for item in result)
        ):
            raise ValidationError("Inbox.pending returned invalid messages")
        return list(result)
    if result is not None and not isinstance(result, dict):
        raise ValidationError(f"Inbox.{method} must return a finite JSON receipt or None")
    return None if result is None else json.loads(_json(result))


async def flush_outbox(outbox, bus, scope, *, limit=100):
    """Borrow a structural Outbox and require completed bounded delivery evidence."""
    validate_outbox(outbox)
    _inputs(scope, "handoff")
    _integer(limit, "Outbox flush limit")
    result = await _completed(await outbox.flush(bus, scope, limit=limit), "Outbox.flush")
    _integer(result, "Outbox delivered count", 0, limit)
    return result


class _SQLiteHandoff:
    table = ""

    def __init__(self, path, *, max_entries=10000):
        _integer(max_entries, "Handoff capacity", 1, 1000000)
        self._max_entries = max_entries
        self._closed = False
        try:
            self._db = sqlite3.connect(str(Path(path)), timeout=5, isolation_level=None)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.execute(f"""CREATE TABLE IF NOT EXISTS {self.table} (
                scope TEXT NOT NULL, message_id TEXT NOT NULL, envelope TEXT NOT NULL,
                result TEXT, PRIMARY KEY(scope,message_id))""")
        except Exception as exc:
            if hasattr(self, "_db"):
                self._db.close()
            raise HandoffError("Handoff store open failed") from exc

    def _open(self):
        if self._closed:
            raise HandoffError("Handoff store is closed")

    def _scope(self, scope):
        _inputs(scope, "handoff")
        return canonical(asdict(scope))

    def _accept(self, scope, message):
        self._open()
        if not isinstance(message, MessageEnvelope):
            raise ValidationError("Handoff requires a MessageEnvelope")
        binding = self._scope(scope)
        encoded = _json(message.to_dict())
        try:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute(
                f"SELECT envelope,result FROM {self.table} WHERE scope=? AND message_id=?",
                (binding, message.message_id),
            ).fetchone()
            if row is not None:
                if row[0] != encoded:
                    raise IdempotencyConflict("Handoff message identity conflict")
            else:
                count = self._db.execute(
                    f"SELECT COUNT(*) FROM {self.table} WHERE scope=?", (binding,)
                ).fetchone()[0]
                if count >= self._max_entries:
                    raise HandoffError("Handoff capacity reached; archive before accepting")
                self._db.execute(
                    f"INSERT INTO {self.table} (scope,message_id,envelope) VALUES (?,?,?)",
                    (binding, message.message_id, encoded),
                )
            self._db.execute("COMMIT")
            return None if row is None or row[1] is None else json.loads(row[1])
        except BaseException as exc:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(exc, (RalfError, KeyboardInterrupt, SystemExit)):
                raise
            raise HandoffError("Handoff store operation failed") from exc

    def _complete(self, scope, message, result):
        # Enforce identity before completion, including callers completing first.
        self._accept(scope, message)
        encoded = _json(result)
        binding = self._scope(scope)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            previous = self._db.execute(
                f"SELECT result FROM {self.table} WHERE scope=? AND message_id=?",
                (binding, message.message_id),
            ).fetchone()[0]
            if previous is not None and previous != encoded:
                raise IdempotencyConflict("Handoff result identity conflict")
            self._db.execute(
                f"UPDATE {self.table} SET result=? WHERE scope=? AND message_id=?",
                (encoded, binding, message.message_id),
            )
            self._db.execute("COMMIT")
        except BaseException as exc:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if isinstance(exc, (RalfError, KeyboardInterrupt, SystemExit)):
                raise
            raise HandoffError("Handoff store operation failed") from exc

    def pending(self, scope, *, limit=100):
        self._open()
        _integer(limit, "Handoff pending limit")
        try:
            rows = self._db.execute(
                f"SELECT envelope FROM {self.table} WHERE scope=? AND result IS NULL ORDER BY rowid LIMIT ?",
                (self._scope(scope), limit),
            ).fetchall()
            return [MessageEnvelope(**json.loads(row[0])) for row in rows]
        except RalfError:
            raise
        except Exception as exc:
            raise HandoffError("Handoff store operation failed") from exc

    def result(self, scope, message_id):
        self._open()
        _text(message_id, "Message identity")
        try:
            row = self._db.execute(
                f"SELECT result FROM {self.table} WHERE scope=? AND message_id=?",
                (self._scope(scope), message_id),
            ).fetchone()
            return None if row is None or row[0] is None else json.loads(row[0])
        except RalfError:
            raise
        except Exception as exc:
            raise HandoffError("Handoff store operation failed") from exc

    def close(self):
        if not self._closed:
            try:
                self._db.close()
            except Exception as exc:
                raise HandoffError("Handoff store close failed") from exc
            self._closed = True

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *args):
        self.close()


class SQLiteInbox(_SQLiteHandoff):
    table = "ralf_inbox"

    def accept(self, scope, message):
        return self._accept(scope, message)

    def complete(self, scope, message, result):
        if not isinstance(result, dict):
            raise ValidationError("Inbox results must be JSON objects")
        self._complete(scope, message, result)


class SQLiteOutbox(_SQLiteHandoff):
    table = "ralf_outbox"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._flush_lock = asyncio.Lock()

    def enqueue(self, scope, message):
        self._accept(scope, message)
        return message.message_id

    async def flush(self, bus, scope, *, limit=100):
        """Publish once per attempt; a crash before marking causes stable replay."""
        async with self._flush_lock:
            count = 0
            for message in self.pending(scope, limit=limit):
                broker_id = await bus.publish(scope, message)
                _text(broker_id, "Broker identity")
                self._complete(scope, message, {"broker_id": broker_id})
                count += 1
            return count


def _receipt(value):
    if is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        raise HandoffError("Engine command returned invalid receipt")
    return json.loads(_json(value))


class LocalCommandAdapter:
    """Awaitable bridge for genuine synchronous LocalEngine controls.

    It executes controls on the caller's coordinator thread; no thread pool or
    fake async methods are introduced on ExecutionEngine itself.
    """

    def __init__(self, engine):
        if not isinstance(getattr(engine, "scope", None), Scope):
            raise ValidationError("Engine adapter requires an explicit trusted Scope")
        for name in ("submit", "approve", "cancel", "reconcile"):
            if not is_sync_callable(getattr(engine, name, None)):
                raise ValidationError("Local command adapter requires synchronous controls")
        self.engine = engine
        self.scope = engine.scope

    async def invoke(self, kind, args, kwargs):
        return _receipt(getattr(self.engine, kind)(*args, **kwargs))


class AsyncCommandAdapter:
    """Explicit adapter for remote facades with native async controls."""

    def __init__(self, engine):
        if not isinstance(getattr(engine, "scope", None), Scope):
            raise ValidationError("Async adapter requires an explicit trusted Scope")
        for name in ("submit", "approve", "cancel", "reconcile"):
            if not is_async_callable(getattr(engine, name, None)):
                raise ValidationError("Async command adapter requires native async controls")
        self.engine = engine
        self.scope = engine.scope

    async def invoke(self, kind, args, kwargs):
        return _receipt(await getattr(self.engine, kind)(*args, **kwargs))


class EngineCommandDispatcher:
    def __init__(self, adapter, *, specs=None):
        validate_command_adapter(adapter)
        if specs is not None and not isinstance(specs, dict):
            raise ValidationError("Command specifications must be a host-owned mapping")
        self.adapter = adapter
        self._scope = adapter.scope
        self.specs = dict(specs or {})

    async def dispatch(self, scope, message):
        if not isinstance(message, MessageEnvelope):
            raise ValidationError("Command dispatch requires a MessageEnvelope")
        _inputs(scope, message.topic)
        validate_command_adapter(self.adapter)
        if scope != self._scope or self.adapter.scope != self._scope:
            raise ValidationError("Command Scope does not match the trusted engine Scope")
        payload = message.payload
        kind = payload.get("kind")
        allowed = {
            "submit": {"kind", "spec", "input", "budget", "session_id"},
            "approve": {"kind", "run_id", "action_id", "target_digest", "approved"},
            "cancel": {"kind", "run_id"},
            "reconcile": {"kind", "run_id", "action_id", "result"},
        }
        required = {
            "submit": {"kind", "spec", "input"},
            "approve": {"kind", "run_id", "action_id", "target_digest"},
            "cancel": {"kind", "run_id"},
            "reconcile": {"kind", "run_id", "action_id", "result"},
        }
        if kind not in allowed or set(payload) - allowed[kind] or required[kind] - set(payload):
            raise ValidationError("Invalid engine control message")
        kwargs = {"command_id": message.message_id}
        if kind == "submit":
            if not isinstance(payload["spec"], str) or payload["spec"] not in self.specs:
                raise ValidationError("Unknown host-owned command specification")
            args = (self.specs[payload["spec"]], payload["input"])
            kwargs.update({k: payload[k] for k in ("budget", "session_id") if k in payload})
        else:
            for key in ("run_id", "action_id", "target_digest"):
                if key in payload:
                    _text(payload[key], key)
            if kind == "cancel":
                args = (payload["run_id"],)
            elif kind == "approve":
                approved = payload.get("approved", True)
                if type(approved) is not bool:
                    raise ValidationError("Approval must be a boolean")
                args = (payload["run_id"], payload["action_id"], payload["target_digest"])
                kwargs["approved"] = approved
            else:
                args = (payload["run_id"], payload["action_id"], payload["result"])
        result = await _completed(
            await self.adapter.invoke(kind, args, kwargs), "CommandAdapter.invoke"
        )
        return _receipt(result)


async def consume_delivery(bus, inbox, dispatcher, scope, topic, group, delivery):
    """Durably receive, obtain the authoritative receipt, save it, then ack.

    Exceptions before completion leave a pending delivery. Receipt persistence
    failure after engine acceptance is repaired on replay by command_id dedup.
    """
    _delivery(scope, topic, group, delivery)
    result = await call_inbox(inbox, "accept", scope, delivery.message)
    if result is None:
        result = await dispatcher.dispatch(scope, delivery.message)
        await call_inbox(inbox, "complete", scope, delivery.message, result)
    await bus.ack(scope, topic, group, delivery)
    return result
