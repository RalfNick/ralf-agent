"""Pure/default transport guards; mock evidence never certifies native isolation."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import relf_agent as r
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, RalfError

IMAGE = "sha256:" + "a" * 64


def api():
    value = getattr(r, "DockerSandbox", None)
    assert value is not None, "Missing DockerSandbox provider"
    return value


def provider(**values):
    return api()(
        **{
            "socket_path": "/private/tmp/no-docker.sock",
            "image": IMAGE,
            "version": "1",
            **values,
        }
    )


def test_valid_configuration_does_not_allocate_transport_or_connect(monkeypatch):
    import httpx

    def forbidden(*args, **kwargs):
        raise AssertionError("constructor must not allocate or connect a client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    value = provider()
    with pytest.raises(RalfError):
        _ = value.identity
    asyncio.run(value.aclose(wait_timeout=0))


@pytest.mark.parametrize(
    "values",
    [
        {"socket_path": "relative.sock"},
        {"socket_path": "https://docker.example"},
        {"socket_path": "/tmp/\x00.sock"},
        {"image": "alpine:latest"},
        {"image": IMAGE.upper()},
        {"version": ""},
        {"version": True},
        {"api_version": "1.43"},
        {"api_version": True},
        {"memory_bytes": True},
        {"memory_bytes": 67108863},
        {"memory_bytes": 1073741825},
        {"nano_cpus": 249999999},
        {"nano_cpus": 4000000001},
        {"pids_limit": 0},
        {"pids_limit": 257},
        {"max_calls": 0},
        {"max_calls": 17},
        {"max_output_bytes": 0},
        {"max_output_bytes": 16777217},
        {"scratch_bytes": 1048575},
        {"scratch_bytes": 67108865},
        {"control_timeout": True},
        {"control_timeout": 0},
        {"control_timeout": float("nan")},
        {"control_timeout": 31},
        {"scopes": []},
        {"scopes": [r.Scope(), r.Scope()]},
        {"scopes": ["user"]},
    ],
)
def test_pure_native_configuration_refuses_unsafe_or_unbounded_profile(values):
    with pytest.raises(RalfError):
        provider(**values)


def test_scope_and_invocation_preflight_happens_before_socket_io():
    value = provider()

    async def run():
        for identity in ("", "x" * 129, "bad/identity"):
            with pytest.raises(RalfError):
                await value.run(r.Scope(), r.SandboxRequest(["/bin/echo"]), invocation_id=identity)
        with pytest.raises(AuthorizationDenied):
            await value.observe(r.Scope("foreign", "user"), "call")
        await value.aclose(wait_timeout=0)

    asyncio.run(run())


def test_restricted_create_profile_does_not_inherit_host_or_image_permissions():
    value = provider()
    config = value._container_config(r.Scope(), "call", r.SandboxRequest(["/bin/sh", "-c", "id"]))
    assert config["User"] == "65534:65534" and config["NetworkDisabled"] is True
    assert config["Entrypoint"] == ["/bin/sh"] and config["Cmd"] == ["-c", "id"]
    assert config["Healthcheck"] == {"Test": ["NONE"]} and config["Tty"] is False
    host = config["HostConfig"]
    assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] is True
    assert host["CapDrop"] == ["ALL"] and host["SecurityOpt"] == ["no-new-privileges"]
    assert host["Memory"] == host["MemorySwap"] == 268435456
    assert host["NanoCpus"] == 1000000000 and host["PidsLimit"] == 64
    assert not any(key in host for key in ("Binds", "Mounts", "Devices", "Privileged"))
    assert set(host["Tmpfs"]) == {"/workspace", "/tmp"}


def test_plain_native_log_multiplex_preserves_streams():
    api()
    from relf_agent.docker_sandbox_transport import decode_logs

    def frame(stream, data):
        return bytes([stream, 0, 0, 0]) + len(data).to_bytes(4, "big") + data

    data = frame(1, "中文🙂".encode()) + frame(2, b"error")
    assert decode_logs(data, max_bytes=100) == ("中文🙂", "error", False)
    stdout, stderr, truncated = decode_logs(data, max_bytes=10)
    assert stdout == "中文🙂" and stderr == "" and truncated is True


@pytest.mark.parametrize(
    "data",
    [
        b"short",
        b"\x03\x00\x00\x00\x00\x00\x00\x00",
        b"\x01\x01\x00\x00\x00\x00\x00\x00",
        b"\x01\x00\x00\x00\x00\x00\x00\x10short",
    ],
)
def test_malformed_native_log_frames_fail_before_adoption(data):
    api()
    from relf_agent.docker_sandbox_transport import decode_logs

    with pytest.raises(RalfError):
        decode_logs(data, max_bytes=100)


def test_missing_socket_explicit_open_fails_closed_and_can_close():
    value = provider()

    async def run():
        with pytest.raises(r.SandboxUnavailable):
            await value.aopen()
        await value.aclose(wait_timeout=0)
        with pytest.raises(RalfError):
            await value.aopen()

    asyncio.run(run())


def test_conflicting_native_request_is_refused_without_killing_existing_work(monkeypatch, tmp_path):
    value = provider()
    identity, native, destructive = "call", "b" * 64, []
    snapshot = {
        "Id": native,
        "Config": {
            "Labels": {**value._labels(r.Scope(), identity), "ralf.sandbox.request": "different"}
        },
        "State": {"Running": True, "Status": "running", "ExitCode": 0},
    }

    class Control:
        def json(self, *args, **kwargs):
            if args[1] == "info":
                return {
                    "ID": "original",
                    "ServerVersion": "29.0.1",
                    "OSType": "linux",
                    "SecurityOptions": ["name=seccomp,profile=builtin"],
                }
            return snapshot

        def request(self, method, path, **kwargs):
            destructive.append((method, path))
            snapshot["State"] = {"Running": False, "Status": "exited", "ExitCode": 137}
            return 204, b""

    monkeypatch.setattr(value, "_check", lambda **kwargs: None)
    value._control = Control()
    value._pin = {"daemon_id": "original", "engine_version": "29.0.1"}
    from relf_agent.docker_sandbox_transport import lease_root

    value._pin["leases"] = lease_root(str(tmp_path / "leases"))
    with pytest.raises(r.SandboxIsolationViolation):
        value._execute(
            r.Scope(), identity, r.SandboxRequest(["/bin/echo"]), {"stop": threading.Event()}
        )
    assert destructive == [], "a conflicting request modified existing native work"


def test_cancel_before_native_thread_begins_releases_only_unstarted_slot(monkeypatch):
    value = provider()
    monkeypatch.setattr(value, "_check", lambda **kwargs: None)
    entered, release = threading.Event(), threading.Event()

    def occupy():
        entered.set()
        assert release.wait(5)

    async def run():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        blocked = loop.run_in_executor(None, occupy)
        task = None
        try:
            for _ in range(500):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set()
            task = asyncio.create_task(
                value.run(r.Scope(), r.SandboxRequest(["/bin/echo"]), invocation_id="queued")
            )
            await asyncio.sleep(0)
            assert len(value._jobs) == 1
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert value._jobs == {}, "cancelled unstarted call retained a native capacity slot"
            await value.aclose(wait_timeout=0)
        finally:
            release.set()
            await blocked
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_same_socket_proxy_replacement_cannot_adopt_other_daemon_evidence(monkeypatch):
    value = provider()
    invocation_id, native, queried = "call", "b" * 64, []

    class Control:
        def json(self, method, path, **kwargs):
            queried.append(path)
            if path == "info":
                return {
                    "ID": "replacement",
                    "ServerVersion": "29.0.1",
                    "OSType": "linux",
                    "SecurityOptions": ["name=seccomp,profile=builtin"],
                }
            return {
                "Id": native,
                "Config": {"Labels": value._labels(r.Scope(), invocation_id)},
                "State": {"Running": False, "Status": "exited", "ExitCode": 0},
            }

    monkeypatch.setattr(value, "_check", lambda **kwargs: None)
    value._control = Control()
    value._pin = {"daemon_id": "original", "engine_version": "29.0.1"}
    with pytest.raises(DefinitionMismatch):
        value._observation(r.Scope(), invocation_id)
    assert queried == ["info"], "replacement daemon result was queried before identity refusal"


@pytest.mark.parametrize("security", [None, ["name=seccomp,profile=custom"]])
def test_open_refuses_missing_or_nondefault_seccomp_before_publishing_identity(
    monkeypatch, security
):
    from relf_agent import docker_sandbox as native

    class Control:
        def __init__(self, *args):
            self.client = object()

        def json(self, method, path, **kwargs):
            if path == "info":
                return {
                    "ID": "original",
                    "ServerVersion": "29.0.1",
                    "OSType": "linux",
                    "SecurityOptions": security,
                }
            return {"Id": IMAGE, "Os": "linux", "Config": {}}

        def request(self, *args, **kwargs):
            raise AssertionError("seccomp admission must precede dispatch")

        def close(self):
            pass

    monkeypatch.setattr(
        native, "socket_identity", lambda path: {"path": path, "device": 1, "inode": 1}
    )
    monkeypatch.setattr(native, "DockerControl", Control)
    value = provider()
    with pytest.raises(RalfError):
        value._open()
    assert value._pin is None and value._control is None


def test_native_profile_method_drift_is_refused_before_dispatch(monkeypatch):
    value = provider()

    def unsafe(*args):
        return {"HostConfig": {"Privileged": True}}

    monkeypatch.setattr(value, "_container_config", unsafe)
    with pytest.raises(DefinitionMismatch):
        value._assert_methods()


def test_provider_implementation_is_part_of_fixed_profile_identity():
    class ChangedDocker(api()):
        def _container_config(self, scope, identity, request):
            return super()._container_config(scope, identity, request)

    original = provider()
    changed = ChangedDocker("/private/tmp/no-docker.sock", IMAGE, version="1")
    assert "implementation" in original._config
    assert original._config["implementation"] != changed._config["implementation"]
    assert original._config_digest != changed._config_digest


def test_concurrent_explicit_open_owns_only_one_control_client(monkeypatch):
    from relf_agent import docker_sandbox as native

    entered, release, clients = threading.Event(), threading.Event(), []

    class Control:
        def __init__(self, *args):
            self.client, self.closed = object(), False
            self.clients.append(self)

        def json(self, method, path, **kwargs):
            if path == "info":
                self.entered.set()
                assert self.release.wait(5)
                return {
                    "ID": "original",
                    "ServerVersion": "29.0.1",
                    "OSType": "linux",
                    "SecurityOptions": ["name=seccomp,profile=builtin"],
                }
            return {"Id": IMAGE, "Os": "linux", "Config": {}}

        def request(self, *args, **kwargs):
            raise AssertionError("no container dispatch during open")

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        native, "socket_identity", lambda path: {"path": path, "device": 1, "inode": 1}
    )
    monkeypatch.setattr(native, "DockerControl", Control)
    Control.entered, Control.release, Control.clients = entered, release, clients
    value = provider()

    async def run():
        first = asyncio.create_task(value.aopen())
        second = None
        try:
            for _ in range(500):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set()
            second = asyncio.create_task(value.aopen())
            await asyncio.sleep(0.05)
            release.set()
            assert await first is value and await second is value
            assert len(clients) == 1, "concurrent open allocated two clients and lost one owner"
            await value.aclose(wait_timeout=1)
            assert all(client.closed for client in clients)
        finally:
            release.set()
            await asyncio.gather(
                first, *([] if second is None else [second]), return_exceptions=True
            )

    asyncio.run(run())


def test_scope_raw_fields_are_rejected_before_authorization_comparison():
    value = provider()

    class Forged(str):
        def __eq__(self, other):
            raise AssertionError("Scope comparison hook must not run")

    scope = r.Scope(Forged("default"), "local-owner")
    with pytest.raises(AuthorizationDenied):
        value._scope(scope)
