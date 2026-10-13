"""Two reaped independent process windows over original memory authority."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from ralf_agent import SQLiteStore
from tests.test_facts_adapter_starter import application


def worker(project, phase, window):
    module = Path(__file__).with_name("facts_adapter_recovery_worker.py")
    assert module.exists(), "The original Facts recovery process worker is missing"
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.facts_adapter_recovery_worker", str(project), phase, window],
        cwd=project,
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join(
                [
                    str(Path(__file__).resolve().parents[1]),
                    str(Path(__file__).resolve().parents[1] / "src"),
                ]
            ),
        },
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
    (project / (phase + "-stdout.txt")).write_text(stdout)
    (project / (phase + "-stderr.txt")).write_text(stderr)
    (project / (phase + "-process.json")).write_text(
        json.dumps(
            {
                "pid": process.pid,
                "returncode": process.returncode,
                "wait_returncode": process.wait(timeout=10),
                "reaped": True,
            }
        )
    )
    return process.returncode, stdout, stderr, process.pid


def evidence(project, run_id):
    with SQLiteStore(project / ".ralf/runs.sqlite", readonly=True) as store:
        run, budget = store.run(run_id), store.budget(run_id)
        commands = [
            tuple(row)
            for row in store.conn.execute("SELECT id,digest,receipt FROM commands ORDER BY id")
        ]
        reservations = [
            dict(row) for row in store.conn.execute("SELECT * FROM reservations ORDER BY rowid")
        ]
    with sqlite3.connect(project / ".ralf/facts.sqlite") as connection:
        counts = dict(connection.execute("SELECT kind,count FROM audit"))
        facts = list(
            connection.execute(
                "SELECT workspace,principal,namespace,key,value,version,expires_at FROM facts"
            )
        )
        dataset = connection.execute("SELECT dataset_id FROM facts_resource").fetchone()[0]
    return run, budget, commands, reservations, counts, facts, dataset


@pytest.mark.parametrize("window", ["accepted-put-lost-ack", "receipt-before-settlement"])
def test_original_run_action_command_profile_and_budget_survive_actual_process_window(
    tmp_path, window
):
    project = application(tmp_path)
    code, _, stderr, first_pid = worker(project, "crash", window)
    assert code == 77, stderr
    ref = json.loads((project / "refs.json").read_text())
    original, budget, commands, reservations, counts, facts, dataset = evidence(
        project, ref["run_id"]
    )
    (project / "before-evidence.json").write_text(
        json.dumps(
            {
                "run": original,
                "budget": budget,
                "commands": commands,
                "reservations": reservations,
                "audit": counts,
                "facts": facts,
                "dataset_id": dataset,
            },
            allow_nan=False,
        )
    )
    assert original["state"] == "running"
    assert len(original["actions"]) == 1 and original["actions"][0]["status"] == "completed"
    assert counts["model_calls"] == counts["put_calls"] == counts["write_count"] == len(facts) == 1
    assert budget == {"limit": 32, "held": 1, "spent": 2}
    stage = original["memory_stages"]["0"]
    assert len(stage["facts"]) == 1
    fact = stage["facts"][0]
    assert fact["status"] == (
        "writing" if window == "accepted-put-lost-ack" else "receipt_received"
    )
    assert (fact["receipt"] is None) == (window == "accepted-put-lost-ack")
    reservation = next(row for row in reservations if row["id"] == fact["reservation_id"])
    assert reservation["state"] == "reserved"
    code, stdout, stderr, second_pid = worker(project, "recover", window)
    assert code == 0 and first_pid != second_pid, stderr
    actual = json.loads(stdout)
    (
        after,
        final_budget,
        final_commands,
        final_reservations,
        final_counts,
        final_facts,
        final_dataset,
    ) = evidence(project, ref["run_id"])
    (project / "after-evidence.json").write_text(
        json.dumps(
            {
                "run": after,
                "budget": final_budget,
                "commands": final_commands,
                "reservations": final_reservations,
                "audit": final_counts,
                "facts": final_facts,
                "dataset_id": final_dataset,
            },
            allow_nan=False,
        )
    )
    assert actual["state"] == after["state"] == "succeeded"
    assert actual["result"] == {"answer": "Facts reference received", "facts": []}
    assert actual["source_closed"] and actual["descriptor_closed"]
    assert after["id"] == original["id"] and after["release_digest"] == original["release_digest"]
    assert after["manifest"]["runtime_profile"] == original["manifest"]["runtime_profile"]
    for field in ("id", "snapshot", "request", "received_response", "attempts"):
        assert after["actions"][0][field] == original["actions"][0][field]
    final_stage = after["memory_stages"]["0"]
    final_fact = final_stage["facts"][0]
    assert final_stage["status"] == final_fact["status"] == "completed"
    for field in ("key", "value", "reservation_id", "expires_at"):
        assert final_fact[field] == fact[field]
    settled = next(row for row in final_reservations if row["id"] == fact["reservation_id"])
    assert settled["state"] == "settled" and settled["actual"] == 1
    assert final_budget == {"limit": 32, "held": 0, "spent": 3}
    assert final_commands == commands and final_facts == facts and final_dataset == dataset
    assert (
        final_counts["model_calls"] == final_counts["put_calls"] == final_counts["write_count"] == 1
    )
    assert json.loads(commands[0][2]) == ref["receipt"]
