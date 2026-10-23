"""Actual reaped process windows for the independent Session data adapter."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from relf_agent import SQLiteStore


def worker(directory, phase, window):
    module = Path(__file__).with_name("session_adapter_recovery_worker.py")
    assert module.exists(), "The independent Session recovery worker is missing"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.session_adapter_recovery_worker",
            str(directory),
            phase,
            window,
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
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
    (directory / (phase + "-stdout.txt")).write_text(stdout)
    (directory / (phase + "-stderr.txt")).write_text(stderr)
    (directory / (phase + "-process.json")).write_text(
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


def evidence(directory, run_id):
    with SQLiteStore(directory / "runs.sqlite", readonly=True) as store:
        run = store.run(run_id)
        budget = store.budget(run_id)
        commands = [
            tuple(row)
            for row in store.conn.execute("SELECT id,digest,receipt FROM commands ORDER BY id")
        ]
    with sqlite3.connect(directory / "sessions.sqlite") as connection:
        counts = dict(connection.execute("SELECT kind,count FROM audit"))
        messages = list(
            connection.execute(
                "SELECT workspace,principal,address,message_id,revision,message FROM session_messages"
            )
        )
        dataset = connection.execute("SELECT dataset_id FROM session_resource").fetchone()[0]
    return run, budget, commands, counts, messages, dataset


@pytest.mark.parametrize("window", ["accepted-save-lost-ack", "confirmed-before-terminal"])
def test_original_run_turn_and_receipt_survive_independent_process_save_window(tmp_path, window):
    code, stdout, stderr, first_pid = worker(tmp_path, "crash", window)
    assert code == 77, stderr
    refs = json.loads((tmp_path / "refs.json").read_text())
    original, budget, commands, counts, messages, dataset = evidence(
        tmp_path, refs["run"]["run_id"]
    )
    assert original["state"] == "running"
    assert original["session_turn"]["session"] == refs["session"]
    assert original["session_turn"]["turn_id"]
    assert len(original["actions"]) == 1
    action = original["actions"][0]
    assert action["kind"] == "model" and action["status"] == "completed"
    intent = original["remote_session_saves"]["0"]
    assert (intent["receipt"] is None) == (window == "accepted-save-lost-ack")
    assert (
        counts["model_calls"]
        == counts["append_calls"]
        == counts["save_count"]
        == len(messages)
        == 1
    )
    assert budget == {"limit": 32, "held": 0, "spent": 2}
    code, stdout, stderr, second_pid = worker(tmp_path, "recover", window)
    assert code == 0 and second_pid != first_pid, stderr
    actual = json.loads(stdout)
    after, final_budget, final_commands, final_counts, final_messages, final_dataset = evidence(
        tmp_path, refs["run"]["run_id"]
    )
    assert actual["state"] == after["state"] == "succeeded"
    assert actual["result"] == intent["message"]["content"]
    assert not actual["busy"]
    assert after["id"] == original["id"] and after["session_turn"] == original["session_turn"]
    assert after["release_digest"] == original["release_digest"] == refs["run"]["release_digest"]
    for field in ("id", "snapshot", "request", "received_response", "attempts"):
        assert after["actions"][0][field] == action[field]
    final_intent = after["remote_session_saves"]["0"]
    assert final_intent["message_id"] == intent["message_id"] == f"{original['id']}:0:result"
    assert final_intent["message"] == intent["message"]
    assert final_intent["attempts"] == intent["attempts"] == 1
    assert final_intent["receipt"]["receipt"] == {"revision": 1, "message": intent["message"]}
    assert final_budget == budget and final_commands == commands
    assert final_messages == messages and final_dataset == dataset
    assert (
        final_counts["model_calls"]
        == final_counts["append_calls"]
        == final_counts["save_count"]
        == 1
    )
    receipt = json.loads(next(row[2] for row in commands if row[0] == "submit"))
    assert receipt == refs["receipt"]
