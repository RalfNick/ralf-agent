"""POSIX workspace reads through a pinned root and independently owned FDs."""

import copy
import os
import stat
import threading
from contextlib import contextmanager

from .errors import DefinitionMismatch, ValidationError
from .types import digest
from .workspace import (
    DEFAULT_SCOPES,
    PROTECTED,
    WorkspaceError,
    _authorize,
    _bound,
    _configuration,
    _path,
    _scopes_json,
    _snapshot,
    _utf8,
)


def _revision(value):
    return digest(
        [
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        ]
    )


def _root_text(root):
    try:
        value = os.fspath(root)
    except TypeError:
        raise ValidationError("Workspace root requires a host filesystem path") from None
    if not _utf8(value, "Workspace root", max_bytes=4096) or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        raise ValidationError("Workspace root requires a host filesystem path")
    return value


def _open_address(root):
    """Resolve a canonical absolute address without following any new symlink."""
    descriptors, chain, keep = [], [], False
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        current = os.open("/", flags)
        descriptors.append(current)
        value = os.fstat(current)
        chain.append((value.st_dev, value.st_ino))
        for part in root.split("/")[1:]:
            if not part:
                continue
            current = os.open(part, flags, dir_fd=current)
            descriptors.append(current)
            value = os.fstat(current)
            chain.append((value.st_dev, value.st_ino))
        keep = True
        return current, tuple(chain)
    finally:
        for fd in reversed(descriptors[:-1] if keep else descriptors):
            os.close(fd)


