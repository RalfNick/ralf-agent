"""Retained Docker namespace resource. Preparation is never Turn authorization.

The caller must freshly inspect before spawning transport_argv(), and must stop
the whole resource when its transport ends. Inspection proves the container
boundary/configuration; it does not prove every native tool or model channel.
"""

import asyncio
import copy
import fcntl
import hashlib
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .codex_coding_profile import CodexCodingProfile
from .errors import DefinitionMismatch, ExecutionHostFailed, ValidationError
from .tools import ThreadExecutionTracker

_SECCOMP_DIGEST = "569e7aa0a4d8ed2b0bfada839187309d880c21350c36eaa2b55f15c0c85b41aa"
_COMMAND = ["app-server", "--listen", "stdio://", "--strict-config"]
_ENTRYPOINT = "/opt/codex/bin/codex"
_IMAGE_ENV = [
    "PATH=/opt/codex/bin:/opt/codex/codex-path:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME=/home/ralf",
    "TMPDIR=/workspace/.tmp",
]
_REGISTRY = "/tmp/codex-bwrap-synthetic-mount-targets-10001"
_REGISTRY_OPTIONS = "rw,nosuid,nodev,noexec,size=1048576,uid=10001,gid=10001,mode=0700"
_CAP = 2 * 1024 * 1024
_ZERO_TIME = "0001-01-01T00:00:00Z"


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _require(condition):
    if not condition:
        raise DefinitionMismatch("Retained Coding environment differs from its pinned declaration")


def _pin(path):
    info = path.lstat()
    _require(not stat.S_ISLNK(info.st_mode))
    return {"path": str(path.resolve(strict=True)), "device": info.st_dev, "inode": info.st_ino}


