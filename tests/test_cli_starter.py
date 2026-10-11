"""Whole application subprocesses use installed-package-compatible templates."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from ralf_agent import SQLiteRunReader
from ralf_agent.starter import create_starter


def test_cli_starter_approval_restart_duplicate_controls_and_one_business_write(tmp_path):
    project = create_starter(tmp_path / "application", template="cli")
    root = tmp_path / "application"
    assert project.factory is None

    def call(arguments):
        result = subprocess.run(
            [sys.executable, "-m", "agent_app", *arguments],
            cwd=root,
            env={"PATH": os.environ.get("PATH", "")},
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    accepted = call(["run", "--value", "3", "--command-id", "same"])
    assert accepted["state"] == "waiting_approval"
    assert not (root / ".ralf/business.sqlite").exists()
    assert (root / ".ralf/read-audit").read_text().splitlines() == ["read"]

    workflow = SQLiteRunReader(root / ".ralf/runs.sqlite").diagnostics(accepted["run_id"]).workflow
    assert workflow["nodes"]["read"]["state"] == "completed"
    assert workflow["nodes"]["plan"]["state"] == "completed"
    assert workflow["nodes"]["plan"]["result"] == {"value": 3}
    pending = accepted["pending"][0]
    args = [
        "approve",
        accepted["run_id"],
        pending["action_id"],
        "--digest",
        pending["digest"],
        "--command-id",
        "approve",
    ]
    first = call(args)
    assert call(args) == first and first["apply_state"] == "applied"
    done = call(["resume", accepted["run_id"]])
    assert done["state"] == "succeeded" and done["result"]["value"] == 3
    assert call(["run", "--value", "3", "--command-id", "same"])["run_id"] == accepted["run_id"]
    assert call(["resume", accepted["run_id"]])["state"] == "succeeded"
    with sqlite3.connect(root / ".ralf/business.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
    assert (root / ".ralf/call-audit").read_text().splitlines() == ["call"]
    assert (root / ".ralf/read-audit").read_text().splitlines() == ["read"]


@pytest.mark.parametrize("directory", ["data#1", "data?1", "data%23"])
def test_generated_business_read_escapes_uri_path_without_opening_another_file(tmp_path, directory):
    from ralf_agent.cli_starter import CLI_FILES

    root = tmp_path / directory
    root.mkdir()
    database = root / "business.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE effects (effect_key TEXT PRIMARY KEY, result TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO effects VALUES (?,?)", ("original", "{}"))
    program = tmp_path / "business_tool.py"
    program.write_text(CLI_FILES["business_tool.py"])
    result = subprocess.run(
        [sys.executable, str(program), str(database), "read"],
        input='{"value":7}',
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert not (tmp_path / "data").exists()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"value": 7, "applied_count": 1}
