"""Consumer reproductions for the single dev75 Important fix pass."""

import asyncio
import hashlib
import os
import sys
import threading
import tracemalloc

import pytest

from relf_agent import (
    FileSystemWorkspace,
    InMemoryWorkspace,
    Scope,
    ToolPolicy,
    ToolRegistry,
    WorkspaceError,
    WorkspaceToolSource,
    register_tool_source,
)
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError

from .test_workspace_tools import context


@pytest.mark.parametrize("suffix", ["/", "/."])
def test_workspace_root_alias_does_not_erase_forbidden_symlink(tmp_path, suffix):
    root = tmp_path / "root"
    root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    port = None
    try:
        with pytest.raises(ValidationError):
            port = FileSystemWorkspace(str(alias) + suffix, version="1")
    finally:
        if port is not None:
            port.close()


def test_workspace_root_entry_swap_during_initialization_refuses(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "note").write_text("allowed")
    other = tmp_path / "other"
    other.mkdir()
    (other / "note").write_text("unallowed")
    actual_lstat = os.lstat
    changed = False

    def swap(path, *args, **kwargs):
        nonlocal changed
        result = actual_lstat(path, *args, **kwargs)
        if not changed and os.fspath(path) == str(root):
            changed = True
            root.rename(tmp_path / "moved")
            root.symlink_to(other, target_is_directory=True)
        return result

    monkeypatch.setattr(os, "lstat", swap)
    port = None
    try:
        with pytest.raises((ValidationError, DefinitionMismatch)):
            port = FileSystemWorkspace(root, version="1")
        assert changed
    finally:
        if port is not None:
            port.close()


def test_workspace_root_fspath_is_captured_once(tmp_path):
    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    (allowed / "note").write_text("allowed")
    (other / "note").write_text("other")

    class ChangingPath:
        calls = 0

        def __fspath__(self):
            self.calls += 1
            return str(allowed if self.calls == 1 else other)

    value = ChangingPath()
    port = FileSystemWorkspace(value, version="1")
    try:
        assert port.read_text(Scope(), "note")["text"] == "allowed"
        assert value.calls == 1
    finally:
        port.close()


def test_workspace_root_ancestor_move_and_alias_refuses(tmp_path):
    parent = tmp_path / "parent"
    root = parent / "root"
    root.mkdir(parents=True)
    (root / "note").write_text("original")
    port = FileSystemWorkspace(root, version="1")
    moved = tmp_path / "moved-parent"
    parent.rename(moved)
    parent.symlink_to(moved, target_is_directory=True)
    try:
        with pytest.raises(DefinitionMismatch):
            port.read_text(Scope(), "note")
    finally:
        port.close()


