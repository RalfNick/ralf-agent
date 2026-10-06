import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict

import pytest

from ralf_agent import SQLiteStore

from .receipt_runtime import create_engine
from .test_cli import subprocess_env


def worker(database, scenario, *arguments):
    return subprocess.run(
        [sys.executable, "-m", "tests.receipt_runtime", str(database), scenario, *arguments],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )


def crash_at(database, scenario, event):
    crashed = worker(database, scenario, "--trigger-event", event)
    assert crashed.returncode == 77, crashed.stderr
    return json.loads(crashed.stdout)["run_id"]


def read_run(database, run_id):
    with SQLiteStore(database, readonly=True) as store:
        return store.run(run_id), store.events(run_id), store.budget(run_id)


def evidence(database):
    with sqlite3.connect(str(database) + ".evidence.sqlite") as connection:
        calls = dict(connection.execute("SELECT kind, count FROM calls"))
        results = [json.loads(row[0]) for row in connection.execute("SELECT result FROM effects")]
    return {kind: calls.get(kind, 0) for kind in ("model", "handler", "reconciler")}, results


def resume(database, scenario, run_id, *, cancel=False):
    arguments = ["--run-id", run_id]
    if cancel:
        arguments.append("--cancel-before-resume")
    restarted = worker(database, scenario, *arguments)
    assert restarted.returncode == 0, restarted.stderr
    return json.loads(restarted.stdout)


def adoption_pair(events, receiver, adopted, action_id):
    received = [
        event for event in events if event.kind == receiver and event.data["action_id"] == action_id
    ]
    commits = [
        event for event in events if event.kind == adopted and event.data["action_id"] == action_id
    ]
    assert len(received) == len(commits) == 1
    assert received[0].seq < commits[0].seq


@pytest.mark.parametrize("scenario", ["final", "queryable_write"])
def test_real_process_death_after_response_commit_reuses_the_full_model_response(
    tmp_path, scenario
):
    database = tmp_path / "response.sqlite"
    run_id = crash_at(database, scenario, "model_response_recorded")
    interrupted, events, budget = read_run(database, run_id)
    assert len(interrupted["actions"]) == 1
    model = interrupted["actions"][0]
    assert model["kind"] == "model" and model["status"] == "response_received"
    assert len(model["attempts"]) == 1
    received = model["received_response"]
    assert received["usage"] == {
        "input_tokens": 11,
        "output_tokens": 3,
        "source": "offline-fixture",
    }
    if scenario == "final":
        assert received["output"] == {"completed": True, "answer": "recorded model response"}
        assert received["tool_calls"] == []
    else:
        assert received["tool_calls"] == [
            {"name": "write", "arguments": {"value": 7}, "call_id": "fixture-call"}
        ]
    assert not any(event.kind == "decision_adopted" for event in events)
    assert budget["held"] + budget["spent"] == 2
    calls, results = evidence(database)
    assert calls == {"model": 1, "handler": 0, "reconciler": 0} and results == []

    done = resume(database, scenario, run_id)
    assert done["state"] == "succeeded"
    run, events, budget = read_run(database, run_id)
    adopted = next(action for action in run["actions"] if action["id"] == model["id"])
    assert adopted["status"] == "completed" and adopted["response"] == received
    assert len(adopted["attempts"]) == 1
    adoption_pair(events, "model_response_recorded", "decision_adopted", model["id"])
    calls, results = evidence(database)
    if scenario == "final":
        assert calls == {"model": 1, "handler": 0, "reconciler": 0}
        assert results == [] and len(run["actions"]) == 1
        assert budget == {"limit": 12, "held": 0, "spent": 2}
    else:
        assert calls == {"model": 2, "handler": 1, "reconciler": 0}
        assert len(results) == 1 and len(run["actions"]) == 3
        assert budget == {"limit": 12, "held": 0, "spent": 7}
        assert len([action for action in run["actions"] if action["kind"] == "tool"]) == 1


