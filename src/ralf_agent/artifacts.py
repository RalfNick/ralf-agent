"""Explicit scoped JSON artifacts, independent of execution and memory authority."""

import copy
import hashlib
import json
import sqlite3
import stat
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .context_budget import _positive
from .errors import (
    AuthorizationDenied,
    BudgetExceeded,
    DefinitionMismatch,
    NotFound,
    ValidationError,
)
from .memory import _validate_expires_at
from .types import Scope, canonical, digest


def _name(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValidationError(f"Artifact {label} must be bounded non-empty text")
    return value


def _hex(value):
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


@dataclass(frozen=True)
class ArtifactReference:
    backend_id: str
    workspace: str
    principal: str
    namespace: str
    content_digest: str
    byte_length: int
    expires_at: float | None
    artifact_id: str

    def __post_init__(self):
        for name in ("backend_id", "workspace", "principal", "namespace"):
            _name(getattr(self, name), name)
        _positive(self.byte_length, "Artifact byte length", 1024 * 1024)
        if not _hex(self.content_digest) or not _hex(self.artifact_id):
            raise ValidationError("Artifact identities must be SHA256 digests")
        object.__setattr__(self, "expires_at", _validate_expires_at(self.expires_at))
        metadata = asdict(self)
        metadata.pop("artifact_id")
        if digest(metadata) != self.artifact_id:
            raise ValidationError("Artifact reference metadata does not match its identity")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValidationError("Artifact reference requires exact metadata fields")
        return cls(**copy.deepcopy(value))


class ArtifactStore(Protocol):
    backend_id: str

    def put(self, scope: Scope, namespace: str, value, *, expires_at=None) -> ArtifactReference: ...
    def get(self, scope: Scope, reference: ArtifactReference, *, max_bytes=None): ...
    def delete(self, scope: Scope, reference: ArtifactReference) -> bool: ...
    def close(self) -> None: ...


class AsyncArtifactStore(Protocol):
    backend_id: str

    async def put(
        self, scope: Scope, namespace: str, value, *, expires_at=None
    ) -> ArtifactReference: ...
    async def get(self, scope: Scope, reference: ArtifactReference, *, max_bytes=None): ...
    async def delete(self, scope: Scope, reference: ArtifactReference) -> bool: ...
    async def aclose(self) -> None: ...


class _Artifacts:
    def _configure(self, backend_id, max_bytes, capacity):
        self._backend_id = _name(backend_id, "backend ID")
        self._max_bytes = _positive(max_bytes, "Artifact byte limit", 1024 * 1024)
        self._capacity = _positive(capacity, "Artifact capacity", 100000)
        self._lock = threading.RLock()
        self._closed = False

    @property
    def backend_id(self):
        return self._backend_id

    @property
    def identity(self):
        return {
            "kind": type(self).__name__,
            "version": "1",
            "backend_id": self.backend_id,
            "max_bytes": self._max_bytes,
            "capacity": self._capacity,
        }

    def _open(self):
        if self._closed:
            raise ValidationError("Artifact store is closed")

    @staticmethod
    def _scope(scope):
        if not isinstance(scope, Scope):
            raise ValidationError("Artifact operations require a trusted Scope")
        _name(scope.workspace, "workspace")
        _name(scope.principal, "principal")

    def _prepare(self, scope, namespace, value, expires_at):
        self._scope(scope)
        _name(namespace, "namespace")
        text = canonical(value)
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            raise ValidationError("Artifact must contain valid UTF-8") from None
        if size > self._max_bytes:
            raise ValidationError("Artifact payload exceeds its byte limit")
        metadata = {
            "backend_id": self.backend_id,
            "workspace": scope.workspace,
            "principal": scope.principal,
            "namespace": namespace,
            "content_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "byte_length": size,
            "expires_at": _validate_expires_at(expires_at),
        }
        return ArtifactReference(**metadata, artifact_id=digest(metadata)), text

    def _reference(self, scope, reference, *, read=False, max_bytes=None):
        self._scope(scope)
        if not isinstance(reference, ArtifactReference):
            raise ValidationError("Artifact operations require an ArtifactReference")
        ref = ArtifactReference.from_dict(reference.to_dict())
        if (ref.workspace, ref.principal) != (scope.workspace, scope.principal):
            raise AuthorizationDenied("Artifact belongs to another workspace or principal")
        if ref.backend_id != self.backend_id:
            raise DefinitionMismatch("Artifact belongs to a different backend")
        if read:
            maximum = (
                self._max_bytes
                if max_bytes is None
                else _positive(max_bytes, "Artifact read limit", self._max_bytes)
            )
            if ref.byte_length > maximum:
                raise ValidationError("Artifact exceeds the requested read limit")
            if ref.expires_at is not None and ref.expires_at <= time.time():
                raise NotFound("Artifact is expired")
        return ref

    def _decode(self, scope, ref, payload, receipt, max_bytes):
        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError:
                raise ValidationError("Stored artifact payload is invalid") from None
        if receipt != canonical(ref.to_dict()):
            raise ValidationError("Stored artifact metadata changed")
        try:
            value = json.loads(payload)
            size = len(payload.encode("utf-8"))
        except (ValueError, UnicodeEncodeError, AttributeError):
            raise ValidationError("Stored artifact payload is invalid") from None
        if (
            size != ref.byte_length
            or digest(value) != ref.content_digest
            or canonical(value) != payload
        ):
            raise ValidationError("Stored artifact content failed integrity validation")
        self._reference(scope, ref, read=True, max_bytes=max_bytes)
        return value

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *args):
        self.close()


