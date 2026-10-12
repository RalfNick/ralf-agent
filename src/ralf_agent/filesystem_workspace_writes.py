"""Opt-in POSIX file writes under original safe-root access and one owner."""

import os
import stat
import threading
import uuid
from contextlib import contextmanager

from .errors import DefinitionMismatch, IdempotencyConflict
from .filesystem_workspace import FileSystemWorkspace, _revision
from .types import Scope, canonical, digest
from .workspace import DEFAULT_SCOPES, WorkspaceError, _authorize, _bound, _path
from .workspace_write_journal import WorkspaceWriteJournal
from .workspace_writes import _key, validate_write_receipt, write_receipt, write_request


class FileSystemWritableWorkspace(FileSystemWorkspace):
    def __init__(self, root, *, version, scopes=DEFAULT_SCOPES, max_bytes=1048576, capacity=1024):
        _bound(max_bytes, 16777216, "write byte")
        _bound(capacity, 100000, "write receipt capacity")
        self._journal, self._write_mutex = None, threading.RLock()
        self._max_write_bytes = max_bytes
        super().__init__(root, version=version, scopes=scopes)
        try:
            self._journal = WorkspaceWriteJournal(
                self._root_fd, self._root, self._identity, capacity=capacity
            )
            self._identity = {
                **self._identity,
                "kind": "filesystem-writable-workspace",
                "write_journal": self._journal.identity,
                "max_write_bytes": max_bytes,
                "write_capacity": capacity,
            }
            self._root_check()
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _operation(self, scope):
        with super()._operation(scope):
            self._journal.check()
            yield
            self._journal.check()

    def _target(self, parent, name):
        try:
            value = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None
        self._safe(value)
        if not stat.S_ISREG(value.st_mode):
            raise WorkspaceError("Workspace writes require an ordinary file target")
        return value

    def _check_parents(self, chain):
        for parent, name, device, inode in chain:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
                device,
                inode,
            ):
                raise DefinitionMismatch("Workspace write ancestor changed")

    def _pending_target(self, parent, name, record):
        """Use native addresses; absent pending names conservatively hold their parent."""
        evidence = record["evidence"]
        parents = evidence.get("parents") if type(evidence) is dict else None
        if type(parents) is not list or any(
            type(item) is not list
            or len(item) != 3
            or type(item[0]) is not str
            or type(item[1]) is not int
            or type(item[2]) is not int
            or item[1] < 0
            or item[2] <= 0
            for item in parents
        ):
            raise WorkspaceError("Unknown Workspace write has invalid parent evidence")
        root = os.fstat(self._root_fd)
        expected = tuple(parents[-1][1:]) if parents else (root.st_dev, root.st_ino)
        actual = os.fstat(parent)
        if (actual.st_dev, actual.st_ino) != expected:
            return False
        original_name = _path(record["request"]["path"])[-1]
        predecessor = self._target(parent, original_name)
        if predecessor is None:
            return True
        target = self._target(parent, name)
        return target is not None and (target.st_dev, target.st_ino) == (
            predecessor.st_dev,
            predecessor.st_ino,
        )

    def _confirmed_version(self, fd, parent, name, data, proof):
        initial = os.fstat(fd)
        self._safe(initial)
        current = self._target(parent, name)
        if (
            current is None
            or (initial.st_dev, initial.st_ino) != proof
            or _revision(initial) != _revision(current)
        ):
            raise WorkspaceError("Workspace target lost the original temporary file proof")
        os.lseek(fd, 0, os.SEEK_SET)
        chunks, size = [], 0
        while size <= self._max_write_bytes:
            chunk = os.read(fd, min(65536, self._max_write_bytes + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            chunks.append(chunk)
        final = os.fstat(fd)
        current = self._target(parent, name)
        if (
            b"".join(chunks) != data
            or _revision(initial) != _revision(final)
            or current is None
            or _revision(final) != _revision(current)
        ):
            raise WorkspaceError("Workspace file changed before its write was confirmed")
        return _revision(final)

    def _recover(self, scope, effect_key, record, *, execute=False):
        """Query confirms proof only; executing the original key may finish its intent."""
        _authorize(scope, self._scopes)
        request, evidence = record["request"], record["evidence"]
        try:
            actual, data = write_request(
                scope,
                request["path"],
                request["text"],
                request["expected_version"],
                effect_key,
                max_bytes=self._max_write_bytes,
            )
            if canonical(actual) != canonical(request):
                raise WorkspaceError("Original Workspace request evidence changed")
            if (
                type(evidence) is not dict
                or set(evidence) != {"temporary", "device", "inode", "parents", "original_version"}
                or type(evidence["temporary"]) is not str
                or not evidence["temporary"].startswith("prepared-")
                or len(evidence["temporary"]) != 41
                or set(evidence["temporary"][9:]) - set("0123456789abcdef")
                or type(evidence["device"]) is not int
                or evidence["device"] < 0
                or type(evidence["inode"]) is not int
                or evidence["inode"] <= 0
                or type(evidence["parents"]) is not list
                or evidence["original_version"] != request["expected_version"]
            ):
                raise WorkspaceError("Original Workspace temporary proof is invalid")
            proof = evidence["device"], evidence["inode"]
            parts = _path(request["path"])
            with self._parent(parts) as (parent, chain):
                parents = [[name, device, inode] for _, name, device, inode in chain]
                if canonical(parents) != canonical(evidence["parents"]):
                    raise WorkspaceError("Original Workspace write parents changed")
                current = self._target(parent, parts[-1])
                published = current is not None and (current.st_dev, current.st_ino) == proof
                if not published and not execute:
                    return None
                if published:
                    fd = os.open(
                        parts[-1],
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                        dir_fd=parent,
                    )
                else:
                    if (None if current is None else _revision(current)) != request[
                        "expected_version"
                    ]:
                        raise WorkspaceError("Original Workspace file outcome remains unknown")
                    fd = os.open(
                        evidence["temporary"],
                        os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                        dir_fd=self._journal._metadata_fd,
                    )
                try:
                    if not published:
                        self._confirmed_version(
                            fd, self._journal._metadata_fd, evidence["temporary"], data, proof
                        )
                        self._root_check()
                        self._journal.check()
                        self._check_parents(chain)
                        latest = self._target(parent, parts[-1])
                        if (None if latest is None else _revision(latest)) != request[
                            "expected_version"
                        ]:
                            raise WorkspaceError("Workspace original CAS changed during recovery")
                        os.replace(
                            evidence["temporary"],
                            parts[-1],
                            src_dir_fd=self._journal._metadata_fd,
                            dst_dir_fd=parent,
                        )
                    os.fsync(parent)
                    self._root_check()
                    self._journal.check()
                    self._check_parents(chain)
                    version = self._confirmed_version(fd, parent, parts[-1], data, proof)
                    return self._journal.confirm(
                        scope, effect_key, write_receipt(scope, effect_key, request, version)
                    )
                finally:
                    os.close(fd)
        except (OSError, WorkspaceError, DefinitionMismatch, KeyError, TypeError, ValueError):
            if execute:
                raise WorkspaceError(
                    "Original Workspace file effect requires evidence recovery"
                ) from None
            return None

    def write_text(self, scope, path, text, *, expected_version, effect_key):
        with self._write_mutex, self._operation(scope):
            request, data = write_request(
                scope, path, text, expected_version, effect_key, max_bytes=self._max_write_bytes
            )
            saved = self._journal.lookup(scope, effect_key)
            if saved is not None:
                if digest(saved["request"]) != digest(request):
                    raise IdempotencyConflict("Workspace effect key already pins another request")
                if saved["receipt"] is not None:
                    return validate_write_receipt(saved["receipt"], scope, effect_key, request)
                return self._recover(scope, effect_key, saved, execute=True)
            parts = _path(path)
            with self._parent(parts) as (parent, chain):
                for workspace, principal, key in self._journal.pending():
                    owner = Scope(workspace, principal)
                    pending = self._journal.lookup(owner, key)
                    if (
                        self._pending_target(parent, parts[-1], pending)
                        and self._recover(owner, key, pending) is None
                    ):
                        raise WorkspaceError("An unknown Workspace write still owns this target")
                current = self._target(parent, parts[-1])
                original = None if current is None else _revision(current)
                if original != expected_version:
                    raise WorkspaceError(
                        "Workspace target differs from its expected original version"
                    )
                name = "prepared-" + uuid.uuid4().hex
                fd = os.open(
                    name,
                    os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=self._journal._metadata_fd,
                )
                prepared = False
                try:
                    os.fchmod(fd, 0o600 if current is None else current.st_mode & 0o777)
                    offset = 0
                    while offset < len(data):
                        written = os.write(fd, data[offset : offset + 65536])
                        if written <= 0:
                            raise WorkspaceError("Workspace temporary write did not progress")
                        offset += written
                    os.fsync(fd)
                    os.fsync(self._journal._metadata_fd)
                    value = os.fstat(fd)
                    self._safe(value)
                    evidence = {
                        "temporary": name,
                        "device": value.st_dev,
                        "inode": value.st_ino,
                        "parents": [[part, device, inode] for _, part, device, inode in chain],
                        "original_version": original,
                    }
                    self._journal.prepare(scope, effect_key, request, evidence)
                    prepared = True
                    self._root_check()
                    self._journal.check()
                    self._check_parents(chain)
                    latest = self._target(parent, parts[-1])
                    if (None if latest is None else _revision(latest)) != original:
                        raise WorkspaceError("Workspace target changed before file replacement")
                    os.replace(
                        name, parts[-1], src_dir_fd=self._journal._metadata_fd, dst_dir_fd=parent
                    )
                    os.fsync(parent)
                    self._root_check()
                    self._journal.check()
                    self._check_parents(chain)
                    version = self._confirmed_version(
                        fd, parent, parts[-1], data, (value.st_dev, value.st_ino)
                    )
                    receipt = write_receipt(scope, effect_key, request, version)
                    return self._journal.confirm(scope, effect_key, receipt)
                finally:
                    os.close(fd)
                    if not prepared:
                        os.unlink(name, dir_fd=self._journal._metadata_fd)

    def query_write(self, scope, effect_key):
        with self._write_mutex, self._operation(scope):
            _key(effect_key)
            record = self._journal.lookup(scope, effect_key)
            if record is None:
                return None
            if record["receipt"] is None:
                return self._recover(scope, effect_key, record)
            return validate_write_receipt(record["receipt"], scope, effect_key, record["request"])

    def close(self):
        with self._lock:
            self._closing = True
            if self._active:
                raise WorkspaceError(
                    "Workspace still owns an executing handler; retry close after exit"
                )
            if self._journal is not None:
                self._journal.close()
            if self._root_fd is not None:
                os.close(self._root_fd)
                self._root_fd = None
