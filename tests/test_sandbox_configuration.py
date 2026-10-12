"""Explicit declarations fail before native admission and allocation."""

import asyncio

import pytest

import ralf_agent as r
from ralf_agent.errors import ValidationError


def config():
    return {"version": "1", "socket_path": "/missing/docker.sock", "image": "sha256:" + "a" * 64}


def test_native_sandbox_default_is_registered_as_async_only():
    from ralf_agent.ports import is_async_callable

    factory, _ = r.ComponentRegistry().prepare(
        "tools", {"adapter": "sandbox-docker", "config": config()}
    )
    assert is_async_callable(factory)


@pytest.mark.parametrize(
    "extra",
    [
        {"network": "host"},
        {"mounts": ["/"]},
        {"image": "alpine:latest"},
        {"max_timeout": True},
        {"memory_bytes": 0},
        {"prefix": False},
        {"requires_approval": "no"},
        {"cost": -1},
        {"scopes": [{"workspace": "x", "principal": 0}]},
    ],
)
def test_declared_resource_limits_and_tool_policy_preflight_before_io(tmp_path, extra):
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "sandbox-docker", "config": {**config(), **extra}}},
    )

    async def run():
        with pytest.raises(ValidationError):
            await r.RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert not (tmp_path / "runs.sqlite").exists()


def test_sync_build_refuses_native_async_admission_before_store(tmp_path):
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "sandbox-docker", "config": config()}},
    )
    with pytest.raises(ValidationError, match="abuild"):
        r.RuntimeBuilder(base_dir=tmp_path).build(profile, tmp_path / "runs.sqlite")
    assert not (tmp_path / "runs.sqlite").exists()


def test_partial_native_admission_failure_closes_owned_provider_without_store(
    tmp_path, monkeypatch
):
    from ralf_agent import sandbox_factories
    from ralf_agent.errors import RalfError

    owned = []

    class FailedProvider:
        def __init__(self, *args, **kwargs):
            self.closed = False

        async def aopen(self):
            owned.append(self)
            raise RalfError("test-native-admission-refused")

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(sandbox_factories, "DockerSandbox", FailedProvider)
    profile = r.RuntimeProfile(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "sandbox-docker", "config": config()}},
    )

    async def run():
        with pytest.raises(RalfError):
            await r.RuntimeBuilder(base_dir=tmp_path).abuild(profile, tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert len(owned) == 1 and owned[0].closed
