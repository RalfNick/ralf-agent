"""Independent, replaceable short-term and explicit long-term memory ports."""

import asyncio
import copy
import inspect
import json
import math
import threading
import time
import uuid
from pathlib import Path
from typing import Protocol

from .errors import IdempotencyConflict, MemoryBackendError, RalfError, ValidationError
from .storage import SQLiteStore
from .types import Scope, canonical


def _validate_expires_at(expires_at):
    """Normalize optional Unix seconds before either backend changes a fact."""
    if expires_at is None:
        return None
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        raise ValidationError("expires_at must be a finite int or float Unix timestamp, or None")
    try:
        timestamp = float(expires_at)
    except OverflowError as exc:
        raise ValidationError("expires_at must be a finite Unix timestamp") from exc
    if not math.isfinite(timestamp):
        raise ValidationError("expires_at must be a finite Unix timestamp")
    return timestamp


class SessionStore(Protocol):
    backend_id: str

    def read(self, scope: Scope, session_id: str) -> tuple[int, list[dict]]: ...

    def append(
        self,
        scope: Scope,
        session_id: str,
        message: dict,
        *,
        expected_revision: int,
        message_id: str,
    ) -> int: ...


class LongTermMemoryStore(Protocol):
    backend_id: str

    def facts(self, scope: Scope, namespace: str) -> list[dict]: ...

    def put_fact(
        self,
        scope: Scope,
        namespace: str,
        key: str,
        value,
        *,
        expected_version: int,
        expires_at: float | None = None,
    ) -> int: ...


class AsyncSessionStore(Protocol):
    backend_id: str

    async def read(self, scope: Scope, session_id: str) -> tuple[int, list[dict]]: ...
    async def append(
        self,
        scope: Scope,
        session_id: str,
        message: dict,
        *,
        expected_revision: int,
        message_id: str,
    ) -> int: ...


class AsyncLongTermMemoryStore(Protocol):
    backend_id: str

    async def facts(self, scope: Scope, namespace: str) -> list[dict]: ...
    async def put_fact(
        self,
        scope: Scope,
        namespace: str,
        key: str,
        value,
        *,
        expected_version: int,
        expires_at: float | None = None,
    ) -> int: ...


