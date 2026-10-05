import json
import sqlite3
import subprocess
import sys

from .test_cli import ROOT, cli, subprocess_env


def test_cancel_after_crash_preserves_unknown_effect_and_blocks_new_run(tmp_path):
    db = tmp_path / "cancel-crash.db"
    crashed = subprocess.run(
        [sys.executable, str(ROOT / "tests/crash_worker.py"), str(db)],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert crashed.returncode == 77, crashed.stderr
    run_id = json.loads(crashed.stdout)["run_id"]
    cli(db, "cancel", run_id, "--command-id", "cancel-after-crash")
    cancelled = json.loads(cli(db, "status", run_id).stdout)
    assert cancelled["state"] == "cancelled"
    assert any(
        a["kind"] == "tool" and a["status"] == "outcome_unknown" for a in cancelled["actions"]
    )
    replacement = json.loads(
        cli(db, "demo", "--ticket", "INC-CRASH", "--command-id", "replacement").stdout
    )
    assert replacement["state"] == "waiting_reconciliation"
    with sqlite3.connect(str(db) + ".business.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1


def test_real_process_death_after_business_commit_does_not_duplicate_write(tmp_path):
    db = tmp_path / "crash.db"
    env = subprocess_env()
    crashed = subprocess.run(
        [sys.executable, str(ROOT / "tests/crash_worker.py"), str(db)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert crashed.returncode == 77, crashed.stderr
    run_id = json.loads(crashed.stdout)["run_id"]
    with sqlite3.connect(str(db) + ".business.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
    done = json.loads(cli(db, "resume", run_id).stdout)
    assert done["state"] == "succeeded"
    assert done["result"]["verified"] is True
    with sqlite3.connect(str(db) + ".business.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
    events = json.loads(cli(db, "events", run_id).stdout)
    assert (
        sum(
            e["kind"] == "tool_dispatch_intent"
            and e["data"]["action_id"] == done["actions"][3]["id"]
            for e in events
        )
        == 1
    )
