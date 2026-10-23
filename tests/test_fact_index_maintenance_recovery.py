"""Waited/reaped native process windows preserve original authority and evidence."""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from relf_agent import SQLiteStore
from relf_agent.types import canonical


def worker(root, phase, window):
    checkout = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.fact_index_maintenance_recovery_worker",
            str(root),
            phase,
            window,
        ],
        cwd=root,
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join((str(checkout), str(checkout / "src"))),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=25)
    except BaseException:
        process.kill()
        process.wait(timeout=10)
        raise
    assert process.wait(timeout=10) == process.returncode
    (root / (phase + "-stdout.txt")).write_text(stdout)
    (root / (phase + "-stderr.txt")).write_text(stderr)
    (root / (phase + "-process.json")).write_text(
        canonical({"pid": process.pid, "returncode": process.returncode, "waited_reaped": True})
    )
    return process.returncode, stdout, stderr


def evidence(root, run_id):
    with SQLiteStore(root / "runs.sqlite", readonly=True) as store:
        result = {
            "run": store.run(run_id),
            "budget": store.budget(run_id),
            "reservations": [
                dict(row) for row in store.conn.execute("SELECT * FROM reservations ORDER BY id")
            ],
            "commands": [
                dict(row) for row in store.conn.execute("SELECT * FROM commands ORDER BY id")
            ],
            "session_rows": [
                dict(row)
                for row in store.conn.execute(
                    "SELECT * FROM memory_session_items ORDER BY message_id"
                )
            ],
        }
    for name, table in (
        ("source", "memory_facts"),
        ("catalog", "memory_facts"),
        ("vector", "vector_entries"),
        ("trace", "observations"),
    ):
        with closing(sqlite3.connect(root / (name + ".sqlite"))) as db:
            db.row_factory = sqlite3.Row
            result[name] = [
                dict(row) for row in db.execute("SELECT * FROM " + table + " ORDER BY rowid")
            ]
    return result


def count(actual, kind):
    return sum(row["kind"] == kind for row in actual["trace"])


@pytest.mark.parametrize(
    "window",
    [
        "accepted-embedding",
        "vector-commit",
        "page-checkpoint",
        "active-publication",
        "effect-receipt",
        "tool-receipt",
    ],
)
def test_original_session_action_attempt_and_index_evidence_survive_native_death(tmp_path, window):
    code, _, stderr = worker(tmp_path, "crash", window)
    assert code == 77, stderr
    refs = json.loads((tmp_path / "refs.json").read_text())
    run_id = refs["run"]["run_id"]
    before = evidence(tmp_path, run_id)
    (tmp_path / "before.json").write_text(canonical(before))
    original = before["run"]["actions"][0]
    assert before["run"]["state"] == "running"
    assert original["status"] == ("receipt_received" if window == "tool-receipt" else "executing")
    assert len(original["attempts"]) == 1 and before["budget"] == {
        "limit": 8,
        "held": 1,
        "spent": 0,
    }
    assert count(before, "embedding") == count(before, "dispatch") == 1
    code, stdout, stderr = worker(tmp_path, "observe", window)
    assert code == 0, stderr
    observation = json.loads(stdout)
    assert observation["observation_only"] and evidence(tmp_path, run_id) == before
    code, stdout, stderr = worker(tmp_path, "recover", window)
    assert code == 0, stderr
    actual = json.loads(stdout)
    after = evidence(tmp_path, run_id)
    (tmp_path / "after.json").write_text(canonical(after))
    assert actual["state"] == after["run"]["state"] == "succeeded"
    assert (
        after["run"]["id"] == before["run"]["id"]
        and after["run"]["manifest"] == before["run"]["manifest"]
    )
    action = after["run"]["actions"][0]
    for key in ("id", "effect_key", "digest", "arguments"):
        assert action[key] == original[key]
    assert action["status"] == "completed" and action["result"]["status"] == "ready"
    assert after["source"] == before["source"] and len(after["vector"]) == 1
    assert after["commands"] == before["commands"]
    assert actual["turns"] == [refs["turn"]] and not actual["session"]["busy"]
    retry = window not in {"effect-receipt", "tool-receipt"}
    assert len(action["attempts"]) == (2 if retry else 1)
    assert after["budget"] == {"limit": 8, "held": int(retry), "spent": 1}
    if retry:
        assert action["attempts"][0]["id"] == original["attempts"][0]["id"]
        assert (
            action["attempts"][0]["status"] == "unknown"
            and action["attempts"][1]["status"] == "completed"
        )
        assert len(after["reservations"]) == 2 and count(after, "dispatch") == 2
    else:
        assert count(after, "dispatch") == 1 and len(after["reservations"]) == 1
        assert after["catalog"] == before["catalog"] and after["vector"] == before["vector"]
    assert count(after, "embedding") == (2 if window == "accepted-embedding" else 1)
    assert count(after, "vector-commit") == (2 if window == "vector-commit" else 1)
    closed = json.loads((tmp_path / "recover-closed.json").read_text())
    assert closed == {"active_owner": 0, "other_live_tasks": 0, "connections_closed": 3}