async def memory_call(method, *args, **kwargs):
    """Sync local adapters stay on the coordinator; async remote adapters suspend."""
    try:
        result = method(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    except RalfError:
        raise
    except Exception as exc:
        raise MemoryBackendError("Memory backend operation failed") from exc


class ThreadedMemoryAdapter:
    """Explicit bridge for a thread-safe synchronous remote client.

    The underlying backend is caller-owned. SQLiteMemory is thread-affine and
    must stay on the coordinator. Prefer native async adapters for remote I/O.
    """

    def __init__(self, backend):
        self.backend = backend

    @property
    def backend(self):
        return self._backend

    @backend.setter
    def backend(self, backend):
        if isinstance(backend, SQLiteMemory):
            raise ValidationError("SQLiteMemory must remain on its creating thread")
        if not isinstance(getattr(backend, "backend_id", None), str) or not backend.backend_id:
            raise ValidationError("Memory backends require a stable backend_id")
        if any(
            inspect.iscoroutinefunction(getattr(backend, name, None))
            for name in ("read", "append", "facts", "put_fact")
        ):
            raise ValidationError("Use native async memory directly without the threaded bridge")
        self._backend = backend

    @property
    def backend_id(self):
        return f"threaded:{self.backend.backend_id}"

    async def read(self, *args, **kwargs):
        return await asyncio.to_thread(self.backend.read, *args, **kwargs)

    async def append(self, *args, **kwargs):
        return await asyncio.to_thread(self.backend.append, *args, **kwargs)

    async def facts(self, *args, **kwargs):
        return await asyncio.to_thread(self.backend.facts, *args, **kwargs)

    async def put_fact(self, *args, **kwargs):
        return await asyncio.to_thread(self.backend.put_fact, *args, **kwargs)


class InMemoryMemory:
    def __init__(self, *, backend_id=None):
        self.backend_id = backend_id or f"memory:{uuid.uuid4().hex}"
        self._sessions = {}
        self._facts = {}
        self._lock = threading.RLock()

    def read(self, scope, session_id):
        with self._lock:
            records = self._sessions.get((scope.workspace, scope.principal, session_id), [])
            return len(records), [copy.deepcopy(record[1]) for record in records]

    def append(self, scope, session_id, message, *, expected_revision, message_id):
        canonical(message)
        with self._lock:
            records = self._sessions.setdefault((scope.workspace, scope.principal, session_id), [])
            for index, (identity, existing) in enumerate(records, 1):
                if identity == message_id:
                    if canonical(existing) != canonical(message):
                        raise IdempotencyConflict("Message identity conflict")
                    return index
            if len(records) != expected_revision:
                raise ValidationError("Session revision conflict")
            records.append((message_id, copy.deepcopy(message)))
            return len(records)

    def facts(self, scope, namespace):
        with self._lock:
            return [
                copy.deepcopy(v)
                for (workspace, principal, ns, _), v in sorted(self._facts.items())
                if workspace == scope.workspace
                and principal == scope.principal
                and ns == namespace
                and (v["expires_at"] is None or v["expires_at"] > time.time())
            ]

    def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        expires_at = _validate_expires_at(expires_at)
        canonical(value)
        identity = (scope.workspace, scope.principal, namespace, key)
        with self._lock:
            actual = self._facts.get(identity, {}).get("version", 0)
            if actual != expected_version:
                raise ValidationError("Fact version conflict")
            self._facts[identity] = {
                "key": key,
                "value": copy.deepcopy(value),
                "version": actual + 1,
                "expires_at": expires_at,
            }
            return actual + 1

    def close(self):
        pass


class SQLiteMemory:
    def __init__(self, path_or_store):
        self._owns_store = not isinstance(path_or_store, SQLiteStore)
        self.store = SQLiteStore(path_or_store) if self._owns_store else path_or_store
        self.backend_id = (
            self.store.backend_id
            if self.store.path == ":memory:"
            else f"sqlite-memory:{Path(self.store.path).resolve()}"
        )
        self.store.conn.executescript("""
            CREATE TABLE IF NOT EXISTS memory_sessions (workspace TEXT, principal TEXT, session TEXT, data TEXT NOT NULL, PRIMARY KEY(workspace,principal,session));
            CREATE TABLE IF NOT EXISTS memory_facts (workspace TEXT, principal TEXT, namespace TEXT, key TEXT, value TEXT NOT NULL, version INTEGER NOT NULL, expires_at REAL, PRIMARY KEY(workspace,principal,namespace,key));
        """)

    def _records(self, scope, session_id):
        row = self.store.conn.execute(
            "SELECT data FROM memory_sessions WHERE workspace=? AND principal=? AND session=?",
            (scope.workspace, scope.principal, session_id),
        ).fetchone()
        return json.loads(row[0]) if row else []

    def read(self, scope, session_id):
        records = self._records(scope, session_id)
        return len(records), [r[1] for r in records]

    def append(self, scope, session_id, message, *, expected_revision, message_id):
        with self.store.transaction():
            records = self._records(scope, session_id)
            for index, (identity, existing) in enumerate(records, 1):
                if identity == message_id:
                    if canonical(existing) != canonical(message):
                        raise IdempotencyConflict("Message identity conflict")
                    return index
            if len(records) != expected_revision:
                raise ValidationError("Session revision conflict")
            records.append([message_id, message])
            self.store.conn.execute(
                "INSERT INTO memory_sessions VALUES (?,?,?,?) ON CONFLICT(workspace,principal,session) DO UPDATE SET data=excluded.data",
                (scope.workspace, scope.principal, session_id, canonical(records)),
            )
            return len(records)

    def facts(self, scope, namespace):
        return [
            {
                "key": row["key"],
                "value": json.loads(row["value"]),
                "version": row["version"],
                "expires_at": row["expires_at"],
            }
            for row in self.store.conn.execute(
                "SELECT * FROM memory_facts WHERE workspace=? AND principal=? AND namespace=? AND (expires_at IS NULL OR expires_at>?) ORDER BY key",
                (scope.workspace, scope.principal, namespace, time.time()),
            )
        ]

    def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        expires_at = _validate_expires_at(expires_at)
        with self.store.transaction():
            row = self.store.conn.execute(
                "SELECT version FROM memory_facts WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                (scope.workspace, scope.principal, namespace, key),
            ).fetchone()
            actual = row[0] if row else 0
            if actual != expected_version:
                raise ValidationError("Fact version conflict")
            self.store.conn.execute(
                "INSERT INTO memory_facts VALUES (?,?,?,?,?,?,?) ON CONFLICT(workspace,principal,namespace,key) DO UPDATE SET value=excluded.value,version=excluded.version,expires_at=excluded.expires_at",
                (
                    scope.workspace,
                    scope.principal,
                    namespace,
                    key,
                    canonical(value),
                    actual + 1,
                    expires_at,
                ),
            )
            return actual + 1

    def close(self):
        if self._owns_store:
            self.store.close()
