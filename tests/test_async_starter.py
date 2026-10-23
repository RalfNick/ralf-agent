import json
import sys

from relf_agent.cli import main
from relf_agent.starter import create_starter

from .test_starter import installed_wheel as _installed_wheel
from .test_starter import subprocess_result

installed_wheel = _installed_wheel


def test_async_starter_runs_replays_and_closes_real_client(tmp_path):
    project = tmp_path / "async-agent"
    created = create_starter(project, template="async")
    assert created.factory == "agent_app.runtime:create_runtime"
    output = subprocess_result(
        [sys.executable, "-m", "agent_app", "--input", "hello", "--command-id", "s"], cwd=project
    )
    first = json.loads(output)
    assert first["state"] == "succeeded" and first["result"] == "async: hello"
    replay = json.loads(
        subprocess_result(
            [sys.executable, "-m", "agent_app", "--input", "hello", "--command-id", "s"],
            cwd=project,
        )
    )
    assert replay == first
    script = """
import asyncio
from agent_app.runtime import create_runtime

async def probe():
    runtime = await create_runtime('.ralf/client.sqlite')
    client = runtime.providers['default'].client
    assert not client.is_closed
    await runtime.aclose()
    assert client.is_closed

asyncio.run(probe())
"""
    subprocess_result([sys.executable, "-c", script], cwd=project)


def test_async_starter_resumes_original_profile_after_default_changes(tmp_path):
    project = tmp_path / "async-history"
    create_starter(project, template="async")
    queued = json.loads(
        subprocess_result(
            [
                sys.executable,
                "-m",
                "agent_app",
                "--input",
                "hello",
                "--command-id",
                "s",
                "--submit-only",
            ],
            cwd=project,
        )
    )
    path = project / "runtime.toml"
    path.write_text(
        path.read_text().replace('version = "1"', 'version = "2"', 1)
        + """

[[profiles]]
name = "async-assistant"
version = "2"
[profiles.providers.default]
adapter = "async-demo"
[profiles.providers.default.config]
label = "second"
"""
    )
    result = json.loads(
        subprocess_result(
            [sys.executable, "-m", "agent_app", "--resume", queued["run_id"]], cwd=project
        )
    )
    assert result["state"] == "succeeded" and result["result"] == "async: hello"
    assert (
        json.loads(
            subprocess_result(
                [sys.executable, "-m", "agent_app", "--input", "hello", "--command-id", "s"],
                cwd=project,
            )
        )
        == result
    )
    fresh = json.loads(
        subprocess_result(
            [sys.executable, "-m", "agent_app", "--input", "hello", "--command-id", "new"],
            cwd=project,
        )
    )
    assert fresh["result"] == "second: hello"


def test_async_starter_text_hint_uses_its_async_application_entry(tmp_path, capsys):
    directory = tmp_path / "text-async"
    assert main(["--format", "text", "init", str(directory), "--template", "async"]) == 0
    text = capsys.readouterr().out
    assert "--input hello" in text
    assert "--resume RUN_ID" in text
    assert "--factory" not in text


def test_installed_async_starter_needs_no_source_checkout(tmp_path, installed_wheel):
    python, ralf = installed_wheel
    project = tmp_path / "installed-async"
    subprocess_result([ralf, "init", project, "--template", "async"], cwd=tmp_path)
    result = json.loads(
        subprocess_result(
            [python, "-m", "agent_app", "--input", "hello", "--command-id", "s"], cwd=project
        )
    )
    assert result["state"] == "succeeded" and result["result"] == "async: hello"
    assert (
        json.loads(
            subprocess_result(
                [python, "-m", "agent_app", "--input", "hello", "--command-id", "s"], cwd=project
            )
        )
        == result
    )
