"""Original Local Action retains approval, one attempt, auth and namespace fence."""

import asyncio
import json
import secrets

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, ToolCall, ToolRegistry
from relf_agent.codex_connected_runner import ConnectedCodexCodingRunner
from relf_agent.codex_model_connection import CodexModelConnection
from relf_agent.delegated_coding import register_coding_tool
from relf_agent.runner_journal import RunnerJournal
from relf_agent.storage import SQLiteStore
from tests.connected_coding_fixture import connected_native_fixture
from tests.helpers import ScriptedProvider


def application(tmp_path, mode="completed", source=None):
    root = tmp_path / "coding"
    root.mkdir(mode=0o700)
    connection = CodexModelConnection(
        "https://api.deepseek.com", "deepseek-flash", "CODING_TEST_KEY", "primary", "1"
    )
    journal = RunnerJournal(str(tmp_path / "native.sqlite"), identity={"fixture": "connected-loop"})
    runner = ConnectedCodexCodingRunner(
        root,
        connection=connection,
        credential_source=source,
        journal=journal,
        docker_executable=str(connected_native_fixture(tmp_path, connection, mode)),
        docker_host="unix:///fixture/docker.sock",
        request_timeout=8,
    )
    tools = ToolRegistry()
    register_coding_tool(tools, runner)
    engine = LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        tools=tools,
        providers={
            "default": ScriptedProvider(
                [
                    ModelResponse(
                        tool_calls=(ToolCall("coding", {"task": "bounded fixture task"}),)
                    ),
                    ModelResponse(output="complete"),
                ]
            )
        },
    )
    return engine, runner, journal


def assert_no_key_files(tmp_path, key):
    for file in tmp_path.rglob("*"):
        if file.is_file():
            assert key.encode() not in file.read_bytes(), file.name


@pytest.mark.parametrize("mode", ["completed", "echo"])
def test_original_approval_authentication_and_fence_do_not_persist_credentials(
    tmp_path, monkeypatch, mode
):
    key = "synthetic-" + secrets.token_hex(24)
    monkeypatch.setenv("CODING_TEST_KEY", key)
    engine, runner, journal = application(tmp_path, mode)

    async def run():
        handle = engine.submit(
            AgentSpec("connected", "connected", tools=("coding",)), {}, command_id="submit"
        )
        waiting = await engine.drive(handle.run_id)
        assert waiting.state == "waiting_approval"
        assert not (tmp_path / "auth-methods.txt").exists()
        assert list((tmp_path / "coding").iterdir()) == []
        pending = waiting.pending[0]
        engine.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="approve")
        result = await engine.drive(handle.run_id)
        assert result.state == ("succeeded" if mode == "completed" else "waiting_reconciliation")
        action = next(a for a in engine.store.run(handle.run_id)["actions"] if a["kind"] == "tool")
        assert len(action["attempts"]) == 1
        delegated = action["delegated_execution"]
        assert delegated["fenced"] is True and delegated["pending_stop"] is False
        assert json.loads((tmp_path / "docker.json").read_text())["containers"] == {}
        assert (tmp_path / "auth-methods.txt").read_text().splitlines() == (
            ["account/read", "account/login/start", "account/read"]
            if mode == "completed"
            else ["account/read", "account/login/start"]
        )
        assert (tmp_path / "native-submissions.jsonl").exists() == (mode == "completed")
        assert_no_key_files(tmp_path, key)
        await runner.aclose()

    try:
        asyncio.run(run())
    finally:
        journal.close()
        engine.close()
