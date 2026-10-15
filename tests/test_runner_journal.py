"""Native startup evidence survives restarts without granting repeated starts."""

import copy
import json
import os
import signal
import subprocess
import sys

import pytest

from ralf_agent.errors import (
    CoordinatorBusy,
    DefinitionMismatch,
    IdempotencyConflict,
    RuntimeClosed,
    ValidationError,
)
from ralf_agent.runner_journal import RunnerJournal
from ralf_agent.types import Scope

IDENTITY = {
    "adapter": "codex/1",
    "profile": "coding/1",
    "external": "1",
    "schema": "abc",
    "environment": {"digest": "env"},
}
BINDING = {
    "run_id": "run",
    "action_id": "action",
    "attempt_id": "first",
    "operation_digest": "op",
    "release_digest": "release",
    "profile": "coding/1",
    "environment": "env",
    "native_epoch": "native-1",
}
SCOPE = Scope("workspace", "principal")


def journal(path, **kwargs):
    return RunnerJournal(str(path), identity=copy.deepcopy(IDENTITY), **kwargs)


def thread(j):
    j.begin(SCOPE, "effect", BINDING)
    j.mark_thread_submitted(SCOPE, "effect", binding=BINDING)
    return j.record_thread(
        SCOPE, "effect", binding=BINDING, thread_id="thread", process_epoch="process"
    )


def turn(j):
    thread(j)
    j.mark_turn_submitted(SCOPE, "effect", binding=BINDING)
    return j.record_turn(SCOPE, "effect", binding=BINDING, turn_id="turn")


def test_start_permissions_are_committed_once_and_receipts_remain_detached(tmp_path):
    path = tmp_path / "native.sqlite"
    j = journal(path)
    try:
        assert j.begin(SCOPE, "effect", BINDING)["execute"] is True
        assert j.begin(SCOPE, "effect", BINDING)["execute"] is False
        first = j.mark_thread_submitted(SCOPE, "effect", binding=BINDING)
        assert first["stage"] == "thread_submitted"
        assert first["thread_id"] is None
        assert first["execute"] is True
        assert j.mark_thread_submitted(SCOPE, "effect", binding=BINDING)["execute"] is False
        thread(j)
        assert j.mark_turn_submitted(SCOPE, "effect", binding=BINDING)["execute"] is True
        assert j.mark_turn_submitted(SCOPE, "effect", binding=BINDING)["execute"] is False
        receipt = j.record_turn(SCOPE, "effect", binding=BINDING, turn_id="turn")
        receipt["binding"]["run_id"] = "mutated"
        assert j.lookup(SCOPE, "effect", binding=BINDING)["binding"]["run_id"] == "run"
    finally:
        j.close()
    reopened = journal(path)
    try:
        assert reopened.begin(SCOPE, "effect", BINDING)["execute"] is False
        assert reopened.lookup(SCOPE, "effect", binding=BINDING)["stage"] == "turn_confirmed"
        assert reopened.mark_thread_submitted(SCOPE, "effect", binding=BINDING)["execute"] is False
        assert reopened.mark_turn_submitted(SCOPE, "effect", binding=BINDING)["execute"] is False
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "stage", ["intent", "thread_submitted", "thread_confirmed", "turn_submitted", "turn_confirmed"]
)
def test_process_kill_preserves_every_committed_startup_stage(tmp_path, stage):
    path = tmp_path / "native.sqlite"
    script = """import json,sys,time
from ralf_agent.runner_journal import RunnerJournal
from ralf_agent.types import Scope
j=RunnerJournal(sys.argv[1],identity=json.loads(sys.argv[2]))
s=Scope('workspace','principal'); b=json.loads(sys.argv[3]); stage=sys.argv[4]
j.begin(s,'effect',b)
if stage!='intent': j.mark_thread_submitted(s,'effect',binding=b)
if stage in ('thread_confirmed','turn_submitted','turn_confirmed'): j.record_thread(s,'effect',binding=b,thread_id='thread',process_epoch='process')
if stage in ('turn_submitted','turn_confirmed'): j.mark_turn_submitted(s,'effect',binding=b)
if stage=='turn_confirmed': j.record_turn(s,'effect',binding=b,turn_id='turn')
print('committed',flush=True)
time.sleep(60)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(path), json.dumps(IDENTITY), json.dumps(BINDING), stage],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "committed"
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
        j = journal(path)
        try:
            record = j.begin(SCOPE, "effect", BINDING)
            assert record["stage"] == stage
            assert record["execute"] is False
            assert record["turn_id"] == ("turn" if stage == "turn_confirmed" else None)
            if stage != "intent":
                assert j.mark_thread_submitted(SCOPE, "effect", binding=BINDING)["execute"] is False
            if stage in ("turn_submitted", "turn_confirmed"):
                assert j.mark_turn_submitted(SCOPE, "effect", binding=BINDING)["execute"] is False
        finally:
            j.close()
    finally:
        try:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        finally:
            child.stdout.close()
            child.stderr.close()


def test_second_owner_refused_in_same_and_real_process(tmp_path):
    path = tmp_path / "native.sqlite"
    j = journal(path)
    try:
        with pytest.raises(CoordinatorBusy):
            journal(path)
        script = """import json,sys
