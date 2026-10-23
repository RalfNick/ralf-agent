"""Frozen filesystem reference catalogs retain original revisions and actual I/O ownership."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

import relf_agent as r
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, RalfError, ValidationError
from relf_agent.filesystem_workspace import FileSystemWorkspace

SCOPE = r.Scope()


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "skills"
    (path / "help").mkdir(parents=True)
    (path / "help/SKILL.md").write_text("Use approved tools.")
    (path / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {
                        "name": "help",
                        "description": "Reference",
                        "version": "1",
                        "path": "help/SKILL.md",
                    }
                ],
            }
        )
    )
    return path


def catalog(root, **options):
    cls = getattr(r, "FileSystemSkillCatalog", None)
    assert cls is not None, "public FileSystemSkillCatalog is missing"
    return cls(root, version="1", **options)


def test_file_default_matches_memory_snapshots_and_pins_original_root(root):
    port = catalog(root)
    other = r.InMemorySkillCatalog(
        [r.SkillSpec("help", "Reference", "Use approved tools.")], version="1"
    )
    try:
        assert port.list(SCOPE) == other.list(SCOPE)
        assert port.get(SCOPE, "help") == other.get(SCOPE, "help")
        identity = port.identity
        assert identity["kind"] == "filesystem-skill-catalog"
        port.close()
        resumed = catalog(root)
        try:
            assert resumed.identity == identity and resumed.get(SCOPE, "help") == other.get(
                SCOPE, "help"
            )
        finally:
            resumed.close()
    finally:
        port.close()
        other.close()


@pytest.mark.parametrize(
    "change", ["body", "metadata", "equal_foreign_inode", "root_moved", "missing"]
)
def test_changed_original_file_catalog_refuses_silent_refresh(root, change):
    port = catalog(root)
    try:
        if change == "body":
            (root / "help/SKILL.md").write_text("Different instructions")
        elif change == "metadata":
            value = json.loads((root / "skills.json").read_text())
            value["skills"][0]["description"] = "Different"
            (root / "skills.json").write_text(json.dumps(value))
        elif change == "equal_foreign_inode":
            (root / "foreign").write_text("Use approved tools.")
            os.replace(root / "foreign", root / "help/SKILL.md")
        elif change == "root_moved":
            root.rename(root.with_name("moved"))
            root.mkdir()
        else:
            (root / "help/SKILL.md").unlink()
        for method, kwargs in (("list", {}), ("get", {"name": "help"})):
            with pytest.raises(DefinitionMismatch):
                getattr(port, method)(SCOPE, **kwargs)
    finally:
        port.close()


@pytest.mark.parametrize(
    "path",
    ["../secret", ".git/config", ".ralf/data", "/absolute", "help/../SKILL.md", "help\\SKILL.md"],
)
def test_manifest_cannot_expand_root_or_protected_paths(root, path):
    value = json.loads((root / "skills.json").read_text())
    value["skills"][0]["path"] = path
    (root / "skills.json").write_text(json.dumps(value))
    with pytest.raises((ValidationError, r.SkillError)):
        catalog(root)


@pytest.mark.parametrize(
    "alias", ["body_symlink", "body_hardlink", "manifest_symlink", "root_symlink"]
)
def test_unsafe_file_aliases_are_refused(root, alias):
    if alias == "root_symlink":
        target = root.with_name("alias")
        target.symlink_to(root, target_is_directory=True)
        root = target
    else:
        path = root / ("skills.json" if alias == "manifest_symlink" else "help/SKILL.md")
        original = root.with_name("outside")
        original.write_bytes(path.read_bytes())
        path.unlink()
        if alias == "body_hardlink":
            os.link(original, path)
        else:
            path.symlink_to(original)
    with pytest.raises(RalfError):
        catalog(root)


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "unknown", "wrong_version", "nul", "blank", "capacity"]
)
def test_invalid_catalog_content_refused_with_owned_cleanup(root, monkeypatch, change):
    value = json.loads((root / "skills.json").read_text())
    if change == "missing":
        (root / "help/SKILL.md").unlink()
    elif change == "duplicate":
        value["skills"].append(dict(value["skills"][0]))
    elif change == "unknown":
        value["extra"] = True
    elif change == "wrong_version":
        value["version"] = True
    elif change in {"nul", "blank"}:
        (root / "help/SKILL.md").write_text("\x00" if change == "nul" else "\u3000")
    (root / "skills.json").write_text(json.dumps(value))
    opened, closed = [], []
    original_open, original_close = os.open, os.close

    def track_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def track_close(fd):
        closed.append(fd)
        return original_close(fd)

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {track_open})
    monkeypatch.setattr(os, "close", track_close)
    with pytest.raises(RalfError):
        catalog(root, **({"max_bytes": 1} if change == "capacity" else {}))
    assert opened and set(opened) <= set(closed)


def test_bad_options_are_refused_before_root_allocation(root, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid options must not allocate a root")

    monkeypatch.setattr(FileSystemWorkspace, "__init__", forbidden)
    for options in (
        {"max_skills": True},
        {"max_bytes": 0},
        {"manifest": "../secret"},
        {"scopes": []},
    ):
        with pytest.raises(ValidationError):
            catalog(root, **options)


def test_denied_scope_does_not_probe_original_files_and_close_is_idempotent(root, monkeypatch):
    port = catalog(root)

    def forbidden(*args, **kwargs):
        raise AssertionError("denied Scope must not probe files")

    monkeypatch.setattr(port._workspace, "stat", forbidden)
    try:
        with pytest.raises(AuthorizationDenied):
            port.get(r.Scope("other", "owner"), "help")
    finally:
        port.close()
    port.close()
    with pytest.raises(RalfError):
        port.list(SCOPE)


def test_actual_handler_retains_original_root_fd_during_close_failure(root, monkeypatch):
    port = catalog(root)
    ready, release = Event(), Event()
    original_stat = port._workspace.stat

    def blocked(scope, path):
        if path == "help/SKILL.md":
            ready.set()
            assert release.wait(10)
        return original_stat(scope, path)

    monkeypatch.setattr(port._workspace, "stat", blocked)
    with ThreadPoolExecutor() as threads:
        future = threads.submit(port.list, SCOPE)
        try:
            assert ready.wait(5)
            with pytest.raises(RalfError):
                port.close()
            assert port._workspace._root_fd is not None
        finally:
            release.set()
            try:
                future.result(timeout=10)
            except RalfError:
                pass
            port.close()
    assert port._workspace._root_fd is None


@pytest.mark.parametrize("method", ["list", "get"])
def test_file_revision_rechecked_after_snapshot_before_return(root, monkeypatch, method):
    port = catalog(root)
    original = getattr(r.InMemorySkillCatalog, method)

    def changed(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        (root / "help/SKILL.md").write_text("Late changed instructions")
        return value

    monkeypatch.setattr(r.InMemorySkillCatalog, method, changed)
    try:
        with pytest.raises(DefinitionMismatch):
            getattr(port, method)(SCOPE, **({"name": "help"} if method == "get" else {}))
    finally:
        port.close()