class InMemoryArtifactStore(_Artifacts):
    def __init__(self, *, backend_id=None, max_bytes=1024 * 1024, capacity=1024):
        self._configure(
            "memory-artifacts:" + uuid.uuid4().hex if backend_id is None else backend_id,
            max_bytes,
            capacity,
        )
        self._records = {}

    def put(self, scope, namespace, value, *, expires_at=None):
        with self._lock:
            self._open()
            ref, text = self._prepare(scope, namespace, value, expires_at)
            if ref.artifact_id not in self._records:
                count = sum(
                    1
                    for r, _ in self._records.values()
                    if (r.workspace, r.principal, r.namespace)
                    == (scope.workspace, scope.principal, namespace)
                )
                if count >= self._capacity:
                    raise BudgetExceeded(
                        "Artifact namespace capacity is full; explicitly delete retained entries"
                    )
                # Retain independent metadata; callers must not hold the object
                # used for integrity checks or namespace capacity accounting.
                self._records[ref.artifact_id] = (ArtifactReference.from_dict(ref.to_dict()), text)
            else:
                stored, payload = self._records[ref.artifact_id]
                if stored.to_dict() != ref.to_dict() or payload != text:
                    raise ValidationError("Stored artifact identity conflicts with content")
            return ref

    def get(self, scope, reference, *, max_bytes=None):
        with self._lock:
            self._open()
            ref = self._reference(scope, reference, read=True, max_bytes=max_bytes)
            record = self._records.get(ref.artifact_id)
            if record is None:
                raise NotFound("Artifact is unavailable")
            stored, text = record
            return self._decode(scope, ref, text, canonical(stored.to_dict()), max_bytes)

    def delete(self, scope, reference):
        with self._lock:
            self._open()
            ref = self._reference(scope, reference)
            return self._records.pop(ref.artifact_id, None) is not None

    def close(self):
        with self._lock:
            self._closed = True