from ralf_agent.runner_journal import RunnerJournal
from ralf_agent.errors import CoordinatorBusy
try: j=RunnerJournal(sys.argv[1],identity=json.loads(sys.argv[2]))
except CoordinatorBusy: print('busy')
else: j.close();print('owned')
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(path), json.dumps(IDENTITY)],
            check=True,
            text=True,
            capture_output=True,
        )
        assert result.stdout.strip() == "busy"
    finally:
        j.close()
    journal(path).close()


def test_binding_scope_and_native_receipt_are_immutable(tmp_path):
    j = journal(tmp_path / "native.sqlite")
    try:
        turn(j)
        changed = {**BINDING, "run_id": "other"}
        with pytest.raises(IdempotencyConflict):
            j.begin(SCOPE, "effect", changed)
        with pytest.raises(IdempotencyConflict):
            j.lookup(SCOPE, "effect", binding=changed)
        # Effect keys are scoped: another principal cannot read or mutate this receipt.
        assert j.lookup(Scope("workspace", "other"), "effect", binding=BINDING) is None
        with pytest.raises(ValidationError):
            j.record_turn(Scope("workspace", "other"), "effect", binding=BINDING, turn_id="turn")
        with pytest.raises(IdempotencyConflict):
            j.record_thread(
                SCOPE, "effect", binding=BINDING, thread_id="other", process_epoch="process"
            )
        with pytest.raises(IdempotencyConflict):
            j.record_thread(
                SCOPE, "effect", binding=BINDING, thread_id="thread", process_epoch="other"
            )
        with pytest.raises(IdempotencyConflict):
            j.record_turn(SCOPE, "effect", binding=BINDING, turn_id="other")
        assert (
            j.record_turn(SCOPE, "effect", binding=BINDING, turn_id="turn")["stage"]
            == "turn_confirmed"
        )
    finally:
        j.close()


def test_missing_submission_cannot_manufacture_native_receipts(tmp_path):
    j = journal(tmp_path / "native.sqlite")
    try:
        j.begin(SCOPE, "effect", BINDING)
        with pytest.raises(ValidationError):
            j.record_thread(
                SCOPE, "effect", binding=BINDING, thread_id="thread", process_epoch="process"
            )
        with pytest.raises(ValidationError):
            j.mark_turn_submitted(SCOPE, "effect", binding=BINDING)
        with pytest.raises(ValidationError):
            j.record_turn(SCOPE, "effect", binding=BINDING, turn_id="turn")
        thread(j)
        with pytest.raises(ValidationError):
            j.record_turn(SCOPE, "effect", binding=BINDING, turn_id="turn")
    finally:
        j.close()


def test_cancel_intent_and_ack_never_project_stop_or_reset_start(tmp_path):
    path = tmp_path / "native.sqlite"
    j = journal(path)
    try:
        turn(j)
        cancelled = j.request_cancel(SCOPE, "effect", binding=BINDING)
        assert cancelled["cancel_requested"] is True
        observation = {"kind": "cancel_ack", "native": {}}
        record = j.record_observation(SCOPE, "effect", binding=BINDING, observation=observation)
        observation["native"]["changed"] = True
        assert record["stage"] == "turn_confirmed"
        assert record["observations"] == [{"kind": "cancel_ack", "native": {}}]
        assert "stopped" not in record and "run_state" not in record
        assert (
            j.record_observation(
                SCOPE, "effect", binding=BINDING, observation={"kind": "cancel_ack", "native": {}}
            )["observations"]
            == record["observations"]
        )
    finally:
        j.close()
    j = journal(path)
    try:
        record = j.lookup(SCOPE, "effect", binding=BINDING)
        assert record["cancel_requested"] is True
        assert record["observations"] == [{"kind": "cancel_ack", "native": {}}]
        assert j.begin(SCOPE, "effect", BINDING)["execute"] is False
    finally:
        j.close()


