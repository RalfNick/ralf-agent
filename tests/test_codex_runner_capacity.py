"""Actual private-root exclusion survives actor death and uncertain native effects."""

import asyncio
import importlib
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from relf_agent.errors import DefinitionMismatch, RuntimeClosed, ValidationError

DISPATCH = "a" * 64
RUNNER = "b" * 64
GENERATION = "c" * 32


def capacity_type():
    name = "relf_agent.codex_runner_capacity"
    assert importlib.util.find_spec(name) is not None, "RootCapacity is not implemented"
    return importlib.import_module(name).RootCapacity


def pin(root):
    info = root.stat()
    return {"path": str(root), "device": info.st_dev, "inode": info.st_ino}


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "runner"
    path.mkdir(mode=0o700)
    return path.resolve()


def slot(root, **changes):
    arguments = {
        "root_pin": pin(root),
        "dispatch_digest": DISPATCH,
        "runner_digest": RUNNER,
        "generation": GENERATION,
    }
    arguments.update(changes)
    return capacity_type()(root, **arguments)


def fence(**changes):
    proof = {
        "dispatch_digest": DISPATCH,
        "runner_digest": RUNNER,
        "generation": GENERATION,
        "container_id": "d" * 64,
        "stopped": True,
        "fenced": True,
        "retired": True,
        "container_present": False,
        "pid": 0,
    }
    proof.update(changes)
    return proof


def test_root_domain_excludes_different_dispatch_and_runner_until_original_release(root):
    holder, waiter = slot(root), slot(root, dispatch_digest="e" * 64, runner_digest="f" * 64)
    try:
        claim = holder.try_acquire()
        assert claim["recovery_only"] is False
        assert waiter.try_acquire() is None
        claim["token"] = "0" * 32
        assert holder.claim["token"] != claim["token"]
        holder.release(holder.claim["token"], definitely_undispatched=True)
        assert waiter.try_acquire() is not None
    finally:
        holder.close()
        waiter.close()


def test_different_private_roots_admit_independently(root, tmp_path):
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    first, second = slot(root), slot(other.resolve())
    try:
        assert first.try_acquire() is not None
        assert second.try_acquire() is not None
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("native", [False, True])
def test_close_keeps_obligation_and_only_same_original_can_recover(root, native):
    holder = slot(root)
    claim = holder.try_acquire()
    if native:
        holder.mark_native_intent(claim["token"])
    holder.close()
    foreign = slot(root, generation="e" * 32)
    original = slot(root)
    try:
        assert foreign.try_acquire() is None
        with pytest.raises(DefinitionMismatch):
            foreign.try_acquire(recovery=True)
        assert original.try_acquire() is None
        recovered = original.try_acquire(recovery=True)
        assert recovered["token"] == claim["token"]
        assert recovered["recovery_only"] is True
        with pytest.raises(DefinitionMismatch):
            original.mark_native_intent(recovered["token"])
        if native:
            original.release(recovered["token"], fenced_receipt=fence())
        else:
            original.release(recovered["token"], definitely_undispatched=True)
        assert foreign.try_acquire() is not None
    finally:
        foreign.close()
        original.close()


def test_recovery_on_empty_root_never_creates_original_business_claim(root):
    control = slot(root)
    try:
        assert control.try_acquire(recovery=True) is None
        assert control.claim is None
        assert control.try_acquire() is not None
    finally:
        control.close()


def test_absent_original_control_leaves_foreign_obligation_untouched(root):
    holder = slot(root)
    claim = holder.try_acquire()
    holder.mark_native_intent(claim["token"])
    waiter = slot(root, dispatch_digest="e" * 64)
    record = root / ".coding-capacity.json"
    before = record.read_bytes()
    try:
        assert waiter.try_acquire(recovery=True, absent_original_ok=True) is None
        assert holder.claim["token"] == claim["token"]
        holder.close()
        assert waiter.try_acquire(recovery=True, absent_original_ok=True) is None
        assert waiter.claim is None
        assert record.read_bytes() == before
        with pytest.raises(DefinitionMismatch):
            waiter.try_acquire(recovery=True)
        assert waiter.try_acquire() is None
    finally:
        holder.close()
        waiter.close()


