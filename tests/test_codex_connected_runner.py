"""Connected Coding keeps credentials lazy and independently fixes new helpers."""

import importlib.util
import sys

import pytest

from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.runner_journal import RunnerJournal


def runner_type():
    assert importlib.util.find_spec("relf_agent.codex_connected_runner") is not None, (
        "managed connected Runner is missing"
    )
    from relf_agent.codex_connected_runner import ConnectedCodexCodingRunner

    return ConnectedCodexCodingRunner


def connection():
    from relf_agent.codex_model_connection import CodexModelConnection

    return CodexModelConnection(
        "https://api.deepseek.com", "deepseek-flash", "CODING_TEST_KEY", "coding-model", "1"
    )


def parts(tmp_path):
    root = tmp_path / "coding"
    root.mkdir(mode=0o700)
    journal = RunnerJournal(str(tmp_path / "runner.sqlite"), identity={"fixture": "connected"})
    return root, journal


def test_connected_constructor_and_identity_never_resolve_credentials(tmp_path, monkeypatch):
    cls = runner_type()
    root, journal = parts(tmp_path)
    monkeypatch.delenv("CODING_TEST_KEY", raising=False)
    try:
        runner = cls(
            root,
            journal=journal,
            docker_executable=sys.executable,
            docker_host="unix:///fixture/docker.sock",
            connection=connection(),
        )
        identity = runner.identity
        assert identity["version"] == "2" and identity["connection"] == connection().identity
        assert identity["configuration_readonly"] is True
        assert identity["credentials"] == "ephemeral-api-key"
        assert identity["connection_implementation"]
        assert list(root.iterdir()) == []
        identity["connection"]["model"] = "forged"
        assert runner.identity["connection"]["model"] == "deepseek-flash"
    finally:
        journal.close()


def test_connected_helper_change_is_rejected_before_credentials_or_business(tmp_path, monkeypatch):
    cls = runner_type()
    root, journal = parts(tmp_path)
    try:
        runner = cls(
            root,
            journal=journal,
            docker_executable=sys.executable,
            docker_host="unix:///fixture/docker.sock",
            connection=connection(),
        )
        original = cls._make_transport

        def forged(self, owner, environment):
            return original(self, owner, environment)

        monkeypatch.setattr(cls, "_make_transport", forged)
        with pytest.raises(DefinitionMismatch):
            _ = runner.identity
        assert list(root.iterdir()) == []
    finally:
        journal.close()


def test_connected_configuration_rejects_nonconnection_before_native_io(tmp_path):
    cls = runner_type()
    root, journal = parts(tmp_path)
    try:
        with pytest.raises(ValidationError):
            cls(
                root,
                journal=journal,
                docker_executable=sys.executable,
                docker_host="unix:///fixture/docker.sock",
                connection={"secret": "forbidden"},
            )
        assert list(root.iterdir()) == []
    finally:
        journal.close()


@pytest.mark.parametrize("field,value", [("digest", "0" * 64), ("algorithm", "forged")])
def test_public_inventory_digest_must_match_independently_checked_private_inventory(
    tmp_path, field, value
):
    root, journal = parts(tmp_path)
    try:
        runner = runner_type()(
            root,
            journal=journal,
            docker_executable=sys.executable,
            docker_host="unix:///fixture/docker.sock",
            connection=connection(),
        )
        runner._identity["connection_implementation"][field] = value
        with pytest.raises(DefinitionMismatch):
            _ = runner.identity
        assert list(root.iterdir()) == []
    finally:
        journal.close()


@pytest.mark.parametrize(
    "module_name,name,replacement",
    [
        ("codex_rpc", "_METHODS", frozenset({"initialize", "account/login/start"})),
        ("codex_rpc", "_CONTROL_METHODS", frozenset({"initialize", "account/login/start"})),
        ("codex_rpc", "_MAX_ID", 7),
        ("codex_auth_transport", "_MAX_ID", 7),
        ("codex_environment", "_COMMAND", ["app-server", "--listen", "stdio://"]),
    ],
)
def test_security_global_change_is_refused_before_credentials(
    tmp_path, monkeypatch, module_name, name, replacement
):
    import importlib

    cls = runner_type()
    root, journal = parts(tmp_path)
    try:
        runner = cls(
            root,
            journal=journal,
            docker_executable=sys.executable,
            docker_host="unix:///fixture/docker.sock",
            connection=connection(),
        )
        module = importlib.import_module("relf_agent." + module_name)
        monkeypatch.setattr(module, name, replacement)
        with pytest.raises(DefinitionMismatch):
            _ = runner.identity
        assert list(root.iterdir()) == []
    finally:
        journal.close()
