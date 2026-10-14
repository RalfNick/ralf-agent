"""Mechanical capacity-one lease for an actual private Runner root.

This module has no Run authority. Callers validate original stop/absence evidence
before supplying its bounded projection here. A recovery claim permits control
only, and closing or losing an OS owner never clears a durable obligation.
All operations are synchronous and nonblocking; callers own cancellation-aware
waiting and must mark native intent durably before any native side effect.
"""

import copy
import fcntl
import json
import os
import re
import stat
import uuid
from pathlib import Path

from .errors import DefinitionMismatch, RuntimeClosed, ValidationError

_LOCK = ".coding-capacity.lock"
_RECORD = ".coding-capacity.json"
_LIMIT = 4096


def _require(condition):
    if not condition:
        raise DefinitionMismatch("Original Runner capacity binding or evidence changed")


def _hex(value, length):
    return type(value) is str and re.fullmatch("[a-f0-9]{" + str(length) + "}", value) is not None


def _pin(info):
    return {"device": info.st_dev, "inode": info.st_ino}


def _private_file(info):
    _require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
    )


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result)
        result[key] = value
    return result


class RootCapacity:
    """Root flock plus durable original obligation; never a business permit."""

    def __init__(self, root, *, root_pin, dispatch_digest, runner_digest, generation):
        try:
            path = Path(root)
            valid = (
                os.name == "posix"
                and path.is_absolute()
                and str(path) == str(path.resolve(strict=True))
                and type(root_pin) is dict
                and set(root_pin) == {"path", "device", "inode"}
                and root_pin["path"] == str(path)
                and type(root_pin["device"]) is int
                and type(root_pin["inode"]) is int
                and _hex(dispatch_digest, 64)
                and _hex(runner_digest, 64)
                and _hex(generation, 32)
            )
        except (OSError, ValueError, TypeError):
            valid = False
        if not valid:
            raise ValidationError(
                "Capacity requires its private canonical root and original digests"
            )
        self._root = path
        self._root_pin = copy.deepcopy(root_pin)
        self._original = {
            "dispatch_digest": dispatch_digest,
            "runner_digest": runner_digest,
            "generation": generation,
        }
        self._directory = None
        self._lease = None
        self._lock_pin = None
        self._state = None
        self._recovery = False
        self._closed = False
        try:
            self._directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._check_root()
        except OSError:
            self.close()
            raise DefinitionMismatch("Original Runner capacity root is unavailable") from None
        except BaseException:
            self.close()
            raise

    def _check_root(self):
        info = self._root.lstat()
        _require(
            str(self._root.resolve(strict=True)) == str(self._root)
            and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700
            and {"path": str(self._root), **_pin(info)} == self._root_pin
            and _pin(os.fstat(self._directory)) == _pin(info)
        )

    def _check_lock(self):
        self._check_root()
        opened = os.fstat(self._lease)
        named = os.stat(_LOCK, dir_fd=self._directory, follow_symlinks=False)
        _private_file(opened)
        _private_file(named)
        _require(
            _pin(opened) == _pin(named) == self._lock_pin and opened.st_size == named.st_size == 0
        )

    def _validate_state(self, state):
        _require(
            type(state) is dict
            and set(state) == {"version", "root", "lock", "obligation"}
            and type(state["version"]) is int
            and state["version"] == 1
            and type(state["root"]) is dict
            and type(state["lock"]) is dict
            and all(
                type(state[section].get(key)) is int
                for section in ("root", "lock")
                for key in ("device", "inode")
            )
            and state["root"] == self._root_pin
            and state["lock"] == self._lock_pin
        )
        value = state["obligation"]
        if value is not None:
            _require(
                type(value) is dict
                and set(value)
                == {"dispatch_digest", "runner_digest", "generation", "token", "phase"}
                and _hex(value["dispatch_digest"], 64)
                and _hex(value["runner_digest"], 64)
                and _hex(value["generation"], 32)
                and _hex(value["token"], 32)
                and type(value["phase"]) is str
                and value["phase"] in {"acquired", "native_intent"}
            )

    def _read(self):
        self._check_lock()
        fd = os.open(_RECORD, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._directory)
        try:
            before = os.fstat(fd)
            _private_file(before)
            _require(before.st_size <= _LIMIT)
            raw = os.read(fd, _LIMIT + 1)
            _require(len(raw) <= _LIMIT)
            after = os.fstat(fd)
            named = os.stat(_RECORD, dir_fd=self._directory, follow_symlinks=False)
            _private_file(named)
            _require(
                _pin(before) == _pin(after) == _pin(named)
                and before.st_size == after.st_size == len(raw)
                and before.st_mtime_ns == after.st_mtime_ns
            )
            value = json.loads(raw, object_pairs_hook=_pairs)
            self._validate_state(value)
            return value
        except (ValueError, UnicodeError, TypeError):
            raise DefinitionMismatch("Original Runner capacity record is invalid") from None
        finally:
            os.close(fd)

    def _write(self, value, *, initial=False):
        self._check_lock()
        self._validate_state(value)
        if initial:
            try:
                os.stat(_RECORD, dir_fd=self._directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise DefinitionMismatch(
                    "Capacity initialization cannot replace an existing record"
                )
        else:
            _require(self._read() == self._state)
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        _require(len(raw) <= _LIMIT)
        name = ".coding-capacity-write-" + uuid.uuid4().hex
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self._directory,
        )
        try:
            _private_file(os.fstat(fd))
            with os.fdopen(fd, "wb", closefd=False) as out:
                out.write(raw)
                out.flush()
                os.fsync(fd)
            self._check_lock()
            if not initial:
                _require(self._read() == self._state)
            os.replace(name, _RECORD, src_dir_fd=self._directory, dst_dir_fd=self._directory)
            os.fsync(self._directory)
            self._state = copy.deepcopy(value)
        finally:
            os.close(fd)
            try:
                os.unlink(name, dir_fd=self._directory)
            except FileNotFoundError:
                pass

    def _drop_lock(self):
        if self._lease is not None:
            os.close(self._lease)
            self._lease = None
        self._lock_pin = None
        self._state = None
        self._recovery = False

    def try_acquire(self, *, recovery=False, absent_original_ok=False):
        """Return a detached claim or None; recovery is control-only, never execute."""
        if self._closed:
            raise RuntimeClosed("Runner capacity is closed")
        if type(recovery) is not bool:
            raise ValidationError("Capacity recovery mode must be explicit boolean")
        if type(absent_original_ok) is not bool or (absent_original_ok and not recovery):
            raise ValidationError("Absent original capacity is only explicit recovery control")
        try:
            if self._lease is not None:
                self._check_lock()
                _require(self._read() == self._state and recovery == self._recovery)
                return self.claim
            self._check_root()
            created = False
            try:
                fd = os.open(
                    _LOCK,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=self._directory,
                )
                created = True
            except FileExistsError:
                fd = os.open(
                    _LOCK, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._directory
                )
            self._lease = fd
            self._lock_pin = _pin(os.fstat(fd))
            self._check_lock()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self._drop_lock()
                return None
            if created:
                os.fsync(fd)
                self._write(
                    {
                        "version": 1,
                        "root": self._root_pin,
                        "lock": self._lock_pin,
                        "obligation": None,
                    },
                    initial=True,
                )
            else:
                self._state = self._read()
            value = self._state["obligation"]
            if value is not None:
                matches = all(value[key] == expected for key, expected in self._original.items())
                if recovery:
                    if not matches and absent_original_ok:
                        self._drop_lock()
                        return None
                    _require(matches)
                    self._recovery = True
                    return self.claim
                self._drop_lock()
                return None
            if recovery:
                self._drop_lock()
                return None
            value = {**self._original, "token": uuid.uuid4().hex, "phase": "acquired"}
            self._write({**self._state, "obligation": value})
            return self.claim
        except OSError:
            self._drop_lock()
            raise DefinitionMismatch("Original Runner capacity files are unavailable") from None
        except BaseException:
            self._drop_lock()
            raise

    @property
    def claim(self):
        if self._lease is None or self._state is None or self._state["obligation"] is None:
            return None
        self._check_lock()
        _require(self._read() == self._state)
        return {**copy.deepcopy(self._state["obligation"]), "recovery_only": self._recovery}

    def _owned(self, token):
        if self._closed:
            raise RuntimeClosed("Runner capacity is closed")
        value = self.claim
        _require(value is not None and _hex(token, 32) and value["token"] == token)
        _require(all(value[key] == expected for key, expected in self._original.items()))
        return value

    def mark_native_intent(self, token):
        """Commit possible native effects before submission; cannot be undone."""
        value = self._owned(token)
        _require(not value["recovery_only"])
        if value["phase"] == "native_intent":
            return
        value = self._state["obligation"].copy()
        value["phase"] = "native_intent"
        self._write({**self._state, "obligation": value})

    def release(
        self,
        token,
        *,
        definitely_undispatched=False,
        fenced_receipt=None,
        namespace_absent_proof=None,
        create_not_dispatched_proof=None,
    ):
        """Clear only with original caller-validated end/physical evidence."""
        value = self._owned(token)
        _require(type(definitely_undispatched) is bool)
        _require(
            sum(
                (
                    definitely_undispatched,
                    fenced_receipt is not None,
                    namespace_absent_proof is not None,
                    create_not_dispatched_proof is not None,
                )
            )
            == 1
        )
        if definitely_undispatched:
            _require(value["phase"] == "acquired")
        elif fenced_receipt is not None:
            proof = fenced_receipt
            _require(
                type(proof) is dict
                and set(proof)
                == {
                    *self._original,
                    "container_id",
                    "stopped",
                    "fenced",
                    "retired",
                    "container_present",
                    "pid",
                }
            )
            _require(
                all(proof[key] == expected for key, expected in self._original.items())
                and _hex(proof["container_id"], 64)
                and proof["stopped"] is True
                and proof["fenced"] is True
                and proof["retired"] is True
                and proof["container_present"] is False
                and type(proof["pid"]) is int
                and proof["pid"] == 0
            )
        elif create_not_dispatched_proof is not None:
            from .coding_execution_rules import validate_create_not_dispatched_projection

            _require(value["phase"] == "native_intent")
            validate_create_not_dispatched_projection(
                create_not_dispatched_proof, self._original, token
            )
        else:
            proof = namespace_absent_proof
            _require(
                type(proof) is dict
                and set(proof)
                == {
                    *self._original,
                    "namespace_absent",
                    "metadata_present",
                    "container_present",
                    "process_present",
                }
            )
            _require(
                all(proof[key] == expected for key, expected in self._original.items())
                and proof["namespace_absent"] is True
                and proof["metadata_present"] is False
                and proof["container_present"] is False
                and proof["process_present"] is False
            )
        self._write({**self._state, "obligation": None})
        self._drop_lock()

    def close(self):
        """Close mechanical OS ownership; retain any original obligation."""
        if self._closed:
            return
        self._drop_lock()
        if self._directory is not None:
            os.close(self._directory)
            self._directory = None
        self._closed = True