def test_absent_original_control_can_only_recover_its_own_existing_claim(root):
    holder = slot(root)
    claim = holder.try_acquire()
    holder.close()
    original = slot(root)
    try:
        recovered = original.try_acquire(recovery=True, absent_original_ok=True)
        assert recovered["token"] == claim["token"]
        assert recovered["recovery_only"] is True
        original.release(recovered["token"], definitely_undispatched=True)
        assert original.try_acquire(recovery=True, absent_original_ok=True) is None
    finally:
        original.close()


@pytest.mark.parametrize(
    "arguments",
    [
        {"absent_original_ok": True},
        {"recovery": True, "absent_original_ok": 1},
        {"recovery": True, "absent_original_ok": None},
        {"recovery": True, "absent_original_ok": "true"},
    ],
)
def test_absent_original_flag_requires_explicit_control_mode_before_any_files(root, arguments):
    holder = slot(root)
    try:
        with pytest.raises(ValidationError):
            holder.try_acquire(**arguments)
        assert list(root.iterdir()) == []
    finally:
        holder.close()


@pytest.mark.parametrize("bad", ["0" * 32, True, None, "short"])
def test_stale_token_cannot_mark_or_release_owner(root, bad):
    holder = slot(root)
    try:
        claim = holder.try_acquire()
        with pytest.raises(DefinitionMismatch):
            holder.mark_native_intent(bad)
        with pytest.raises(DefinitionMismatch):
            holder.release(bad, definitely_undispatched=True)
        assert holder.claim["token"] == claim["token"]
        holder.release(claim["token"], definitely_undispatched=True)
        newer = holder.try_acquire()
        assert newer["token"] != claim["token"]
        with pytest.raises(DefinitionMismatch):
            holder.release(claim["token"], definitely_undispatched=True)
    finally:
        holder.close()


def test_native_intent_cannot_release_as_undispatched_even_after_close(root):
    holder = slot(root)
    claim = holder.try_acquire()
    holder.mark_native_intent(claim["token"])
    holder.mark_native_intent(claim["token"])
    with pytest.raises(DefinitionMismatch):
        holder.release(claim["token"], definitely_undispatched=True)
    holder.close()
    recovery = slot(root)
    try:
        recovery.try_acquire(recovery=True)
        with pytest.raises(DefinitionMismatch):
            recovery.release(claim["token"], definitely_undispatched=True)
        recovery.release(claim["token"], fenced_receipt=fence())
    finally:
        recovery.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"dispatch_digest": "e" * 64},
        {"runner_digest": "e" * 64},
        {"generation": "e" * 32},
        {"container_id": "short"},
        {"stopped": 1},
        {"fenced": False},
        {"retired": False},
        {"container_present": 0},
        {"pid": False},
        {"pid": 1},
        {"extra": True},
    ],
)
def test_foreign_or_incomplete_fence_cannot_clear_obligation(root, changes):
    holder = slot(root)
    try:
        claim = holder.try_acquire()
        holder.mark_native_intent(claim["token"])
        with pytest.raises(DefinitionMismatch):
            holder.release(claim["token"], fenced_receipt=fence(**changes))
        assert holder.claim["phase"] == "native_intent"
        holder.release(claim["token"], fenced_receipt=fence())
        assert holder.claim is None
    finally:
        holder.close()


