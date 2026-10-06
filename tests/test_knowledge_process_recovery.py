import json
import sqlite3
import subprocess
import sys

import pytest

from .test_cli import subprocess_env
from .test_receipt_process_recovery import read_run


def worker(database, *arguments):
    return subprocess.run(
        [sys.executable, "-m", "tests.knowledge_runtime", str(database), *arguments],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.parametrize("receiver_saved", [False, True])
def test_source_deletion_after_process_death_never_replaces_original_knowledge_snapshot(
    tmp_path, receiver_saved
):
    database = tmp_path / "knowledge.sqlite"
    event = "model_response_recorded" if receiver_saved else "model_dispatched"
    crashed = worker(database, "--trigger", event)
    assert crashed.returncode == 77, crashed.stderr
    run_id = json.loads(crashed.stdout)["run_id"]
    original, _, _ = read_run(database, run_id)
    assert len(original["actions"]) == 1 and original["actions"][0]["knowledge_references"]
    restarted = worker(database, "--run-id", run_id, "--delete-source")
    assert restarted.returncode == 0, restarted.stderr
    result = json.loads(restarted.stdout)
    after, _, budget = read_run(database, run_id)
    assert after["actions"][0]["snapshot"] == original["actions"][0]["snapshot"]
    assert (
        after["actions"][0]["knowledge_references"]
        == original["actions"][0]["knowledge_references"]
    )
    with sqlite3.connect(str(database) + ".audit.sqlite") as connection:
        calls = dict(connection.execute("SELECT kind,count FROM calls"))
    assert calls.get("retrieval", 0) == 1
    if receiver_saved:
        assert result["state"] == "succeeded" and result["result"]["version"] == 1
        assert result["result"]["answer"] == "Cache timeout: inspect connection pool."
        assert calls.get("model", 0) == 1
        assert budget == {"limit": 32, "held": 0, "spent": 2}
    else:
        assert result["state"] == "failed"
        assert calls.get("model", 0) == 0
        assert budget == {"limit": 32, "held": 2, "spent": 0}
