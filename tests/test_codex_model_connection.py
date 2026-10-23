import dataclasses
import importlib
import json

import pytest

from relf_agent.errors import ValidationError


def connection(**overrides):
    values = dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        credential_env="RALF_DEEPSEEK_API_KEY",
        credential_id="deepseek-primary",
        generation="1",
        reasoning_effort="low",
    )
    values.update(overrides)
    return importlib.import_module("relf_agent.codex_model_connection").CodexModelConnection(
        **values
    )


def test_connection_is_fixed_nonsecret_data_without_environment_reads(monkeypatch):
    monkeypatch.setenv("RALF_DEEPSEEK_API_KEY", "private-canary-not-a-key")
    value = connection()
    assert value.identity == {
        "kind": "codex-model-connection",
        "version": "1",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "credential_env": "RALF_DEEPSEEK_API_KEY",
        "credential_id": "deepseek-primary",
        "generation": "1",
        "reasoning_effort": "low",
    }
    assert "private-canary-not-a-key" not in json.dumps(value.identity)
    identity = value.identity
    identity["model"] = "another"
    assert value.identity["model"] == "deepseek-v4-pro"
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        value.model = "another"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.deepseek.com/v1",
        "https://user:private-canary@api.deepseek.com/v1",
        "https://api.deepseek.com/v1?token=private-canary",
        "https://api.deepseek.com/v1#private-canary",
        "https://api.deepseek.com/v1?",
        "https://api.deepseek.com/v1#",
        "https://api.deepseek.com/\\private-canary",
        "https://api.deepseek.com/%0aAuthorization",
        "https:///v1",
        "https://api.deepseek.com:bad/v1",
        "https://api.deepseek.com:0/v1",
        "https://api.deepseek.com:65536/v1",
        "https://api.deepseek.com/v1\n",
        "https://api.deepseek.com/../v1",
        "https://é.example/v1",
        "https://api.deepseek.com/" + "x" * 2048,
        None,
        True,
        12,
    ],
)
def test_endpoint_authentication_and_ambiguous_urls_are_rejected_without_echo(base_url):
    with pytest.raises(ValidationError) as error:
        connection(base_url=base_url)
    assert "private-canary" not in str(error.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "deepseek\nmodel_provider='evil'"),
        ("model", "deepseek v4"),
        ("model", 'deepseek"'),
        ("model", ""),
        ("model", "x" * 129),
        ("model", True),
        ("model", "非ASCII"),
        ("credential_env", "KEY=value"),
        ("credential_env", "api-key"),
        ("credential_env", "1KEY"),
        ("credential_env", "KEY\n"),
        ("credential_env", ""),
        ("credential_env", "x" * 129),
        ("credential_id", "private-canary\n"),
        ("credential_id", ""),
        ("credential_id", {}),
        ("generation", 1),
        ("generation", "private-canary\n"),
        ("generation", ""),
        ("reasoning_effort", "private-canary"),
        ("reasoning_effort", None),
    ],
)
def test_connection_rejects_injection_and_wrong_types_without_echo(field, value):
    with pytest.raises(ValidationError) as error:
        connection(**{field: value})
    assert "private-canary" not in str(error.value)


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh"])
def test_connection_supports_native_reasoning_effort_values(effort):
    assert connection(reasoning_effort=effort).identity["reasoning_effort"] == effort


def test_alternate_https_connection_changes_identity_and_never_resolves_credentials(monkeypatch):
    monkeypatch.setattr(
        "os.getenv", lambda *args: pytest.fail("credential resolution in data author")
    )
    value = connection(base_url="https://responses.example.org:8443/api/v1", model="team/model:1")
    assert value.base_url == "https://responses.example.org:8443/api/v1"
    assert value.model == "team/model:1"
    assert value.identity != connection().identity


def test_connection_declarations_roundtrip_with_optional_reasoning_default():
    module = importlib.import_module("relf_agent.codex_model_connection")
    declared = connection().to_dict()
    assert set(declared) == {
        "base_url",
        "model",
        "credential_env",
        "credential_id",
        "generation",
        "reasoning_effort",
    }
    assert module.CodexModelConnection.from_dict(declared).identity == connection().identity
    declared.pop("reasoning_effort")
    assert module.CodexModelConnection.from_dict(declared).reasoning_effort == "low"


@pytest.mark.parametrize("mutation", ["missing", "extra", "identity", "not_dict"])
def test_connection_declarations_reject_unknown_fields_and_identity_projection(mutation):
    module = importlib.import_module("relf_agent.codex_model_connection")
    declared = connection().to_dict()
    if mutation == "missing":
        declared.pop("credential_id")
    elif mutation == "extra":
        declared["api_key"] = "private-canary"
    elif mutation == "identity":
        declared = connection().identity
    else:
        declared = []
    with pytest.raises(ValidationError) as error:
        module.CodexModelConnection.from_dict(declared)
    assert "private-canary" not in str(error.value)
