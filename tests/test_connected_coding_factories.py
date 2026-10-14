"""Connected declarations use nonsecret data and do not resolve auth at assembly."""

import asyncio
import copy

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.runtime_builder import RuntimeBuilder
from ralf_agent.runtime_config import RuntimeProfile
from tests.test_coding_assembly import options


def entry(tmp_path):
    value = options(tmp_path)
    value["connection"] = {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "credential_env": "CODING_TEST_KEY",
        "credential_id": "coding-primary",
        "generation": "1",
    }
    return value


def profile(value):
    return RuntimeProfile(
        "connected",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "codex-coding-connected", "config": value}},
        binding_components=[
            {
                "role": "runner",
                "component_id": "native",
                "version": "1",
                "component": {"adapter": "registered-tool", "config": {"name": "coding"}},
            }
        ],
    )


def test_default_factory_assembles_without_credentials_or_native_business(tmp_path, monkeypatch):
    monkeypatch.delenv("CODING_TEST_KEY", raising=False)
    value = entry(tmp_path)

    async def run():
        runtime = await RuntimeBuilder().abuild(profile(value), tmp_path / "runs.sqlite")
        try:
            resource = runtime.tools.get("coding").handler.runner
            assert resource.identity["version"] == "2"
            assert resource.identity["connection"]["credential_env"] == "CODING_TEST_KEY"
            assert not (tmp_path / "native").exists()
            assert list((tmp_path / "runner").iterdir()) == []
        finally:
            await runtime.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["secret", "env_value", "unknown", "invalid_endpoint"])
def test_invalid_connection_is_refused_before_any_owned_resource(tmp_path, mutation):
    value = entry(tmp_path)
    if mutation == "secret":
        value["connection"]["api_key"] = "synthetic-not-an-allowed-field"
    elif mutation == "env_value":
        value["connection"]["credential_env"] = "bad=embedded-value"
    elif mutation == "unknown":
        value["connection"]["extra"] = True
    else:
        value["connection"]["base_url"] = "https://user:password@api.deepseek.com"

    async def run():
        with pytest.raises(ValidationError):
            await RuntimeBuilder().abuild(profile(copy.deepcopy(value)), tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert not (tmp_path / "native").exists()
    assert not (tmp_path / "runner.sqlite").exists()
