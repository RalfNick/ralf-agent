import json
import sys

from ralf_agent.starter import create_starter

from .test_starter import installed_wheel as _installed_wheel
from .test_starter import subprocess_result

installed_wheel = _installed_wheel


def test_config_starter_runs_without_editing_python_and_keeps_original_version(tmp_path):
    project = tmp_path / "configured"
    create_starter(project, template="config")
    submitted = json.loads(
        subprocess_result(
            [sys.executable, "-m", "agent_app", "--input", "question", "--submit-only"],
            cwd=project,
        )
    )
    path = project / "runtime.toml"
    contents = path.read_text()
    path.write_text(contents.replace('version = "1"', 'version = "2"', 1))
    completed = json.loads(
        subprocess_result(
            [sys.executable, "-m", "ralf_agent", "--config", path, "resume", submitted["run_id"]],
            cwd=project,
        )
    )
    assert completed["result"] == {"echo": "question", "label": "config-v1"}
    latest = json.loads(
        subprocess_result(
            [sys.executable, "-m", "agent_app", "--input", "question", "--command-id", "new"],
            cwd=project,
        )
    )
    assert latest["result"]["label"] == "config-v2"


def test_installed_wheel_config_template_and_text_commands_are_independent(
    tmp_path, installed_wheel
):
    python, ralf = installed_wheel
    project = tmp_path / "configuration-only"
    text = subprocess_result(
        [ralf, "--format", "text", "init", project, "--template", "config"], cwd=tmp_path
    )
    assert "--input" in text and "--ticket" not in text
    done = json.loads(
        subprocess_result(
            [python, "-m", "agent_app", "--input", "installed question"],
            cwd=project,
        )
    )
    assert done["state"] == "succeeded" and done["result"]["echo"] == "installed question"
    assert done["result"]["label"] == "config-v1"
    observed = json.loads(
        subprocess_result(
            [
                ralf,
                "--db",
                project / ".ralf/runs.sqlite",
                "--config",
                project / "runtime.toml",
                "inspect",
                done["run_id"],
            ],
            cwd=tmp_path,
        )
    )
    assert observed["needs_factory"] is False
