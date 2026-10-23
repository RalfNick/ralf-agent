"""One original CREATE broker, two sealed gates, and no cold execution rights."""

import copy
import ctypes
import fcntl
import hashlib
import json
import math
import os
import select
import selectors
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .codex_create_journal import (
    OperationJournal,
    accepted_frame,
    birth,
    check_fd,
    check_registration,
    gate_message,
    hex_value,
    load_declaration,
    lock_released,
    pairs,
    pin,
    private_directory,
    process_ended,
    registration,
    require,
)
from .coding_process_wait import ChildExitMonitor, signal_unreaped_group
from .coding_resource_fingerprint import policy_value
from .errors import DefinitionMismatch, ExecutionHostFailed, ValidationError
from .types import canonical, digest

_PYTHON_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
_BOOTSTRAP = """import hashlib,json,os,stat,sys,types
names=('__init__','errors','types','component_fingerprint','coding_resource_fingerprint','coding_process_wait','coding_execution_rules','coding_create_inventory','codex_create_journal','codex_create_supervisor','codex_create_gate')
directory=sys.argv[1];required=json.loads(sys.argv[2]);entry=sys.argv[3]
if type(required) is not dict or set(required)!=set(names) or entry not in ('codex_create_supervisor','codex_create_gate'):raise SystemExit(2)
sources={}
for name in names:
 path=os.path.join(directory,name+'.py');fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=8388608:raise SystemExit(2)
  with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(info.st_size+1)
  if len(data)!=info.st_size or type(required[name]) is not str or hashlib.sha256(data).hexdigest()!=required[name]:raise SystemExit(2)
  sources[name]=(path,data)
 finally:os.close(fd)
package=types.ModuleType('relf_agent');package.__path__=[directory];package.__package__='relf_agent';sys.modules['relf_agent']=package
for name in names[1:]:
 path,data=sources[name];module=types.ModuleType('relf_agent.'+name);module.__file__=path;module.__package__='relf_agent';sys.modules[module.__name__]=module;setattr(package,name,module)
 exec(compile(data,path,'exec'),module.__dict__)
sys.argv=[sources[entry][0],*sys.argv[4:]]
raise SystemExit(sys.modules['relf_agent.'+entry].main())
"""
_RECEIPT_FIELDS = frozenset(
    {
        "version",
        "declaration_digest",
        "binding_digest",
        "token",
        "command_digest",
        "broker",
        "child",
        "outer_gate_accepted",
        "gate_sealed",
        "cli_gate_accepted",
        "cli_exec_started",
        "child_ended",
        "exit_code",
        "output_complete",
        "stdout_digest",
        "stderr_digest",
        "cid",
        "reason",
    }
)


def _spawn_argv(declaration, entry, arguments):
    from .coding_create_inventory import check_source_inventory, source_paths

    check_source_inventory(declaration["required_sources"])
    package = str(Path(source_paths()["codex_create_supervisor"]).parent)
    return [
        declaration["python"],
        "-I",
        "-c",
        _BOOTSTRAP,
        package,
        canonical(declaration["required_sources"]),
        entry,
        *arguments,
    ]