class FileSystemWorkspace:
    def __init__(self, root, *, version, scopes=DEFAULT_SCOPES):
        self._scopes = _configuration(version, scopes)
        root_text = _root_text(root)
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise ValidationError("FileSystemWorkspace requires POSIX FD-relative nofollow support")
        address = os.path.abspath(root_text)
        self._root_fd = None
        try:
            initial = os.lstat(address)
            if not stat.S_ISDIR(initial.st_mode):
                raise ValidationError("Workspace root requires a non-symlink directory")
            self._root = os.path.realpath(address)
            _utf8(self._root, "Normalized Workspace root", max_bytes=4096)
            self._root_fd, self._root_chain = _open_address(self._root)
            value = os.fstat(self._root_fd)
            current = os.lstat(address)
            expected = (initial.st_dev, initial.st_ino)
            if (
                not stat.S_ISDIR(current.st_mode)
                or (current.st_dev, current.st_ino) != expected
                or (value.st_dev, value.st_ino) != expected
            ):
                raise DefinitionMismatch("Workspace root changed during initialization")
            self._device, self._inode = value.st_dev, value.st_ino
            self._lock, self._active, self._closing = threading.Lock(), 0, False
            self._identity = {
                "kind": "filesystem-workspace",
                "version": "1",
                "behavior_version": version,
                "scopes": _scopes_json(self._scopes),
                "root_fingerprint": digest(self._root),
                "device": self._device,
                "inode": self._inode,
            }
            self._root_check()
        except BaseException as exc:
            if self._root_fd is not None:
                os.close(self._root_fd)
                self._root_fd = None
            if isinstance(exc, OSError):
                raise ValidationError(
                    "Workspace root requires an existing readable directory"
                ) from None
            raise

    @property
    def identity(self):
        return copy.deepcopy(self._identity)

    def _root_check(self):
        try:
            fd, chain = _open_address(self._root)
        except OSError:
            raise DefinitionMismatch(
                "Original Workspace root address is unavailable or changed"
            ) from None
        try:
            if chain != self._root_chain:
                raise DefinitionMismatch("Original Workspace root address changed")
        finally:
            os.close(fd)

    @contextmanager
    def _operation(self, scope):
        _authorize(scope, self._scopes)
        with self._lock:
            if self._closing:
                raise WorkspaceError("Workspace is closing or closed")
            self._active += 1
        try:
            self._root_check()
            yield
            self._root_check()
        except OSError:
            raise WorkspaceError("Workspace address is unavailable or unsafe") from None
        finally:
            with self._lock:
                self._active -= 1

    def _safe(self, value):
        if value.st_dev != self._device or not (
            stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode)
        ):
            raise WorkspaceError("Workspace entry is outside the regular data allowance")
        if stat.S_ISREG(value.st_mode) and value.st_nlink != 1:
            raise WorkspaceError("Workspace regular files require a single link")

    def _record(self, path, value):
        self._safe(value)
        return {
            "path": path,
            "kind": "directory" if stat.S_ISDIR(value.st_mode) else "file",
            "size": None if stat.S_ISDIR(value.st_mode) else value.st_size,
            "version": _revision(value),
        }

    @contextmanager
    def _parent(self, parts):
        parent, opened, chain = self._root_fd, [], []
        try:
            for part in parts[:-1]:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
                )
                opened.append(child)
                value = os.fstat(child)
                self._safe(value)
                chain.append((parent, part, value.st_dev, value.st_ino))
                parent = child
            yield parent, chain
            for source, name, device, inode in chain:
                value = os.stat(name, dir_fd=source, follow_symlinks=False)
                if not stat.S_ISDIR(value.st_mode) or (value.st_dev, value.st_ino) != (
                    device,
                    inode,
                ):
                    raise DefinitionMismatch("Workspace ancestor changed during the read")
        finally:
            for fd in reversed(opened):
                os.close(fd)

    def stat(self, scope, path):
        parts = _path(path, directory=True)
        with self._operation(scope), self._parent(parts) as (parent, _):
            if not parts:
                return self._record(path, os.fstat(parent))
            first = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            result = self._record(path, first)
            if _revision(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)) != _revision(
                first
            ):
                raise DefinitionMismatch("Workspace entry changed during the read")
            return result

    def read_text(self, scope, path, *, max_bytes=1048576):
        parts = _path(path)
        _bound(max_bytes, 16777216, "byte")
        with self._operation(scope), self._parent(parts) as (parent, _):
            fd = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent
            )
            try:
                first = os.fstat(fd)
                self._safe(first)
                if not stat.S_ISREG(first.st_mode):
                    raise WorkspaceError("Workspace text reads require a regular file")
                if first.st_size > max_bytes:
                    raise WorkspaceError("Workspace file exceeds its byte allowance")
                chunks, size = [], 0
                while size <= max_bytes:
                    chunk = os.read(fd, min(65536, max_bytes + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                if size > max_bytes:
                    raise WorkspaceError("Workspace file exceeds its byte allowance")
                last = os.fstat(fd)
                current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if _revision(first) != _revision(last) or _revision(first) != _revision(current):
                    raise DefinitionMismatch("Workspace file changed during the read")
                return _snapshot(path, b"".join(chunks), _revision(first))
            finally:
                os.close(fd)

    def list(self, scope, directory="", *, max_entries=100):
        parts = _path(directory, directory=True)
        _bound(max_entries, 1000, "entry")
        with self._operation(scope), self._parent(parts) as (parent, _):
            fd = (
                os.open(
                    parts[-1],
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=parent,
                )
                if parts
                else os.dup(parent)
            )
            try:
                first = os.fstat(fd)
                self._safe(first)
                entries, count = [], 0
                with os.scandir(fd) as iterator:
                    for entry in iterator:
                        count += 1
                        if count > max_entries + 3:
                            raise WorkspaceError("Workspace directory exceeds its scan allowance")
                        if entry.name.casefold() in PROTECTED:
                            continue
                        path = directory + "/" + entry.name if directory else entry.name
                        try:
                            _path(path)
                        except ValidationError:
                            raise WorkspaceError(
                                "Workspace directory contains an unsafe address"
                            ) from None
                        entries.append(self._record(path, entry.stat(follow_symlinks=False)))
                        if len(entries) > max_entries:
                            raise WorkspaceError("Workspace directory exceeds its entry allowance")
                for record in entries:
                    current_entry = os.stat(
                        record["path"].rsplit("/", 1)[-1], dir_fd=fd, follow_symlinks=False
                    )
                    if _revision(current_entry) != record["version"]:
                        raise DefinitionMismatch("Workspace listing entry changed during the read")
                current = (
                    os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                    if parts
                    else os.fstat(parent)
                )
                if _revision(first) != _revision(os.fstat(fd)) or _revision(first) != _revision(
                    current
                ):
                    raise DefinitionMismatch("Workspace directory changed during the read")
                return {
                    "path": directory,
                    "entries": sorted(entries, key=lambda item: item["path"]),
                }
            finally:
                os.close(fd)

    def close(self):
        with self._lock:
            self._closing = True
            if self._active:
                raise WorkspaceError(
                    "Workspace still owns an executing read; retry close after exit"
                )
            if self._root_fd is not None:
                os.close(self._root_fd)
                self._root_fd = None
