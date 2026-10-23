"""Explicit History config protection; original Local defaults remain omitted."""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from relf_agent.codex_environment import DockerCodingEnvironment
from relf_agent.codex_runner import CodexCodingRunner
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.types import canonical, digest
from tests.test_codex_environment import environment, load
from tests.test_codex_environment import resource as base_resource
from tests.test_codex_runner import native_fixture
from tests.test_postgres_runner_journal import journals
from tests.test_postgres_runner_journal import postgres_dsn as postgres_dsn


@pytest.fixture
def resource(tmp_path):
    root, cli = base_resource.__wrapped__(tmp_path)
    # The existing CLI fixture treats a substring in the host path as a
    # readonly flag. Parse the exact mount token for these protected-mode cases.
    cli.write_text(
        cli.read_text().replace(
            "'RW':'readonly' not in value", "'RW':'readonly' not in value.split(',')"
        )
    )
    return root, cli


def test_readonly_config_mount_is_explicit_exact_third_mount_and_fences(resource):
    async def scenario():
        env = environment(
            resource, retire_on_stop=True, expected_generation="a" * 32, configuration_readonly=True
        )
        assert env.identity.get("configuration_readonly") is True
        first = await env.prepare()
        state = load(resource)["containers"][first["container_id"]]
        protected = next(
            m for m in state["Mounts"] if m["Destination"] == "/home/ralf/.codex/config.toml"
        )
        assert len(state["Mounts"]) == 3
        assert protected == {
            "Type": "bind",
            "Source": str(resource[0] / "state/config.toml"),
            "Destination": "/home/ralf/.codex/config.toml",
            "RW": False,
            "Propagation": "rprivate",
        }
        before = (resource[0] / "state/config.toml").stat()
        content = (resource[0] / "state/config.toml").read_bytes()
        stopped = await env.stop()
        assert stopped["fenced"] is True and stopped["retired"] is True
        assert (resource[0] / "state/config.toml").stat().st_ino == before.st_ino
        assert (resource[0] / "state/config.toml").read_bytes() == content
        await env.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("flag", [None, 0, 1, "true", [], {}])
def test_readonly_configuration_requires_exact_boolean_before_io(resource, flag):
    with pytest.raises(ValidationError):
        environment(resource, configuration_readonly=flag)
    assert not tuple(resource[0].iterdir())
    assert not (resource[1].parent / "docker.json").exists()


def test_readonly_mount_rejects_writable_or_replaced_configuration(resource):
    async def scenario():
        env = environment(
            resource, retire_on_stop=True, expected_generation="a" * 32, configuration_readonly=True
        )
        first = await env.prepare()
        cid = first["container_id"]
        original = load(resource)
        for replacement in (
            {"RW": True},
            {"Source": str(resource[0] / "workspace/config.toml")},
            {"RW": 0},
        ):
            changed = copy.deepcopy(original)
            mount = next(
                m
                for m in changed["containers"][cid]["Mounts"]
                if m["Destination"] == "/home/ralf/.codex/config.toml"
            )
            mount.update(replacement)
            (resource[1].parent / "docker.json").write_text(__import__("json").dumps(changed))
            with pytest.raises(DefinitionMismatch):
                await env.inspect()
            (resource[1].parent / "docker.json").write_text(__import__("json").dumps(original))
            await env.inspect()
        config = resource[0] / "state/config.toml"
        config.chmod(0o600)
        with pytest.raises(DefinitionMismatch):
            env.transport_argv()
        config.chmod(0o444)
        await env.stop()
        await env.aclose()

    asyncio.run(scenario())


def test_omitted_default_and_explicit_false_preserve_baseline_identity_and_create_bytes(resource):
    # Frozen accepted105 identity/argv; works with installed wheel and shallow CI.
    baseline = json.loads(
        (Path(__file__).parent / "fixtures/codex_environment_local105.json").read_text()
    )
    root, cli = resource
    kwargs = {
        "docker_executable": str(cli),
        "docker_host": "unix:///fixture/docker.sock",
        "retire_on_stop": True,
        "expected_generation": "a" * 32,
    }
    current = DockerCodingEnvironment(root, "test-retained", **kwargs)
    disabled = DockerCodingEnvironment(
        root, "test-retained", **kwargs, configuration_readonly=False
    )
    assert canonical(current.identity) == canonical(disabled.identity)
    assert "configuration_readonly" not in current.identity
    for env in (current, disabled):
        env._metadata = {"generation": "a" * 32}
        original = env.identity
        root_hash = digest(original["root"])
        original["root"] = "$ROOT_PIN"
        original["docker_executable_pin"] = "$DOCKER_PIN"

        def normalize(value, *, root_hash=root_hash, resource_name=env._name):
            if type(value) is str:
                return (
                    value.replace(str(root), "$ROOT")
                    .replace(str(cli), "$DOCKER")
                    .replace(root_hash, "$ROOT_DIGEST")
                    .replace(resource_name, "$RESOURCE_NAME")
                )
            if type(value) is list:
                return [normalize(item) for item in value]
            if type(value) is dict:
                return {key: normalize(item) for key, item in value.items()}
            return value

        assert normalize(original) == baseline["identity"]
        assert normalize(env._create_argv()) == baseline["create_argv"]


def test_pg_runner_publishes_and_passes_protected_configuration(postgres_dsn, tmp_path):
    from tests.test_codex_runner import envelope

    async def scenario():
        async with journals(postgres_dsn) as (views, _, _, _):
            root = tmp_path / "protected-runner"
            root.mkdir(mode=0o700)
            cli = native_fixture(tmp_path)
            native = CodexCodingRunner(
                root,
                journal=views[0],
                docker_executable=str(cli),
                docker_host="unix:///fixture/docker.sock",
            )
            assert native.identity.get("configuration_readonly") is True
            env = native._environment(envelope(), create=True)
            assert env.identity.get("configuration_readonly") is True
            prepared = await env.prepare()
            assert (
                len(
                    __import__("json").loads((tmp_path / "docker.json").read_text())["containers"][
                        prepared["container_id"]
                    ]["Mounts"]
                )
                == 3
            )
            await env.stop()
            await env.aclose()
            await native.aclose()

    asyncio.run(scenario())
