"""A protected transport hook composes the original authorized business loop."""

import asyncio
import subprocess

import pytest

from relf_agent import AgentSpec, LocalEngine, ModelResponse, ToolCall, ToolRegistry
from relf_agent.codex_runner import CodexCodingRunner
from relf_agent.delegated_coding import register_coding_tool
from relf_agent.runner_journal import RunnerJournal
from relf_agent.storage import SQLiteStore
from tests.helpers import ScriptedProvider
from tests.test_codex_runner import native_fixture, original_engine


@pytest.mark.parametrize(
    ("branch", "error"),
    [
        ("sys.exit(7)", subprocess.CalledProcessError),
        ("print('not ready'); sys.exit(0)", AssertionError),
        ("pathlib.Path(__file__).write_text('changed'); sys.exit(0)", AssertionError),
    ],
    ids=["failed", "noisy", "changed-executable"],
)
def test_native_fixture_rejects_unready_cli_before_any_business(
    tmp_path, monkeypatch, branch, error
):
    from tests import test_codex_environment

    monkeypatch.setattr(
        test_codex_environment,
        "FAKE_DOCKER",
        test_codex_environment.FAKE_DOCKER.replace(
            "if sys.argv[1:]==['--fixture-ready']: sys.exit(0)",
            "if sys.argv[1:]==['--fixture-ready']: " + branch,
        ),
    )
    with pytest.raises(error):
        native_fixture(tmp_path)
    assert set(tmp_path.iterdir()) == {tmp_path / "codex_rpc_docker_fixture"}


def test_unready_cli_does_not_open_engine_or_runner_journal(tmp_path, monkeypatch):
    from tests import test_codex_environment

    monkeypatch.setattr(
        test_codex_environment,
        "FAKE_DOCKER",
        test_codex_environment.FAKE_DOCKER.replace(
            "if sys.argv[1:]==['--fixture-ready']: sys.exit(0)",
            "if sys.argv[1:]==['--fixture-ready']: sys.exit(7)",
        ),
    )
    with pytest.raises(subprocess.CalledProcessError):
        original_engine(tmp_path)
    assert set(tmp_path.iterdir()) == {
        tmp_path / "coding",
        tmp_path / "codex_rpc_docker_fixture",
    }
    assert not tuple((tmp_path / "coding").iterdir())


def test_native_fixture_prepares_cold_start_before_original_three_second_operation(
    tmp_path, monkeypatch
):
    from tests import test_codex_environment

    # This marker belongs only to the controlled host-startup simulation.
    # No Docker state, container, thread or turn may be prepared by readiness.
    marker = tmp_path / "fixture-interpreter-ready"
    prelude = (
        "import pathlib,time\n"
        f"marker=pathlib.Path({str(marker)!r})\n"
        "if not marker.exists():\n marker.touch();time.sleep(3.2)\n"
    )
    monkeypatch.setattr(
        test_codex_environment, "FAKE_DOCKER", prelude + test_codex_environment.FAKE_DOCKER
    )
    cli = native_fixture(tmp_path)
    assert marker.exists(), "fixture must finish its cold startup before returning to the product"
    assert set(tmp_path.iterdir()) == {cli, marker}
    original = cli.read_bytes()
    ready = subprocess.run(
        [str(cli), "--fixture-ready"],
        env={"PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        start_new_session=True,
        timeout=3,
        check=True,
    )
    assert ready.stdout == ready.stderr == b""
    assert cli.read_bytes() == original
    assert set(tmp_path.iterdir()) == {cli, marker}
    approved_action(tmp_path, cli)


def test_original_approved_action_uses_subclass_transport_hook_without_duplicate_turn(tmp_path):
    approved_action(tmp_path, native_fixture(tmp_path))


def approved_action(tmp_path, cli):
    calls = []

    class HookRunner(CodexCodingRunner):
        def _make_transport(self, owner, environment):
            calls.append((owner["envelope"].context.action_id, environment.identity))
            return super()._make_transport(owner, environment)

    root = tmp_path / "coding"
    root.mkdir(mode=0o700)
    journal = RunnerJournal(str(tmp_path / "native.sqlite"), identity={"fixture": "hook"})
    resource = HookRunner(
        root,
        journal=journal,
        docker_executable=str(cli),
        docker_host="unix:///fixture/docker.sock",
        request_timeout=3,
    )
    tools = ToolRegistry()
    register_coding_tool(tools, resource)
    engine = LocalEngine(
        SQLiteStore(tmp_path / "runs.sqlite"),
        tools=tools,
        providers={
            "default": ScriptedProvider(
                [
                    ModelResponse(tool_calls=(ToolCall("coding", {"task": "fixture task"}),)),
                    ModelResponse(output="finished"),
                ]
            )
        },
    )

    async def scenario():
        handle = engine.submit(
            AgentSpec("hook", "hook", tools=("coding",)), {}, command_id="submit"
        )
        waiting = await engine.drive(handle.run_id)
        assert waiting.state == "waiting_approval" and calls == []
        action = waiting.pending[0]
        engine.approve(handle.run_id, action["action_id"], action["digest"], command_id="approve")
        finished = await engine.drive(handle.run_id)
        assert finished.state == "succeeded"
        assert len(calls) == 1, "original business loop must select the protected transport hook"
        assert calls[0][0] == action["action_id"]
        assert (tmp_path / "native-submissions.jsonl").read_text().count(
            '"method": "thread/start"'
        ) == 1
        assert (tmp_path / "native-submissions.jsonl").read_text().count(
            '"method": "turn/start"'
        ) == 1
        assert resource.active_operations == 0
        await resource.aclose()

    try:
        asyncio.run(scenario())
    finally:
        journal.close()
        engine.close()
