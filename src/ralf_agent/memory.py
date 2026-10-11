"""Independent, replaceable short-term and explicit long-term memory ports."""

import asyncio
import copy
import inspect
import json
import math
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from .errors import (
    DefinitionMismatch,
    IdempotencyConflict,
    MemoryBackendError,
    RalfError,
    ValidationError,
)
from .recall import (
    LegacyMemoryRecallAdapter,
    _binding,
    _current_fact,
    _decode_cursor,
    _fact_inputs,
    _integer,
    _method_backend,
    _name,
    _page,
)
from .recall import MemoryRecallPolicy as MemoryRecallPolicy
from .recall import RecallQuery as RecallQuery
from .storage import SQLiteStore
from .tools import current_thread_group, current_thread_tracker
from .types import Scope, _require_text, canonical


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
            or (
                callable(getattr(backend, name, None))
                and inspect.iscoroutinefunction(type(getattr(backend, name)).__call__)
            )
            for name in (
                "read",
                "append",
                "facts",
                "put_fact",
                "read_page",
                "recall",
                "validate_facts",
                "scan_facts",
                "fact_snapshot",
                "inspect_message",
            )
        ):
            raise ValidationError("Use native async memory directly without the threaded bridge")
        self._backend = backend

    @property
    def backend_id(self):
        return f"threaded:{self.backend.backend_id}"

    @property
    def fact_inspection_version(self):
        return getattr(self.backend, "fact_inspection_version", None)

    @property
    def fact_scan_version(self):
        return getattr(self.backend, "fact_scan_version", None)

    @property
    def session_receipt_version(self):
        return getattr(self.backend, "session_receipt_version", None)

    async def inspect_message(self, scope, session_id, message_id):
        from .session_receipts import inspection_inputs, validate_inspection

        inspection_inputs(scope, session_id, message_id)
        result = await self._page_call("inspect_message", scope, session_id, message_id)
        return validate_inspection(result, scope, session_id, message_id)

    async def inspect_session_identity(self):
        return await self._call(self.backend.inspect_session_identity)

    async def inspect_fact(self, *args, **kwargs):
        return await self._call(self.backend.inspect_fact, *args, **kwargs)

    async def read(self, *args, **kwargs):
        return await self._call(self.backend.read, *args, **kwargs)

    async def append(self, *args, **kwargs):
        return await self._call(self.backend.append, *args, **kwargs)

    async def facts(self, *args, **kwargs):
        return await self._call(self.backend.facts, *args, **kwargs)

    async def put_fact(self, *args, **kwargs):
        return await self._call(self.backend.put_fact, *args, **kwargs)

    async def read_page(self, *args, **kwargs):
        return await self._page_call("read_page", *args, **kwargs)

    async def recall(self, *args, **kwargs):
        return await self._page_call("recall", *args, **kwargs)

    async def validate_facts(self, *args, **kwargs):
        return await self._page_call("validate_facts", *args, **kwargs)

    async def scan_facts(self, *args, **kwargs):
        return await self._page_call("scan_facts", *args, **kwargs)

    async def fact_snapshot(self, *args, **kwargs):
        return await self._page_call("fact_snapshot", *args, **kwargs)

    async def _page_call(self, name, *args, **kwargs):
        backend = self.backend
        identity = backend.backend_id
        method = getattr(backend, name, None)
        if not callable(method):
            if name in {"scan_facts", "fact_snapshot", "inspect_message"}:
                raise ValidationError(f"Backend does not provide {name}")
            method = getattr(LegacyMemoryRecallAdapter(backend), name)
        owner, owner_identity = _method_backend(method)
        result = await self._call(method, *args, **kwargs)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise ValidationError("Threaded memory methods must return synchronously")
        if self.backend is not backend or backend.backend_id != identity:
            raise DefinitionMismatch("Memory backend identity changed during recall")
        if owner is not None and owner.backend_id != owner_identity:
            raise DefinitionMismatch("Memory method backend identity changed during recall")
        return result

    async def _call(self, method, *args, **kwargs):
        tracker = current_thread_tracker.get()
        if tracker is None:
            return await asyncio.to_thread(method, *args, **kwargs)
        return await tracker.run(method, *args, group=current_thread_group.get(), **kwargs)


