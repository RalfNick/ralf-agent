import json
import os
import subprocess
import sys

from relf_agent.starter import create_starter


def test_mcp_starter_approval_restart_and_one_business_effect(tmp_path):
    project = create_starter(tmp_path / "application", template="mcp")
    root = tmp_path / "application"
    env = {"PATH": os.environ.get("PATH", "")}

    def call(args):
        result = subprocess.run(
            [sys.executable, *args], cwd=root, env=env, text=True, capture_output=True, timeout=20
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    queued = call(["-m", "agent_app", "--value", "3", "--command-id", "same"])
    assert queued["state"] == "waiting_approval"
    pending = queued["pending"][0]
    approved = call(
        [
            "-m",
            "relf_agent",
            "--db",
            ".ralf/runs.sqlite",
            "--factory",
            project.factory,
            "approve",
            queued["run_id"],
            pending["action_id"],
            "--digest",
            pending["digest"],
            "--command-id",
            "approve",
        ]
    )
    done = call(
        [
            "-m",
            "relf_agent",
            "--db",
            ".ralf/runs.sqlite",
            "--factory",
            project.factory,
            "resume",
            queued["run_id"],
        ]
    )
    assert done["state"] == "succeeded" and done["result"]["structuredContent"]["value"] == 3
    assert (
        call(["-m", "agent_app", "--value", "3", "--command-id", "same"])["run_id"]
        == queued["run_id"]
    )
    import sqlite3

    with sqlite3.connect(root / ".ralf/business.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
    assert approved["apply_state"] == "applied"
