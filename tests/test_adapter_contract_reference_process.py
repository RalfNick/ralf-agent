"""Actual independent process loss with the independent external source adapter."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from relf_agent import SQLiteStore


def worker(database, *arguments):
    path = Path(__file__).with_name("adapter_contract_reference_worker.py")
    assert path.exists(), "The original-window independent worker is missing"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.adapter_contract_reference_worker",
            str(database),
            *arguments,
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={"PATH": os.environ.get("PATH", "")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
    except BaseException:
        process.kill()
        process.wait(timeout=10)
        raise
    assert process.poll() is not None
    return process.returncode, stdout, stderr, process.pid


def read(database, run_id):
    with SQLiteStore(database, readonly=True) as store:
        run = store.run(run_id)
        return run, store.budget(run_id)


@pytest.mark.parametrize("received", [False, True])
def test_external_source_deletion_after_actual_process_exit_preserves_original_response_window(
    tmp_path, received
):
    database = tmp_path / "runs.sqlite"
    event = "model_response_recorded" if received else "model_dispatched"
    code, stdout, stderr, old_pid = worker(database, "--trigger", event)
    assert code == 77, stderr
    run_id = json.loads(stdout)["run_id"]
    original, budget = read(database, run_id)
    assert original["session_turn"]["session"]["key"]["session_id"] == "knowledge-session"
    assert original["session_turn"]["turn_id"]
    assert len(original["actions"]) == 1 and original["actions"][0]["knowledge_references"]
    before = original["actions"][0]
    assert before["status"] == ("response_received" if received else "executing")
    assert budget == {"limit": 32, "held": 0 if received else 2, "spent": 2 if received else 0}
    with sqlite3.connect(database) as connection:
        original_commands = list(connection.execute("SELECT id,digest,receipt FROM commands"))
    code, stdout, stderr, new_pid = worker(database, "--run-id", run_id, "--delete-source")
    assert code == 0 and old_pid != new_pid, stderr
    actual = json.loads(stdout)
    after, final_budget = read(database, run_id)
    assert actual["run_id"] == run_id
    assert after["id"] == original["id"] and after["session_id"] == original["session_id"]
    assert after["session_turn"] == original["session_turn"]
    action = after["actions"][0]
    for field in ("id", "snapshot", "request", "knowledge_references", "context_manifest"):
        assert action[field] == before[field]
    assert action["attempts"][0]["id"] == before["attempts"][0]["id"]
    with sqlite3.connect(database) as connection:
        assert (
            list(connection.execute("SELECT id,digest,receipt FROM commands")) == original_commands
        )
    with sqlite3.connect(str(database) + ".external.sqlite") as connection:
        audit = dict(connection.execute("SELECT kind,count FROM audit"))
        assert connection.execute("SELECT deleted,version FROM sources").fetchone() == (1, 2)
    assert audit["retrieval"] == 1 and audit.get("model", 0) == int(received)
    assert final_budget == budget
    if received:
        assert actual["state"] == "succeeded"
        assert actual["result"]["answer"] == "cache timeout inspect connection pool"
        assert actual["result"]["sources"][0]["version"] == 1
        assert action["received_response"] == before["received_response"]
    else:
        assert actual["state"] == "failed"