class InMemoryMemory:
    @property
    def session_dataset_id(self):
        return self._session_instance_id

    def inspect_session_identity(self):
        return self.session_dataset_id

    fact_scan_version = 1
    fact_inspection_version = 1
    session_receipt_version = 1

    def __init__(self, *, backend_id=None):
        self.backend_id = backend_id or f"memory:{uuid.uuid4().hex}"
        self._session_instance_id = uuid.uuid4().hex
        self._sessions = {}
        self._facts = {}
        self._fact_positions = {}
        self._fact_generations = {}
        self._lock = threading.RLock()

    def read(self, scope, session_id):
        _require_text(session_id, "Session ID")
        with self._lock:
            records = self._sessions.get((scope.workspace, scope.principal, session_id), [])
            return len(records), [copy.deepcopy(record[1]) for record in records]

    def inspect_message(self, scope, session_id, message_id):
        from .session_receipts import inspection_inputs, validate_inspection

        inspection_inputs(scope, session_id, message_id)
        with self._lock:
            records = self._sessions.get((scope.workspace, scope.principal, session_id), [])
            found = [
                (index, message)
                for index, (identity, message) in enumerate(records, 1)
                if identity == message_id
            ]
            if len(found) > 1:
                raise ValidationError("Ambiguous Session message identity")
            return validate_inspection(
                {
                    "scope": asdict(scope),
                    "session_id": session_id,
                    "message_id": message_id,
                    "revision": len(records),
                    "receipt": {"revision": found[0][0], "message": found[0][1]} if found else None,
                },
                scope,
                session_id,
                message_id,
            )

    def append(self, scope, session_id, message, *, expected_revision, message_id):
        _require_text(session_id, "Session ID")
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

    def inspect_fact(self, scope, namespace, key):
        _fact_inputs(scope, namespace, [])
        _name(key, "Fact key")
        with self._lock:
            return copy.deepcopy(
                self._facts.get((scope.workspace, scope.principal, namespace, key))
            )

    def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        _name(namespace, "Fact namespace")
        _name(key, "Fact key")
        expires_at = _validate_expires_at(expires_at)
        canonical(value)
        identity = (scope.workspace, scope.principal, namespace, key)
        with self._lock:
            actual = self._facts.get(identity, {}).get("version", 0)
            if actual != expected_version:
                raise ValidationError("Fact version conflict")
            namespace_id = identity[:3]
            if identity not in self._facts:
                self._fact_positions.setdefault(namespace_id, []).append(identity)
            self._facts[identity] = {
                "key": key,
                "value": copy.deepcopy(value),
                "version": actual + 1,
                "expires_at": expires_at,
            }
            self._fact_generations[namespace_id] = self._fact_generations.get(namespace_id, 0) + 1
            return actual + 1

    def recall(self, scope, namespace, query):
        binding = _binding(self.backend_id, scope, "facts", namespace, query)
        with self._lock:
            namespace_id = (scope.workspace, scope.principal, namespace)
            snapshot = {"generation": self._fact_generations.get(namespace_id, 0)}
            positions = self._fact_positions.get(namespace_id, [])
            after = 0
            decoded = _decode_cursor(query.cursor, binding)
            if decoded is not None:
                previous, after = decoded
                if set(previous) != {"generation"}:
                    raise ValidationError("Fact recall snapshot is invalid")
                _integer(previous["generation"], "Fact generation")
                if previous != snapshot or after > len(positions):
                    raise ValidationError("Fact recall snapshot is no longer available")
            candidates = [
                (index, self._facts[identity])
                for index, identity in enumerate(
                    positions[after : after + query.scan_limit], start=after + 1
                )
            ]
            return _page(
                candidates,
                query,
                "facts",
                binding,
                snapshot,
                has_more=after + len(candidates) < len(positions),
            )

    def read_page(self, scope, session_id, query):
        binding = _binding(self.backend_id, scope, "session", session_id, query)
        with self._lock:
            records = self._sessions.get((scope.workspace, scope.principal, session_id), [])
            snapshot, before = _session_cursor(query, binding, 0, len(records))
            candidates = [
                (seq, records[seq - 1][1])
                for seq in range(before - 1, max(0, before - query.scan_limit - 1), -1)
            ]
            return _page(
                candidates,
                query,
                "session",
                binding,
                snapshot,
                has_more=before - 1 > len(candidates),
            )

    def validate_facts(self, scope, namespace, items):
        references = _fact_inputs(scope, namespace, items)
        with self._lock:
            now = time.time()
            for reference in references:
                actual = self._facts.get(
                    (scope.workspace, scope.principal, namespace, reference["key"])
                )
                if actual is None:
                    raise ValidationError("Fact reference is no longer current")
                _current_fact(reference, actual["version"], actual["expires_at"], now)

    def scan_facts(self, scope, namespace, query):
        from .fact_scan import _scan_binding, _scan_page, _scan_position

        binding, query = _scan_binding(self.backend_id, scope, namespace, query)
        with self._lock:
            namespace_id = (scope.workspace, scope.principal, namespace)
            positions = self._fact_positions.get(namespace_id, [])
            snapshot, after = _scan_position(
                binding, json.loads(self.fact_snapshot(scope, namespace)), query
            )
            if after > len(positions):
                raise ValidationError("Fact scan position is unavailable")
            candidates = (
                (index, lambda identity=identity: self._facts[identity])
                for index, identity in enumerate(
                    positions[after : after + query.limit + 1], start=after + 1
                )
            )
            return _scan_page(query, binding, snapshot, candidates)

    def fact_snapshot(self, scope, namespace):
        from .fact_scan import _scan_snapshot

        with self._lock:
            if not hasattr(self, "_fact_scan_epoch"):
                self._fact_scan_epoch = uuid.uuid4().hex
            return canonical(
                _scan_snapshot(
                    scope,
                    namespace,
                    self._fact_scan_epoch,
                    self._fact_generations.get((scope.workspace, scope.principal, namespace), 0),
                )
            )

    def close(self):
        pass


