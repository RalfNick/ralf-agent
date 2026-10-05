"""Independent, replaceable short-term and explicit long-term memory ports."""

import copy
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Protocol

from .errors import IdempotencyConflict, ValidationError
from .storage import SQLiteStore
from .types import Scope, canonical


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
        self.backend_id = f"sqlite-memory:{Path(self.store.path).resolve()}"
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