@pytest.mark.parametrize("stage", ["intent", "thread_confirmed"])
def test_cancellation_prevents_new_submission_permissions(tmp_path, stage):
    j = journal(tmp_path / "native.sqlite")
    try:
        j.begin(SCOPE, "effect", BINDING)
        if stage == "thread_confirmed":
            thread(j)
        j.request_cancel(SCOPE, "effect", binding=BINDING)
        with pytest.raises(ValidationError):
            if stage == "intent":
                j.mark_thread_submitted(SCOPE, "effect", binding=BINDING)
            else:
                j.mark_turn_submitted(SCOPE, "effect", binding=BINDING)
        assert j.lookup(SCOPE, "effect", binding=BINDING)["stage"] == stage
    finally:
        j.close()


def test_observations_cannot_claim_a_different_native_handle(tmp_path):
    j = journal(tmp_path / "native.sqlite")
    try:
        turn(j)
        with pytest.raises(IdempotencyConflict):
            j.record_observation(
                SCOPE, "effect", binding=BINDING, observation={"thread_id": "other"}
            )
        with pytest.raises(IdempotencyConflict):
            j.record_observation(SCOPE, "effect", binding=BINDING, observation={"turn_id": "other"})
        assert j.lookup(SCOPE, "effect", binding=BINDING)["observations"] == []
    finally:
        j.close()


@pytest.mark.parametrize("capacity", [True, False, 0, -1, 1.5, 10**100])
def test_invalid_capacity_rejected_before_creating_files(tmp_path, capacity):
    path = tmp_path / "native.sqlite"
    with pytest.raises(ValidationError):
        journal(path, capacity=capacity)
    assert list(tmp_path.iterdir()) == []


def test_capacity_preserves_existing_records(tmp_path):
    j = journal(tmp_path / "native.sqlite", capacity=1)
    try:
        j.begin(SCOPE, "effect", BINDING)
        with pytest.raises(ValidationError):
            j.begin(SCOPE, "next", BINDING)
        assert j.begin(SCOPE, "effect", BINDING)["execute"] is False
        assert j.lookup(SCOPE, "next", binding=BINDING) is None
    finally:
        j.close()


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {1: "coerced"},
        {"bad": float("nan")},
        {"bad": float("inf")},
        {"bad": 10**100},
        {"bad": "x" * 100000},
        {"bad": (1, 2)},
    ],
)
def test_invalid_binding_rejected_without_mutation(tmp_path, bad):
    j = journal(tmp_path / "native.sqlite")
    try:
        with pytest.raises(ValidationError):
            j.begin(SCOPE, "effect", bad)
        assert j.lookup(SCOPE, "effect", binding=BINDING) is None
    finally:
        j.close()


@pytest.mark.parametrize("bad", [True, "", " ", "x" * 1025, "bad\x00id"])
def test_invalid_keys_and_native_ids_rejected_without_mutation(tmp_path, bad):
    j = journal(tmp_path / "native.sqlite")
    try:
        with pytest.raises(ValidationError):
            j.begin(SCOPE, bad, BINDING)
        j.begin(SCOPE, "effect", BINDING)
        j.mark_thread_submitted(SCOPE, "effect", binding=BINDING)
        with pytest.raises(ValidationError):
            j.record_thread(
                SCOPE, "effect", binding=BINDING, thread_id=bad, process_epoch="process"
            )
        assert j.lookup(SCOPE, "effect", binding=BINDING)["stage"] == "thread_submitted"
    finally:
        j.close()


def test_identity_is_detached_and_dependency_drift_refused_on_reopen(tmp_path):
    path = tmp_path / "native.sqlite"
    identity = copy.deepcopy(IDENTITY)
    j = RunnerJournal(str(path), identity=identity)
    original = j.identity
    identity["environment"]["digest"] = "changed"
    detached = j.identity
    detached["dependencies"]["environment"]["digest"] = "changed"
    assert j.identity == original
    j.close()
    with pytest.raises(DefinitionMismatch):
        RunnerJournal(str(path), identity=identity)
    j = journal(path)
    try:
        assert j.identity == original
    finally:
        j.close()


