import json
import sys

import pytest

from relf_agent.starter import create_starter

from .test_starter import installed_wheel as _installed_wheel
from .test_starter import subprocess_result

installed_wheel = _installed_wheel


@pytest.mark.parametrize("template", ["plan", "team", "dag", "nested"])
def test_new_starter_runs_replays_and_resumes_outside_source(tmp_path, template):
    project = tmp_path / template
    create_starter(project, template=template)
    args = [sys.executable, "-m", "agent_app", "--input", "task", "--command-id", "s"]
    first = json.loads(subprocess_result(args, cwd=project))
    assert first["state"] == "succeeded"
    assert json.loads(subprocess_result(args, cwd=project)) == first
    queued = json.loads(
        subprocess_result(
            [
                sys.executable,
                "-m",
                "agent_app",
                "--input",
                "queued",
                "--command-id",
                "q",
                "--submit-only",
            ],
            cwd=project,
        )
    )
    resumed = json.loads(
        subprocess_result(
            [sys.executable, "-m", "agent_app", "--resume", queued["run_id"]], cwd=project
        )
    )
    assert resumed["state"] == "succeeded"


@pytest.mark.parametrize("template", ["plan", "team", "dag", "nested"])
def test_installed_plan_team_starter_and_readonly_child_inspection(
    tmp_path, installed_wheel, template
):
    python, ralf = installed_wheel
    project = tmp_path / ("installed-" + template)
    subprocess_result([ralf, "init", project, "--template", template], cwd=tmp_path)
    first = json.loads(
        subprocess_result(
            [python, "-m", "agent_app", "--input", "task", "--command-id", "s"], cwd=project
        )
    )
    assert first["state"] == "succeeded"
    text = subprocess_result(
        [ralf, "--db", ".ralf/runs.sqlite", "--format", "text", "inspect", first["run_id"]],
        cwd=project,
    )
    assert "Child:" in text
