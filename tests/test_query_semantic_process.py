import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import ralf_agent
from tests.test_h3_semantic_http import synonym_endpoint  # noqa: F401


def test_received_model_reuses_query_and_semantic_fact_snapshots_after_process_death(
    tmp_path, request
):
    endpoint, requests = request.getfixturevalue("synonym_endpoint")
    fixture = Path(__file__).with_name("query_semantic_crash_fixture.py")
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
        if mode != "crash":
            assert json.loads(result.stdout)["state"] == (
                "waiting_approval" if mode == "waiting" else "succeeded"
            )
        count = 2 if mode == "finish" else 1
        assert len(requests) == count
        with sqlite3.connect(tmp_path / "business.sqlite") as db:
            for kind in ("facts_transform", "knowledge_transform", "model"):
                assert (
                    db.execute("SELECT COUNT(*) FROM calls WHERE kind=?", (kind,)).fetchone()[0]
                    == count
                )
    with sqlite3.connect(tmp_path / "business.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
