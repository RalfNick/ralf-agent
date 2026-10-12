"""Scoped file CAS and downstream effect receipts; no execution authority."""

import copy
import hashlib
import json
import uuid
from dataclasses import asdict
from typing import Protocol

from .errors import IdempotencyConflict, ValidationError
from .types import Scope, canonical, digest
from .workspace import (
    DEFAULT_SCOPES,
    InMemoryWorkspace,
    WorkspaceError,
    WorkspacePort,
    _bound,
    _path,
    _snapshot,
    _utf8,
)


class WritableWorkspacePort(WorkspacePort, Protocol):
    def write_text(
        self, scope: Scope, path: str, text: str, *, expected_version: str | None, effect_key: str
    ) -> dict: ...

    def query_write(self, scope: Scope, effect_key: str) -> dict | None: ...


def _key(value):
    _utf8(value, "Workspace effect key", max_bytes=256)
    if not value.strip():
        raise ValidationError("Workspace effect key requires nonblank text")
    return value


def _version(value):
    if type(value) is not str or len(value) != 64 or set(value) - set("0123456789abcdef"):
        raise ValidationError("Workspace write version requires a lowercase SHA256 identity")
    return value


def _scope(scope):
    if type(scope) is not Scope:
        raise ValidationError("Workspace write evidence requires an ordinary Scope")
    for value in (scope.workspace, scope.principal):
        _utf8(value, "Workspace write Scope")
    return asdict(scope)


def write_request(scope, path, text, expected_version, effect_key, *, max_bytes):
    """Pure request validation; it does not authorize or perform a write."""
    _bound(max_bytes, 16777216, "write byte")
    _path(path)
    _key(effect_key)
    if expected_version is not None:
        _version(expected_version)
    data = _utf8(text, "Workspace write content", max_bytes=max_bytes)
    if b"\x00" in data:
        raise ValidationError("Workspace text cannot contain embedded NUL")
    return {
        "scope": _scope(scope),
        "path": path,
        "text": text,
        "expected_version": expected_version,
    }, data


def _request(request, scope, effect_key):
    if type(request) is not dict or set(request) != {"scope", "path", "text", "expected_version"}:
        raise ValidationError("Workspace write requires its exact original request")
    value, data = write_request(
        scope,
        request["path"],
        request["text"],
        request["expected_version"],
        effect_key,
        max_bytes=16777216,
    )
    if canonical(value) != canonical(request):
        raise ValidationError("Workspace write request differs from its original Scope")
    return value, data


def write_receipt(scope, effect_key, request, file_version):
    """Build evidence only after the adapter has confirmed its actual file effect."""
    request, data = _request(request, scope, effect_key)
    return {
        "kind": "workspace-write-receipt",
        "version": "1",
        "scope": _scope(scope),
        "effect_key": _key(effect_key),
        "request_digest": digest(request),
        "path": request["path"],
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "file_version": _version(file_version),
    }


def validate_write_receipt(value, scope, effect_key, request):
    if type(value) is not dict or type(value.get("file_version")) is not str:
        raise ValidationError("Workspace write returned invalid receipt evidence")
    expected = write_receipt(scope, effect_key, request, value["file_version"])
    if canonical(expected) != canonical(value):
        raise ValidationError("Workspace write receipt differs from the original request")
    return json.loads(canonical(expected))


class InMemoryWritableWorkspace(InMemoryWorkspace):
    """Process-bound mutable root; use the durable file adapter for restarts."""

    def __init__(
        self, files=None, *, version, scopes=DEFAULT_SCOPES, max_bytes=1048576, capacity=1024
    ):
        _bound(max_bytes, 16777216, "write byte")
        _bound(capacity, 100000, "write receipt capacity")
        super().__init__(files, version=version, scopes=scopes)
        self._max_write_bytes, self._write_capacity = max_bytes, capacity
        self._identity = {
            **self._identity,
            "kind": "memory-writable-workspace",
            "dataset_uuid": uuid.uuid4().hex,
            "max_write_bytes": max_bytes,
            "write_capacity": capacity,
        }
        self._write_revision, self._write_receipts = 0, {}
        self._write_total = sum(len(data) for data in self._files.values())
        self._file_versions = {
            path: self._revision(path, data, 0) for path, data in self._files.items()
        }

    def _revision(self, path, data, revision):
        return digest(
            {
                "dataset_uuid": self._identity["dataset_uuid"],
                "path": path,
                "revision": revision,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    def _record(self, path):
        record = super()._record(path)
        record["version"] = (
            self._file_versions[path] if path in self._files else digest(self._file_versions)
        )
        return record

    def read_text(self, scope, path, *, max_bytes=1048576):
        _path(path)
        _bound(max_bytes, 16777216, "byte")
        with self._lock:
            self._check(scope)
            if path not in self._files:
                raise WorkspaceError("Workspace file is unavailable")
            data = self._files[path]
            if len(data) > max_bytes:
                raise WorkspaceError("Workspace file exceeds its byte allowance")
            return _snapshot(path, data, self._file_versions[path])

    def write_text(self, scope, path, text, *, expected_version, effect_key):
        with self._lock:
            self._check(scope)
            request, data = write_request(
                scope, path, text, expected_version, effect_key, max_bytes=self._max_write_bytes
            )
            key = scope, effect_key
            receipt = self._write_receipts.get(key)
            if receipt is not None:
                if receipt["request_digest"] != digest(request):
                    raise IdempotencyConflict("Workspace effect key already pins another request")
                return validate_write_receipt(receipt, scope, effect_key, request)
            if len(self._write_receipts) >= self._write_capacity:
                raise WorkspaceError("Workspace write receipt capacity is full")
            parent = path.rpartition("/")[0]
            if parent not in self._directories or path in self._directories:
                raise WorkspaceError("Workspace write requires an existing ordinary parent")
            if self._file_versions.get(path) != expected_version:
                raise WorkspaceError("Workspace target differs from the expected original version")
            total = self._write_total + len(data) - len(self._files.get(path, b""))
            if total > 67108864 or (path not in self._files and len(self._files) >= 4096):
                raise WorkspaceError("Workspace data exceeds its root allowance")
            revision = self._write_revision + 1
            version = self._revision(path, data, revision)
            receipt = write_receipt(scope, effect_key, request, version)
            self._files[path], self._file_versions[path] = data, version
            self._write_total, self._write_revision = total, revision
            self._write_receipts[key] = receipt
            return copy.deepcopy(receipt)

    def query_write(self, scope, effect_key):
        with self._lock:
            self._check(scope)
            _key(effect_key)
            return copy.deepcopy(self._write_receipts.get((scope, effect_key)))