@pytest.mark.parametrize("alias", ["symlink", "hardlink", "parent_symlink", "sidecar_symlink"])
def test_aliases_rejected_before_sqlite_can_touch_unsafe_files(tmp_path, alias):
    target = tmp_path / "target"
    target.write_text("untouched")
    path = tmp_path / "native.sqlite"
    if alias == "symlink":
        path.symlink_to(target)
    elif alias == "hardlink":
        os.link(target, path)
    elif alias == "parent_symlink":
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
        path = tmp_path / "alias/native.sqlite"
    else:
        (tmp_path / "native.sqlite-wal").symlink_to(target)
    with pytest.raises(ValidationError):
        journal(path)
    assert target.read_text() == "untouched"


@pytest.mark.parametrize("which", ["database", "owner", "directory", "hardlink", "metadata"])
def test_live_physical_and_dataset_identity_drift_rejected_before_mutation(tmp_path, which):
    directory = tmp_path / "owned"
    directory.mkdir()
    path = directory / "native.sqlite"
    j = journal(path)
    try:
        j.begin(SCOPE, "effect", BINDING)
        if which == "directory":
            directory.rename(tmp_path / "old")
            directory.mkdir()
        elif which == "hardlink":
            os.link(path, directory / "alias")
        elif which == "metadata":
            j.conn.execute("UPDATE runner_metadata SET value='{}'")
        else:
            changed = path if which == "database" else directory / "native.sqlite.owner"
            changed.rename(directory / "old")
            changed.write_bytes(b"")
        with pytest.raises(DefinitionMismatch):
            j.begin(SCOPE, "next", BINDING)
    finally:
        j.close()


def test_observation_accumulation_is_bounded_without_losing_existing_evidence(tmp_path):
    j = journal(tmp_path / "native.sqlite")
    try:
        turn(j)
        for n in range(1000):
            j.record_observation(SCOPE, "effect", binding=BINDING, observation={"sequence": n})
        with pytest.raises(ValidationError):
            j.record_observation(SCOPE, "effect", binding=BINDING, observation={"sequence": 1000})
        assert len(j.lookup(SCOPE, "effect", binding=BINDING)["observations"]) == 1000
        assert (
            len(
                j.record_observation(SCOPE, "effect", binding=BINDING, observation={"sequence": 0})[
                    "observations"
                ]
            )
            == 1000
        )
    finally:
        j.close()


def test_failed_close_keeps_ownership_and_disables_methods_until_retry(tmp_path):
    path = tmp_path / "native.sqlite"
    j = journal(path)
    real = j.conn

    class FailedClose:
        def close(self):
            raise RuntimeError("close failed")

    j.conn = FailedClose()
    with pytest.raises(RuntimeError, match="close failed"):
        j.close()
    with pytest.raises(RuntimeClosed):
        j.begin(SCOPE, "effect", BINDING)
    with pytest.raises(CoordinatorBusy):
        journal(path)
    j.conn = real
    j.close()
    journal(path).close()
    with pytest.raises(RuntimeClosed):
        j.lookup(SCOPE, "effect", binding=BINDING)


def test_total_observation_bytes_are_bounded_and_duplicate_still_reused(tmp_path):
    j = journal(tmp_path / "native.sqlite")
    try:
        turn(j)
        for n in range(16):
            j.record_observation(
                SCOPE,
                "effect",
                binding=BINDING,
                observation={"sequence": n, "evidence": "x" * 65000},
            )
        with pytest.raises(ValidationError):
            j.record_observation(
                SCOPE,
                "effect",
                binding=BINDING,
                observation={"sequence": 16, "evidence": "x" * 65000},
            )
        assert len(j.lookup(SCOPE, "effect", binding=BINDING)["observations"]) == 16
        assert (
            len(
                j.record_observation(
                    SCOPE,
                    "effect",
                    binding=BINDING,
                    observation={"sequence": 0, "evidence": "x" * 65000},
                )["observations"]
            )
            == 16
        )
    finally:
        j.close()


@pytest.mark.parametrize(
    "bad", [None, {}, {"bad": float("nan")}, {"bad": 10**100}, {"bad": "x" * 100000}]
)
def test_invalid_identity_rejected_before_creating_files(tmp_path, bad):
    with pytest.raises(ValidationError):
        RunnerJournal(str(tmp_path / "native.sqlite"), identity=bad)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", ["relative.sqlite", ":memory:", "/tmp/../tmp/native.sqlite"])
