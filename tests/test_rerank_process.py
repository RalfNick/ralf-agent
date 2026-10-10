import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import ralf_agent
from tests.test_rerank_integration import rerank_service  # noqa: F401


def test_received_model_response_reuses_rerank_snapshot_through_process_exit_and_approval(
    tmp_path, request
):
    endpoint, requests = request.getfixturevalue("rerank_service")
    fixture = Path(__file__).with_name("rerank_crash_fixture.py")
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(
            [str(Path(ralf_agent.__file__).parents[1]), str(Path(__file__).parents[1])]
        ),
    }
    for mode, expected in (("crash", 77), ("waiting", 0), ("finish", 0)):
        result = subprocess.run(
            [sys.executable, str(fixture), str(tmp_path), endpoint, mode],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == expected, result.stderr
        if mode == "waiting":
            assert json.loads(result.stdout)["state"] == "waiting_approval" and len(requests) == 1
        if mode == "finish":
            assert json.loads(result.stdout)["state"] == "succeeded" and len(requests) == 2
    with sqlite3.connect(tmp_path / "business.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
