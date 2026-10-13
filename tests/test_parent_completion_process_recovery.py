"""Independent processes recover original receipt/adoption windows without duplication."""

import json
import sqlite3
import subprocess
import sys

import pytest

from .test_cli import subprocess_env
from .test_local_parent_completion import api


@pytest.mark.parametrize("kind", ["flat", "dag", "team"])
@pytest.mark.parametrize(
    "window",
    [
        "parent_completion_source_recorded",
        "parent_verification_child_intent_recorded",
        "model_response_recorded",
        "decision_adopted",
        "parent_verification_proposal_received",
        "parent_completion_adopted",
        "run_succeeded",
    ],
)
def test_real_process_verification_boundaries_resume_one_original_call(tmp_path, kind, window):
    api()
    path = tmp_path / "run.sqlite"
    base = [
        sys.executable,
        "-m",
        "tests.parent_completion_crash_fixture",
        str(path),
        "--kind",
        kind,
    ]
    crashed = subprocess.run(
        [*base, "--window", window],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert crashed.returncode == 77, crashed.stderr
    run_id = json.loads(crashed.stdout.splitlines()[0])["run_id"]
    recovered = subprocess.run(
        [*base, "--run-id", run_id],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout.splitlines()[-1])["state"] == "succeeded"
    with sqlite3.connect(path.with_suffix(".markers.sqlite")) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM calls WHERE kind='worker-model'").fetchone()[0] == 2
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM calls WHERE kind='verifier-model'").fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM calls WHERE kind='effect'").fetchone()[0] == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 3
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE kind='parent_completion_gate_recorded'"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE kind='parent_completion_adopted'"
            ).fetchone()[0]
            == 1
        )
