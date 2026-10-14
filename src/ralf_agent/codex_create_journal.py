"""Private immutable records for one original mechanical CREATE operation."""

import fcntl
import json
import os
import re
import stat
import subprocess
import time
import uuid
from pathlib import Path

from .coding_resource_fingerprint import policy_value
from .errors import DefinitionMismatch
from .types import canonical, digest

_MAX_RECORD = 65536
_WRITERS = {
    "declaration.json": "worker",
    "launch.json": "worker",
    "worker-go.json": "worker",
    "broker-register.json": "broker",
    "outer-decision.json": "broker",
    "inner-go.json": "broker",
    "broker-result.json": "broker",
    "gate-register.json": "gate",
    "inner-decision.json": "gate",
    "gate-exec.json": "gate",
}


def require(value):
    if not value:
        raise DefinitionMismatch("Original CREATE supervision binding changed")


def hex_value(value, count):
    return type(value) is str and re.fullmatch("[a-f0-9]{" + str(count) + "}", value) is not None


def pin(path):
    path = Path(path)
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and str(path) == str(path.resolve(strict=True)))
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def private_directory(path, expected=None):
    actual = pin(path)
    info = Path(path).lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )
    require(expected is None or actual == expected)
    return actual


def private_file(info):
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
    )


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result)
        result[key] = value
    return result


def birth(pid):
    """Read-only birth observation, never permission to signal a cold PID."""
    require(type(pid) is int and pid > 0)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart="],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        capture_output=True,
        timeout=3,
    )
    text = result.stdout.decode("ascii").strip()
    if result.returncode == 0 and 0 < len(text) <= 256 and "\n" not in text:
        return text
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    raise DefinitionMismatch("Original CREATE process birth is unavailable")


def process_ended(registered):
    """Observe disappearance or an exited zombie; never signal or wait a cold PID."""
    current = birth(registered["pid"])
    if current != registered["birth"]:
        return True
    result = subprocess.run(
        ["/bin/ps", "-p", str(registered["pid"]), "-o", "stat="],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        capture_output=True,
        timeout=3,
    )
    state = result.stdout.decode("ascii").strip()
    if not (result.returncode == 0 and 0 < len(state) <= 64 and "\n" not in state):
        require(birth(registered["pid"]) != registered["birth"])
        return True
    return state.startswith("Z") and birth(registered["pid"]) == registered["birth"]


def check_fd(fd, expected):
    require(type(fd) is int and fd >= 3)
    info = os.fstat(fd)
    private_file(info)
    require({"path": expected["path"], "device": info.st_dev, "inode": info.st_ino} == expected)
    require(pin(Path(expected["path"])) == expected)


