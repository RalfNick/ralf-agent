"""Actual POSIX file CAS, exclusive writer ownership and durable receipts."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

import ralf_agent as r
from ralf_agent.errors import (
    CoordinatorBusy,
    DefinitionMismatch,
    IdempotencyConflict,
    ValidationError,
)
from ralf_agent.workspace import WorkspaceError

SCOPE = r.Scope()


def writer(root, **options):
    cls = getattr(r, "FileSystemWritableWorkspace", None)
    assert cls is not None, "public FileSystemWritableWorkspace is missing"
    return cls(root, version="1", **options)


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "files"
    path.mkdir()
    (path / "note").write_text("old")
    (path / "directory").mkdir()
    return path


def test_durable_create_cas_reopen_and_historical_receipt_without_replacement(root):
    port = writer(root)
    identity = port.identity
    original = port.read_text(SCOPE, "note")["version"]
    first = port.write_text(SCOPE, "note", "new", expected_version=original, effect_key="k")
    assert port.read_text(SCOPE, "note")["version"] == first["file_version"]
    port.close()
    resumed = writer(root)
    try:
        assert resumed.identity == identity
        receipt = resumed.query_write(SCOPE, "k")
        assert receipt == first
        (root / "note").write_text("later external content")
        version = resumed.stat(SCOPE, "note")["version"]
        assert (
            resumed.write_text(SCOPE, "note", "new", expected_version=original, effect_key="k")
            == first
        )
        assert resumed.stat(SCOPE, "note")["version"] == version
        assert (root / "note").read_text() == "later external content"
        receipt["scope"]["workspace"] = "wrong"
        assert resumed.query_write(SCOPE, "k") == first
    finally:
        resumed.close()


def test_same_root_lexical_alias_cannot_acquire_second_writer_lease(root):
    port = writer(root)
    try:
        for address in (root, str(root / "."), root.parent / "files/../files"):
            with pytest.raises(CoordinatorBusy):
                writer(address)
        readonly = r.FileSystemWorkspace(root, version="1")
        try:
            assert readonly.read_text(SCOPE, "note")["text"] == "old"
        finally:
            readonly.close()
    finally:
        port.close()
    replacement = writer(root)
    replacement.close()


def test_request_conflict_capacity_and_cas_do_not_mutate_target(root):
    port = writer(root, capacity=1, max_bytes=4)
    try:
        first = port.write_text(SCOPE, "new", "A", expected_version=None, effect_key="k")
        with pytest.raises(IdempotencyConflict):
            port.write_text(
                SCOPE, "new", "B", expected_version=first["file_version"], effect_key="k"
            )
        with pytest.raises(WorkspaceError):
            port.write_text(SCOPE, "other", "A", expected_version=None, effect_key="other")
        assert not (root / "other").exists()
        assert port.query_write(SCOPE, "other") is None
        with pytest.raises(ValidationError):
            port.write_text(SCOPE, "note", "too long", expected_version=None, effect_key="invalid")
        assert (root / "note").read_text() == "old"
        assert (root / "new").read_text() == "A"
    finally:
        port.close()


def test_cas_failure_and_missing_parent_leave_no_effect_receipt(root):
    port = writer(root)
    try:
        for path, version in (("note", None), ("note", "0" * 64), ("missing/child", None)):
            with pytest.raises(WorkspaceError):
                port.write_text(SCOPE, path, "A", expected_version=version, effect_key="k")
        assert port.query_write(SCOPE, "k") is None
        assert (root / "note").read_text() == "old"
        created = port.write_text(
            SCOPE, "directory/empty", "", expected_version=None, effect_key="empty"
        )
        assert created["bytes"] == 0
        assert (root / "directory/empty").read_text() == ""
    finally:
        port.close()


def test_root_address_movement_is_refused_before_new_file_effect(root):
    port = writer(root)
    moved = root.with_name("moved")
    root.rename(moved)
    root.mkdir()
    try:
        with pytest.raises(DefinitionMismatch):
            port.write_text(SCOPE, "new", "A", expected_version=None, effect_key="k")
        assert not (root / "new").exists() and not (moved / "new").exists()
    finally:
        port.close()


@pytest.mark.parametrize(
    "entry",
    [
        ".ralf",
        ".ralf/workspace-writes",
        ".ralf/workspace-writes/writer.lock",
        ".ralf/workspace-writes/journal.sqlite",
    ],
)
def test_private_metadata_symlinks_are_refused_without_touching_foreign_data(root, tmp_path, entry):
    foreign = tmp_path / "foreign"
    if entry.endswith(("lock", "sqlite")):
        foreign.write_bytes(b"foreign")
        before = foreign.read_bytes()
    else:
        foreign.mkdir()
        (foreign / "sentinel").write_text("foreign")
        before = (foreign / "sentinel").read_bytes()
    address = root / entry
    address.parent.mkdir(parents=True, exist_ok=True)
    address.symlink_to(foreign)
    with pytest.raises((ValidationError, DefinitionMismatch)):
        writer(root)
    assert (foreign if foreign.is_file() else foreign / "sentinel").read_bytes() == before
    assert (root / "note").read_text() == "old"


@pytest.mark.parametrize("entry", ["writer.lock", "journal.sqlite"])
def test_private_metadata_hard_links_are_refused_before_wal_open(root, tmp_path, entry):
    port = writer(root)
    port.close()
    address = root / ".ralf/workspace-writes" / entry
    os.link(address, tmp_path / "unsafe-alias")
    with pytest.raises((ValidationError, DefinitionMismatch)):
        writer(root)
    assert (root / "note").read_text() == "old"


def test_replaced_root_and_lock_addresses_refuse_before_business_write(root):
    port = writer(root)
    try:
        lock = root / ".ralf/workspace-writes/writer.lock"
        moved = lock.with_suffix(".original")
        lock.rename(moved)
        lock.write_bytes(b"")
        with pytest.raises(DefinitionMismatch):
            port.write_text(SCOPE, "new", "A", expected_version=None, effect_key="k")
        with pytest.raises((ValidationError, DefinitionMismatch)):
            writer(root)
        assert not (root / "new").exists()
    finally:
        port.close()


@pytest.mark.parametrize("path", [".git/config", ".ralf/write", "../other", "link", "directory"])
def test_target_protected_symlink_directory_and_parent_rules(root, tmp_path, path):
    foreign = tmp_path / "foreign"
    foreign.write_text("foreign")
    (root / "link").symlink_to(foreign)
    port = writer(root)
    try:
        with pytest.raises((ValidationError, WorkspaceError)):
            port.write_text(SCOPE, path, "A", expected_version=None, effect_key="k")
        assert port.query_write(SCOPE, "k") is None
        assert foreign.read_text() == "foreign"
    finally:
        port.close()


def test_actual_executing_file_handler_retains_lease_after_close_request(root, monkeypatch):
    port = writer(root)
    entered, release = Event(), Event()
    original = os.replace

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(os, "replace", blocked)
    with ThreadPoolExecutor(max_workers=1) as threads:
        pending = threads.submit(
            port.write_text, SCOPE, "new", "A", expected_version=None, effect_key="k"
        )
        try:
            assert entered.wait(5)
            with pytest.raises(WorkspaceError):
                port.close()
            with pytest.raises(CoordinatorBusy):
                writer(root)
            assert not (root / "new").exists()
        finally:
            release.set()
        assert pending.result(timeout=5)["path"] == "new"
    port.close()
    replacement = writer(root)
    replacement.close()


def test_changed_body_after_rename_cannot_be_confirmed_as_original_write(root, monkeypatch):
    port = writer(root)
    original = os.replace

    def changed(*args, **kwargs):
        original(*args, **kwargs)
        (root / "new").write_text("B")

    monkeypatch.setattr(os, "replace", changed)
    try:
        with pytest.raises(WorkspaceError):
            port.write_text(SCOPE, "new", "A", expected_version=None, effect_key="k")
        assert port.query_write(SCOPE, "k") is None
        assert (root / "new").read_text() == "B"
    finally:
        port.close()


def test_moved_parent_after_rename_retains_unknown_instead_of_confirmed_receipt(root, monkeypatch):
    port = writer(root)
    original = os.replace

    def moved(*args, **kwargs):
        original(*args, **kwargs)
        (root / "directory").rename(root.parent / "outside")

    monkeypatch.setattr(os, "replace", moved)
    try:
        with pytest.raises((WorkspaceError, DefinitionMismatch)):
            port.write_text(SCOPE, "directory/new", "A", expected_version=None, effect_key="k")
        assert port.query_write(SCOPE, "k") is None
        assert (root.parent / "outside/new").read_text() == "A"
    finally:
        port.close()


def test_temporary_directory_entry_is_durable_before_persisted_intent(root, monkeypatch):
    port = writer(root)
    synchronized = []
    original_sync, original_prepare = os.fsync, port._journal.prepare

    def sync(fd):
        synchronized.append(fd)
        return original_sync(fd)

    def prepare(*args, **kwargs):
        assert len(synchronized) >= 2, "temporary file and directory must both be durable"
        assert synchronized[-1] == port._journal._metadata_fd
        assert synchronized[-2] != port._journal._metadata_fd
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(port._journal, "prepare", prepare)
    try:
        assert (
            port.write_text(SCOPE, "new", "A", expected_version=None, effect_key="k")["path"]
            == "new"
        )
    finally:
        port.close()


def test_journal_close_failure_retains_lease_and_refuses_old_writer_operations(root, monkeypatch):
    port = writer(root)
    original = port._journal.close

    def failed():
        raise RuntimeError("injected close failure")

    monkeypatch.setattr(port._journal, "close", failed)
    try:
        with pytest.raises(RuntimeError, match="injected close failure"):
            port.close()
        with pytest.raises(CoordinatorBusy):
            writer(root)
        with pytest.raises(WorkspaceError):
            port.write_text(SCOPE, "new", "A", expected_version=None, effect_key="k")
    finally:
        monkeypatch.setattr(port._journal, "close", original)
        port.close()
    replacement = writer(root)
    replacement.close()