def child_owner(root):
    script = """import json,sys
from relf_agent.codex_runner_capacity import RootCapacity
c=RootCapacity(sys.argv[1],root_pin=json.loads(sys.argv[2]),dispatch_digest='a'*64,runner_digest='b'*64,generation='c'*32)
claim=c.try_acquire(); c.mark_native_intent(claim['token'])
print(json.dumps(claim),flush=True)
sys.stdin.readline()
c.release(claim['token'],fenced_receipt=dict(dispatch_digest='a'*64,runner_digest='b'*64,generation='c'*32,container_id='d'*64,stopped=True,fenced=True,retired=True,container_present=False,pid=0))
c.close()
"""
    return subprocess.Popen(
        [sys.executable, "-c", script, str(root), json.dumps(pin(root))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )


@pytest.mark.parametrize("kill", [False, True])
def test_real_process_holder_exit_is_not_itself_release_evidence(root, kill):
    capacity_type()
    child = child_owner(root)
    waiter = slot(root, dispatch_digest="e" * 64)
    original = slot(root)
    try:
        claim = json.loads(child.stdout.readline())
        assert waiter.try_acquire() is None
        assert original.try_acquire(recovery=True) is None
        if kill:
            os.kill(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
            assert waiter.try_acquire() is None
            recovered = original.try_acquire(recovery=True)
            assert recovered["token"] == claim["token"]
            original.release(recovered["token"], fenced_receipt=fence())
        else:
            _, error = child.communicate("release\n", timeout=5)
            assert child.returncode == 0, error
        assert waiter.try_acquire() is not None
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)
        waiter.close()
        original.close()


def test_cancelled_waiter_cannot_clear_live_or_persisted_original(root):
    holder, waiter = slot(root), slot(root, dispatch_digest="e" * 64)
    claim = holder.try_acquire()

    async def scenario():
        entered = asyncio.Event()

        async def wait():
            try:
                assert waiter.try_acquire() is None
                entered.set()
                await asyncio.Event().wait()
            finally:
                waiter.close()

        task = asyncio.create_task(wait())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
        assert holder.claim["token"] == claim["token"]
        holder.close()
        later = slot(root, dispatch_digest="e" * 64)
        try:
            assert later.try_acquire() is None
        finally:
            later.close()
    finally:
        holder.close()
        waiter.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"dispatch_digest": True},
        {"runner_digest": "short"},
        {"generation": "g" * 32},
        {"root_pin": {"path": "/foreign", "device": 1, "inode": 1}},
    ],
)
def test_invalid_binding_rejected_before_any_root_files(root, changes):
    with pytest.raises((DefinitionMismatch, ValidationError)):
        slot(root, **changes)
    assert list(root.iterdir()) == []


def test_root_alias_permissions_or_replacement_cannot_acquire(root, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises((DefinitionMismatch, ValidationError)):
        capacity_type()(
            alias,
            root_pin=pin(root),
            dispatch_digest=DISPATCH,
            runner_digest=RUNNER,
            generation=GENERATION,
        )
    original_pin = pin(root)
    holder = slot(root)
    root.rename(tmp_path / "old-root")
    root.mkdir(mode=0o700)
    try:
        with pytest.raises(DefinitionMismatch):
            holder.try_acquire()
        with pytest.raises(DefinitionMismatch):
            slot(root, root_pin=original_pin)
        root.chmod(0o755)
        with pytest.raises((DefinitionMismatch, ValidationError)):
            slot(root)
    finally:
        holder.close()


@pytest.mark.parametrize("name", [".coding-capacity.lock", ".coding-capacity.json"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "directory"])
def test_unsafe_root_files_fail_closed_without_touching_target(root, tmp_path, name, kind):
    target = tmp_path / "target"
    target.write_text("protected")
    target.chmod(0o600)
    path = root / name
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, path)
    elif kind == "public":
        path.write_text("{}")
        path.chmod(0o644)
    else:
        path.mkdir(mode=0o700)
    holder = slot(root)
    try:
        with pytest.raises(DefinitionMismatch):
            holder.try_acquire()
        assert target.read_text() == "protected"
    finally:
        holder.close()


