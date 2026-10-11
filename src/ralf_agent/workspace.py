"""Replaceable, bounded, explicitly authorized read-only workspace data."""

import copy
import hashlib
import threading
from typing import Protocol

from .errors import AuthorizationDenied, RalfError, ValidationError
from .types import Scope, digest


class WorkspaceError(RalfError):
    code = "workspace_error"


class WorkspacePort(Protocol):
    identity: dict

    def stat(self, scope: Scope, path: str) -> dict: ...
    def list(self, scope: Scope, directory: str = "", *, max_entries: int = 100) -> dict: ...
    def read_text(self, scope: Scope, path: str, *, max_bytes: int = 1048576) -> dict: ...
    def close(self) -> None: ...


DEFAULT_SCOPES = (Scope(),)
PROTECTED = frozenset({".git", ".ralf"})


def _utf8(value, label, *, max_bytes=None):
    if type(value) is not str:
        raise ValidationError(f"{label} requires UTF-8 text")
    if max_bytes is not None and len(value) > max_bytes:
        raise ValidationError(f"{label} exceeds its byte allowance")
    try:
        if max_bytes is None:
            return value.encode("utf-8")
        chunks, size = [], 0
        for offset in range(0, len(value), 8192):
            chunk = value[offset : offset + 8192].encode("utf-8")
            size += len(chunk)
            if size > max_bytes:
                raise ValidationError(f"{label} exceeds its byte allowance")
            chunks.append(chunk)
        return b"".join(chunks)
    except UnicodeError:
        raise ValidationError(f"{label} requires UTF-8 text") from None


def _path(value, *, directory=False):
    encoded = _utf8(value, "Workspace path", max_bytes=4096)
    parts = value.split("/")
    if directory and value == "":
        return ()
    if (
        not encoded
        or len(encoded) > 4096
        or len(parts) > 128
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(part in {"", ".", ".."} or part.casefold() in PROTECTED for part in parts)
    ):
        raise ValidationError("Workspace path requires a bounded canonical relative address")
    return tuple(parts)


def _bound(value, maximum, label):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValidationError(f"Workspace {label} limit requires an integer in [1,{maximum}]")


def _configuration(version, scopes):
    if not _utf8(version, "Workspace version").strip():
        raise ValidationError("Workspace requires an explicit behavior version")
    if (
        type(scopes) not in (tuple, list)
        or not 1 <= len(scopes) <= 256
        or any(type(scope) is not Scope for scope in scopes)
    ):
        raise ValidationError("Workspace requires one to256 distinct explicit Scopes")
    for scope in scopes:
        _utf8(scope.workspace, "Workspace Scope")
        _utf8(scope.principal, "Workspace principal")
    if len(set(scopes)) != len(scopes):
        raise ValidationError("Workspace requires distinct explicit Scopes")
    return tuple(sorted(scopes, key=lambda item: (item.workspace, item.principal)))


def _authorize(scope, scopes):
    if (
        type(scope) is not Scope
        or type(scope.workspace) is not str
        or type(scope.principal) is not str
    ):
        raise AuthorizationDenied("Workspace Scope requires ordinary UTF-8 string fields")
    try:
        _utf8(scope.workspace, "Workspace Scope")
        _utf8(scope.principal, "Workspace principal")
    except ValidationError:
        raise AuthorizationDenied("Workspace Scope requires ordinary UTF-8 string fields") from None
    if scope not in scopes:
        raise AuthorizationDenied("Workspace Scope is outside the host allowance")


def _scopes_json(scopes):
    return [{"workspace": scope.workspace, "principal": scope.principal} for scope in scopes]


def _snapshot(path, data, version):
    if b"\x00" in data:
        raise WorkspaceError("Workspace text cannot contain embedded NUL")
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        raise WorkspaceError("Workspace file is not valid UTF-8 text") from None
    return {
        "path": path,
        "text": text,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "version": version,
    }


class InMemoryWorkspace:
    def __init__(self, files=None, *, version, scopes=DEFAULT_SCOPES):
        self._scopes = _configuration(version, scopes)
        self._version = version
        if files is None:
            files = {}
        if type(files) is not dict or len(files) > 4096:
            raise ValidationError("Memory Workspace requires at most4096 explicit files")
        values, directories, total = {}, {""}, 0
        for path, text in files.items():
            parts = _path(path)
            data = _utf8(text, "Workspace content", max_bytes=min(16777216, 67108864 - total))
            total += len(data)
            if len(data) > 16777216 or total > 67108864:
                raise ValidationError("Memory Workspace data exceeds its byte allowance")
            values[path] = data
            directories.update("/".join(parts[:index]) for index in range(1, len(parts)))
        if set(values) & directories:
            raise ValidationError("Workspace files conflict with directory addresses")
        self._files, self._directories = values, frozenset(directories)
        self._lock, self._closed = threading.RLock(), False
        self._identity = {
            "kind": "memory-workspace",
            "version": "1",
            "behavior_version": version,
            "scopes": _scopes_json(self._scopes),
            "content_fingerprint": digest(
                {path: hashlib.sha256(data).hexdigest() for path, data in values.items()}
            ),
        }

    @property
    def identity(self):
        return copy.deepcopy(self._identity)

    def _check(self, scope):
        _authorize(scope, self._scopes)
        if self._closed:
            raise WorkspaceError("Workspace is closing or closed")

    def _record(self, path):
        if path in self._files:
            data = self._files[path]
            return {
                "path": path,
                "kind": "file",
                "size": len(data),
                "version": hashlib.sha256(data).hexdigest(),
            }
        if path in self._directories:
            return {
                "path": path,
                "kind": "directory",
                "size": None,
                "version": self._identity["content_fingerprint"],
            }
        raise WorkspaceError("Workspace address is unavailable")

    def stat(self, scope, path):
        _path(path, directory=True)
        with self._lock:
            self._check(scope)
            return self._record(path)

    def list(self, scope, directory="", *, max_entries=100):
        _path(directory, directory=True)
        _bound(max_entries, 1000, "entry")
        with self._lock:
            self._check(scope)
            if directory not in self._directories:
                raise WorkspaceError("Workspace directory is unavailable")
            prefix = directory + "/" if directory else ""
            names = {
                prefix + path[len(prefix) :].split("/", 1)[0]
                for path in self._files
                if path.startswith(prefix)
            }
            if len(names) > max_entries:
                raise WorkspaceError("Workspace directory exceeds its entry allowance")
            return {"path": directory, "entries": [self._record(path) for path in sorted(names)]}

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
            return _snapshot(path, data, hashlib.sha256(data).hexdigest())

    def close(self):
        with self._lock:
            self._closed = True
