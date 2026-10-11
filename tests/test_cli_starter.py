"""Whole application subprocesses use installed-package-compatible templates."""

import json
import os
import sqlite3
import subprocess
import sys

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