def test_lock_replacement_rejected_during_ownership_and_after_cleared_tombstone(root):
    holder = slot(root)
    try:
        claim = holder.try_acquire()
        lock = root / ".coding-capacity.lock"
        lock.rename(root / "old.lock")
        lock.touch(mode=0o600)
        with pytest.raises(DefinitionMismatch):
            holder.mark_native_intent(claim["token"])
    finally:
        holder.close()
    later = slot(root)
    try:
        with pytest.raises(DefinitionMismatch):
            later.try_acquire(recovery=True)
    finally:
        later.close()


def test_closed_instance_cannot_reenter_business(root):
    holder = slot(root)
    holder.close()
    holder.close()
    with pytest.raises(RuntimeClosed):
        holder.try_acquire()


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"dispatch_digest": "e" * 64},
        {"runner_digest": "e" * 64},
        {"generation": "e" * 32},
        {"namespace_absent": 1},
        {"metadata_present": True},
        {"container_present": True},
        {"process_present": True},
        {"unexpected": None},
    ],
)
def test_namespace_absence_requires_complete_original_mechanical_proof(root, changes):
    holder = slot(root)
    try:
        claim = holder.try_acquire()
        holder.mark_native_intent(claim["token"])
        proof = {
            "dispatch_digest": DISPATCH,
            "runner_digest": RUNNER,
            "generation": GENERATION,
            "namespace_absent": True,
            "metadata_present": False,
            "container_present": False,
            "process_present": False,
        }
        proof.update(changes)
        if changes:
            with pytest.raises(DefinitionMismatch):
                holder.release(claim["token"], namespace_absent_proof=proof)
            assert holder.claim is not None
        else:
            holder.release(claim["token"], namespace_absent_proof=proof)
            assert holder.claim is None
    finally:
        holder.close()


def test_record_is_bounded_exact_and_private(root):
    holder = slot(root)
    try:
        holder.try_acquire()
        record = root / ".coding-capacity.json"
        assert stat.S_IMODE(record.stat().st_mode) == 0o600
        assert record.stat().st_nlink == 1
        holder.close()
        content = json.loads(record.read_text())
        content["unexpected"] = "x"
        record.write_text(json.dumps(content))
        later = slot(root)
        try:
            with pytest.raises(DefinitionMismatch):
                later.try_acquire(recovery=True)
        finally:
            later.close()
        record.write_text("x" * 5000)
        later = slot(root)
        try:
            with pytest.raises(DefinitionMismatch):
                later.try_acquire(recovery=True)
        finally:
            later.close()
    finally:
        holder.close()


@pytest.mark.parametrize("native", [False, True])
def test_lost_record_cannot_be_recreated_as_empty_capacity(root, native):
    holder = slot(root)
    claim = holder.try_acquire()
    if native:
        holder.mark_native_intent(claim["token"])
    (root / ".coding-capacity.json").unlink()
    try:
        with pytest.raises(DefinitionMismatch):
            holder.try_acquire()
    finally:
        holder.close()
    later = slot(root, dispatch_digest="e" * 64)
    try:
        with pytest.raises(DefinitionMismatch):
            later.try_acquire()
    finally:
        later.close()


def test_cleared_tombstone_still_pins_original_lock_inode(root):
    holder = slot(root)
    claim = holder.try_acquire()
    holder.release(claim["token"], definitely_undispatched=True)
    holder.close()
    lock = root / ".coding-capacity.lock"
    lock.rename(root / "old.lock")
    lock.touch(mode=0o600)
    later = slot(root)
    try:
        with pytest.raises(DefinitionMismatch):
            later.try_acquire()
    finally:
        later.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"token": "e" * 32},
        {"generation": "e" * 32},
        {"phase": "cleared"},
        {"phase": 1},
        {"dispatch_digest": True},
    ],
)
def test_existing_owner_never_overwrites_changed_obligation(root, changes):
    holder = slot(root)
    claim = holder.try_acquire()
    record = root / ".coding-capacity.json"
    content = json.loads(record.read_text())
    content["obligation"].update(changes)
    record.write_text(json.dumps(content))
    before = record.read_bytes()
    try:
        with pytest.raises(DefinitionMismatch):
            holder.mark_native_intent(claim["token"])
        assert record.read_bytes() == before
    finally:
        holder.close()


