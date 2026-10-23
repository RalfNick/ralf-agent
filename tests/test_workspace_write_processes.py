"""Real owner exits, durable inode proof and conservative unknown effects."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from relf_agent import FileSystemWritableWorkspace, Scope
from relf_agent.errors import CoordinatorBusy
from relf_agent.workspace import WorkspaceError

SCOPE = Scope()
FIXTURE = Path(__file__).with_name("workspace_write_crash_fixture.py")


def environment():
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
    }


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "files"
    path.mkdir()
    (path / "note").write_text("old")
    return path


def crash(root, mode):
    result = subprocess.run(
        [sys.executable, str(FIXTURE), str(root), mode],
        env=environment(),
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 77, result.stderr.decode()


def prepared(root):
    with sqlite3.connect(root / ".ralf/workspace-writes/journal.sqlite") as conn:
        row = conn.execute(
            "SELECT request,evidence FROM workspace_write_effects WHERE effect_key='original'"
        ).fetchone()
    return json.loads(row[0]), json.loads(row[1])


@pytest.mark.parametrize("mode", ["before_rename", "after_rename", "after_receipt"])
def test_real_crash_recovers_original_effect_without_duplicate_replacement(root, mode, monkeypatch):
    crash(root, mode)
    request, evidence = prepared(root)
    before = os.stat(root / "note").st_ino
    count = []
    original_replace = os.replace

    def replace(*args, **kwargs):
        count.append(True)
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    port = FileSystemWritableWorkspace(root, version="1")
    try:
        queried = port.query_write(SCOPE, "original")
        if mode == "before_rename":
            assert queried is None and (root / "note").read_text() == "old"
        else:
            assert queried is not None and queried["path"] == "note"
        receipt = port.write_text(
            SCOPE, "note", "A", expected_version=request["expected_version"], effect_key="original"
        )
        assert port.query_write(SCOPE, "original") == receipt
        assert (root / "note").read_text() == "A"
        assert len(count) == (1 if mode == "before_rename" else 0)
        assert os.stat(root / "note").st_ino == evidence["inode"]
        if mode != "before_rename":
            assert before == os.stat(root / "note").st_ino
    finally:
        port.close()


@pytest.mark.parametrize("tamper", ["body", "equal_foreign_inode", "temporary"])
def test_tampered_prepared_proof_remains_unknown_without_blind_overwrite(root, tamper, monkeypatch):
    crash(root, "before_rename" if tamper == "temporary" else "after_rename")
    request, evidence = prepared(root)
    if tamper == "body":
        (root / "note").write_text("B")
    elif tamper == "equal_foreign_inode":
        foreign = root / "foreign"
        foreign.write_text("A")
        os.replace(foreign, root / "note")
    else:
        (root / ".ralf/workspace-writes" / evidence["temporary"]).write_text("B")
    before = (root / "note").read_bytes(), os.stat(root / "note").st_ino

    def forbidden(*args, **kwargs):
        raise AssertionError("unknown effect cannot blindly replace a file")

    monkeypatch.setattr(os, "replace", forbidden)
    port = FileSystemWritableWorkspace(root, version="1")
    try:
        assert port.query_write(SCOPE, "original") is None
        with pytest.raises(WorkspaceError):
            port.write_text(
                SCOPE,
                "note",
                "A",
                expected_version=request["expected_version"],
                effect_key="original",
            )
        with pytest.raises(WorkspaceError):
            port.write_text(
                SCOPE,
                "note",
                "new",
                expected_version=port.read_text(SCOPE, "note")["version"],
                effect_key="different",
            )
        assert before == ((root / "note").read_bytes(), os.stat(root / "note").st_ino)
    finally:
        port.close()


def test_actual_process_lease_blocks_alias_until_original_owner_exits(root):
    process = subprocess.Popen(
        [sys.executable, str(FIXTURE), str(root), "hold"],
        env=environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not (root.parent / "ready").exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        for address in (root, root.parent / "files/../files"):
            with pytest.raises(CoordinatorBusy):
                FileSystemWritableWorkspace(address, version="1")
    finally:
        (root.parent / "release").touch()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr.decode()
    replacement = FileSystemWritableWorkspace(root, version="1")
    replacement.close()
