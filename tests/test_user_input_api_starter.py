"""The standalone installed template exposes a real durable input cycle."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from ralf_agent.starter import create_starter


def execute(project, *arguments):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "agent_app", *arguments],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_user_input_template_restarts_original_question_and_answer(tmp_path):
    project = tmp_path / "input-app"
    create_starter(project, template="user-input")
    first = execute(project, "run", "--command-id", "start")
    assert first["state"] == "waiting_input"
    question = first["pending"][0]
    second = execute(project, "run", "--command-id", "start")
    assert second["run_id"] == first["run_id"]
    assert second["pending"][0] == question
    arguments = (
        "reply",
        first["run_id"],
        question["pending_id"],
        "--digest",
        question["target_digest"],
        "--value-json",
        '"production"',
        "--command-id",
        "answer",
    )
    receipt = execute(project, *arguments)
    assert receipt["apply_state"] == "applied"
    completed = execute(project, "resume", first["run_id"])
    assert completed["state"] == "succeeded"
    assert completed["result"] == {"environment": "production"}
    assert execute(project, *arguments) == receipt


def test_standard_cli_inspection_and_json_reply_complete_starter_run(tmp_path):
    project = tmp_path / "input's $project"
    create_starter(project, template="user-input")
    first = execute(project, "run", "--command-id", "start")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

    def cli(*arguments):
        result = subprocess.run(
            [sys.executable, "-m", "ralf_agent", *arguments],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    options = ("--db", ".ralf/runs.sqlite", "--factory", "agent_app.runtime:create_engine")
    report = cli(*options, "inspect", first["run_id"])
    question = report["pending"][0]
    hint = shlex.split(question["send_input_command"])
    assert hint.pop(0) == "ralf"
    hint[hint.index("--value-json") + 1] = '"staging"'
    receipt = cli(*hint)
    assert receipt["kind"] == "send_input" and receipt["apply_state"] == "applied"
    assert cli(*hint) == receipt
    result = cli(*options, "resume", first["run_id"])
    assert result["state"] == "succeeded" and result["result"] == {"environment": "staging"}
