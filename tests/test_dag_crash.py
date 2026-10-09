"""Actual process deaths exercise accepted DAG and nested child recovery."""

import json
import sqlite3
import subprocess
import sys

import pytest

from .test_cli import subprocess_env


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    "window",
    [
        "plan_proposal_received",
        "plan_revision_adopted",
        "dag_node_dispatched",
        "dag_nodes_completed",
        "dag_completed",
        "run_succeeded",
    ],
)
def test_dag_crash_recovers_original_plan_and_child_tree(tmp_path, nested, window):
    path = tmp_path / "dag.sqlite"
    base = [sys.executable, "-m", "tests.orchestration_crash_fixture", str(path), "--dag"]
    if nested:
        base.append("--nested")
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
        counts = dict(conn.execute("SELECT kind, COUNT(*) FROM counts GROUP BY kind"))
        assert counts == {"plan": 1, "model": 2}
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == (4 if nested else 3)