@pytest.mark.parametrize("scenario", ["queryable_write", "unqueryable_write"])
def test_real_process_death_after_receipt_commit_does_not_write_or_query_again(tmp_path, scenario):
    database = tmp_path / "receipt.sqlite"
    run_id = crash_at(database, scenario, "tool_receipt_recorded")
    interrupted, events, budget = read_run(database, run_id)
    assert len(interrupted["actions"]) == 2
    tool = next(action for action in interrupted["actions"] if action["kind"] == "tool")
    assert tool["status"] == "receipt_received" and len(tool["attempts"]) == 1
    calls, results = evidence(database)
    assert calls == {"model": 1, "handler": 1, "reconciler": 0} and len(results) == 1
    assert tool["effect_observation"]["result"] == results[0]
    assert "result" not in tool
    assert not any(event.kind == "tool_result_committed" for event in events)
    assert budget["held"] + budget["spent"] == 5

    done = resume(database, scenario, run_id)
    assert done["state"] == "succeeded" and done["result"]["receipt_id"] == results[0]["receipt_id"]
    run, events, budget = read_run(database, run_id)
    assert len(run["actions"]) == 3
    committed = next(action for action in run["actions"] if action["id"] == tool["id"])
    assert committed["status"] == "completed" and committed["result"] == results[0]
    assert len(committed["attempts"]) == 1
    assert sum(message["role"] == "tool" for message in run["messages"]) == 1
    adoption_pair(events, "tool_receipt_recorded", "tool_result_committed", tool["id"])
    dispatches = [
        event
        for event in events
        if event.kind == "tool_dispatch_intent" and event.data["action_id"] == tool["id"]
    ]
    assert len(dispatches) == 1
    calls, after = evidence(database)
    assert calls == {"model": 2, "handler": 1, "reconciler": 0} and after == results
    assert budget == {"limit": 12, "held": 0, "spent": 7}


@pytest.mark.parametrize(
    "event,scenario,expected_cost",
    [
        ("model_response_recorded", "final", 2),
        ("model_response_recorded", "queryable_write", 2),
        ("tool_receipt_recorded", "queryable_write", 5),
    ],
)
def test_cancel_after_recorded_evidence_crash_keeps_terminal_and_settles_without_dispatch(
    tmp_path, event, scenario, expected_cost
):
    database = tmp_path / "cancel-recorded.sqlite"
    run_id = crash_at(database, scenario, event)
    before, _, _ = read_run(database, run_id)
    calls_before, effects_before = evidence(database)
    done = resume(database, scenario, run_id, cancel=True)
    assert done["state"] == "cancelled" and done["result"] is None
    run, events, budget = read_run(database, run_id)
    assert len(run["actions"]) == len(before["actions"])
    assert all(action["status"] == "completed" for action in run["actions"])
    assert budget == {"limit": 12, "held": 0, "spent": expected_cost}
    assert evidence(database) == (calls_before, effects_before)
    if event == "tool_receipt_recorded":
        tool = next(action for action in run["actions"] if action["kind"] == "tool")
        assert tool["result"] == effects_before[0]
        adoption_pair(events, "tool_receipt_recorded", "tool_result_committed", tool["id"])
    assert not any(item.kind == "run_succeeded" for item in events)
    with create_engine(database, scenario) as engine:
        snapshot = engine.status(run_id)
        assert json.loads(json.dumps(asdict(snapshot))) == done


@pytest.mark.parametrize(
    "event,scenario,expected_cost",
    [
        ("model_response_recorded", "final", 2),
        ("model_response_recorded", "queryable_write", 2),
        ("tool_receipt_recorded", "queryable_write", 5),
    ],
)
def test_cancel_in_receiver_commit_window_adopts_evidence_without_followup(
    tmp_path, event, scenario, expected_cost
):
    database = tmp_path / "cancel-between-commits.sqlite"
    stopped = worker(database, scenario, "--trigger-event", event, "--trigger-mode", "cancel")
    assert stopped.returncode == 0, stopped.stderr
    done = json.loads(stopped.stdout)
    assert done["state"] == "cancelled" and done["result"] is None
    run, events, budget = read_run(database, done["run_id"])
    assert all(action["status"] == "completed" for action in run["actions"])
    assert budget == {"limit": 12, "held": 0, "spent": expected_cost}
    calls, results = evidence(database)
    assert calls["model"] == 1 and calls["reconciler"] == 0
    if event == "model_response_recorded":
        assert len(run["actions"]) == 1
        assert calls["handler"] == 0 and results == []
        adoption_pair(
            events, "model_response_recorded", "decision_adopted", run["actions"][0]["id"]
        )
    else:
        assert len(run["actions"]) == 2 and calls["handler"] == 1 and len(results) == 1
        tool = next(action for action in run["actions"] if action["kind"] == "tool")
        assert tool["result"] == results[0]
        adoption_pair(events, "tool_receipt_recorded", "tool_result_committed", tool["id"])
    assert not any(event.kind == "run_succeeded" for event in events)