@pytest.mark.parametrize("filesystem", [False, True])
def test_workspace_scope_subclass_equality_never_authorizes(filesystem, tmp_path):
    (tmp_path / "note").write_text("allowed")
    port = (
        FileSystemWorkspace(tmp_path, version="1")
        if filesystem
        else InMemoryWorkspace({"note": "allowed"}, version="1")
    )
    comparisons = []

    class EqualString(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            comparisons.append(other)
            return True

    scope = Scope(EqualString("unallowed"), EqualString("unallowed"))
    try:
        with pytest.raises(AuthorizationDenied):
            port.read_text(scope, "note")
        assert comparisons == []
    finally:
        port.close()


def test_workspace_config_scope_subclasses_refuse_before_hashing():
    class HashString(str):
        def __hash__(self):
            raise AssertionError("Configuration invoked custom hashing")

    scope = Scope(HashString("bad"), "owner")
    with pytest.raises(ValidationError):
        InMemoryWorkspace({}, version="1", scopes=[scope])


@pytest.mark.parametrize("kind", ["path", "ascii-content", "unicode-content"])
def test_workspace_rejected_oversize_does_not_materialize_unbounded_input(kind):
    value = (
        "/" * (4 * 1024 * 1024)
        if kind == "path"
        else "x" * (32 * 1024 * 1024)
        if kind == "ascii-content"
        else "🙂" * (5 * 1024 * 1024)
    )
    port = InMemoryWorkspace({}, version="1")
    tracemalloc.start()
    try:
        with pytest.raises(ValidationError):
            if kind == "path":
                port.read_text(Scope(), value)
            else:
                InMemoryWorkspace({"file": value}, version="1")
        _, peak = tracemalloc.get_traced_memory()
        assert peak < (18 * 1024 * 1024 if kind == "unicode-content" else 1024 * 1024), peak
    finally:
        tracemalloc.stop()
        port.close()


def test_workspace_sdk_aclose_owns_admission_before_tracker_dispatch():
    paused, release, finished = threading.Event(), threading.Event(), threading.Event()
    observed, failures = [], []

    class Port(InMemoryWorkspace):
        def read_text(self, scope, path, *, max_bytes=1048576):
            observed.append(path)
            return super().read_text(scope, path, max_bytes=max_bytes)

    port = Port({"note": "hello"}, version="1")
    source = WorkspaceToolSource(port, version="1")

    def scheduling_pause(frame, event, arg):
        if (
            frame.f_code is WorkspaceToolSource.call_tool.__code__
            and event == "line"
            and "token" in frame.f_locals
            and not source._lock.locked()
            and not paused.is_set()
        ):
            paused.set()
            assert release.wait(5)
        return scheduling_pause

    def caller():
        async def run():
            descriptor = next(
                item for item in await source.list_tools() if item.name == "workspace_read_text"
            )
            await source.call_tool(descriptor, {"path": "note"}, context())

        try:
            sys.settrace(scheduling_pause)
            asyncio.run(run())
        except WorkspaceError:
            pass  # Closing may reject adoption; real port exit must still be owned.
        except BaseException as exc:
            failures.append(exc)
        finally:
            sys.settrace(None)
            finished.set()

    thread = threading.Thread(target=caller)
    thread.start()

    async def close():
        assert await asyncio.to_thread(paused.wait, 5)
        closing = asyncio.create_task(source.aclose())
        try:
            await asyncio.sleep(0)
            assert not closing.done(), "aclose finished before admitted call registered ownership"
            release.set()
            await closing
        finally:
            release.set()
            await closing

    try:
        asyncio.run(close())
    finally:
        release.set()
        thread.join(5)
        assert finished.is_set() and not failures
        asyncio.run(source.aclose())
        port.close()
    assert observed == ["note"]


def test_workspace_non_utf8_normalized_root_refuses_before_any_fd(tmp_path, monkeypatch):
    # Simulates a Linux byte-name ancestor alias; this macOS filesystem disallows it.
    import relf_agent.filesystem_workspace as filesystem

    original_open = os.open
    allocated = []

    def opened(*args, **kwargs):
        if args and type(args[0]) is str and "\udcff" in args[0]:
            args = (str(tmp_path), *args[1:])
        fd = original_open(*args, **kwargs)
        allocated.append(fd)
        return fd

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {opened})
    monkeypatch.setattr(filesystem.os.path, "realpath", lambda path: str(tmp_path) + "\udcff")
    port = None
    try:
        with pytest.raises(ValidationError):
            port = FileSystemWorkspace(tmp_path, version="1")
        assert allocated == []
    finally:
        if port is not None:
            port.close()
        for fd in allocated:
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.parametrize(
    "policy",
    [
        ToolPolicy(
            "1", effect="queryable_write", reconciler=lambda *a: None, requires_approval=False
        ),
        ToolPolicy("1", effect="unqueryable_write"),
        ToolPolicy("1", effect="read_only", reconciler=lambda *a: None, requires_approval=False),
        ToolPolicy("1", effect="idempotent_write", effect_key_argument="key"),
        ToolPolicy("1", effect="read_only", effect_key_argument="path"),
    ],
)
def test_workspace_source_rejects_non_readonly_or_reconcilable_policies(policy):
    port = InMemoryWorkspace({"note": "hello"}, version="1")
    source = WorkspaceToolSource(port, version="1")

    async def run():
        registry = ToolRegistry()
        with pytest.raises(ValidationError):
            await register_tool_source(registry, source, policies={"workspace_read_text": policy})
        assert registry.manifests([]) == {}
        await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