class DockerCodingEnvironment:
    """One private root, persistent exclusive lease and exact retained container ID.

    Docker Desktop maps the nonroot guest UID differently from the host caller.
    Mount subdirectories are writable inside a host-owned 0700 root; metadata,
    the lease, and seccomp stay outside both mounts. No host credentials or
    repository/socket mounts enter the container. No container removal occurs.
    """

    def __init__(
        self,
        root: str | Path,
        resource_id: str,
        *,
        docker_executable: str,
        docker_host: str,
        command_timeout: float = 20.0,
    ):
        try:
            path = Path(root)
            executable = Path(docker_executable)
            valid = (
                os.name == "posix"
                and path.is_absolute()
                and path.is_dir()
                and not path.is_symlink()
                and path.stat().st_uid == os.getuid()
                and stat.S_IMODE(path.stat().st_mode) == 0o700
                and type(resource_id) is str
                and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", resource_id)
                and executable.is_absolute()
                and executable.is_file()
                and os.access(executable, os.X_OK)
                and type(docker_host) is str
                and docker_host.startswith("unix:///")
                and not any(c in docker_host for c in ("\0", "\n", "\r", "?", "#"))
                and type(command_timeout) in (int, float)
                and math.isfinite(command_timeout)
                and 0 < command_timeout <= 60
            )
        except (OSError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValidationError(
                "Coding environment requires a private absolute root and explicit Docker endpoint"
            )
        if any(c in str(path.resolve()) for c in (",", "\0", "\n", "\r")):
            raise ValidationError("Coding resource path cannot be encoded as a Docker bind mount")
        self._declared_root = path
        self._root = path.resolve(strict=True)
        self._root_pin = _pin(path)
        self._docker = str(executable)
        self._executable_pin = _pin(executable.resolve(strict=True))
        self._host = docker_host
        self._timeout = command_timeout
        self._profile = CodexCodingProfile()
        self._seccomp = Path(__file__).with_name("_codex_coding_seccomp.json").read_bytes()
        _require(_digest(self._seccomp) == _SECCOMP_DIGEST)
        self._identity = {
            "kind": "docker-coding-environment",
            "version": "1",
            "resource_id": resource_id,
            "root": self._root_pin,
            "declared_root": str(path),
            "docker_executable": self._docker,
            "docker_executable_pin": self._executable_pin,
            "docker_host": docker_host,
            "profile": self._profile.identity,
            "seccomp_digest": _SECCOMP_DIGEST,
            "native_argv": [_ENTRYPOINT, *_COMMAND],
            "network": "bridge",
            "tool_network_enabled": False,
            "execution_admitted": False,
        }
        self._resource_id = resource_id
        self._name = "ralf-coding-" + _digest(_canonical(self._identity).encode())[:32]
        self._metadata = None
        self._lease = None
        self._lease_pin = None
        self._prepared = False
        self._closing = False
        self._closed = False
        self._last = None
        self._operation_lock = asyncio.Lock()
        self._operation_task = None
        self._worker_lock = threading.RLock()
        self._workers = ThreadExecutionTracker()

    @property
    def identity(self) -> dict:
        return copy.deepcopy(self._identity)

    @property
    def transport_env(self) -> dict:
        return {"PATH": f"{Path(self._docker).parent}:/usr/bin:/bin"}

    @property
    def active_operations(self) -> int:
        """Actual registered worker calls; an asyncio cancellation is not exit."""
        return self._workers.active_count

    def transport_argv(self) -> tuple[str, ...]:
        """No I/O or implicit start. Caller must freshly inspect before spawn."""
        if (
            not self._prepared
            or self._closing
            or self._closed
            or self._last is None
            or self._last["running"]
            or not self._last["stopped"]
        ):
            raise ValidationError("Coding transport requires a prepared stopped owned resource")
        self._check_root()
        self._check_files()
        return (
            self._docker,
            "--config",
            str(self._root / "docker-client"),
            "--host",
            self._host,
            "start",
            "--attach",
            "--interactive",
            self._metadata["container_id"],
        )

    async def prepare(self) -> dict:
        return await self._owned(self._prepare)

    async def inspect(self) -> dict:
        return await self._owned(self._inspect)

    async def stop(self) -> dict:
        return await self._owned(self._stop)

    async def aclose(self) -> None:
        await self._owned(self._close)

    async def _owned(self, operation):
        async with self._operation_lock:
            task = asyncio.create_task(self._workers.run(self._serialized_operation, operation))
            self._operation_task = task
            cancelled = False
            drain = None
            try:
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        cancelled = True
                    except Exception:
                        break  # Retrieve the error only after actual worker drain.
                # Loop-wide cancel-all can also cancel the tracker Task above.
                # Its Future completion therefore is not worker/Popen exit.
                # Tracker ownership ends in the real worker, independently of
                # asyncio callbacks. Recreate cancelled drains during shutdown.
                while self._workers.has_active:
                    if drain is None or drain.done():
                        drain = asyncio.create_task(self._workers.drain())
                    try:
                        await asyncio.shield(drain)
                    except asyncio.CancelledError:
                        cancelled = True
                if cancelled or task.cancelled():
                    if task.done() and not task.cancelled():
                        task.exception()
                    raise asyncio.CancelledError
                return copy.deepcopy(task.result())
            finally:
                self._operation_task = None

    def _serialized_operation(self, operation):
        # The real mutex also excludes operations across event loops, even if
        # a caller's asyncio wrapper has already been cancelled.
        with self._worker_lock:
            return operation()

    def _check_root(self):
        try:
            _require(_pin(self._declared_root) == self._root_pin)
            info = self._root.stat()
            _require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
            _require(_pin(Path(self._docker).resolve(strict=True)) == self._executable_pin)
            if self._lease is not None:
                lock = self._root / "lease.lock"
                _require(_pin(lock) == self._lease_pin)
                info = lock.lstat()
                _require(
                    info.st_nlink == 1
                    and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600
                )
        except OSError:
            raise DefinitionMismatch("Coding resource physical pin is unavailable") from None

    def _acquire(self):
        self._check_root()
        if self._lease is not None:
            return
        try:
            fd = os.open(self._root / "lease.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            info = os.fstat(fd)
            _require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600
            )
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, DefinitionMismatch):
            if "fd" in locals():
                os.close(fd)
            raise ExecutionHostFailed("Coding resource lease is unavailable") from None
        self._lease = fd
        self._lease_pin = _pin(self._root / "lease.lock")
        self._check_root()

    def _read_metadata(self):
        path = self._root / "environment.json"
        try:
            info = path.lstat()
            _require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_size <= 65536
            )
            value = json.loads(path.read_bytes())
            _require(
                type(value) is dict
                and set(value)
                == {"identity", "generation", "container_id", "files", "lease_pin", "last_state"}
            )
            _require(_canonical(value["identity"]) == _canonical(self._identity))
            _require(value["lease_pin"] == self._lease_pin)
            _require(
                type(value["generation"]) is str
                and re.fullmatch(r"[a-f0-9]{32}", value["generation"])
            )
            _require(
                value["container_id"] is None
                or (
                    type(value["container_id"]) is str
                    and re.fullmatch(r"[a-f0-9]{64}", value["container_id"])
                )
            )
            self._metadata = value
            self._check_files()
        except (OSError, ValueError, TypeError, KeyError):
            raise DefinitionMismatch("Coding metadata is unavailable or invalid") from None

    def _write_metadata(self):
        self._check_root()
        path = self._root / (".metadata-" + uuid.uuid4().hex)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write((_canonical(self._metadata) + "\n").encode())
                out.flush()
                os.fsync(out.fileno())
            os.replace(path, self._root / "environment.json")
            parent = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            path.unlink(missing_ok=True)

    def _provision(self):
        # Pre-existing root children would be an unowned import, not a clean
        # resource. Never silently overwrite config/state or protected paths.
        _require(set(p.name for p in self._root.iterdir()) == {"lease.lock"})
        for relative in (
            "workspace",
            "state",
            "workspace/.git",
            "workspace/.agents",
            "workspace/.codex",
            "workspace/.tmp",
        ):
            directory = self._root / relative
            directory.mkdir(mode=0o777)
            directory.chmod(0o777)
        (self._root / "docker-client").mkdir(mode=0o700)
        for relative, data in (
            ("state/config.toml", self._profile.config_text.encode()),
            ("seccomp.json", self._seccomp),
            ("docker-client/config.json", b"{}\n"),
        ):
            path = self._root / relative
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            path.chmod(0o444 if relative.startswith("state/") else 0o600)
        self._metadata = {
            "identity": self.identity,
            "generation": uuid.uuid4().hex,
            "container_id": None,
            "lease_pin": self._lease_pin,
            "last_state": None,
            "files": {
                p: _pin(self._root / p)
                for p in (
                    "workspace",
                    "state",
                    "workspace/.git",
                    "workspace/.agents",
                    "workspace/.codex",
                    "workspace/.tmp",
                    "state/config.toml",
                    "seccomp.json",
                    "docker-client",
                    "docker-client/config.json",
                )
            },
        }
        self._write_metadata()

    def _check_files(self):
        try:
            files = self._metadata["files"]
            _require(
                type(files) is dict
                and set(files)
                == {
                    "workspace",
                    "state",
                    "workspace/.git",
                    "workspace/.agents",
                    "workspace/.codex",
                    "workspace/.tmp",
                    "state/config.toml",
                    "seccomp.json",
                    "docker-client",
                    "docker-client/config.json",
                }
            )
            for relative, pin in files.items():
                path = self._root / relative
                _require(_pin(path) == pin)
                _require(path.is_file() if relative.endswith((".toml", ".json")) else path.is_dir())
            for relative, expected in (
                ("state/config.toml", self._profile.identity["config_digest"]),
                ("seccomp.json", _SECCOMP_DIGEST),
                ("docker-client/config.json", _digest(b"{}\n")),
            ):
                path = self._root / relative
                _require(path.stat().st_nlink == 1 and path.stat().st_size <= 65536)
                _require(
                    path.stat().st_uid == os.getuid()
                    and stat.S_IMODE(path.stat().st_mode)
                    == (0o444 if relative == "state/config.toml" else 0o600)
                )
                _require(_digest(path.read_bytes()) == expected)
            client = self._root / "docker-client"
            _require(
                client.stat().st_uid == os.getuid()
                and stat.S_IMODE(client.stat().st_mode) == 0o700
                and set(p.name for p in client.iterdir()) == {"config.json"}
            )
        except (OSError, TypeError, KeyError):
            raise DefinitionMismatch(
                "Coding resource paths or configuration have drifted"
            ) from None

    def _labels(self):
        return {
            "ralf.coding.environment": "1",
            "ralf.coding.resource": self._resource_id,
            "ralf.coding.profile": self._profile.identity["config_digest"],
            "ralf.coding.root": _digest(_canonical(self._root_pin).encode()),
            "ralf.coding.generation": self._metadata["generation"],
        }

    def _create_argv(self):
        args = [
            "create",
            "--interactive",
            "--name",
            self._name,
            "--user=10001:10001",
            "--workdir=/workspace",
            "--entrypoint=" + _ENTRYPOINT,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--security-opt=seccomp=" + str(self._root / "seccomp.json"),
            "--network=bridge",
            "--pids-limit=64",
            "--memory=512m",
            "--cpus=1",
            "--restart=no",
            "--pull=never",
            "--ipc=private",
            "--cgroupns=private",
            "--env",
            "TMPDIR=/workspace/.tmp",
            "--tmpfs",
            _REGISTRY + ":" + _REGISTRY_OPTIONS,
        ]
        for key, value in self._labels().items():
            args += ["--label", key + "=" + value]
        for source, target in (("workspace", "/workspace"), ("state", "/home/ralf/.codex")):
            args += ["--mount", f"type=bind,source={self._root / source},target={target}"]
        return [*args, self._profile.identity["image_id"], *_COMMAND]

    def _prepare(self):
        if self._closed or self._closing:
            raise ValidationError("Coding environment is closing or closed")
        self._acquire()
        if (self._root / "environment.json").exists():
            self._read_metadata()
        elif self._metadata is None:
            self._provision()
        self._check_files()
        if self._metadata["container_id"] is None:
            # A persisted intent can recover only its exact generation-labelled,
            # never-started created container after a create/metadata crash.
            ids = (
                self._cli(
                    [
                        "ps",
                        "-a",
                        "--no-trunc",
                        "--filter",
                        "name=^/" + self._name + "$",
                        "--filter",
                        "label=ralf.coding.generation=" + self._metadata["generation"],
                        "--format",
                        "{{.ID}}",
                    ]
                )[0]
                .decode()
                .split()
            )
            _require(len(ids) <= 1)
            if ids:
                cid = ids[0]
            else:
                cid = self._cli(self._create_argv())[0].decode().strip()
            _require(bool(re.fullmatch(r"[a-f0-9]{64}", cid)))
            self._metadata["container_id"] = cid
            # Persist the locator before any exposure, even if validation fails.
            self._write_metadata()
        if self._metadata["last_state"] is None:
            # The locator may have been persisted immediately before a crash
            # or failed validation. It remains an intent until this check and
            # the first complete inspection have both succeeded.
            state = self._inspect_raw()
            _require(
                state["State"]["Status"] == "created" and state["State"]["StartedAt"] == _ZERO_TIME
            )
        result = self._inspect()
        self._prepared = True
        return result

    def _inspect_raw(self):
        try:
            data = json.loads(self._cli(["inspect", self._metadata["container_id"]])[0])
            _require(type(data) is list and len(data) == 1 and type(data[0]) is dict)
            self._validate_container(data[0])
            return data[0]
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise ExecutionHostFailed("Docker container inspection is invalid") from None

    def _validate_container(self, container):
        cfg, host, state = container["Config"], container["HostConfig"], container["State"]
        image = self._profile.identity["image_id"]
        _require(
            container["Id"] == self._metadata["container_id"]
            and container["Name"] == "/" + self._name
            and container["Image"] == image
        )
        for key, value in {
            "User": "10001:10001",
            "WorkingDir": "/workspace",
            "Entrypoint": [_ENTRYPOINT],
            "Cmd": _COMMAND,
            "Image": image,
            "OpenStdin": True,
            "Tty": False,
            "Volumes": None,
        }.items():
            _require(_canonical(cfg.get(key)) == _canonical(value))
        _require(type(cfg["Env"]) is list and sorted(cfg["Env"]) == sorted(_IMAGE_ENV))
        _require(all(cfg["Labels"].get(k) == v for k, v in self._labels().items()))
        # Image labels may coexist; every resource namespace label is frozen.
        _require(
            {k: v for k, v in cfg["Labels"].items() if k.startswith("ralf.coding.")}
            == self._labels()
        )
        for key, value in {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "NetworkMode": "bridge",
            "PidsLimit": 64,
            "Memory": 536870912,
            "NanoCpus": 1000000000,
            "AutoRemove": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "PidMode": "",
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "UTSMode": "",
            "UsernsMode": "",
            "Binds": None,
            "VolumesFrom": None,
            "PortBindings": {},
            "Devices": [],
            "DeviceRequests": None,
            "PublishAllPorts": False,
            "ExtraHosts": None,
            "Links": None,
            "Tmpfs": {_REGISTRY: _REGISTRY_OPTIONS},
        }.items():
            _require(_canonical(host.get(key)) == _canonical(value))
        opts = host["SecurityOpt"]
        _require(type(opts) is list and len(opts) == 2 and "no-new-privileges" in opts)
        seccomp = [v for v in opts if type(v) is str and v.startswith("seccomp=")]
        _require(len(seccomp) == 1)
        _require(_canonical(json.loads(seccomp[0][8:])) == _canonical(json.loads(self._seccomp)))
        mounts = container["Mounts"]
        _require(type(mounts) is list and len(mounts) == 2)
        expected = {
            "/workspace": str(self._root / "workspace"),
            "/home/ralf/.codex": str(self._root / "state"),
        }
        observed = {}
        for mount in mounts:
            _require(
                mount["Type"] == "bind"
                and mount["RW"] is True
                and mount["Propagation"] == "rprivate"
                and mount["Destination"] not in observed
            )
            observed[mount["Destination"]] = mount["Source"]
        _require(observed == expected)
        _require(
            type(state["Running"]) is bool
            and type(state["Pid"]) is int
            and (
                (state["Running"] and state["Pid"] > 0)
                or (not state["Running"] and state["Pid"] == 0)
            )
        )
        _require(
            state["Paused"] is False
            and state["Restarting"] is False
            and state["Dead"] is False
            and container["RestartCount"] == 0
            and state["Status"] in ("created", "running", "exited")
        )
        _require(
            all(type(state[k]) is str and len(state[k]) <= 64 for k in ("StartedAt", "FinishedAt"))
        )
        _require(type(state["ExitCode"]) is int)

    def _inspect(self):
        if self._lease is None or self._metadata is None or self._metadata["container_id"] is None:
            raise ValidationError("Coding resource has no prepared owned container")
        self._check_root()
        self._check_files()
        state = self._inspect_raw()["State"]
        self._last = {
            "identity": self.identity,
            "resource_id": self._resource_id,
            "container_id": self._metadata["container_id"],
            "generation": self._metadata["generation"],
            "running": state["Running"],
            "pid": state["Pid"],
            "stopped": not state["Running"] and state["Pid"] == 0,
            "status": state["Status"],
            "exit_code": state["ExitCode"],
            "started_at": state["StartedAt"],
            "finished_at": state["FinishedAt"],
            "execution_admitted": False,
        }
        self._metadata["last_state"] = {
            k: self._last[k]
            for k in (
                "running",
                "pid",
                "stopped",
                "status",
                "exit_code",
                "started_at",
                "finished_at",
            )
        }
        self._write_metadata()
        return self._last

    def _stop(self):
        state = self._inspect()
        if state["running"]:
            self._cli(["kill", "--signal=KILL", self._metadata["container_id"]])
        result = self._inspect()
        if not result["stopped"]:
            raise ExecutionHostFailed("Coding container stop is not confirmed")
        return result

    def _close(self):
        if self._closed:
            return
        self._closing = True
        if self._lease is None:
            self._closed = True
            return
        # A failure keeps the lease and permits another aclose/stop attempt.
        if self._metadata is None or self._metadata["container_id"] is None:
            self._closing = False
            self._prepare()
            self._closing = True
        self._stop()
        os.close(self._lease)
        self._lease = None
        self._closed = True

    def _cli(self, args):
        """Own real PID immediately; bound output/deadline and always reap it."""
        self._check_root()
        self._check_files()
        process = None
        selector = selectors.DefaultSelector()
        output = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            process = subprocess.Popen(
                [
                    self._docker,
                    "--config",
                    str(self._root / "docker-client"),
                    "--host",
                    self._host,
                    *args,
                ],
                env=self.transport_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            for key in output:
                selector.register(getattr(process, key), selectors.EVENT_READ, key)
            deadline = time.monotonic() + self._timeout
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise ExecutionHostFailed("Docker CLI deadline exceeded")
                for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output[key.data].extend(chunk)
                    if sum(map(len, output.values())) > _CAP:
                        raise ExecutionHostFailed("Docker CLI output bound exceeded")
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            if process.returncode != 0:
                raise ExecutionHostFailed("Docker CLI operation failed")
            self._check_root()
            return bytes(output["stdout"]), bytes(output["stderr"])
        except (OSError, subprocess.TimeoutExpired):
            raise ExecutionHostFailed("Docker CLI operation unavailable") from None
        finally:
            if process is not None:
                # Kill the group even after leader exit: descendants may retain
                # inherited pipes. Never strand a subprocess on cancellation.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                process.stdout.close()
                process.stderr.close()
            selector.close()
