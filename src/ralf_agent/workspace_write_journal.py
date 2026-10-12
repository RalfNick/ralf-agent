"""Single-root downstream file-effect evidence; never an execution store."""

import copy
import json
import os
import sqlite3
import stat
import threading
import uuid

from .errors import CoordinatorBusy, DefinitionMismatch, IdempotencyConflict, ValidationError
from .types import canonical, digest
from .workspace import WorkspaceError


class WorkspaceWriteJournal:
    def __init__(self, root_fd, root, root_identity, *, capacity):
        import fcntl

        self._fcntl, self._root_fd, self._root = fcntl, root_fd, root
        self._capacity, self._mutex = capacity, threading.RLock()
        self._private_fd = self._metadata_fd = self._lease_fd = self.conn = None
        self._files, self._directories = {}, []
        self._closed = False
        try:
            self._private_fd = self._directory(root_fd, ".ralf")
            self._metadata_fd = self._directory(self._private_fd, "workspace-writes")
            self._lease_fd = self._file("writer.lock")
            try:
                fcntl.flock(self._lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CoordinatorBusy("Another writer owns this Workspace root") from None
            database = self._file("journal.sqlite")
            try:
                empty = os.fstat(database).st_size == 0
            finally:
                os.close(database)
            for name in ("journal.sqlite-wal", "journal.sqlite-shm", "journal.sqlite-journal"):
                try:
                    value = os.stat(name, dir_fd=self._metadata_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                self._regular(value)
            physical = {
                "root": {k: root_identity[k] for k in ("device", "inode", "root_fingerprint")},
                "directories": [entry[2] for entry in self._directories],
                "files": self._files,
            }
            self.conn = sqlite3.connect(
                root + "/.ralf/workspace-writes/journal.sqlite",
                isolation_level=None,
                check_same_thread=False,
            )
            self.conn.execute("PRAGMA journal_mode=DELETE")
            self.conn.execute("PRAGMA synchronous=EXTRA")
            if (
                self.conn.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
                or self.conn.execute("PRAGMA synchronous").fetchone()[0] != 3
            ):
                raise ValidationError(
                    "Workspace write journal requires durable DELETE+EXTRA commits"
                )
            if empty:
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    self.conn.execute("CREATE TABLE workspace_write_metadata (value TEXT NOT NULL)")
                    self.conn.execute("""CREATE TABLE workspace_write_effects (
                        workspace TEXT NOT NULL, principal TEXT NOT NULL, effect_key TEXT NOT NULL,
                        path TEXT NOT NULL, request TEXT NOT NULL, evidence TEXT NOT NULL,
                        receipt TEXT, PRIMARY KEY(workspace,principal,effect_key))""")
                    metadata = {
                        "kind": "workspace-write-journal",
                        "version": "1",
                        "dataset_uuid": uuid.uuid4().hex,
                        **physical,
                    }
                    self.conn.execute(
                        "INSERT INTO workspace_write_metadata VALUES (?)", (canonical(metadata),)
                    )
                    self.conn.execute("COMMIT")
                    os.fsync(self._metadata_fd)
                except BaseException:
                    self.conn.execute("ROLLBACK")
                    raise
            rows = self.conn.execute("SELECT value FROM workspace_write_metadata").fetchall()
            if len(rows) != 1:
                raise DefinitionMismatch("Workspace write dataset metadata is unavailable")
            metadata = json.loads(rows[0][0])
            if (
                type(metadata) is not dict
                or set(metadata)
                != {"kind", "version", "dataset_uuid", "root", "directories", "files"}
                or metadata["kind"] != "workspace-write-journal"
                or metadata["version"] != "1"
                or type(metadata["dataset_uuid"]) is not str
                or len(metadata["dataset_uuid"]) != 32
                or set(metadata["dataset_uuid"]) - set("0123456789abcdef")
                or canonical({k: metadata[k] for k in physical}) != canonical(physical)
            ):
                raise DefinitionMismatch("Original Workspace write dataset identity changed")
            self._metadata_json = canonical(metadata)
            self.identity = copy.deepcopy(metadata)
            self.check()
        except BaseException as exc:
            self.close()
            if isinstance(exc, (OSError, sqlite3.Error, ValueError)):
                raise ValidationError("Workspace write metadata is unavailable or unsafe") from None
            raise

    def _directory(self, parent, name):
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        fd = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
        )
        try:
            value = os.fstat(fd)
            if value.st_dev != os.fstat(self._root_fd).st_dev:
                raise ValidationError("Workspace metadata must remain on its root device")
            self._directories.append((parent, name, [value.st_dev, value.st_ino]))
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _regular(self, value):
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_nlink != 1
            or value.st_dev != os.fstat(self._root_fd).st_dev
        ):
            raise ValidationError("Workspace write metadata requires single-link regular files")

    def _file(self, name):
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            0o600,
            dir_fd=self._metadata_fd,
        )
        try:
            value = os.fstat(fd)
            self._regular(value)
            self._files[name] = [value.st_dev, value.st_ino]
            os.fsync(self._metadata_fd)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def check(self):
        with self._mutex:
            if self._closed or self.conn is None:
                raise WorkspaceError("Workspace write journal is closed")
            try:
                for parent, name, expected in self._directories:
                    value = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if not stat.S_ISDIR(value.st_mode) or [value.st_dev, value.st_ino] != expected:
                        raise DefinitionMismatch("Original Workspace metadata directory changed")
                for name, expected in self._files.items():
                    value = os.stat(name, dir_fd=self._metadata_fd, follow_symlinks=False)
                    self._regular(value)
                    if [value.st_dev, value.st_ino] != expected:
                        raise DefinitionMismatch("Original Workspace metadata file changed")
                rows = self.conn.execute("SELECT value FROM workspace_write_metadata").fetchall()
                if len(rows) != 1 or canonical(json.loads(rows[0][0])) != self._metadata_json:
                    raise DefinitionMismatch("Original Workspace write dataset changed")
            except (OSError, sqlite3.Error, ValueError):
                raise DefinitionMismatch(
                    "Original Workspace write metadata is unavailable"
                ) from None

    def lookup(self, scope, key):
        with self._mutex:
            self.check()
            row = self.conn.execute(
                """SELECT request,evidence,receipt FROM workspace_write_effects
                WHERE workspace=? AND principal=? AND effect_key=?""",
                (scope.workspace, scope.principal, key),
            ).fetchone()
            if row is None:
                return None
            return {
                "request": json.loads(row[0]),
                "evidence": json.loads(row[1]),
                "receipt": None if row[2] is None else json.loads(row[2]),
            }

    def prepare(self, scope, key, request, evidence):
        with self._mutex:
            self.check()
            existing = self.lookup(scope, key)
            if existing is not None:
                if digest(existing["request"]) != digest(request):
                    raise IdempotencyConflict("Workspace write key pins another request")
                return existing
            if (
                self.conn.execute("SELECT count(*) FROM workspace_write_effects").fetchone()[0]
                >= self._capacity
            ):
                raise WorkspaceError("Workspace write receipt capacity is full")
            self.conn.execute(
                "INSERT INTO workspace_write_effects VALUES (?,?,?,?,?,?,NULL)",
                (
                    scope.workspace,
                    scope.principal,
                    key,
                    request["path"],
                    canonical(request),
                    canonical(evidence),
                ),
            )
            return {
                "request": copy.deepcopy(request),
                "evidence": copy.deepcopy(evidence),
                "receipt": None,
            }

    def pending(self):
        with self._mutex:
            self.check()
            return self.conn.execute(
                """SELECT workspace,principal,effect_key FROM workspace_write_effects
                WHERE receipt IS NULL""",
            ).fetchall()

    def confirm(self, scope, key, receipt):
        with self._mutex:
            self.check()
            self.conn.execute(
                """UPDATE workspace_write_effects SET receipt=?
                WHERE workspace=? AND principal=? AND effect_key=? AND receipt IS NULL""",
                (canonical(receipt), scope.workspace, scope.principal, key),
            )
            saved = self.lookup(scope, key)["receipt"]
            if canonical(saved) != canonical(receipt):
                raise DefinitionMismatch("Workspace confirmed receipt changed")
            return saved

    def close(self):
        with self._mutex:
            if self.conn is not None:
                self.conn.close()
                self.conn = None
            for name in ("_lease_fd", "_metadata_fd", "_private_fd"):
                fd = getattr(self, name)
                if fd is not None:
                    os.close(fd)
                    setattr(self, name, None)
            self._closed = True
