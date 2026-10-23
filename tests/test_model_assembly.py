import asyncio
import importlib
import json
import sys

import httpx
import pytest

from relf_agent import AgentSpec, RuntimeBuilder, RuntimeProfile
from relf_agent.errors import ValidationError
from relf_agent.starter import create_starter

from .test_starter import installed_wheel as _installed_wheel
from .test_starter import subprocess_result

installed_wheel = _installed_wheel


@pytest.mark.parametrize(
    "adapter,variable,expected",
    [
        ("deepseek-chat", "DEEPSEEK_API_KEY", "deepseek-chat-completions"),
        ("anthropic-messages", "ANTHROPIC_API_KEY", "anthropic-messages"),
        ("gemini-content", "GEMINI_API_KEY", "gemini-generate-content-text"),
    ],
)
def test_native_and_domestic_adapters_build_from_env_without_persisting_keys(
    tmp_path, monkeypatch, adapter, variable, expected
):
    monkeypatch.setenv(variable, "FIXTURE_CREDENTIAL")
    profile = RuntimeProfile(
        "models",
        "1",
        {
            "default": {
                "adapter": adapter,
                "config": {"model": "fixture", "stream": True, "temperature": 0.2},
            }
        },
    )
    with RuntimeBuilder().build(profile, tmp_path / (adapter + ".sqlite")) as engine:
        handle = engine.submit(AgentSpec("a", "Answer"), "q", command_id="s")
        manifest = engine.diagnostics(handle.run_id).manifest
        assert manifest["providers"]["default"]["kind"] == expected
        assert "FIXTURE_CREDENTIAL" not in json.dumps(manifest)


@pytest.mark.parametrize(
    "adapter,config",
    [
        ("chat-completions", {"model": "fixture", "temperature": float("inf")}),
        ("anthropic-messages", {"model": "fixture", "temperature": 2}),
        ("anthropic-messages", {"model": "fixture", "seed": 1}),
        ("gemini-content", {"model": "fixture", "capabilities": {"tools": True}}),
        ("deepseek-chat", {"model": "fixture", "api_key": "SECRET"}),
        ("chat-completions", {"model": "YOUR_MODEL"}),
    ],
)
def test_model_configuration_is_rejected_before_execution_database_creation(
    tmp_path, adapter, config
):
    database = tmp_path / "not-created.sqlite"
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(
            RuntimeProfile("models", "1", {"default": {"adapter": adapter, "config": config}}),
            database,
        )
    assert not database.exists()


def test_explicit_model_env_reference_never_falls_back_to_vendor_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "present")
    monkeypatch.delenv("ABSENT_FIXTURE_ENV", raising=False)
    profile = RuntimeProfile(
        "models",
        "1",
        {
            "default": {
                "adapter": "anthropic-messages",
                "config": {"model": "fixture", "api_key_env": "ABSENT_FIXTURE_ENV"},
            }
        },
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, tmp_path / "missing.sqlite")


def test_deepseek_preset_sends_disabled_thinking_and_correct_token_parameter():
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}
        )

    async def run():
        api = importlib.import_module("relf_agent.providers")
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            provider = api.DeepSeekChatProvider("fixture", api_key="dummy", client=client)
            assert (await provider.complete([{"role": "user", "content": "q"}], [])).output == "ok"
            assert provider.identity["thinking"] == "disabled"

    asyncio.run(run())
    assert str(requests[0].url) == "https://api.deepseek.com/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["thinking"] == {"type": "disabled"} and payload["max_tokens"] == 1024


def test_model_starter_is_explicit_editable_and_does_not_run_placeholders(tmp_path):
    project = tmp_path / "model-app"
    result = create_starter(project, template="model")
    assert result.template == "model"
    assert "api_key_env" in (project / "runtime.toml").read_text()
    process = subprocess_result([sys.executable, "-m", "agent_app"], cwd=project, returncode=2)
    assert process == ""
    assert not (project / ".ralf/runs.sqlite").exists()


def test_model_starter_installed_wheel_requires_only_explicit_configuration(
    tmp_path, installed_wheel
):
    python, ralf = installed_wheel
    project = tmp_path / "installed-model"
    result = json.loads(
        subprocess_result([ralf, "init", project, "--template", "model"], cwd=tmp_path)
    )
    assert result["template"] == "model"
    path = project / "runtime.toml"
    # Substitute an offline adapter to verify the generated independent application;
    # native HTTP protocol behavior is exercised by separate transport fixtures.
    path.write_text(
        'schema_version=1\n[default]\nname="model-assistant"\nversion="1"\n[[profiles]]\nname="model-assistant"\nversion="1"\n[profiles.providers.default]\nadapter="offline-echo"\n'
    )
    completed = json.loads(
        subprocess_result(
            [python, "-m", "agent_app", "--input", "installed model app"], cwd=project
        )
    )
    assert (
        completed["state"] == "succeeded" and completed["result"]["echo"] == "installed model app"
    )