def _peer(connection):
    if hasattr(connection, "getpeereid"):
        require(connection.getpeereid()[0] == os.getuid())
    elif hasattr(socket, "SO_PEERCRED"):
        _, uid, _ = struct.unpack(
            "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        require(uid == os.getuid())
    elif sys.platform == "darwin":
        function = ctypes.CDLL(None, use_errno=True).getpeereid
        function.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        function.restype = ctypes.c_int
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        require(
            function(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0
            and uid.value == os.getuid()
        )
    else:
        raise DefinitionMismatch("Original CREATE peer authentication is unavailable")


def _socket_pin(path):
    value = pin(path)
    info = Path(path).lstat()
    require(
        stat.S_ISSOCK(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
    )
    return value


def _request(journal, command):
    require(command in {"query", "abort", "drain"})
    registered = journal.read("broker-register.json")
    check_registration(registered, journal.declaration)
    path = Path(journal.declaration["control_directory"]["path"]) / "control.sock"
    require(_socket_pin(path) == registered["socket"])
    message = {
        "token": journal.declaration["token"],
        "declaration_digest": digest(journal.declaration),
        "command": command,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        connection.connect(str(path))
        _peer(connection)
        require(_socket_pin(path) == registered["socket"])
        connection.sendall(canonical(message).encode())
        connection.shutdown(socket.SHUT_WR)
        raw = connection.recv(1024)
        reply = json.loads(raw, object_pairs_hook=pairs)
        require(reply == {"token": message["token"], "command": command, "received": True})


def _serve(listener, declaration):
    try:
        connection, _ = listener.accept()
    except BlockingIOError:
        return False
    with connection:
        try:
            _peer(connection)
            connection.settimeout(0.2)
            raw = bytearray()
            while len(raw) <= 512:
                part = connection.recv(513)
                if not part:
                    break
                raw.extend(part)
            require(len(raw) <= 512)
            request = json.loads(raw, object_pairs_hook=pairs)
            require(
                type(request) is dict
                and set(request) == {"token", "declaration_digest", "command"}
                and request["token"] == declaration["token"]
                and request["declaration_digest"] == digest(declaration)
                and request["command"] in {"query", "abort", "drain"}
            )
            connection.sendall(
                canonical(
                    {"token": request["token"], "command": request["command"], "received": True}
                ).encode()
            )
            return request["command"] == "abort"
        except (OSError, ValueError, TypeError, DefinitionMismatch):
            return False


def _receipt(journal, broker, child, outer, exit_code, output, reason, *, output_complete):
    decision = journal.read("inner-decision.json", missing=True)
    if decision is not None:
        check_registration(decision, journal.declaration)
        require(
            set(decision)
            == {"declaration_digest", "token", "command_digest", "pid", "birth", "accepted"}
            and type(decision["accepted"]) is bool
            and child is not None
            and decision["pid"] == child["pid"]
            and decision["birth"] == child["birth"]
        )
    sealed = not outer or decision is not None
    accepted = False if not outer else None if decision is None else decision["accepted"]
    executed = None if accepted is None else accepted
    cid = None
    if exit_code == 0 and accepted and output_complete:
        try:
            candidate = bytes(output["stdout"]).decode("ascii").strip()
        except UnicodeError:
            candidate = ""
        if hex_value(candidate, 64):
            cid = candidate
    return {
        "version": 1,
        "declaration_digest": digest(journal.declaration),
        "binding_digest": digest(journal.declaration["binding"]),
        "token": journal.declaration["token"],
        "command_digest": journal.declaration["command_digest"],
        "broker": {key: broker[key] for key in ("pid", "birth")},
        "child": None if child is None else {key: child[key] for key in ("pid", "birth")},
        "outer_gate_accepted": outer,
        "gate_sealed": sealed,
        "cli_gate_accepted": accepted,
        "cli_exec_started": executed,
        "child_ended": True,
        "exit_code": exit_code,
        "output_complete": output_complete,
        "stdout_digest": hashlib.sha256(output["stdout"]).hexdigest(),
        "stderr_digest": hashlib.sha256(output["stderr"]).hexdigest(),
        "cid": cid,
        "reason": reason,
    }


def validate_receipt(journal, value):
    require(type(value) is dict and set(value) == _RECEIPT_FIELDS)
    require(
        type(value["version"]) is int
        and value["version"] == 1
        and value["declaration_digest"] == digest(journal.declaration)
        and value["binding_digest"] == digest(journal.declaration["binding"])
        and value["token"] == journal.declaration["token"]
        and value["command_digest"] == journal.declaration["command_digest"]
    )
    for name in ("outer_gate_accepted", "gate_sealed", "child_ended", "output_complete"):
        require(type(value[name]) is bool)
    for name in ("cli_gate_accepted", "cli_exec_started"):
        require(value[name] is None or type(value[name]) is bool)
    require(
        value["child_ended"] is True
        and value["cli_exec_started"] is value["cli_gate_accepted"]
        and (value["gate_sealed"] is True) == (value["cli_gate_accepted"] is not None)
        and (value["exit_code"] is None or type(value["exit_code"]) is int)
        and all(hex_value(value[name], 64) for name in ("stdout_digest", "stderr_digest"))
        and (value["cid"] is None or hex_value(value["cid"], 64))
        and value["reason"]
        in {"outer_never", "completed", "timeout", "aborted", "output_limit", "gate_failed"}
    )
    registered = journal.read("broker-register.json")
    check_registration(registered, journal.declaration)
    require(value["broker"] == {key: registered[key] for key in ("pid", "birth")})
    outer = journal.read("outer-decision.json")
    require(
        type(outer) is dict
        and type(outer.get("accepted")) is bool
        and outer
        == {
            "declaration_digest": digest(journal.declaration),
            "accepted": value["outer_gate_accepted"],
        }
    )
    child = journal.read("gate-register.json", missing=True)
    if value["child"] is not None:
        check_registration(child, journal.declaration)
        require(set(child) == {"declaration_digest", "token", "command_digest", "pid", "birth"})
        require(value["child"] == {key: child[key] for key in ("pid", "birth")})
    else:
        require(child is None)
    decision = journal.read("inner-decision.json", missing=True)
    if value["outer_gate_accepted"]:
        worker_go = journal.read("worker-go.json")
        require(worker_go == gate_message(journal.declaration) and worker_go["go"] is True)
        if decision is not None:
            check_registration(decision, journal.declaration)
            require(
                set(decision)
                == {"declaration_digest", "token", "command_digest", "pid", "birth", "accepted"}
                and type(decision["accepted"]) is bool
                and child is not None
                and all(decision[key] == child[key] for key in ("pid", "birth"))
                and value["cli_gate_accepted"] is decision["accepted"]
            )
        else:
            require(value["cli_gate_accepted"] is None)
    else:
        require(
            value["child"] is None
            and decision is None
            and value["cli_gate_accepted"] is False
            and value["reason"] == "outer_never"
        )
    if value["cli_gate_accepted"] is False:
        require(journal.read("gate-exec.json", missing=True) is None)
    require(
        value["cid"] is None
        or (
            value["cli_gate_accepted"] is True
            and value["exit_code"] == 0
            and value["output_complete"] is True
        )
    )


def run_broker(root, namespace_fd, operation_fd, grant_fd, ready_fd):
    declaration = load_declaration(root)
    journal = OperationJournal(root, declaration, actor="broker")
    check_fd(namespace_fd, declaration["namespace_lease"])
    check_fd(operation_fd, declaration["operation_lock"])
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = Path(declaration["control_directory"]["path"]) / "control.sock"
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen(4)
    listener.setblocking(False)
    broker = {**registration(declaration), "socket": _socket_pin(path)}
    journal.write("broker-register.json", broker)
    os.write(ready_fd, b"R")
    os.close(ready_fd)
    raw = bytearray()
    eof, aborted = False, False
    deadline = time.monotonic() + declaration["timeout"]
    while not eof and not aborted and time.monotonic() < deadline:
        ready = select.select([grant_fd, listener], [], [], 0.05)[0]
        if listener in ready:
            aborted = _serve(listener, declaration)
        if grant_fd in ready:
            part = os.read(grant_fd, 513)
            if not part:
                eof = True
            else:
                raw.extend(part)
                if len(raw) > 512:
                    aborted = True
    os.close(grant_fd)
    outer = not aborted and eof and accepted_frame(bytes(raw), declaration)
    if outer:
        require(journal.read("worker-go.json") == gate_message(declaration))
    journal.write(
        "outer-decision.json", {"declaration_digest": digest(declaration), "accepted": outer}
    )
    output = {"stdout": bytearray(), "stderr": bytearray()}
    if not outer:
        listener.close()
        require(_socket_pin(path) == broker["socket"])
        path.unlink()
        journal.write(
            "broker-result.json",
            _receipt(
                journal, broker, None, False, None, output, "outer_never", output_complete=True
            ),
        )
        return 0
    monitor = ChildExitMonitor()
    child = None
    gate_read, gate_write = os.pipe()
    ready_read, ready_write = os.pipe()
    selector = selectors.DefaultSelector()
    reason = "completed"
    process = None
    try:
        process = subprocess.Popen(
            _spawn_argv(
                declaration,
                "codex_create_gate",
                [str(root), str(namespace_fd), str(operation_fd), str(gate_read), str(ready_write)],
            ),
            env=_PYTHON_ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            pass_fds=(namespace_fd, operation_fd, gate_read, ready_write),
            start_new_session=True,
        )
        monitor.register(process)
        os.close(gate_read)
        gate_read = None
        os.close(ready_write)
        ready_write = None
        deadline = time.monotonic() + declaration["timeout"]
        registered = False
        while time.monotonic() < deadline and not monitor.exited() and not aborted:
            ready = select.select([ready_read, listener], [], [], 0.05)[0]
            if listener in ready:
                aborted = _serve(listener, declaration)
            if ready_read in ready:
                if os.read(ready_read, 1) == b"R":
                    child = journal.read("gate-register.json")
                    check_registration(child, declaration)
                    require(child["pid"] == process.pid and child["birth"] == birth(process.pid))
                    registered = True
                break
        os.close(ready_read)
        ready_read = None
        if registered and not aborted:
            journal.write("inner-go.json", gate_message(declaration))
            os.write(gate_write, canonical(gate_message(declaration)).encode())
        os.close(gate_write)
        gate_write = None
        if not registered:
            reason = "gate_failed"
        for key in output:
            selector.register(getattr(process, key), selectors.EVENT_READ, key)
        complete = True
        signalled = False
        while not monitor.exited():
            if time.monotonic() >= deadline:
                reason = "timeout"
                aborted = True
            if listener in select.select([listener], [], [], 0)[0]:
                if _serve(listener, declaration):
                    reason = "aborted"
                    aborted = True
            if aborted and not signalled:
                signal_unreaped_group(process, monitor)
                signalled = True
            for key, _ in selector.select(0.02):
                part = os.read(key.fd, 8192)
                if not part:
                    selector.unregister(key.fileobj)
                elif sum(map(len, output.values())) + len(part) > declaration["output_limit"]:
                    reason = "output_limit"
                    complete = False
                    aborted = True
                elif complete:
                    output[key.data].extend(part)
        # Signal while the unreaped original child still reserves its PID/group.
        signal_unreaped_group(process, monitor)
        exit_code = process.wait()
        drain_deadline = time.monotonic() + 2
        while selector.get_map() and time.monotonic() < drain_deadline:
            for key, _ in selector.select(0.02):
                part = os.read(key.fd, 8192)
                if not part:
                    selector.unregister(key.fileobj)
                elif sum(map(len, output.values())) + len(part) > declaration["output_limit"]:
                    complete = False
                    reason = "output_limit"
                elif complete:
                    output[key.data].extend(part)
        complete = complete and not selector.get_map()
        listener.close()
        require(_socket_pin(path) == broker["socket"])
        path.unlink()
        journal.write(
            "broker-result.json",
            _receipt(
                journal, broker, child, True, exit_code, output, reason, output_complete=complete
            ),
        )
        return 0
    finally:
        if process is not None:
            if process.returncode is None:
                signal_unreaped_group(process, monitor)
                process.wait()
            process.stdout.close()
            process.stderr.close()
        for fd in (gate_read, gate_write, ready_read, ready_write):
            if fd is not None:
                os.close(fd)
        selector.close()
        monitor.close()
        listener.close()
        if path.exists():
            require(_socket_pin(path) == broker["socket"])
            path.unlink()


class CreateSupervisor:
    def __init__(self, root, declaration, *, cold):
        self._journal = OperationJournal(root, declaration, actor="observer" if cold else "worker")
        self._cold = cold
        self._process = None
        self._monitor = None
        self._operation_fd = None
        self._namespace_fd = None
        self._go_write = None
        self._closed = False
        self._ready_validated = False

    @classmethod
    def create(
        cls, root, *, binding, argv, namespace_lease_fd, cli_env, timeout=20.0, output_limit=2097152
    ):
        from .coding_create_inventory import source_inventory

        root = Path(root)
        policy_value(binding)
        require(
            type(binding) is dict
            and set(binding)
            in (
                {"environment", "generation", "operation_digest"},
                {"environment", "generation", "operation_digest", "dispatch_digest"},
            )
            and type(binding["environment"]) is dict
            and hex_value(binding["generation"], 32)
            and hex_value(binding["operation_digest"], 64)
            and ("dispatch_digest" not in binding or hex_value(binding["dispatch_digest"], 64))
        )
        if not (
            type(argv) is list
            and 6 <= len(argv) <= 128
            and all(type(arg) is str and "\0" not in arg and len(arg) <= 8192 for arg in argv)
            and argv[1] == "--config"
            and argv[3] == "--host"
            and argv[5] == "create"
            and type(cli_env) is dict
            and set(cli_env) == {"PATH"}
            and type(cli_env["PATH"]) is str
            and len(cli_env["PATH"]) <= 4096
            and type(timeout) in (int, float)
            and math.isfinite(timeout)
            and 0 < timeout <= 60
            and type(output_limit) is int
            and 64 <= output_limit <= 2097152
        ):
            raise ValidationError(
                "CREATE supervisor requires one fixed bounded command and PATH-only environment"
            )
        root_pin = private_directory(root)
        lease_pin = pin(root / "lease.lock")
        check_fd(namespace_lease_fd, lease_pin)
        executable = pin(Path(argv[0]).resolve(strict=True))
        require(Path(argv[0]).is_file() and os.access(argv[0], os.X_OK))
        directory = root / ".create-operation"
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            raise DefinitionMismatch("Original CREATE operation cannot be relaunched") from None
        operation_fd = os.open(
            directory / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        fcntl.flock(operation_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        control = Path(tempfile.mkdtemp(prefix="ralf-c-", dir=str(Path("/tmp").resolve())))
        try:
            declaration = {
                "version": 1,
                "binding": json.loads(canonical(binding)),
                "token": uuid.uuid4().hex,
                "root": root_pin,
                "operation_root": private_directory(directory),
                "operation_lock": pin(directory / "operation.lock"),
                "namespace_lease": lease_pin,
                "control_directory": private_directory(control),
                "argv": argv.copy(),
                "cli_env": cli_env.copy(),
                "executable": executable,
                "python": sys.executable,
                "python_executable": pin(Path(sys.executable).resolve(strict=True)),
                "timeout": timeout,
                "output_limit": output_limit,
                "command_digest": digest({"argv": argv, "env": cli_env}),
                "required_sources": source_inventory(),
            }
            result = cls(root, declaration, cold=False)
            result._journal.write("declaration.json", declaration)
            result._operation_fd = operation_fd
            result._namespace_fd = namespace_lease_fd
            return result
        except BaseException:
            os.close(operation_fd)
            raise

    @classmethod
    def open(cls, root, declaration):
        actual = load_declaration(root)
        require(canonical(actual) == canonical(declaration))
        return cls(root, actual, cold=True)

    @property
    def declaration(self):
        return copy.deepcopy(self._journal.declaration)

    def launch(self):
        require(not self._cold and not self._closed and self._process is None)
        require(self._journal.read("launch.json", missing=True) is None)
        self._monitor = ChildExitMonitor()
        self._journal.write("launch.json", {"declaration_digest": digest(self.declaration)})
        grant_read, grant_write = os.pipe()
        ready_read, ready_write = os.pipe()
        try:
            self._process = subprocess.Popen(
                _spawn_argv(
                    self.declaration,
                    "codex_create_supervisor",
                    [
                        "broker",
                        str(self._journal.root),
                        str(self._namespace_fd),
                        str(self._operation_fd),
                        str(grant_read),
                        str(ready_write),
                    ],
                ),
                env=_PYTHON_ENV,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=(self._namespace_fd, self._operation_fd, grant_read, ready_write),
                start_new_session=True,
            )
            self._monitor.register(self._process)
            os.close(self._operation_fd)
            self._operation_fd = None
            os.close(grant_read)
            grant_read = None
            os.close(ready_write)
            ready_write = None
            self._go_write = grant_write
            grant_write = None
            deadline = time.monotonic() + self.declaration["timeout"]
            while time.monotonic() < deadline:
                if self._monitor.exited():
                    break
                if select.select([ready_read], [], [], 0.05)[0]:
                    require(os.read(ready_read, 1) == b"R")
                    registered = self._journal.read("broker-register.json")
                    check_registration(registered, self.declaration)
                    require(
                        registered["pid"] == self._process.pid
                        and registered["birth"] == birth(self._process.pid)
                    )
                    self._ready_validated = True
                    return self
            raise ExecutionHostFailed("Original CREATE broker registration is unconfirmed")
        finally:
            for fd in (grant_read, grant_write, ready_read, ready_write):
                if fd is not None:
                    os.close(fd)

    def start_once(self):
        require(
            not self._cold
            and not self._closed
            and self._process is not None
            and self._ready_validated
            and self._process.returncode is None
            and not self._monitor.exited()
            and self._go_write is not None
            and self._journal.read("outer-decision.json", missing=True) is None
            and self._journal.read("worker-go.json", missing=True) is None
        )
        message = gate_message(self.declaration)
        self._journal.write("worker-go.json", message)
        self._journal.check()
        os.write(self._go_write, canonical(message).encode())
        os.close(self._go_write)
        self._go_write = None

    def query(self):
        self._journal.check()
        registered = self._journal.read("broker-register.json", missing=True)
        receipt = self._journal.read("broker-result.json", missing=True)
        if registered is not None:
            check_registration(registered, self.declaration)
        if receipt is not None:
            validate_receipt(self._journal, receipt)
        if self._process is not None:
            if self._process.returncode is None and self._monitor.exited():
                signal_unreaped_group(self._process, self._monitor)
                self._process.wait()
            broker_ended = self._process.returncode is not None
        else:
            broker_ended = registered is not None and process_ended(registered)
        drained = lock_released(self.declaration["operation_lock"])
        ended = bool(receipt is not None and broker_ended and drained)
        return {
            "declaration_digest": digest(self.declaration),
            "receipt": receipt,
            "receipt_digest": None if receipt is None else digest(receipt),
            "helpers_ended": ended,
            "control_drained": ended,
            "complete": ended,
        }

    def drain(self, *, timeout=None):
        timeout = self.declaration["timeout"] + 5 if timeout is None else timeout
        require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 65)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.query()
            if result["complete"]:
                return result
            time.sleep(0.02)
        raise ExecutionHostFailed("Original CREATE supervision remains unknown")

    def abort(self, *, timeout=None):
        if self._go_write is not None:
            os.close(self._go_write)
            self._go_write = None
        try:
            _request(self._journal, "abort")
        except (OSError, ValueError, ExecutionHostFailed):
            pass  # Query immutable receipts; never signal a cold numeric PID.
        return self.drain(timeout=timeout)

    def close(self):
        if self._go_write is not None:
            os.close(self._go_write)
            self._go_write = None
        if self._operation_fd is not None:
            os.close(self._operation_fd)
            self._operation_fd = None
        if (
            self._process is not None
            and self._process.returncode is None
            and self._monitor.exited()
        ):
            signal_unreaped_group(self._process, self._monitor)
            self._process.wait()
        if self._monitor is not None and (
            self._process is None or self._process.returncode is not None
        ):
            self._monitor.close()
        self._closed = True


def main():
    try:
        require(len(sys.argv) == 7 and sys.argv[1] == "broker")
        return run_broker(sys.argv[2], *(int(value) for value in sys.argv[3:]))
    except BaseException:
        return 2


if __name__ == "__main__":
    sys.exit(main())