class SQLiteMemory:
    fact_scan_version = 1
    fact_inspection_version = 1
    session_receipt_version = 1

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
            CREATE TABLE IF NOT EXISTS memory_session_resource (singleton INTEGER PRIMARY KEY CHECK(singleton=1), dataset_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_facts (workspace TEXT, principal TEXT, namespace TEXT, key TEXT, value TEXT NOT NULL, version INTEGER NOT NULL, expires_at REAL, PRIMARY KEY(workspace,principal,namespace,key));
            CREATE INDEX IF NOT EXISTS memory_facts_recall_scope ON memory_facts(workspace,principal,namespace);
            CREATE TABLE IF NOT EXISTS memory_fact_generations (workspace TEXT, principal TEXT, namespace TEXT, generation INTEGER NOT NULL, PRIMARY KEY(workspace,principal,namespace));
            CREATE TABLE IF NOT EXISTS memory_session_index_state (workspace TEXT, principal TEXT, session TEXT, generation INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0, dirty INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(workspace,principal,session));
            CREATE TABLE IF NOT EXISTS memory_session_items (workspace TEXT, principal TEXT, session TEXT, seq INTEGER NOT NULL, message_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(workspace,principal,session,seq));
            CREATE TABLE IF NOT EXISTS memory_session_receipt_ids (workspace TEXT, principal TEXT, session TEXT, seq INTEGER NOT NULL, message_id TEXT NOT NULL, PRIMARY KEY(workspace,principal,session,seq));
            CREATE INDEX IF NOT EXISTS memory_session_receipt_id_lookup ON memory_session_receipt_ids(workspace,principal,session,message_id,seq);
            CREATE TABLE IF NOT EXISTS memory_session_receipt_state (workspace TEXT, principal TEXT, session TEXT, dirty INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(workspace,principal,session));
            CREATE TRIGGER IF NOT EXISTS memory_session_receipt_insert AFTER INSERT ON memory_sessions BEGIN
                INSERT INTO memory_session_receipt_state VALUES (NEW.workspace,NEW.principal,NEW.session,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_session_receipt_update AFTER UPDATE ON memory_sessions BEGIN
                INSERT INTO memory_session_receipt_state VALUES (NEW.workspace,NEW.principal,NEW.session,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=1;
                INSERT INTO memory_session_receipt_state VALUES (OLD.workspace,OLD.principal,OLD.session,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_session_receipt_delete AFTER DELETE ON memory_sessions BEGIN
                INSERT INTO memory_session_receipt_state VALUES (OLD.workspace,OLD.principal,OLD.session,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_fact_generation_insert AFTER INSERT ON memory_facts BEGIN
                INSERT INTO memory_fact_generations VALUES (NEW.workspace,NEW.principal,NEW.namespace,1) ON CONFLICT(workspace,principal,namespace) DO UPDATE SET generation=generation+1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_fact_generation_update AFTER UPDATE ON memory_facts BEGIN
                INSERT INTO memory_fact_generations VALUES (OLD.workspace,OLD.principal,OLD.namespace,1) ON CONFLICT(workspace,principal,namespace) DO UPDATE SET generation=generation+1;
                INSERT INTO memory_fact_generations SELECT NEW.workspace,NEW.principal,NEW.namespace,1 WHERE NEW.workspace!=OLD.workspace OR NEW.principal!=OLD.principal OR NEW.namespace!=OLD.namespace ON CONFLICT(workspace,principal,namespace) DO UPDATE SET generation=generation+1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_fact_generation_delete AFTER DELETE ON memory_facts BEGIN
                INSERT INTO memory_fact_generations VALUES (OLD.workspace,OLD.principal,OLD.namespace,1) ON CONFLICT(workspace,principal,namespace) DO UPDATE SET generation=generation+1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_session_dirty_insert AFTER INSERT ON memory_sessions BEGIN
                INSERT INTO memory_session_index_state(workspace,principal,session,dirty) VALUES (NEW.workspace,NEW.principal,NEW.session,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_session_dirty_update AFTER UPDATE ON memory_sessions BEGIN
                INSERT INTO memory_session_index_state(workspace,principal,session,dirty) VALUES (OLD.workspace,OLD.principal,OLD.session,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=1;
                INSERT INTO memory_session_index_state(workspace,principal,session,dirty) VALUES (NEW.workspace,NEW.principal,NEW.session,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_session_dirty_delete AFTER DELETE ON memory_sessions BEGIN
                INSERT INTO memory_session_index_state(workspace,principal,session,dirty) VALUES (OLD.workspace,OLD.principal,OLD.session,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_session_generation_delete AFTER DELETE ON memory_sessions BEGIN
                INSERT INTO memory_session_index_state VALUES (OLD.workspace,OLD.principal,OLD.session,1,0,1) ON CONFLICT(workspace,principal,session) DO UPDATE SET generation=generation+1,dirty=1;
            END;
            CREATE TRIGGER IF NOT EXISTS memory_session_generation_clear AFTER UPDATE ON memory_sessions WHEN json_valid(OLD.data) AND json_valid(NEW.data) AND json_array_length(OLD.data)>0 AND json_array_length(NEW.data)=0 BEGIN
                UPDATE memory_session_index_state SET generation=generation+1,dirty=1 WHERE workspace=OLD.workspace AND principal=OLD.principal AND session=OLD.session;
            END;
        """)

        with self.store.transaction():
            self.store.conn.execute(
                "INSERT OR IGNORE INTO memory_session_resource VALUES (1,?)", (uuid.uuid4().hex,)
            )
            self._session_dataset_id = self.store.conn.execute(
                "SELECT dataset_id FROM memory_session_resource WHERE singleton=1"
            ).fetchone()[0]

    @property
    def session_dataset_id(self):
        with self.store.transaction():
            row = self.store.conn.execute(
                "SELECT dataset_id FROM memory_session_resource WHERE singleton=1"
            ).fetchone()
        if row is None or row[0] != self._session_dataset_id:
            raise DefinitionMismatch("SQLite Session dataset changed")
        return self._session_dataset_id

    def inspect_session_identity(self):
        return self.session_dataset_id

    def _records(self, scope, session_id):
        _require_text(session_id, "Session ID")
        row = self.store.conn.execute(
            "SELECT data FROM memory_sessions WHERE workspace=? AND principal=? AND session=?",
            (scope.workspace, scope.principal, session_id),
        ).fetchone()
        return json.loads(row[0]) if row else []

    def read(self, scope, session_id):
        records = self._records(scope, session_id)
        return len(records), [r[1] for r in records]

    def inspect_message(self, scope, session_id, message_id):
        from .session_receipts import inspection_inputs, validate_inspection

        inspection_inputs(scope, session_id, message_id)
        with self.store.transaction():
            _, revision = self._sync_session_index(scope, session_id)
            self._sync_receipt_ids(scope, session_id)
            rows = self.store.conn.execute(
                "SELECT i.seq,i.data FROM memory_session_receipt_ids r JOIN memory_session_items i USING(workspace,principal,session,seq) WHERE r.workspace=? AND r.principal=? AND r.session=? AND r.message_id=? ORDER BY r.seq LIMIT 2",
                (scope.workspace, scope.principal, session_id, message_id),
            ).fetchall()
            if len(rows) > 1:
                raise ValidationError("Ambiguous Session message identity")
            return validate_inspection(
                {
                    "scope": asdict(scope),
                    "session_id": session_id,
                    "message_id": message_id,
                    "revision": revision,
                    "receipt": {"revision": rows[0]["seq"], "message": json.loads(rows[0]["data"])}
                    if rows
                    else None,
                },
                scope,
                session_id,
                message_id,
            )

    def append(self, scope, session_id, message, *, expected_revision, message_id):
        canonical(message)
        with self.store.transaction():
            records = self._records(scope, session_id)
            self._sync_session_index(scope, session_id, records=records)
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
            self.store.conn.execute(
                "INSERT INTO memory_session_items VALUES (?,?,?,?,?,?)",
                (
                    scope.workspace,
                    scope.principal,
                    session_id,
                    len(records),
                    message_id,
                    canonical(message),
                ),
            )
            self.store.conn.execute(
                "UPDATE memory_session_index_state SET revision=?,dirty=0 WHERE workspace=? AND principal=? AND session=?",
                (len(records), scope.workspace, scope.principal, session_id),
            )
            self._sync_receipt_ids(scope, session_id, records=records)
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

    def inspect_fact(self, scope, namespace, key):
        _fact_inputs(scope, namespace, [])
        _name(key, "Fact key")
        row = self.store.conn.execute(
            "SELECT key,value,version,expires_at FROM memory_facts WHERE workspace=? AND principal=? AND namespace=? AND key=?",
            (scope.workspace, scope.principal, namespace, key),
        ).fetchone()
        return (
            None
            if row is None
            else {
                "key": row[0],
                "value": json.loads(row[1]),
                "version": row[2],
                "expires_at": row[3],
            }
        )

    def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        _name(namespace, "Fact namespace")
        _name(key, "Fact key")
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

    def recall(self, scope, namespace, query):
        binding = _binding(self.backend_id, scope, "facts", namespace, query)
        parameters = (scope.workspace, scope.principal, namespace)
        with self.store.transaction():
            row = self.store.conn.execute(
                "SELECT generation FROM memory_fact_generations WHERE workspace=? AND principal=? AND namespace=?",
                parameters,
            ).fetchone()
            snapshot = {"generation": row[0] if row else 0}
            after = 0
            decoded = _decode_cursor(query.cursor, binding)
            if decoded is not None:
                previous, after = decoded
                if set(previous) != {"generation"}:
                    raise ValidationError("Fact recall snapshot is invalid")
                _integer(previous["generation"], "Fact generation")
                if previous != snapshot:
                    raise ValidationError("Fact recall snapshot is no longer available")
            rows = self.store.conn.execute(
                "SELECT rowid AS position,key,value,version,expires_at FROM memory_facts WHERE workspace=? AND principal=? AND namespace=? AND rowid>? ORDER BY rowid LIMIT ?",
                (*parameters, after, query.scan_limit),
            ).fetchall()
            candidates = [
                (
                    row["position"],
                    {
                        "key": row["key"],
                        "value": json.loads(row["value"]),
                        "version": row["version"],
                        "expires_at": row["expires_at"],
                    },
                )
                for row in rows
            ]
            has_more = (
                bool(rows)
                and self.store.conn.execute(
                    "SELECT 1 FROM memory_facts WHERE workspace=? AND principal=? AND namespace=? AND rowid>? LIMIT 1",
                    (*parameters, rows[-1]["position"]),
                ).fetchone()
                is not None
            )
            return _page(candidates, query, "facts", binding, snapshot, has_more=has_more)

    def scan_facts(self, scope, namespace, query):
        from .errors import BudgetExceeded
        from .fact_scan import (
            _scan_binding,
            _scan_epoch,
            _scan_page,
            _scan_position,
            _scan_snapshot,
        )

        binding, query = _scan_binding(self.backend_id, scope, namespace, query)
        parameters = (scope.workspace, scope.principal, namespace)
        with self.store.transaction():
            row = self.store.conn.execute(
                "SELECT generation FROM memory_fact_generations WHERE workspace=? AND principal=? AND namespace=?",
                parameters,
            ).fetchone()
            snapshot, after = _scan_position(
                binding,
                _scan_snapshot(scope, namespace, _scan_epoch(self.store), row[0] if row else 0),
                query,
            )
            rows = self.store.conn.execute(
                "SELECT rowid AS position,substr(CAST(key AS BLOB),1,?) AS key,substr(CAST(value AS BLOB),1,?) AS payload,version,expires_at FROM memory_facts WHERE workspace=? AND principal=? AND namespace=? AND rowid>? ORDER BY rowid LIMIT ?",
                (query.max_bytes + 1, query.max_bytes + 1, *parameters, after, query.limit + 1),
            )

            def load(row):
                if len(row["payload"]) > query.max_bytes or len(row["key"]) > query.max_bytes:
                    raise BudgetExceeded("Fact record does not fit scan byte budget")
                return {
                    "key": row["key"].decode("utf-8"),
                    "value": json.loads(row["payload"]),
                    "version": row["version"],
                    "expires_at": row["expires_at"],
                }

            try:
                return _scan_page(
                    query,
                    binding,
                    snapshot,
                    ((row["position"], lambda row=row: load(row)) for row in rows),
                )
            finally:
                rows.close()

    def fact_snapshot(self, scope, namespace):
        from .fact_scan import _scan_epoch, _scan_snapshot

        _fact_inputs(scope, namespace, [])
        with self.store.transaction():
            row = self.store.conn.execute(
                "SELECT generation FROM memory_fact_generations WHERE workspace=? AND principal=? AND namespace=?",
                (scope.workspace, scope.principal, namespace),
            ).fetchone()
            return canonical(
                _scan_snapshot(scope, namespace, _scan_epoch(self.store), row[0] if row else 0)
            )

    def _sync_receipt_ids(self, scope, session_id, *, records=None):
        """Retain original string IDs, independently invalidated by older writers."""
        parameters = (scope.workspace, scope.principal, session_id)
        state = self.store.conn.execute(
            "SELECT dirty FROM memory_session_receipt_state WHERE workspace=? AND principal=? AND session=?",
            parameters,
        ).fetchone()
        if state is not None and not state["dirty"]:
            return
        if records is None:
            records = self._records(scope, session_id)
        self.store.conn.execute(
            "DELETE FROM memory_session_receipt_ids WHERE workspace=? AND principal=? AND session=?",
            parameters,
        )
        self.store.conn.executemany(
            "INSERT INTO memory_session_receipt_ids VALUES (?,?,?,?,?)",
            [
                (*parameters, seq, identity)
                for seq, (identity, _) in enumerate(records, 1)
                if isinstance(identity, str)
            ],
        )
        self.store.conn.execute(
            "INSERT INTO memory_session_receipt_state VALUES (?,?,?,0) ON CONFLICT(workspace,principal,session) DO UPDATE SET dirty=0",
            parameters,
        )

    def _sync_session_index(self, scope, session_id, *, records=None):
        parameters = (scope.workspace, scope.principal, session_id)
        state = self.store.conn.execute(
            "SELECT generation,revision,dirty FROM memory_session_index_state WHERE workspace=? AND principal=? AND session=?",
            parameters,
        ).fetchone()
        if state is not None and not state["dirty"]:
            return state["generation"], state["revision"]
        if records is None:
            records = self._records(scope, session_id)
        previous = self.store.conn.execute(
            "SELECT seq,message_id,data FROM memory_session_items WHERE workspace=? AND principal=? AND session=? ORDER BY seq",
            parameters,
        ).fetchall()
        normalized = [
            (index, identity, canonical(message))
            for index, (identity, message) in enumerate(records, 1)
        ]
        generation = state["generation"] if state is not None else 0
        if len(previous) > len(normalized) or any(
            (row["seq"], row["message_id"], row["data"]) != record
            for row, record in zip(previous, normalized, strict=False)
        ):
            generation += 1
        self.store.conn.execute(
            "DELETE FROM memory_session_items WHERE workspace=? AND principal=? AND session=?",
            parameters,
        )
        self.store.conn.executemany(
            "INSERT INTO memory_session_items VALUES (?,?,?,?,?,?)",
            [(*parameters, seq, identity, data) for seq, identity, data in normalized],
        )
        self.store.conn.execute(
            "INSERT INTO memory_session_index_state VALUES (?,?,?,?,?,0) ON CONFLICT(workspace,principal,session) DO UPDATE SET generation=excluded.generation,revision=excluded.revision,dirty=0",
            (*parameters, generation, len(records)),
        )
        self._sync_receipt_ids(scope, session_id, records=records)
        return generation, len(records)

    def read_page(self, scope, session_id, query):
        binding = _binding(self.backend_id, scope, "session", session_id, query)
        with self.store.transaction():
            generation, revision = self._sync_session_index(scope, session_id)
            snapshot, before = _session_cursor(query, binding, generation, revision)
            rows = self.store.conn.execute(
                "SELECT seq,data FROM memory_session_items WHERE workspace=? AND principal=? AND session=? AND seq<? AND seq<=? ORDER BY seq DESC LIMIT ?",
                (
                    scope.workspace,
                    scope.principal,
                    session_id,
                    before,
                    snapshot["revision"],
                    query.scan_limit,
                ),
            ).fetchall()
            candidates = [(row["seq"], json.loads(row["data"])) for row in rows]
            has_more = (
                bool(rows)
                and self.store.conn.execute(
                    "SELECT 1 FROM memory_session_items WHERE workspace=? AND principal=? AND session=? AND seq<? AND seq<=? LIMIT 1",
                    (
                        scope.workspace,
                        scope.principal,
                        session_id,
                        rows[-1]["seq"],
                        snapshot["revision"],
                    ),
                ).fetchone()
                is not None
            )
            return _page(candidates, query, "session", binding, snapshot, has_more=has_more)

    def validate_facts(self, scope, namespace, items):
        references = _fact_inputs(scope, namespace, items)
        with self.store.transaction():
            now = time.time()
            for reference in references:
                row = self.store.conn.execute(
                    "SELECT version,expires_at FROM memory_facts WHERE workspace=? AND principal=? AND namespace=? AND key=?",
                    (scope.workspace, scope.principal, namespace, reference["key"]),
                ).fetchone()
                if row is None:
                    raise ValidationError("Fact reference is no longer current")
                _current_fact(reference, row["version"], row["expires_at"], now)

    def close(self):
        if self._owns_store:
            self.store.close()


def _session_cursor(query, binding, generation, revision):
    snapshot = {"generation": generation, "revision": revision}
    before = revision + 1
    decoded = _decode_cursor(query.cursor, binding)
    if decoded is not None:
        snapshot, before = decoded
        if set(snapshot) != {"generation", "revision"}:
            raise ValidationError("Session recall snapshot is invalid")
        _integer(snapshot["generation"], "Session generation")
        _integer(snapshot["revision"], "Session revision")
        if (
            snapshot["generation"] != generation
            or snapshot["revision"] > revision
            or before > snapshot["revision"]
            or before < 1
        ):
            raise ValidationError("Session recall snapshot is no longer available")
    return snapshot, before
