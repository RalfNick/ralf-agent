"""Actual POSIX data-policy boundaries and independent FD ownership."""

import os

import pytest

from ralf_agent import Scope
from ralf_agent.errors import DefinitionMismatch, ValidationError

from .test_workspace import api


def test_filesystem_workspace_has_no_implicit_metadata_and_restart_identity(tmp_path):
    (tmp_path / "file.txt").write_text("content")
    before = set(tmp_path.iterdir())
    first = api("FileSystemWorkspace")(tmp_path, version="v1")
    identity = first.identity
    assert str(tmp_path) not in str(identity)
    first.close()
    with_port = api("FileSystemWorkspace")(tmp_path, version="v1")
    try:
        assert with_port.identity == identity
        assert with_port.read_text(Scope(), "file.txt")["text"] == "content"
    finally:
        with_port.close()
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_filesystem_workspace_rejects_actual_unsafe_leaf(tmp_path, kind):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("secret")
    leaf = root / "unsafe"
    if kind == "symlink":
        leaf.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, leaf)
    else:
        os.mkfifo(leaf)
    port = api("FileSystemWorkspace")(root, version="v1")
    try:
        for operation in (port.stat, port.read_text):
            with pytest.raises(api("WorkspaceError")):
                operation(Scope(), "unsafe")
        with pytest.raises(api("WorkspaceError")):
            port.list(Scope())
    finally:
        port.close()


def test_filesystem_workspace_rejects_symlink_ancestor_and_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("secret")
    (root / "jump").symlink_to(outside, target_is_directory=True)
    link = tmp_path / "root-link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValidationError):
        api("FileSystemWorkspace")(link, version="v1")
    port = api("FileSystemWorkspace")(root, version="v1")
    try:
        with pytest.raises(api("WorkspaceError")):
            port.read_text(Scope(), "jump/secret")
    finally:
        port.close()


def test_filesystem_workspace_root_replacement_refuses_original_binding(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "file").write_text("original")
    port = api("FileSystemWorkspace")(root, version="v1")
    original = tmp_path / "moved"
    root.rename(original)
    root.mkdir()
    (root / "file").write_text("replacement")
    try:
        with pytest.raises(DefinitionMismatch):
            port.read_text(Scope(), "file")
    finally:
        port.close()


def test_filesystem_workspace_protected_entries_omitted_from_allowed_view(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/config").write_text("protected")
    (tmp_path / "allowed").write_text("text")
    port = api("FileSystemWorkspace")(tmp_path, version="v1")
    try:
        assert [entry["path"] for entry in port.list(Scope(), max_entries=1)["entries"]] == [
            "allowed"
        ]
    finally:
        port.close()


def test_filesystem_workspace_invalid_utf8_refuses_no_absolute_os_error(tmp_path):
    (tmp_path / "binary").write_bytes(b"\xff\xfe")
    port = api("FileSystemWorkspace")(tmp_path, version="v1")
    try:
        with pytest.raises(api("WorkspaceError")) as caught:
            port.read_text(Scope(), "binary")
        assert str(tmp_path) not in str(caught.value)
    finally:
        port.close()


@pytest.mark.parametrize("path", ["a" * 4097, "/".join(["a"] * 129)])
def test_filesystem_workspace_path_limits_are_caller_validation(tmp_path, path):
    port = api("FileSystemWorkspace")(tmp_path, version="v1")
    try:
        with pytest.raises(ValidationError):
            port.stat(Scope(), path)
    finally:
        port.close()


def test_filesystem_workspace_root_initialization_failure_closes_allocated_fd(
    tmp_path, monkeypatch
):
    actual_open, actual_fstat = os.open, os.fstat
    allocated = []

    def opened(*args, **kwargs):
        fd = actual_open(*args, **kwargs)
        allocated.append(fd)
        return fd

    def failed(fd):
        raise OSError("private-host-diagnostic")

    monkeypatch.setattr(os, "open", opened)
    # Preserve platform capability detection while instrumenting the real allocation.
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {opened})
    monkeypatch.setattr(os, "fstat", failed)
    with pytest.raises(ValidationError) as caught:
        api("FileSystemWorkspace")(tmp_path, version="v1")
    assert "private-host" not in str(caught.value)
    assert len(allocated) == 1
    try:
        with pytest.raises(OSError):
            actual_fstat(allocated[0])
    finally:
        try:
            os.close(allocated[0])
        except OSError:
            pass


def test_filesystem_workspace_listing_rechecks_each_file_metadata(tmp_path, monkeypatch):
    leaf = tmp_path / "file"
    leaf.write_text("a")
    port = api("FileSystemWorkspace")(tmp_path, version="v1")
    original_scandir = os.scandir

    class MutatedAfterScan:
        def __init__(self, fd):
            self.iterator = original_scandir(fd)

        def __enter__(self):
            return self.iterator.__enter__()

        def __exit__(self, *args):
            result = self.iterator.__exit__(*args)
            leaf.write_text("longer")
            return result

    monkeypatch.setattr(os, "scandir", MutatedAfterScan)
    try:
        with pytest.raises(DefinitionMismatch):
            port.list(Scope())
    finally:
        port.close()


def test_filesystem_workspace_running_read_retains_fd_through_close(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    (tmp_path / "file").write_text("hello")
    port = api("FileSystemWorkspace")(tmp_path, version="v1")
    started, release = threading.Event(), threading.Event()
    actual_read = os.read

    def blocked(fd, count):
        started.set()
        assert release.wait(5)
        return actual_read(fd, count)

    monkeypatch.setattr(os, "read", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(port.read_text, Scope(), "file")
        try:
            assert started.wait(5)
            with pytest.raises(api("WorkspaceError")):
                port.close()
            assert not future.done()
            with pytest.raises(api("WorkspaceError")):
                port.stat(Scope(), "file")
            release.set()
            assert future.result(5)["text"] == "hello"
        finally:
            release.set()
            future.result(5)
            port.close()


def test_filesystem_workspace_file_mutation_and_moved_ancestor_refuse(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    leaf = root / "docs/file"
    leaf.write_text("before")
    port = api("FileSystemWorkspace")(root, version="v1")
    actual_read = os.read
    changed = False

    def mutate(fd, count):
        nonlocal changed
        data = actual_read(fd, count)
        if not changed:
            changed = True
            (root / "docs").rename(tmp_path / "moved")
            (root / "docs").mkdir()
            (root / "docs/file").write_text("new")
        return data

    monkeypatch.setattr(os, "read", mutate)
    try:
        with pytest.raises(DefinitionMismatch):
            port.read_text(Scope(), "docs/file")
    finally:
        port.close()
