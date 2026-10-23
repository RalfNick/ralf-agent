"""Restricted local Docker execution through real owned control threads."""

import asyncio
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict

from .component_fingerprint import executable_digest
from .docker_sandbox_transport import (
    DockerControl,
    NativeSandboxLease,
    decode_logs,
    lease_root,
    socket_identity,
)
from .errors import AuthorizationDenied, CloseIncomplete, DefinitionMismatch, ValidationError
from .sandbox import (
    SandboxExecutionRejected,
    SandboxIsolationViolation,
    SandboxObservation,
    SandboxRequest,
    SandboxResult,
    SandboxUnavailable,
    invocation,
    native_identity,
    validate_sandbox_result,
)
from .task_controls import _binding
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import Scope, canonical, digest
from .workspace import DEFAULT_SCOPES, _configuration, _utf8


class DockerSandbox:
    def __init__(
        self,
        socket_path,
        image,
        *,
        version,
        scopes=DEFAULT_SCOPES,
        api_version="1.44",
        memory_bytes=268435456,
        nano_cpus=1000000000,
        pids_limit=64,
        max_calls=4,
        max_output_bytes=1048576,
        scratch_bytes=33554432,
        control_timeout=5,
        lease_root_path=None,
    ):
        _utf8(socket_path, "Docker Unix socket", max_bytes=4096)
        if not socket_path.startswith("/") or "\x00" in socket_path:
            raise ValidationError("Docker Sandbox requires explicit absolute local Unix socket")
        if lease_root_path is None:
            lease_root_path = tempfile.gettempdir() + "/ralf-sandbox-leases-" + str(os.getuid())
        _utf8(lease_root_path, "Sandbox native lease root", max_bytes=4096)
        if not lease_root_path.startswith("/") or "\x00" in lease_root_path:
            raise ValidationError("Sandbox native leases require an absolute host directory")
        if type(image) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None:
            raise ValidationError("Docker Sandbox requires explicit installed image SHA256")
        _utf8(version, "Docker Sandbox version", max_bytes=256)
        if not version.strip():
            raise ValidationError("Docker Sandbox requires an explicit version")
        if type(api_version) is not str or api_version not in {f"1.{n}" for n in range(44, 53)}:
            raise ValidationError("Docker Sandbox requires explicit supported API1.44 through1.52")
        bounds = {
            "memory_bytes": (memory_bytes, 67108864, 1073741824),
            "nano_cpus": (nano_cpus, 250000000, 4000000000),
            "pids_limit": (pids_limit, 1, 256),
            "max_calls": (max_calls, 1, 16),
            "max_output_bytes": (max_output_bytes, 1, 16777216),
            "scratch_bytes": (scratch_bytes, 1048576, 67108864),
        }
        if any(
            type(value) is not int or not minimum <= value <= maximum
            for value, minimum, maximum in bounds.values()
        ):
            raise ValidationError("Docker Sandbox resource allowance is invalid")
        if type(control_timeout) not in (int, float) or not 0 < control_timeout <= 30:
            raise ValidationError("Docker control timeout requires finite seconds in (0,30]")
        self._scopes = _configuration(version, scopes)
        self._scope_json = canonical(
            [{"workspace": s.workspace, "principal": s.principal} for s in self._scopes]
        )
        for scope in self._scopes:
            self._scope(scope)
        self._config = {
            "kind": "docker-sandbox",
            "version": "1",
            "behavior_version": version,
            "socket_path": socket_path,
            "lease_root_path": lease_root_path,
            "image": image,
            "api_version": api_version,
            "scopes": [asdict(scope) for scope in self._scopes],
            **{name: value for name, (value, _, _) in bounds.items()},
            "control_timeout": control_timeout,
            "isolation": {
                "network": "none",
                "host_mounts": False,
                "persistent_files": False,
                "user": "65534:65534",
            },
        }
        self._control, self._pin, self._client = None, None, None
        self._closing, self._jobs = False, {}
        self._lock, self._tracker = threading.RLock(), ThreadExecutionTracker()
        self._open_gate = threading.Lock()
        self._hooks = {
            name: _binding(getattr(self, name))
            for name in (
                "aopen",
                "run",
                "observe",
                "stop",
                "aclose",
                "_container_config",
                "_check",
                "_open",
                "_connect",
                "_inspect",
                "_observation",
                "_stop",
                "_execute",
                "_tracked",
                "_check_scopes",
                "_scope",
                "_labels",
                "_name",
            )
        }
        self._config["implementation"] = {
            **{name: executable_digest(getattr(self, name)) for name in self._hooks},
            "control_request": executable_digest(DockerControl.request),
            "control_init": executable_digest(DockerControl.__init__),
            "control_json": executable_digest(DockerControl.json),
            "control_close": executable_digest(DockerControl.close),
            "decode_logs": executable_digest(decode_logs),
            "native_lease": executable_digest(NativeSandboxLease.__init__),
            "native_lease_close": executable_digest(NativeSandboxLease.close),
        }
        self._helper_pins = self._helpers()
        self._control_bindings = None
        self._config_json = canonical(self._config)
        self._config_digest = digest(self._config)

    def _assert_methods(self):
        if any(
            _binding(getattr(self, name, None)) != original
            for name, original in self._hooks.items()
        ):
            raise DefinitionMismatch("Original Docker Sandbox control implementation changed")
        try:
            helpers = self._helpers()
        except (AttributeError, ValidationError):
            raise DefinitionMismatch("Original Docker Sandbox native helpers changed") from None
        if helpers != self._helper_pins:
            raise DefinitionMismatch("Original Docker Sandbox native helper implementation changed")
        if self._control_bindings is not None and any(
            _binding(getattr(self._control, name, None)) != original
            for name, original in self._control_bindings.items()
        ):
            raise DefinitionMismatch("Original Docker control receiver changed")

    @staticmethod
    def _helpers():
        return {
            "control_factory": _binding(DockerControl),
            **{
                name: _binding(getattr(DockerControl, name))
                for name in ("__init__", "request", "json", "close")
            },
            "decode_logs": _binding(decode_logs),
            "lease_init": _binding(NativeSandboxLease.__init__),
            "lease_close": _binding(NativeSandboxLease.close),
        }

    def _check_scopes(self):
        if (
            type(self._scopes) not in (tuple, list)
            or not 1 <= len(self._scopes) <= 256
            or any(
                type(s) is not Scope or type(s.workspace) is not str or type(s.principal) is not str
                for s in self._scopes
            )
        ):
            raise DefinitionMismatch("Original Sandbox Scope allowlist changed")
        if (
            canonical([{"workspace": s.workspace, "principal": s.principal} for s in self._scopes])
            != self._scope_json
        ):
            raise DefinitionMismatch("Original Sandbox Scope allowlist changed")

    def _scope(self, scope):
        self._check_scopes()
        if (
            type(scope) is not Scope
            or type(scope.workspace) is not str
            or type(scope.principal) is not str
            or scope not in self._scopes
        ):
            raise AuthorizationDenied("Sandbox Scope is not authorized by the host")
        for name in ("workspace", "principal"):
            _utf8(getattr(scope, name), "Sandbox Scope", max_bytes=512)

    def _check(self, *, closing=False):
        self._assert_methods()
        self._check_scopes()
        if canonical(self._config) != self._config_json:
            raise DefinitionMismatch("Original Docker Sandbox configuration changed")
        if self._closing and not closing:
            raise SandboxUnavailable("Docker Sandbox is closing or closed")
        if self._control is None or self._pin is None:
            raise SandboxUnavailable("Docker Sandbox must be explicitly opened")
        if (
            self._control.client is not self._client
            or socket_identity(self._config["socket_path"]) != self._pin["socket"]
        ):
            raise DefinitionMismatch("Original Docker control endpoint changed")

    @property
    def identity(self):
        self._check()
        return json.loads(canonical({**self._config, "native": self._pin}))

    async def _tracked(self, function, *args):
        tracker = current_thread_tracker.get() or self._tracker
        token = (
            self._tracker._register(current_thread_group.get())
            if tracker is not self._tracker
            else None
        )

        def execute():
            if token is not None and not self._tracker._begin(token):
                return None
            try:
                return function(*args)
            finally:
                if token is not None:
                    self._tracker._finish(token)

        try:
            return await tracker.run(execute, group=current_thread_group.get())
        except BaseException:
            if token is not None:
                self._tracker._withdraw_pending(token)
            raise

    def _open(self):
        self._assert_methods()
        with self._open_gate:
            if self._control is not None:
                self._check()
                return
            self._connect()

    def _connect(self):
        if self._closing:
            raise SandboxUnavailable("Docker Sandbox is closed")
        socket = socket_identity(self._config["socket_path"])
        leases = lease_root(self._config["lease_root_path"])
        control = DockerControl(
            socket["path"], self._config["api_version"], self._config["control_timeout"]
        )
        try:
            info = control.json("GET", "info")
            image = control.json("GET", "images/" + self._config["image"] + "/json")
            if (
                type(info.get("ID")) is not str
                or not info["ID"]
                or info.get("OSType") != "linux"
                or type(info.get("SecurityOptions")) is not list
                or "name=seccomp,profile=builtin" not in info["SecurityOptions"]
                or image.get("Id") != self._config["image"]
                or image.get("Os") != "linux"
                or type(image.get("Config")) is not dict
                or image["Config"].get("Volumes")
            ):
                raise SandboxIsolationViolation(
                    "Docker engine or image does not satisfy the restricted profile"
                )
            self._pin = {
                "socket": socket,
                "leases": leases,
                "daemon_id": info["ID"],
                "engine_version": info["ServerVersion"],
                "image": image["Id"],
            }
            self._control, self._client = control, control.client
            self._control_bindings = {
                name: _binding(getattr(control, name)) for name in ("request", "json", "close")
            }
            self._check()
        except BaseException:
            control.close()
            self._pin, self._control, self._client = None, None, None
            self._control_bindings = None
            raise

    async def aopen(self):
        with self._lock:
            if self._closing:
                raise SandboxUnavailable("Docker Sandbox is closed")
            if self._control is not None:
                self._check()
                return self
        await self._tracked(self._open)
        return self

    def _name(self, scope, identity):
        return "ralf-sandbox-" + digest([self._config_digest, asdict(scope), identity])

    def _labels(self, scope, identity):
        return {
            "ralf.sandbox.owner": self._config_digest,
            "ralf.sandbox.scope": digest(asdict(scope)),
            "ralf.sandbox.invocation": identity,
        }

    def _container_config(self, scope, identity, request):
        self._scope(scope)
        invocation(identity)
        if type(request) is not SandboxRequest:
            raise ValidationError("Docker Sandbox requires original request")
        SandboxRequest.__post_init__(request)
        c = self._config
        return {
            "Image": c["image"],
            "User": "65534:65534",
            "WorkingDir": "/workspace",
            "Entrypoint": [request.argv[0]],
            "Cmd": list(request.argv[1:]),
            "Tty": False,
            "AttachStdout": True,
            "AttachStderr": True,
            "NetworkDisabled": True,
            "Healthcheck": {"Test": ["NONE"]},
            "Labels": {
                **self._labels(scope, identity),
                "ralf.sandbox.request": digest(SandboxRequest.to_dict(request)),
            },
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges"],
                "Memory": c["memory_bytes"],
                "MemorySwap": c["memory_bytes"],
                "NanoCpus": c["nano_cpus"],
                "PidsLimit": c["pids_limit"],
                "Tmpfs": {
                    path: f"rw,nosuid,nodev,size={c['scratch_bytes']},mode=1777"
                    for path in ("/workspace", "/tmp")
                },
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "16m", "max-file": "1"}},
            },
        }

    def _inspect(self, scope, identity, native=None):
        self._check(closing=True)
        info = self._control.json("GET", "info")
        if (
            info.get("ID") != self._pin["daemon_id"]
            or info.get("ServerVersion") != self._pin["engine_version"]
            or info.get("OSType") != "linux"
            or type(info.get("SecurityOptions")) is not list
            or "name=seccomp,profile=builtin" not in info["SecurityOptions"]
        ):
            raise DefinitionMismatch("Original Docker daemon or isolation policy changed")
        value = self._control.json(
            "GET",
            "containers/" + (native or self._name(scope, identity)) + "/json",
            accepted=(200, 404),
        )
        if value is None:
            return None
        native_identity(value.get("Id"))
        config = value.get("Config")
        labels = config.get("Labels") if type(config) is dict else None
        if type(labels) is not dict or any(
            labels.get(k) != v for k, v in self._labels(scope, identity).items()
        ):
            raise SandboxIsolationViolation(
                "Docker native environment belongs to another source or Scope"
            )
        if native is not None and value["Id"] != native:
            raise SandboxIsolationViolation("Docker native environment identity changed")
        return value

    def _observation(self, scope, identity, native=None):
        value = self._inspect(scope, identity, native)
        if value is None:
            return SandboxObservation(identity, None, "not_found")
        state = value.get("State", {})
        if type(state) is not dict or type(state.get("Running")) is not bool:
            raise SandboxUnavailable("Docker returned incomplete native state evidence")
        if state["Running"]:
            kind, code = "running", None
        elif state.get("Status") == "exited":
            kind, code = "stopped", state.get("ExitCode")
        elif state.get("Status") == "created":
            kind, code = "created", None
        else:
            kind, code = "unknown", None
        return SandboxObservation(identity, value["Id"], kind, code)

    async def observe(self, scope, invocation_id):
        self._scope(scope)
        invocation(invocation_id)
        return await self._tracked(self._observation, scope, invocation_id)

    def _stop(self, scope, identity, native=None):
        value = self._observation(scope, identity, native)
        if value.state == "running":
            self._control.request(
                "POST", "containers/" + value.native_id + "/kill", accepted=(204, 409)
            )
            value = self._observation(scope, identity, value.native_id)
        return value

    async def stop(self, scope, invocation_id):
        self._scope(scope)
        invocation(invocation_id)
        with self._lock:
            job = self._jobs.get(self._name(scope, invocation_id))
            if job is not None:
                job["stop"].set()
        return await self._tracked(self._stop, scope, invocation_id)

    def _execute(self, scope, identity, request, job):
        with self._lock:
            if job.get("withdrawn"):
                raise SandboxExecutionRejected(handler_not_started=True)
            job["started"] = True
        native, result, error = None, None, None
        lease = None
        create_dispatched = False
        timed_out, truncated, stdout, stderr = False, False, "", ""
        try:
            try:
                lease = NativeSandboxLease(self._pin["leases"], self._name(scope, identity))
            except SandboxUnavailable:
                raise SandboxExecutionRejected(handler_not_started=True) from None
            config = self._container_config(scope, identity, request)
            existing = self._inspect(scope, identity)
            if existing is None:
                create_dispatched = True
                try:
                    created = self._control.json(
                        "POST",
                        "containers/create?name=" + self._name(scope, identity),
                        body=config,
                        accepted=(201,),
                    )
                    native = native_identity(created.get("Id"))
                except Exception:
                    existing = self._inspect(scope, identity)
                    if existing is None:
                        raise
            if existing is not None:
                if (
                    existing["Config"]["Labels"].get("ralf.sandbox.request")
                    != config["Labels"]["ralf.sandbox.request"]
                ):
                    raise SandboxIsolationViolation(
                        "Docker invocation differs from its original native request"
                    )
                native = existing["Id"]
            observed = self._observation(scope, identity, native)
            if observed.state == "created":
                try:
                    self._control.request(
                        "POST", "containers/" + native + "/start", accepted=(204, 304)
                    )
                except SandboxUnavailable:
                    observed = self._observation(scope, identity, native)
                    if observed.state not in {"running", "stopped"}:
                        raise
            deadline = time.monotonic() + request.timeout
            while True:
                observed = self._observation(scope, identity, native)
                _, data = self._control.request(
                    "GET",
                    "containers/" + native + "/logs?stdout=1&stderr=1",
                    max_bytes=16777216 + 65536,
                )
                stdout, stderr, truncated = decode_logs(
                    data, max_bytes=self._config["max_output_bytes"]
                )
                if observed.state == "stopped":
                    result = SandboxResult(
                        identity,
                        native,
                        observed.exit_code,
                        stdout,
                        stderr,
                        truncated,
                        timed_out,
                        observed,
                    )
                    break
                timed_out |= time.monotonic() >= deadline
                if timed_out or truncated or job["stop"].is_set():
                    self._stop(scope, identity, native)
                time.sleep(0.05)
        except BaseException as exc:
            error = exc
        finally:
            if native is not None or create_dispatched:
                while True:
                    try:
                        if native is None:
                            existing = self._inspect(scope, identity)
                            if existing is None:
                                break
                            native = existing["Id"]
                        observed = self._stop(scope, identity, native)
                        if observed.state in {"stopped", "created", "not_found"}:
                            if observed.state != "not_found":
                                self._control.request(
                                    "DELETE", "containers/" + native, accepted=(204, 404)
                                )
                            break
                    except Exception:
                        pass  # Keep the actual thread/slot owned until native cleanup can be proven.
                    time.sleep(0.25)
            with self._lock:
                self._jobs.pop(self._name(scope, identity), None)
            if lease is not None:
                lease.close()
        if error is not None:
            raise error
        return validate_sandbox_result(
            result, identity, max_output_bytes=self._config["max_output_bytes"]
        )

    async def run(self, scope, request, *, invocation_id):
        self._scope(scope)
        invocation(invocation_id)
        self._container_config(scope, invocation_id, request)
        request = SandboxRequest.from_dict(SandboxRequest.to_dict(request))
        self._check()
        key = self._name(scope, invocation_id)
        with self._lock:
            if self._closing or key in self._jobs or len(self._jobs) >= self._config["max_calls"]:
                raise SandboxExecutionRejected(handler_not_started=True)
            job = {"stop": threading.Event()}
            self._jobs[key] = job
        try:
            return await self._tracked(self._execute, scope, invocation_id, request, job)
        except BaseException:
            job["stop"].set()
            with self._lock:
                if not job.get("started"):
                    job["withdrawn"] = True
                    self._jobs.pop(key, None)
            raise

    async def aclose(self, wait_timeout=30):
        if type(wait_timeout) not in (int, float) or not 0 <= wait_timeout <= 300:
            raise ValidationError("Docker close timeout requires finite nonnegative seconds")
        with self._lock:
            self._closing = True
            for job in self._jobs.values():
                job["stop"].set()
        try:
            async with asyncio.timeout(wait_timeout):
                await self._tracker.drain()
        except TimeoutError:
            raise CloseIncomplete("Actual Docker execution is still owned") from None
        with self._lock:
            if self._jobs:
                raise CloseIncomplete("Unresolved native Docker executions remain owned")
            if self._control is not None:
                self._control.close()
                self._control, self._client = None, None
                self._control_bindings = None
