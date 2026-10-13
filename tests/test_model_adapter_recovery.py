"""Reaped original processes retain supplier evidence without a retry cache."""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from ralf_agent import SQLiteStore
from ralf_agent.types import canonical


def worker(root, phase, window):
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.model_adapter_recovery_worker", str(root), phase, window],
        cwd=root,
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
    waited = process.wait(timeout=10)
    assert process.poll() == waited
    (root / f"{phase}-stdout.txt").write_text(stdout)
    (root / f"{phase}-stderr.txt").write_text(stderr)
    (root / f"{phase}-process.json").write_text(
        canonical(
            {
                "pid": process.pid,
                "returncode": process.returncode,
                "wait_returncode": waited,
                "reaped": True,
            }
        )
    )
    return process.returncode, stdout, stderr, process.pid


def evidence(root, run_id):
    with SQLiteStore(root / "runs.sqlite", readonly=True) as store:
        run, budget = store.run(run_id), store.budget(run_id)
        commands = [tuple(row) for row in store.conn.execute("SELECT * FROM commands ORDER BY id")]
        reservations = [
            dict(row) for row in store.conn.execute("SELECT * FROM reservations ORDER BY id")
        ]
    with closing(sqlite3.connect(root / "supplier.sqlite")) as db:
        counts = dict(db.execute("SELECT kind,count FROM supplier_audit"))
        dataset = db.execute("SELECT dataset_id FROM model_resource").fetchone()[0]
        requests = [tuple(row) for row in db.execute("SELECT * FROM supplier_requests ORDER BY id")]
        responses = [
            tuple(row) for row in db.execute("SELECT * FROM supplier_responses ORDER BY id")
        ]
    with closing(sqlite3.connect(root / "business.sqlite")) as db:
        effects = [tuple(row) for row in db.execute("SELECT * FROM effects ORDER BY effect_key")]
        invocations = [tuple(row) for row in db.execute("SELECT * FROM invocations")]
    return {
        "run": run,
        "budget": budget,
        "commands": commands,
        "reservations": reservations,
        "counts": counts,
        "dataset": dataset,
        "requests": requests,
        "responses": responses,
        "effects": effects,
        "invocations": invocations,
    }


@pytest.mark.parametrize("window", ["recorded-response", "accepted-response-lost"])
def test_original_run_action_attempt_receipt_budget_and_source_survive_reaped_process(
    tmp_path, window
):
    code, _, stderr, first_pid = worker(tmp_path, "crash", window)
    assert code == 77, stderr
    refs = json.loads((tmp_path / "refs.json").read_text())
    original = evidence(tmp_path, refs["run_id"])
    (tmp_path / "before-evidence.json").write_text(canonical(original))
    run = original["run"]
    models = [a for a in run["actions"] if a["kind"] == "model"]
    assert run["state"] == "running"
    target = models[-1]
    held = window == "accepted-response-lost"
    assert target["status"] == ("executing" if held else "response_received")
    assert target["attempts"][0]["status"] == ("executing" if held else "completed")
    assert (target.get("received_response") is None) == held
    assert original["budget"] == {"limit": 8, "held": 1 if held else 0, "spent": 2 if held else 1}
    assert (
        original["counts"]["model_calls"]
        == original["counts"]["request_count"]
        == original["counts"]["response_count"]
        == (2 if held else 1)
    )
    assert len(original["effects"]) == len(original["invocations"]) == int(held)
    if held:
        tool = next(a for a in run["actions"] if a["kind"] == "tool")
        assert tool["status"] == "completed" and tool["approved"]
        assert tool["receipt"]
    code, stdout, stderr, second_pid = worker(tmp_path, "recover", window)
    assert code == 0 and second_pid != first_pid, stderr
    actual = json.loads(stdout)
    after = evidence(tmp_path, refs["run_id"])
    (tmp_path / "after-evidence.json").write_text(canonical(after))
    assert actual["source_closed"] and actual["descriptor_closed"]
    assert after["run"]["id"] == run["id"] and after["run"]["manifest"] == run["manifest"]
    assert after["run"]["release_digest"] == run["release_digest"]
    assert after["budget"] == original["budget"]
    assert after["reservations"] == original["reservations"]
    for key in ("commands", "dataset", "requests", "responses", "effects", "invocations"):
        assert after[key] == original[key]
    assert after["counts"]["model_calls"] == original["counts"]["model_calls"]
    assert after["counts"]["response_count"] == original["counts"]["response_count"]
    assert after["counts"]["close_calls"] == 1
    if held:
        assert after["run"] == run
        assert actual["state"] == "running"
        assert target.get("received_response") is None
    else:
        assert actual["state"] == after["run"]["state"] == "succeeded"
        recovered = after["run"]["actions"][0]
        assert recovered["status"] == "completed"
        for key in ("id", "snapshot", "request", "received_response", "attempts"):
            assert recovered[key] == target[key]
        assert after["run"]["result"] == {"actual": [None, False, 7, "中文🙂"]}