@pytest.mark.parametrize("filesystem", [False, True])
def test_workspace_text_snapshots_refuse_embedded_nul_binary(filesystem, tmp_path):
    (tmp_path / "binary").write_bytes(b"\x00\x01\x02")
    port = (
        FileSystemWorkspace(tmp_path, version="1")
        if filesystem
        else InMemoryWorkspace({"binary": "\x00\x01\x02"}, version="1")
    )
    try:
        with pytest.raises(WorkspaceError):
            port.read_text(Scope(), "binary")
    finally:
        port.close()


def test_workspace_source_custom_port_nul_binary_refuses():
    class BinaryPort(InMemoryWorkspace):
        def read_text(self, scope, path, *, max_bytes=1048576):
            return {
                "path": path,
                "text": "\x00",
                "bytes": 1,
                "sha256": hashlib.sha256(b"\x00").hexdigest(),
                "version": "1",
            }

    port = BinaryPort({}, version="1")
    source = WorkspaceToolSource(port, version="1")

    async def run():
        descriptor = next(
            item for item in await source.list_tools() if item.name == "workspace_read_text"
        )
        with pytest.raises(WorkspaceError):
            await source.call_tool(descriptor, {"path": "binary"}, context())
        await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_workspace_policy_admission_lazy_return_cannot_be_ignored():
    from contextlib import contextmanager

    class LazyPolicySource(WorkspaceToolSource):
        @contextmanager
        def validate_tool_policy(self, descriptor, policy):
            raise AuthorizationDenied("refused")
            yield

    port = InMemoryWorkspace({"note": "hello"}, version="1")
    source = LazyPolicySource(port, version="1")

    async def run():
        registry = ToolRegistry()
        with pytest.raises(ValidationError):
            await register_tool_source(
                registry,
                source,
                policies={
                    "workspace_read_text": ToolPolicy(
                        "1", effect="read_only", requires_approval=False
                    )
                },
            )
        assert registry.manifests([]) == {}
        await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_workspace_custom_port_oversize_is_rejected_before_json_copy():
    text = "x" * (4 * 1024 * 1024)
    checksum = hashlib.sha256(text.encode()).hexdigest()

    class Oversize(InMemoryWorkspace):
        def read_text(self, scope, path, *, max_bytes=1048576):
            return {
                "path": path,
                "text": text,
                "bytes": len(text),
                "sha256": checksum,
                "version": "1",
            }

    port = Oversize({}, version="1")
    source = WorkspaceToolSource(port, version="1", max_bytes=16)

    async def run():
        descriptor = next(
            item for item in await source.list_tools() if item.name == "workspace_read_text"
        )
        tracemalloc.start()
        try:
            with pytest.raises(WorkspaceError):
                await source.call_tool(descriptor, {"path": "note"}, context())
            _, peak = tracemalloc.get_traced_memory()
            assert peak < 1024 * 1024, peak
        finally:
            tracemalloc.stop()
            await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()


def test_workspace_readonly_policy_field_subclass_cannot_override_comparison():
    class Effect(str):
        def __ne__(self, other):
            return False

    port = InMemoryWorkspace({"note": "hello"}, version="1")
    source = WorkspaceToolSource(port, version="1")

    async def run():
        registry = ToolRegistry()
        with pytest.raises(ValidationError):
            await register_tool_source(
                registry,
                source,
                policies={
                    "workspace_read_text": ToolPolicy(
                        "1", effect=Effect("unqueryable_write"), requires_approval=False
                    )
                },
            )
        assert registry.manifests([]) == {}
        await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()
