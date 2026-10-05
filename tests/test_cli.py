import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cli(db, *args, check=True):
    env = subprocess_env()
    result = subprocess.run(
        [sys.executable, "-m", "ralf_agent", "--db", str(db), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def subprocess_env():
    # Do not copy credentials into subprocesses or pytest's failure-local diagnostics.
    return {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "src")}


def test_cli_demo_requires_explicit_approval_and_resumes_across_processes(tmp_path):
    db = tmp_path / "demo.db"
    waiting = json.loads(cli(db, "demo", "--ticket", "INC-1").stdout)
    assert waiting["state"] == "waiting_approval"
    pending = waiting["pending"][0]
    receipt = json.loads(
        cli(
            db,
            "approve",
            waiting["run_id"],
            pending["action_id"],
            "--digest",
            pending["digest"],
            "--command-id",
            "approve-1",
        ).stdout
    )
    assert receipt["apply_state"] == "applied"
    done = json.loads(cli(db, "resume", waiting["run_id"]).stdout)
    assert done["state"] == "succeeded"
    assert done["result"]["verified"] is True
    events = json.loads(cli(db, "events", waiting["run_id"], "--after", "0").stdout)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    replay = json.loads(cli(db, "demo", "--ticket", "INC-1").stdout)
    assert replay["run_id"] == waiting["run_id"]
    assert replay["state"] == "succeeded"


def test_cli_reports_typed_errors_without_a_traceback(tmp_path):
    result = cli(tmp_path / "demo.db", "status", "missing", check=False)
    assert result.returncode == 2
    assert json.loads(result.stderr)["code"] == "not_found"
    assert "Traceback" not in result.stderr
