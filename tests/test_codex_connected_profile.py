import copy
import hashlib
import importlib
import json
import tomllib
from pathlib import Path

import pytest

from ralf_agent.codex_coding_profile import CodexCodingProfile
from ralf_agent.codex_model_connection import CodexModelConnection
from ralf_agent.errors import ValidationError


def connection(**kwargs):
    values = dict(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        credential_env="RALF_DEEPSEEK_API_KEY",
        credential_id="deepseek-primary",
        generation="1",
    )
    return CodexModelConnection(**(values | kwargs))


def profile(value=None):
    return importlib.import_module(
        "ralf_agent.codex_connected_profile"
    ).ConnectedCodexCodingProfile(connection() if value is None else value)


def native_results(value=None):
    # Full native baseline plus the documented ModelProviderInfo serialization.
    selected = connection() if value is None else value
    results = json.loads(Path(__file__).with_name("codex_control_fixture.json").read_text())
    parsed = tomllib.loads(CodexCodingProfile().config_text)
    additions = {
        "model": selected.model,
        "model_provider": "ralf-connected",
        "model_reasoning_effort": selected.reasoning_effort,
        "model_providers": {
            "ralf-connected": {
                "name": "Ralf connected Responses",
                "base_url": selected.base_url,
                "wire_api": "responses",
                "requires_openai_auth": True,
            }
        },
    }
    parsed.update(additions)
    read = results["config/read"]
    read["config"].update(copy.deepcopy(additions))
    provider = read["config"]["model_providers"]["ralf-connected"]
    provider.update(
        {
            "env_key": None,
            "env_key_instructions": None,
            "experimental_bearer_token": None,
            "auth": None,
            "aws": None,
            "query_params": None,
            "http_headers": None,
            "env_http_headers": None,
            "request_max_retries": None,
            "stream_max_retries": None,
            "stream_idle_timeout_ms": None,
            "websocket_connect_timeout_ms": None,
            "supports_websockets": False,
        }
    )
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    origin = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    metadata = {
        "name": {"type": "user", "file": "/home/ralf/.codex/config.toml", "profile": None},
        "version": origin,
    }
    for key in read["origins"]:
        read["origins"][key] = copy.deepcopy(metadata)
    for key in ("model", "model_provider", "model_reasoning_effort"):
        read["origins"][key] = copy.deepcopy(metadata)
    for key in additions["model_providers"]["ralf-connected"]:
        read["origins"][f"model_providers.ralf-connected.{key}"] = copy.deepcopy(metadata)
    read["layers"][1] = {**metadata, "config": parsed}
    return results


def test_connected_config_preserves_all_safe_defaults_and_uses_account_bearer_only(monkeypatch):
    monkeypatch.setenv("RALF_DEEPSEEK_API_KEY", "private-canary-not-a-key")
    configured = tomllib.loads(profile().config_text)
    legacy = tomllib.loads(CodexCodingProfile().config_text)
    assert configured["model"] == "deepseek-v4-pro"
    assert configured["model_provider"] == "ralf-connected"
    assert configured["model_reasoning_effort"] == "low"
    assert configured["model_providers"] == {
        "ralf-connected": {
            "name": "Ralf connected Responses",
            "base_url": "https://api.deepseek.com/v1",
            "wire_api": "responses",
            "requires_openai_auth": True,
        }
    }
    for key, value in legacy.items():
        assert configured[key] == value
    assert "private-canary-not-a-key" not in profile().config_text
    assert "RALF_DEEPSEEK_API_KEY" not in profile().config_text
    assert profile().identity["connection"] == connection().identity
    assert profile().identity["config_digest"] != CodexCodingProfile().identity["config_digest"]
    assert profile().identity["control_verified"] is False


def test_complete_connected_readback_is_control_only_and_detached():
    configured = profile()
    accepted = configured.validate_control(native_results())
    assert accepted["control_verified"] is True and accepted["execution_admitted"] is False
    assert accepted["connection"] == connection().identity
    accepted["connection"]["model"] = "other"
    assert configured.identity["connection"]["model"] == "deepseek-v4-pro"


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_config",
        "unknown_provider",
        "extra_provider",
        "env_key",
        "bearer",
        "headers",
        "provider_auth_false",
        "provider_bool_int",
        "model",
        "reasoning",
        "origin",
        "missing_origin",
        "extra_layer",
        "project_unknown",
        "system_unknown",
        "user_layer",
        "no_layers",
    ],
)
def test_connected_validation_rejects_complete_native_drift_before_projection(mutation):
    results = native_results()
    read = results["config/read"]
    provider = read["config"]["model_providers"]["ralf-connected"]
    if mutation == "unknown_config":
        read["config"]["unknown"] = "private-canary"
    elif mutation == "unknown_provider":
        provider["unknown"] = "private-canary"
    elif mutation == "extra_provider":
        read["config"]["model_providers"]["other"] = copy.deepcopy(provider)
    elif mutation in {"env_key", "bearer", "headers"}:
        provider[
            {
                "env_key": "env_key",
                "bearer": "experimental_bearer_token",
                "headers": "http_headers",
            }[mutation]
        ] = "private-canary"
    elif mutation.startswith("provider_"):
        provider["requires_openai_auth"] = False if mutation.endswith("false") else 1
    elif mutation == "model":
        read["config"]["model"] = "other"
    elif mutation == "reasoning":
        read["config"]["model_reasoning_effort"] = "high"
    elif mutation == "origin":
        read["origins"]["model"]["version"] = "sha256:" + "0" * 64
    elif mutation == "missing_origin":
        read["origins"].pop("model_providers.ralf-connected.requires_openai_auth")
    elif mutation == "extra_layer":
        read["layers"].append(copy.deepcopy(read["layers"][0]))
    elif mutation in {"project_unknown", "system_unknown", "user_layer"}:
        index = {"project_unknown": 0, "system_unknown": 2, "user_layer": 1}[mutation]
        read["layers"][index]["config"]["unknown"] = "private-canary"
    else:
        read["layers"] = None
    with pytest.raises(ValidationError) as error:
        profile().validate_control(results)
    assert "private-canary" not in str(error.value)


def test_profile_refuses_unvalidated_connection_and_supports_separate_model_choice():
    with pytest.raises(ValidationError):
        profile({"base_url": "https://api.deepseek.com/v1"})
    selected = connection(
        model="example-model", base_url="https://responses.example/v1", reasoning_effort="high"
    )
    accepted = profile(selected).validate_control(native_results(selected))
    assert accepted["connection"]["model"] == "example-model"


@pytest.mark.parametrize("name", ["__init__", "identity"])
def test_authored_connected_profile_methods_are_executable_fingerprintable(name):
    from ralf_agent.component_fingerprint import executable_digest

    module = importlib.import_module("ralf_agent.codex_connected_profile")
    method = vars(module.ConnectedCodexCodingProfile)[name]
    if isinstance(method, property):
        method = method.fget
    assert len(executable_digest(method)) == 64
