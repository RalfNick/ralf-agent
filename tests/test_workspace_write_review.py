"""Independent review regressions for native addresses, durable commits and modes."""

import os
import stat
import unicodedata

import pytest

from relf_agent import FileSystemWritableWorkspace, Scope
from relf_agent.workspace import WorkspaceError

from .test_workspace_write_processes import crash, prepared

SCOPE = Scope()


@pytest.mark.parametrize(
    "original,alternate",
    [
        ("note", "NOTE"),
        ("folder/note", "FOLDER/NOTE"),
        ("café", unicodedata.normalize("NFD", "café")),
    ],
)
def test_published_pending_write_is_confirmed_before_native_alias_replacement(
    tmp_path, monkeypatch, original, alternate
):
    first, second = tmp_path / original, tmp_path / alternate
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("old")
    second.parent.mkdir(parents=True, exist_ok=True)
    if not second.exists():
        second.write_text("separate")
    aliases = os.path.samefile(first, second)
    port = FileSystemWritableWorkspace(tmp_path, version="1")
    confirm = port._journal.confirm
    try:

        def lost(*args, **kwargs):
            raise WorkspaceError("lost downstream confirmation")

        monkeypatch.setattr(port._journal, "confirm", lost)
        with pytest.raises(WorkspaceError):
            port.write_text(
                SCOPE,
                original,
                "A",
                expected_version=port.read_text(SCOPE, original)["version"],
                effect_key="old",
            )
        monkeypatch.setattr(port._journal, "confirm", confirm)
        port.write_text(
            SCOPE,
            alternate,
            "B",
            expected_version=port.read_text(SCOPE, alternate)["version"],
            effect_key="new",
        )
        assert port.query_write(SCOPE, "old") is not None
        assert first.read_text() == ("B" if aliases else "A")
    finally:
        port.close()


@pytest.mark.parametrize("alternate", ["NOTE", "unrelated"])
def test_absent_prepared_target_holds_its_physical_parent_before_another_create(
    tmp_path, monkeypatch, alternate
):
    (tmp_path / "elsewhere").mkdir()
    port = FileSystemWritableWorkspace(tmp_path, version="1")
    replace = os.replace
    try:

        def interrupted(*args, **kwargs):
            raise OSError("intent committed before rename")

        monkeypatch.setattr(os, "replace", interrupted)
        with pytest.raises(WorkspaceError):
            port.write_text(SCOPE, "note", "A", expected_version=None, effect_key="old")
        monkeypatch.setattr(os, "replace", replace)
        assert port.query_write(SCOPE, "old") is None
        with pytest.raises(WorkspaceError):
            port.write_text(SCOPE, alternate, "B", expected_version=None, effect_key="new")
        assert not (tmp_path / alternate).exists()
        port.write_text(SCOPE, "elsewhere/note", "B", expected_version=None, effect_key="other")
        port.write_text(SCOPE, "note", "A", expected_version=None, effect_key="old")
        assert port.query_write(SCOPE, "old") is not None
    finally:
        port.close()


@pytest.mark.parametrize("reopened", [False, True])
def test_every_native_journal_connection_uses_delete_extra(tmp_path, reopened):
    port = FileSystemWritableWorkspace(tmp_path, version="1")
    if reopened:
        port.close()
        port = FileSystemWritableWorkspace(tmp_path, version="1")
    try:
        assert port._journal.conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert port._journal.conn.execute("PRAGMA synchronous").fetchone()[0] == 3
    finally:
        port.close()


@pytest.mark.parametrize("mode", [0o644, 0o755, 0o640])
def test_replacing_text_preserves_existing_ordinary_permissions(tmp_path, mode):
    path = tmp_path / "note"
    path.write_text("old")
    path.chmod(mode)
    port = FileSystemWritableWorkspace(tmp_path, version="1")
    try:
        port.write_text(
            SCOPE,
            "note",
            "new",
            expected_version=port.read_text(SCOPE, "note")["version"],
            effect_key="k",
        )
        assert stat.S_IMODE(path.stat().st_mode) == mode
        port.write_text(SCOPE, "new", "new", expected_version=None, effect_key="create")
        assert stat.S_IMODE((tmp_path / "new").stat().st_mode) == 0o600
    finally:
        port.close()


def test_real_before_rename_recovery_preserves_existing_executable_permissions(tmp_path):
    path = tmp_path / "note"
    path.write_text("old")
    path.chmod(0o755)
    crash(tmp_path, "before_rename")
    request, _ = prepared(tmp_path)
    port = FileSystemWritableWorkspace(tmp_path, version="1")
    try:
        port.write_text(
            SCOPE, "note", "A", expected_version=request["expected_version"], effect_key="original"
        )
        assert stat.S_IMODE(path.stat().st_mode) == 0o755
    finally:
        port.close()