class SQLiteArtifactStore(_Artifacts):
    def __init__(self, path, *, backend_id=None, max_bytes=1024 * 1024, capacity=1024):
        self.path = str(Path(path).expanduser().resolve())
        self._configure(
            "sqlite-artifacts:" + digest(self.path) if backend_id is None else backend_id,
            max_bytes,
            capacity,
        )
        self._file = self._file_identity(required=False)
        self._close_complete = False
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False, timeout=10
        )
        try:
            self._assert_file()
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS ralf_artifacts (
                    artifact_id TEXT PRIMARY KEY, workspace TEXT NOT NULL,
                    principal TEXT NOT NULL, namespace TEXT NOT NULL,
                    receipt TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ralf_artifact_scope ON ralf_artifacts(workspace,principal,namespace);
            """)
        except BaseException:
            self.close()
            raise

    def _file_identity(self, *, required=True):
        try:
            info = Path(self.path).lstat()
        except FileNotFoundError:
            if not required:
                return None
            raise ValidationError("Artifact database file identity changed") from None
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValidationError("Artifact database requires a regular file without hard links")
        return info.st_dev, info.st_ino

    def _assert_file(self):
        actual = self._file_identity()
        if self._file is not None and actual != self._file:
            raise ValidationError("Artifact database file identity changed")
        self._file = actual

    def _open(self):
        super()._open()
        self._assert_file()
        if self.conn.in_transaction:
            raise ValidationError("Artifact database has an external uncommitted transaction")

    def put(self, scope, namespace, value, *, expires_at=None):
        with self._lock:
            self._open()
            ref, text = self._prepare(scope, namespace, value, expires_at)
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute(
                    "SELECT receipt,substr(CAST(payload AS BLOB),1,?) FROM ralf_artifacts WHERE artifact_id=?",
                    (self._max_bytes + 1, ref.artifact_id),
                ).fetchone()
                if row is None:
                    count = self.conn.execute(
                        "SELECT COUNT(*) FROM ralf_artifacts WHERE workspace=? AND principal=? AND namespace=?",
                        (scope.workspace, scope.principal, namespace),
                    ).fetchone()[0]
                    if count >= self._capacity:
                        raise BudgetExceeded(
                            "Artifact namespace capacity is full; explicitly delete retained entries"
                        )
                    self.conn.execute(
                        "INSERT INTO ralf_artifacts VALUES (?,?,?,?,?,?)",
                        (
                            ref.artifact_id,
                            scope.workspace,
                            scope.principal,
                            namespace,
                            canonical(ref.to_dict()),
                            text,
                        ),
                    )
                elif row != (canonical(ref.to_dict()), text.encode("utf-8")):
                    raise ValidationError("Stored artifact identity conflicts with content")
                self._assert_file()
                self.conn.execute("COMMIT")
            except BaseException:
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise
            return ref

    def get(self, scope, reference, *, max_bytes=None):
        with self._lock:
            self._open()
            ref = self._reference(scope, reference, read=True, max_bytes=max_bytes)
            row = self.conn.execute(
                "SELECT receipt,substr(CAST(payload AS BLOB),1,?) FROM ralf_artifacts WHERE artifact_id=? AND workspace=? AND principal=? AND namespace=?",
                (
                    self._max_bytes + 1,
                    ref.artifact_id,
                    scope.workspace,
                    scope.principal,
                    ref.namespace,
                ),
            ).fetchone()
            if row is None:
                raise NotFound("Artifact is unavailable")
            value = self._decode(scope, ref, row[1], row[0], max_bytes)
            self._assert_file()
            return value

    def delete(self, scope, reference):
        with self._lock:
            self._open()
            ref = self._reference(scope, reference)
            cursor = self.conn.execute(
                "DELETE FROM ralf_artifacts WHERE artifact_id=? AND workspace=? AND principal=? AND namespace=?",
                (ref.artifact_id, scope.workspace, scope.principal, ref.namespace),
            )
            self._assert_file()
            return cursor.rowcount == 1

    def close(self):
        with self._lock:
            if self._close_complete:
                return
            self._closed = True
            self.conn.close()
            self._close_complete = True