def lock_released(expected):
    fd = os.open(expected["path"], os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        check_fd(fd, expected)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    finally:
        os.close(fd)


class OperationJournal:
    def __init__(self, root, declaration, *, actor="observer"):
        self.root = Path(root)
        self.declaration = json.loads(canonical(declaration))
        self.actor = actor
        self.directory = self.root / ".create-operation"
        self.check()

    def check(self):
        value = self.declaration
        require(
            type(value) is dict
            and set(value)
            == {
                "version",
                "binding",
                "token",
                "root",
                "operation_root",
                "operation_lock",
                "namespace_lease",
                "control_directory",
                "argv",
                "cli_env",
                "executable",
                "python",
                "python_executable",
                "timeout",
                "output_limit",
                "command_digest",
                "required_sources",
            }
        )
        require(type(value["version"]) is int and value["version"] == 1)
        require(hex_value(value["token"], 32) and hex_value(value["command_digest"], 64))
        private_directory(self.root, value["root"])
        private_directory(self.directory, value["operation_root"])
        private_directory(value["control_directory"]["path"], value["control_directory"])
        require(Path(value["namespace_lease"]["path"]) == self.root / "lease.lock")
        require(Path(value["operation_lock"]["path"]) == self.directory / "operation.lock")
        for name in ("namespace_lease", "operation_lock"):
            expected = value[name]
            require(pin(expected["path"]) == expected)
            private_file(Path(expected["path"]).lstat())
        for name, executable in (
            ("executable", value["argv"][0]),
            ("python_executable", value["python"]),
        ):
            resolved = Path(executable).resolve(strict=True)
            require(
                pin(resolved) == value[name] and resolved.is_file() and os.access(resolved, os.X_OK)
            )
        require(digest({"argv": value["argv"], "env": value["cli_env"]}) == value["command_digest"])
        from .coding_create_inventory import check_source_inventory

        check_source_inventory(value["required_sources"])

    def read(self, name, *, missing=False):
        require(name in _WRITERS)
        self.check()
        path = self.directory / name
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            if missing:
                return None
            raise DefinitionMismatch("Original CREATE writer receipt is missing") from None
        except OSError:
            raise DefinitionMismatch("Original CREATE writer receipt is unavailable") from None
        try:
            info = os.fstat(fd)
            # Publication briefly has the writer's temporary link and target.
            # An alias that remains is still rejected by private_file below.
            if info.st_nlink == 2:
                for _ in range(20):
                    time.sleep(0.005)
                    info = os.fstat(fd)
                    if info.st_nlink != 2:
                        break
            private_file(info)
            require(info.st_size <= _MAX_RECORD)
            raw = os.read(fd, _MAX_RECORD + 1)
            require(len(raw) == info.st_size and len(raw) <= _MAX_RECORD)
            require(pin(path) == {"path": str(path), "device": info.st_dev, "inode": info.st_ino})
            value = json.loads(raw, object_pairs_hook=pairs)
            policy_value(value)
            return value
        except (ValueError, UnicodeError, TypeError):
            raise DefinitionMismatch("Original CREATE writer receipt is invalid") from None
        finally:
            os.close(fd)

    def write(self, name, value):
        require(_WRITERS.get(name) == self.actor)
        self.check()
        policy_value(value)
        raw = canonical(value).encode()
        require(len(raw) <= _MAX_RECORD)
        path = self.directory / name
        temporary = self.directory / (".write-" + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
            self.check()
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                require(canonical(self.read(name)) == raw.decode())
            temporary.unlink()
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.close(fd)
            temporary.unlink(missing_ok=True)


def registration(declaration):
    return {
        "declaration_digest": digest(declaration),
        "token": declaration["token"],
        "command_digest": declaration["command_digest"],
        "pid": os.getpid(),
        "birth": birth(os.getpid()),
    }


def check_registration(value, declaration):
    fields = {"declaration_digest", "token", "command_digest", "pid", "birth"}
    require(
        type(value) is dict and set(value) in (fields, fields | {"socket"}, fields | {"accepted"})
    )
    require(
        value["declaration_digest"] == digest(declaration)
        and value["token"] == declaration["token"]
        and value["command_digest"] == declaration["command_digest"]
        and type(value["pid"]) is int
        and value["pid"] > 0
        and type(value["birth"]) is str
        and 0 < len(value["birth"]) <= 256
    )


def gate_message(declaration):
    return {"token": declaration["token"], "declaration_digest": digest(declaration), "go": True}


def accepted_frame(raw, declaration):
    try:
        require(len(raw) <= 512)
        value = json.loads(raw, object_pairs_hook=pairs)
        require(type(value) is dict and set(value) == {"token", "declaration_digest", "go"})
        return value == gate_message(declaration) and value["go"] is True
    except (ValueError, DefinitionMismatch, UnicodeError):
        return False


def load_declaration(root):
    private_directory(root)
    directory = Path(root) / ".create-operation"
    private_directory(directory)
    path = directory / "declaration.json"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        private_file(info)
        require(info.st_size <= _MAX_RECORD)
        raw = os.read(fd, _MAX_RECORD + 1)
        require(len(raw) == info.st_size)
        value = json.loads(raw, object_pairs_hook=pairs)
    finally:
        os.close(fd)
    journal = OperationJournal(root, value)
    require(journal.read("declaration.json") == value)
    return value