def test_noncanonical_or_nonpersistent_path_rejected_before_creating_files(tmp_path, bad):
    with pytest.raises(ValidationError):
        journal(bad)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "name", ["native.sqlite.owner", "native.sqlite-shm", "native.sqlite-journal"]
)
def test_owner_and_sidecar_aliases_rejected_without_touching_targets(tmp_path, name):
    target = tmp_path / "target"
    target.write_text("untouched")
    (tmp_path / name).symlink_to(target)
    with pytest.raises(ValidationError):
        journal(tmp_path / "native.sqlite")
    assert target.read_text() == "untouched"


def test_native_receipt_can_arrive_after_cancel_intent_without_reopening_permission(tmp_path):
    j = journal(tmp_path / "native.sqlite")
    try:
        thread(j)
        j.mark_turn_submitted(SCOPE, "effect", binding=BINDING)
        j.request_cancel(SCOPE, "effect", binding=BINDING)
        receipt = j.record_turn(SCOPE, "effect", binding=BINDING, turn_id="turn")
        assert receipt["cancel_requested"] is True
        assert receipt["stage"] == "turn_confirmed"
        assert j.mark_turn_submitted(SCOPE, "effect", binding=BINDING)["execute"] is False
    finally:
        j.close()


def test_copied_database_cannot_become_a_new_identity_at_another_path(tmp_path):
    import shutil

    path = tmp_path / "native.sqlite"
    j = journal(path)
    turn(j)
    j.close()
    copied = tmp_path / "copied.sqlite"
    shutil.copyfile(path, copied)
    with pytest.raises(DefinitionMismatch):
        journal(copied)
    j = journal(path)
    try:
        assert j.lookup(SCOPE, "effect", binding=BINDING)["turn_id"] == "turn"
    finally:
        j.close()


@pytest.mark.parametrize(
    "bad", [[], {}, {"native": float("nan")}, {"native": "x" * 100000}, {"native": 10**100}]
)
def test_invalid_observation_preserves_native_receipt(tmp_path, bad):
    j = journal(tmp_path / "native.sqlite")
    try:
        turn(j)
        with pytest.raises(ValidationError):
            j.record_observation(SCOPE, "effect", binding=BINDING, observation=bad)
        record = j.lookup(SCOPE, "effect", binding=BINDING)
        assert record["observations"] == []
        assert record["stage"] == "turn_confirmed"
    finally:
        j.close()


def test_inconsistent_persisted_receipt_refused_instead_of_granting_start(tmp_path):
    j = journal(tmp_path / "native.sqlite")
    try:
        turn(j)
        record = j.lookup(SCOPE, "effect", binding=BINDING)
        record["stage"] = "intent"
        j.conn.execute("UPDATE runner_effects SET record=?", (json.dumps(record),))
        with pytest.raises(DefinitionMismatch):
            j.mark_thread_submitted(SCOPE, "effect", binding=BINDING)
    finally:
        j.close()


def test_competing_workers_get_only_one_thread_and_turn_submission_permission(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    j = journal(tmp_path / "native.sqlite")
    try:
        j.begin(SCOPE, "effect", BINDING)
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(
                workers.map(
                    lambda _: j.mark_thread_submitted(SCOPE, "effect", binding=BINDING), range(16)
                )
            )
        assert sum(record["execute"] for record in results) == 1
        j.record_thread(
            SCOPE, "effect", binding=BINDING, thread_id="thread", process_epoch="process"
        )
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(
                workers.map(
                    lambda _: j.mark_turn_submitted(SCOPE, "effect", binding=BINDING), range(16)
                )
            )
        assert sum(record["execute"] for record in results) == 1
        assert j.lookup(SCOPE, "effect", binding=BINDING)["stage"] == "turn_submitted"
    finally:
        j.close()


def test_unknown_native_ids_cannot_be_stored_as_a_receipt_reference(tmp_path):
    j = journal(tmp_path / "native.sqlite")
    try:
        j.begin(SCOPE, "effect", BINDING)
        with pytest.raises(ValidationError):
            j.record_observation(SCOPE, "effect", binding=BINDING, observation={"thread_id": None})
        assert j.lookup(SCOPE, "effect", binding=BINDING)["observations"] == []
    finally:
        j.close()