@pytest.mark.parametrize("directory", [False, True])
def test_failed_native_intent_fsync_never_exposes_start_permission(root, monkeypatch, directory):
    holder = slot(root)
    claim = holder.try_acquire()
    real_fsync = os.fsync

    def fail_selected(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode) is directory:
            raise OSError("synthetic disk failure")
        real_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_selected)
        with pytest.raises(OSError):
            holder.mark_native_intent(claim["token"])
    holder.close()
    foreign, original = slot(root, dispatch_digest="e" * 64), slot(root)
    try:
        assert foreign.try_acquire() is None
        recovered = original.try_acquire(recovery=True)
        if directory:
            assert recovered["phase"] == "native_intent"
            with pytest.raises(DefinitionMismatch):
                original.release(recovered["token"], definitely_undispatched=True)
            original.release(recovered["token"], fenced_receipt=fence())
        else:
            assert recovered["phase"] == "acquired"
            original.release(recovered["token"], definitely_undispatched=True)
        assert not list(root.glob(".coding-capacity-write-*"))
    finally:
        foreign.close()
        original.close()


def test_initial_record_fsync_failure_does_not_return_business_claim(root, monkeypatch):
    holder = slot(root)
    real_fsync = os.fsync

    def failed_record(fd):
        if os.fstat(fd).st_size:
            raise OSError("synthetic disk failure")
        real_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", failed_record)
        with pytest.raises(DefinitionMismatch):
            holder.try_acquire()
    assert holder.claim is None
    holder.close()
    later = slot(root)
    try:
        with pytest.raises(DefinitionMismatch):
            later.try_acquire()
    finally:
        later.close()


def test_duplicate_json_keys_are_rejected_without_repair(root):
    holder = slot(root)
    holder.try_acquire()
    holder.close()
    record = root / ".coding-capacity.json"
    text = record.read_text()
    record.write_text(text[:-1] + ',"version":1}')
    later = slot(root)
    try:
        with pytest.raises(DefinitionMismatch):
            later.try_acquire(recovery=True)
    finally:
        later.close()


@pytest.mark.parametrize("section", ["root", "lock"])
@pytest.mark.parametrize("field", ["device", "inode"])
def test_persistent_physical_pins_reject_equal_float_values(root, section, field):
    holder = slot(root)
    holder.try_acquire()
    holder.close()
    record = root / ".coding-capacity.json"
    data = json.loads(record.read_text())
    data[section][field] = float(data[section][field])
    record.write_text(json.dumps(data))
    later = slot(root)
    try:
        with pytest.raises(DefinitionMismatch):
            later.try_acquire(recovery=True)
    finally:
        later.close()


def test_corrupted_lock_payload_cannot_become_a_new_mutex(root):
    original = slot(root)
    claim = original.try_acquire()
    original.release(claim["token"], definitely_undispatched=True)
    original.close()
    lock = root / ".coding-capacity.lock"
    lock.write_text("unexpected payload")
    lock.chmod(0o600)
    holder = slot(root)
    try:
        with pytest.raises(DefinitionMismatch):
            holder.try_acquire()
        assert lock.read_text() == "unexpected payload"
    finally:
        holder.close()


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"definitely_undispatched": True, "fenced_receipt": fence()},
        {"definitely_undispatched": 1},
        {"fenced_receipt": {}},
    ],
)
def test_release_requires_one_explicit_complete_evidence_kind(root, arguments):
    holder = slot(root)
    try:
        claim = holder.try_acquire()
        with pytest.raises(DefinitionMismatch):
            holder.release(claim["token"], **arguments)
        assert holder.claim is not None
    finally:
        holder.close()
