import json
import os
import sqlite3
import subprocess
import sys

import pytest

from relf_agent.errors import ValidationError
from relf_agent.storage import SQLiteStore

from .test_cli import subprocess_env


def coordinator_probe(path):
    """A separate process must observe the same local authority."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
import sys
from relf_agent.errors import RalfError
from relf_agent.storage import SQLiteStore

try:
    with SQLiteStore(sys.argv[1]) as store:
        coordinator = store.create_coordinator()
        coordinator.acquire()
        try:
            store.create_budget('probe', 1)
            print(json.dumps({'outcome': 'acquired'}))
        finally:
            coordinator.release()
except RalfError as error:
    print(json.dumps({'outcome': error.code}))
""",
            str(path),
        ],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["outcome"]


def test_relative_path_keeps_same_coordinator_after_chdir(tmp_path, monkeypatch):
    initial = tmp_path / "initial"
    later = tmp_path / "later"
    initial.mkdir()
    later.mkdir()
    monkeypatch.chdir(initial)
    with SQLiteStore("runs.db") as store:
        monkeypatch.chdir(later)
        coordinator = store.create_coordinator()
        coordinator.acquire()
        try:
            assert coordinator_probe(initial / "runs.db") == "coordinator_busy"
            assert store.path == str(initial / "runs.db")
            assert store.backend_id == f"sqlite:{initial / 'runs.db'}"
            assert not (later / "runs.db.coordinator").exists()
        finally:
            coordinator.release()


@pytest.mark.parametrize("readonly", [False, True])
@pytest.mark.parametrize("open_alias", [False, True])
def test_hard_links_are_rejected_before_wal_is_opened(tmp_path, readonly, open_alias):
    original = tmp_path / "runs.db"
    alias = tmp_path / "alias.db"
    with SQLiteStore(original) as store:
        store.create_budget("original", 3)
    os.link(original, alias)
    path = alias if open_alias else original
    with pytest.raises(ValidationError, match="hard link"):
        SQLiteStore(path, readonly=readonly)
    assert not (tmp_path / "alias.db-wal").exists()
    assert not (tmp_path / "alias.db-shm").exists()
    assert not (tmp_path / "runs.db-wal").exists()
    assert not (tmp_path / "runs.db-shm").exists()


def test_hard_link_alias_cannot_gain_authority_in_another_process(tmp_path):
    original = tmp_path / "runs.db"
    alias = tmp_path / "alias.db"
    with SQLiteStore(original) as store:
        coordinator = store.create_coordinator()
        coordinator.acquire()
        try:
            os.link(original, alias)
            assert coordinator_probe(alias) == "validation_error"
            assert not (tmp_path / "alias.db-wal").exists()
            assert not (tmp_path / "alias.db-shm").exists()
        finally:
            coordinator.release()


def test_hard_link_created_during_open_is_rejected_before_wal(tmp_path, monkeypatch):
    original = tmp_path / "runs.db"
    alias = tmp_path / "alias.db"
    connect = sqlite3.connect

    def open_then_link(*args, **kwargs):
        connection = connect(*args, **kwargs)
        os.link(original, alias)
        return connection

    monkeypatch.setattr(sqlite3, "connect", open_then_link)
    with pytest.raises(ValidationError, match="hard link"):
        SQLiteStore(original)
    assert not (tmp_path / "runs.db-wal").exists()
    assert not (tmp_path / "runs.db-shm").exists()


def test_new_hard_link_is_rejected_before_coordinator_and_writes(tmp_path):
    original = tmp_path / "runs.db"
    with SQLiteStore(original) as store:
        coordinator = store.create_coordinator()
        os.link(original, tmp_path / "alias.db")
        with pytest.raises(ValidationError, match="hard link"):
            store.create_coordinator()
        with pytest.raises(ValidationError, match="hard link"):
            coordinator.acquire()
        with pytest.raises(ValidationError, match="hard link"):
            store.create_budget("blocked", 1)
        assert store.conn.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0


def test_replaced_database_cannot_reuse_an_existing_connection(tmp_path):
    original = tmp_path / "runs.db"
    with SQLiteStore(original) as store:
        coordinator = store.create_coordinator()
        original.rename(tmp_path / "old.db")
        with sqlite3.connect(original) as replacement:
            replacement.execute("CREATE TABLE replacement (id INTEGER)")
        with pytest.raises(ValidationError, match="identity"):
            store.create_coordinator()
        with pytest.raises(ValidationError, match="identity"):
            coordinator.acquire()
        with pytest.raises(ValidationError, match="identity"):
            store.create_budget("blocked", 1)


def test_symlink_uses_canonical_database_and_coordinator(tmp_path):
    original = tmp_path / "runs.db"
    alias = tmp_path / "alias.db"
    with SQLiteStore(original) as store:
        store.create_budget("original", 3)
        alias.symlink_to(original)
        coordinator = store.create_coordinator()
        coordinator.acquire()
        try:
            assert coordinator_probe(alias) == "coordinator_busy"
            with SQLiteStore(alias, readonly=True) as observer:
                assert observer.path == str(original)
                assert observer.backend_id == store.backend_id
                assert observer.budget("original")["limit"] == 3
            assert not (tmp_path / "alias.db-wal").exists()
        finally:
            coordinator.release()


def test_directory_path_is_rejected_with_validation_error(tmp_path):
    with pytest.raises(ValidationError, match="regular file"):
        SQLiteStore(tmp_path)
