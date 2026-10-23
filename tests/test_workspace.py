"""Replaceable Workspace defaults exercise the same consumer-visible contract."""

import hashlib

import pytest

import relf_agent as ralf
from relf_agent.errors import AuthorizationDenied, ValidationError

SCOPE = ralf.Scope("documents", "reader")


def api(name):
    value = getattr(ralf, name, None)
    assert value is not None, f"Missing public Workspace API: {name}"
    return value


@pytest.fixture(params=["memory", "filesystem"])
def workspace(request, tmp_path):
    if request.param == "memory":
        port = api("InMemoryWorkspace")(
            {"docs/note.txt": "hello", "docs/unicode.txt": "你好", "empty.txt": ""},
            version="content-v1",
            scopes=[SCOPE],
        )
    else:
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs/note.txt").write_text("hello")
        (tmp_path / "docs/unicode.txt").write_text("你好")
        (tmp_path / "empty.txt").write_text("")
        port = api("FileSystemWorkspace")(tmp_path, version="content-v1", scopes=[SCOPE])
    try:
        yield port
    finally:
        port.close()


def test_workspace_detached_utf8_snapshot_and_sorted_complete_listing(workspace):
    value = workspace.read_text(SCOPE, "docs/note.txt")
    assert value["text"] == "hello" and value["bytes"] == 5
    assert value["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert value["path"] == "docs/note.txt" and isinstance(value["version"], str)
    value["text"] = "caller mutation"
    assert workspace.read_text(SCOPE, "docs/note.txt")["text"] == "hello"
    root = workspace.list(SCOPE)
    assert [entry["path"] for entry in root["entries"]] == ["docs", "empty.txt"]
    assert root["entries"][0]["kind"] == "directory" and root["entries"][0]["size"] is None
    assert workspace.stat(SCOPE, "docs/note.txt")["size"] == 5
    assert workspace.read_text(SCOPE, "empty.txt")["sha256"] == hashlib.sha256(b"").hexdigest()


def test_workspace_exact_scope_allows_no_other_tenant_or_principal(workspace):
    for scope in (ralf.Scope("other", "reader"), ralf.Scope("documents", "other")):
        for function in (workspace.stat, workspace.list, workspace.read_text):
            with pytest.raises(AuthorizationDenied):
                function(scope, "docs/note.txt")


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../x",
        "docs/../x",
        "./x",
        "docs//x",
        "a\\b",
        "x\x00y",
        "x\ny",
        ".GIT/config",
        ".ralf/state",
        "x\ud800",
        "a/",
        1,
    ],
)
def test_workspace_bad_path_refuses_before_data_read(workspace, path):
    with pytest.raises(ValidationError):
        workspace.read_text(SCOPE, path)


def test_workspace_byte_bounds_count_utf8_and_refuse_truncation(workspace):
    with pytest.raises(api("WorkspaceError")):
        workspace.read_text(SCOPE, "docs/unicode.txt", max_bytes=5)
    assert workspace.read_text(SCOPE, "docs/unicode.txt", max_bytes=6)["bytes"] == 6
    with pytest.raises(api("WorkspaceError")):
        workspace.list(SCOPE, "docs", max_entries=1)
    assert len(workspace.list(SCOPE, "docs", max_entries=2)["entries"]) == 2


@pytest.mark.parametrize("limit", [True, 0, -1, 16777217, float("nan"), "10"])
def test_workspace_invalid_read_limit_is_validation_error(workspace, limit):
    with pytest.raises(ValidationError):
        workspace.read_text(SCOPE, "docs/note.txt", max_bytes=limit)


@pytest.mark.parametrize("limit", [True, 0, 1001, "10"])
def test_workspace_invalid_list_limit_is_validation_error(workspace, limit):
    with pytest.raises(ValidationError):
        workspace.list(SCOPE, max_entries=limit)


def test_workspace_missing_directory_or_file_has_sanitized_typed_error(workspace):
    for function, path in (
        (workspace.read_text, "missing"),
        (workspace.read_text, "docs"),
        (workspace.list, "empty.txt"),
    ):
        with pytest.raises(api("WorkspaceError")) as caught:
            function(SCOPE, path)
        assert "/Users/" not in str(caught.value) and "[Errno" not in str(caught.value)


def test_workspace_close_rejects_future_operations_and_is_retryable(workspace):
    workspace.close()
    workspace.close()
    with pytest.raises(api("WorkspaceError")):
        workspace.read_text(SCOPE, "docs/note.txt")


def test_memory_workspace_copies_host_mapping_and_identity():
    files = {"a": "original"}
    port = api("InMemoryWorkspace")(files, version="v1")
    try:
        identity = port.identity
        identity["behavior_version"] = "changed"
        files["a"] = "changed"
        assert port.read_text(ralf.Scope(), "a")["text"] == "original"
        assert port.identity["behavior_version"] == "v1"
        assert port.identity != api("InMemoryWorkspace")({"a": "other"}, version="v1").identity
    finally:
        port.close()


@pytest.mark.parametrize(
    "files", [{"a": "x", "a/b": "y"}, {"a": 1}, {"a": "\ud800"}, {"../a": "x"}]
)
def test_memory_workspace_invalid_host_data_refuses(files):
    with pytest.raises(ValidationError):
        api("InMemoryWorkspace")(files, version="v1")


def test_memory_workspace_file_count_is_bounded():
    with pytest.raises(ValidationError):
        api("InMemoryWorkspace")({f"file-{i}": "" for i in range(4097)}, version="v1")
