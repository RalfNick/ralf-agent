"""Bounded local native startup evidence; never a Run store or scheduler.

Commit submission intent before native I/O. A submitted stage without its
receipt stays uncertain, including after reopen. ``execute`` is a transient
permission returned only by the first committed submission advance; ``begin``
only indicates whether intent was newly recorded. Callers must not log secrets,
authentication challenges, or full native payloads as observations.
"""

import fcntl
import json
import os
import sqlite3
import stat
import threading
import uuid

from .errors import (
    CoordinatorBusy,
    DefinitionMismatch,
    RuntimeClosed,
    ValidationError,
)
from .runner_journal_state import (
    _MAX_RECORD,
    _json,
    _text,
    append_observation,
    cancel_record,
    new_record,
    receive_record,
    submit_record,
    validate_record,
)
from .types import Scope, canonical


class RunnerJournal:
    """Single-owner POSIX SQLite evidence pinned to dependencies and physical files.

    Capacity bounds distinct scoped effects. Each effect separately retains at
    most 1000 observations and 1 MiB total evidence; each input JSON object is
    bounded to 64 KiB. Evidence is append-only, with exact duplicates reused.
    No stage reset, startup retry, native recovery, or cancellation stop proof is
    provided here. The owner lease is held until the connection closes safely.
    """

    def __init__(self, path: str, *, identity: dict, capacity: int = 1000):
        if type(capacity) is not int or not 1 <= capacity <= 1000000:
            raise ValidationError("Runner journal requires bounded positive capacity")
        dependencies = _json(identity, "Runner dependencies")
        _text(path, "Runner journal path", limit=4096)
        if not os.path.isabs(path) or os.path.abspath(path) != path:
            raise ValidationError("Runner journal requires a canonical absolute path")
        self._path, self._capacity = path, capacity
        self._mutex, self._closed = threading.RLock(), False
        self._lease_fd = self._database_fd = self.conn = None
        self._directories, self._files = [], {}
        self._metadata_json = None
        try:
            self._open_parent()
            self._lease_fd = self._file(os.path.basename(path) + ".owner")
            try:
                fcntl.flock(self._lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CoordinatorBusy("Another owner holds the Runner journal") from None
            self._database_fd = self._file(os.path.basename(path))
            empty = os.fstat(self._database_fd).st_size == 0
            self._check_physical()
            self.conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=DELETE")
            self.conn.execute("PRAGMA synchronous=EXTRA")
            if (
                self.conn.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
                or self.conn.execute("PRAGMA synchronous").fetchone()[0] != 3
            ):
                raise ValidationError("Runner journal requires durable DELETE+EXTRA commits")
            physical = {"path": path, "directories": self._directories, "files": self._files}
            if empty:
                metadata = {
                    "kind": "runner-journal",
                    "version": "1",
                    "dataset_uuid": uuid.uuid4().hex,
                    "dependencies": json.loads(dependencies),
                    "physical": physical,
                }
                self.conn.execute("BEGIN IMMEDIATE")
                try:
                    self.conn.execute("CREATE TABLE runner_metadata (value TEXT NOT NULL)")
                    self.conn.execute("""CREATE TABLE runner_effects (
                        workspace TEXT NOT NULL, principal TEXT NOT NULL, effect_key TEXT NOT NULL,
                        record TEXT NOT NULL, PRIMARY KEY(workspace,principal,effect_key))""")
                    self.conn.execute(
                        "INSERT INTO runner_metadata VALUES (?)", (canonical(metadata),)
                    )
                    self.conn.execute("COMMIT")
                    os.fsync(self._parent_fd)
                except BaseException:
                    if self.conn.in_transaction:
                        self.conn.execute("ROLLBACK")
                    raise
            rows = self.conn.execute("SELECT value FROM runner_metadata").fetchall()
            if len(rows) != 1:
                raise DefinitionMismatch("Runner journal dataset metadata is unavailable")
            metadata = json.loads(rows[0][0])
            if (
                type(metadata) is not dict
                or set(metadata) != {"kind", "version", "dataset_uuid", "dependencies", "physical"}
                or metadata["kind"] != "runner-journal"
                or metadata["version"] != "1"
                or type(metadata["dataset_uuid"]) is not str
                or len(metadata["dataset_uuid"]) != 32
                or set(metadata["dataset_uuid"]) - set("0123456789abcdef")
                or canonical(metadata["dependencies"]) != dependencies
                or canonical(metadata["physical"]) != canonical(physical)
            ):
                raise DefinitionMismatch("Original Runner journal dataset or dependencies changed")
            self._metadata_json = canonical(metadata)
            self._identity_json = canonical(
                {k: metadata[k] for k in ("kind", "version", "dataset_uuid", "dependencies")}
            )
            self._check()
        except BaseException as exc:
            self.close()
            if isinstance(exc, (OSError, sqlite3.Error, ValueError)) and not isinstance(
                exc, ValidationError
            ):
                raise ValidationError("Runner journal is unavailable or unsafe") from None
            raise

    @property
    def identity(self):
        return json.loads(self._identity_json)

    def _open_parent(self):
        # Open every component without following aliases, then keep its identity
        # to refuse later directory replacement before issuing any database work.
        self._directory_fds = []
        parent = os.path.dirname(self._path)
        components = ["/"]
        current = ""
        for component in parent.split("/")[1:]:
            if component:
                current += "/" + component
                components.append(current)
        for directory in components:
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            self._directory_fds.append(fd)
            value = os.fstat(fd)
            self._directories.append([directory, value.st_dev, value.st_ino])
        self._parent_fd = self._directory_fds[-1]

    def _regular(self, value):
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_nlink != 1
            or value.st_dev != os.fstat(self._parent_fd).st_dev
        ):
            raise ValidationError("Runner journal requires single-link regular metadata files")

    def _file(self, name):
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            0o600,
            dir_fd=self._parent_fd,
        )
        try:
            value = os.fstat(fd)
            self._regular(value)
            self._files[name] = [value.st_dev, value.st_ino]
            os.fsync(self._parent_fd)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _check_physical(self):
        for directory, device, inode in self._directories:
            value = os.stat(directory, follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode) or [value.st_dev, value.st_ino] != [device, inode]:
                raise DefinitionMismatch("Original Runner journal directory changed")
        for name, expected in self._files.items():
            value = os.stat(name, dir_fd=self._parent_fd, follow_symlinks=False)
            self._regular(value)
            if [value.st_dev, value.st_ino] != expected:
                raise DefinitionMismatch("Original Runner journal file changed")
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                value = os.stat(
                    os.path.basename(self._path) + suffix,
                    dir_fd=self._parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            self._regular(value)

    def _check(self):
        if self._closed or self.conn is None:
            raise RuntimeClosed("Runner journal is closed")
        try:
            self._check_physical()
            rows = self.conn.execute("SELECT value FROM runner_metadata").fetchall()
            if len(rows) != 1 or canonical(json.loads(rows[0][0])) != self._metadata_json:
                raise DefinitionMismatch("Original Runner journal dataset changed")
        except (OSError, sqlite3.Error, ValueError):
            raise DefinitionMismatch(
                "Original Runner journal metadata is unavailable or changed"
            ) from None

    def _key(self, scope, effect_key, binding):
        if not isinstance(scope, Scope):
            raise ValidationError("Runner journal requires Scope")
        key = (
            _text(scope.workspace, "Workspace"),
            _text(scope.principal, "Principal"),
            _text(effect_key, "Effect key"),
        )
        return key, _json(binding, "Runner binding")

    def _lookup(self, key, binding):
        row = self.conn.execute(
            "SELECT record FROM runner_effects WHERE workspace=? AND principal=? AND effect_key=?",
            key,
        ).fetchone()
        if row is None:
            return None
        return validate_record(row[0], key, binding)

    def _required(self, key, binding):
        record = self._lookup(key, binding)
        if record is None:
            raise ValidationError("No durable Runner startup intent for evidence")
        return record

    def _save(self, key, record):
        encoded = _json(record, "Runner record", limit=_MAX_RECORD)
        self.conn.execute(
            "UPDATE runner_effects SET record=? WHERE workspace=? AND principal=? AND effect_key=?",
            (encoded, *key),
        )
        return json.loads(encoded)

    def lookup(self, scope: Scope, effect_key: str, *, binding: dict) -> dict | None:
        key, binding_json = self._key(scope, effect_key, binding)
        with self._mutex:
            self._check()
            return self._lookup(key, binding_json)

    def begin(self, scope: Scope, effect_key: str, binding: dict) -> dict:
        key, binding_json = self._key(scope, effect_key, binding)
        with self._mutex:
            self._check()
            record = self._lookup(key, binding_json)
            if record is not None:
                return {**record, "execute": False}
            if (
                self.conn.execute("SELECT count(*) FROM runner_effects").fetchone()[0]
                >= self._capacity
            ):
                raise ValidationError("Runner journal effect capacity is full")
            record = new_record(key, binding_json)
            encoded = _json(record, "Runner record", limit=_MAX_RECORD)
            self.conn.execute("INSERT INTO runner_effects VALUES (?,?,?,?)", (*key, encoded))
            return {**json.loads(encoded), "execute": True}

    def _submit(self, scope, effect_key, binding, previous, stage):
        key, binding_json = self._key(scope, effect_key, binding)
        with self._mutex:
            self._check()
            record = self._required(key, binding_json)
            record, execute = submit_record(record, previous, stage)
            return {**(self._save(key, record) if execute else record), "execute": execute}

    def mark_thread_submitted(self, scope: Scope, effect_key: str, *, binding: dict) -> dict:
        return self._submit(scope, effect_key, binding, "intent", "thread_submitted")

    def mark_turn_submitted(self, scope: Scope, effect_key: str, *, binding: dict) -> dict:
        return self._submit(scope, effect_key, binding, "thread_confirmed", "turn_submitted")

    def record_thread(
        self, scope: Scope, effect_key: str, *, binding: dict, thread_id: str, process_epoch: str
    ) -> dict:
        native = {
            "thread_id": _text(thread_id, "Thread ID"),
            "process_epoch": _text(process_epoch, "Process epoch"),
        }
        return self._receipt(
            scope, effect_key, binding, native, "thread_submitted", "thread_confirmed"
        )

    def record_turn(self, scope: Scope, effect_key: str, *, binding: dict, turn_id: str) -> dict:
        native = {"turn_id": _text(turn_id, "Turn ID")}
        return self._receipt(scope, effect_key, binding, native, "turn_submitted", "turn_confirmed")

    def _receipt(self, scope, effect_key, binding, native, previous, stage):
        key, binding_json = self._key(scope, effect_key, binding)
        with self._mutex:
            self._check()
            record = self._required(key, binding_json)
            original = canonical(record)
            record = receive_record(record, native, previous, stage)
            return record if canonical(record) == original else self._save(key, record)

    def record_observation(
        self, scope: Scope, effect_key: str, *, binding: dict, observation: dict
    ) -> dict:
        key, binding_json = self._key(scope, effect_key, binding)
        encoded = _json(observation, "Runner observation")
        evidence = json.loads(encoded)
        for name in ("thread_id", "turn_id", "process_epoch"):
            if name in evidence:
                _text(evidence[name], name)
        with self._mutex:
            self._check()
            record = self._required(key, binding_json)
            original = canonical(record)
            record = append_observation(record, encoded)
            return record if canonical(record) == original else self._save(key, record)

    def request_cancel(self, scope: Scope, effect_key: str, *, binding: dict) -> dict:
        key, binding_json = self._key(scope, effect_key, binding)
        with self._mutex:
            self._check()
            record = self._required(key, binding_json)
            if record["cancel_requested"]:
                return record
            return self._save(key, cancel_record(record))

    def close(self):
        with self._mutex:
            # A failed connection close leaves the lease held and the object
            # unwritable. Retrying close can safely finish releasing resources.
            self._closed = True
            if self.conn is not None:
                self.conn.close()
                self.conn = None
            for name in ("_database_fd", "_lease_fd"):
                fd = getattr(self, name)
                if fd is not None:
                    os.close(fd)
                    setattr(self, name, None)
            for fd in getattr(self, "_directory_fds", []):
                os.close(fd)
            self._directory_fds = []
