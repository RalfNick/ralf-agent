import asyncio
import importlib
import json
import os

import pytest

from relf_agent.codex_coding_profile import CodexCodingProfile
from relf_agent.codex_environment import DockerCodingEnvironment
from relf_agent.codex_model_connection import CodexModelConnection
from relf_agent.errors import DefinitionMismatch, ValidationError
from tests import test_codex_environment as retained

load = retained.load


@pytest.fixture
def resource(tmp_path):
    return retained.resource.__wrapped__(tmp_path)


def connection(**kwargs):
    values = dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        credential_env="RALF_DEEPSEEK_API_KEY",
        credential_id="deepseek-primary",
        generation="1",
    )
    return CodexModelConnection(**(values | kwargs))


def environment(resource, selected=None, **kwargs):
    module = importlib.import_module("relf_agent.codex_connected_environment")
    return module.ConnectedDockerCodingEnvironment(
        resource[0],
        "test-connected",
        connection=connection() if selected is None else selected,
        docker_executable=str(resource[1]),
        docker_host="unix:///fixture/docker.sock",
        **kwargs,
    )


def test_connected_prepare_recovery_uses_model_identity_and_readonly_configuration(
    resource, monkeypatch
):
    monkeypatch.setenv("RALF_DEEPSEEK_API_KEY", "private-canary-not-a-key")

    async def run():
        env = environment(resource)
        assert isinstance(env, DockerCodingEnvironment)
        assert env.identity["version"] == "2" and env.identity["retire_on_stop"] is True
        assert env.identity["configuration_readonly"] is True
        assert env.identity["profile"]["connection"] == connection().identity
        assert not tuple(resource[0].iterdir())
        prepared = await env.prepare()
        cid = prepared["container_id"]
        assert (
            json.loads((resource[0] / "environment.json").read_text())["identity"] == env.identity
        )
        owned = load(resource)["containers"][cid]
        mounts = owned["Mounts"]
        assert (
            next(m for m in mounts if m["Destination"] == "/home/ralf/.codex/config.toml")["RW"]
            is False
        )
        assert owned["Config"]["Cmd"] == ["app-server", "--listen", "stdio://", "--strict-config"]
        assert owned["Config"]["Env"] == [
            "TMPDIR=/workspace/.tmp",
            "PATH=/opt/codex/bin:/opt/codex/codex-path:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME=/home/ralf",
        ]
        assert "private-canary-not-a-key" not in json.dumps(owned)
        for path in resource[0].rglob("*"):
            if path.is_file():
                assert b"private-canary-not-a-key" not in path.read_bytes()
        assert "private-canary-not-a-key" not in str(env.transport_argv())
        await env.aclose()
        cold = environment(resource)
        assert (await cold.prepare())["container_id"] == cid
        assert load(resource)["creates"] == 1
        assert (await cold.stop())["fenced"] is True
        await cold.aclose()
        assert load(resource)["removed"] == [cid]

    asyncio.run(run())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"configuration_readonly": False},
        {"configuration_readonly": 1},
        {"retire_on_stop": False},
        {"retire_on_stop": 1},
    ],
)
def test_connected_environment_rejects_weaker_configuration_before_resource_io(resource, kwargs):
    with pytest.raises(ValidationError):
        environment(resource, **kwargs)
    assert not tuple(resource[0].iterdir())
    assert not (resource[1].parent / "docker.json").exists()


@pytest.mark.parametrize(
    "mutation",
    ["connection", "profile", "profile_text", "profile_identity", "expected_config", "parsed"],
)
def test_connection_and_profile_mutation_are_rejected_before_prepare_effects(resource, mutation):
    env = environment(resource)
    if mutation == "connection":
        object.__setattr__(env._connection, "model", "another-model")
    elif mutation == "profile":
        env._profile = CodexCodingProfile()
    elif mutation == "profile_text":
        env._profile._config_text += "\n# changed\n"
    elif mutation == "profile_identity":
        env._profile._connection_identity["model"] = "another-model"
    elif mutation == "expected_config":
        env._profile._expected_config["model"] = "another-model"
    else:
        env._profile._parsed["model"] = "another-model"

    async def run():
        with pytest.raises(DefinitionMismatch):
            await env.prepare()
        assert not tuple(resource[0].iterdir())
        assert not (resource[1].parent / "docker.json").exists()
        await env.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "other-model"),
        ("base_url", "https://another.example/v1"),
        ("credential_env", "OTHER_KEY"),
        ("credential_id", "other-reference"),
        ("generation", "2"),
        ("reasoning_effort", "high"),
    ],
)
def test_cold_connection_change_cannot_adopt_the_original_namespace(resource, field, value):
    async def run():
        original = environment(resource)
        cid = (await original.prepare())["container_id"]
        await original.aclose()
        before = load(resource)
        changed = environment(resource, connection(**{field: value}))
        with pytest.raises(DefinitionMismatch):
            await changed.prepare()
        assert load(resource) == before
        # A declaration mismatch has no verified original ID; close the test lease.
        os.close(changed._lease)
        changed._lease = None
        cold = environment(resource)
        assert (await cold.prepare())["container_id"] == cid
        await cold.stop()
        await cold.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("name", ["__init__", "_check_root"])
def test_authored_connected_environment_methods_are_executable_fingerprintable(name):
    from relf_agent.component_fingerprint import executable_digest

    module = importlib.import_module("relf_agent.codex_connected_environment")
    assert len(executable_digest(vars(module.ConnectedDockerCodingEnvironment)[name])) == 64


def test_connected_profile_state_helper_is_executable_fingerprintable():
    from relf_agent.component_fingerprint import executable_digest

    module = importlib.import_module("relf_agent.codex_connected_environment")
    assert len(executable_digest(module._profile_state)) == 64
