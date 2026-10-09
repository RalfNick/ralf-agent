import json
import sqlite3
import subprocess
import sys

import pytest

from .test_cli import subprocess_env


@pytest.mark.parametrize(
    "window",
    [
        "plan_proposal_received",
        "plan_revision_adopted",
        "child_submitted",
        "run_succeeded",
        "plan_verified",
    ],
)
def test_real_process_durability_windows_resume_without_replanning_or_duplicate_child(
    tmp_path, window
):
    path = tmp_path / "crash.sqlite"
    base = [sys.executable, "-m", "tests.orchestration_crash_fixture", str(path)]
    crashed = subprocess.run(
        [*base, "--crash", window], env=subprocess_env(), capture_output=True, text=True, timeout=10
    )
    assert crashed.returncode == 77, crashed.stderr
    run_id = json.loads(crashed.stdout.splitlines()[0])["run_id"]
    recovered = subprocess.run(
        [*base, "--run-id", run_id],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout.splitlines()[-1])["state"] == "succeeded"
    with sqlite3.connect(path.with_suffix(".counter.sqlite")) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM counts WHERE kind=?", ("plan",)).fetchone()[0] == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM counts WHERE kind=?", ("model",)).fetchone()[0] == 1
        )
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
