"""Frozen standard-document catalogs reuse original safe-file and scope ownership."""

import builtins
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

import relf_agent as r
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, RalfError, ValidationError


def api():
    value = getattr(r, "FileSkillDocumentCatalog", None)
    assert value is not None, "public FileSkillDocumentCatalog is missing"
    return value


def write(root, name="help", body="Original", metadata=""):
    parent = root / name
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / "SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: Reference\n{metadata}---\n{body}")
    return path


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "skills"
    write(root)
    return root


def test_default_parsed_snapshots_match_original_memory_and_fixed_identity(root):
    cls = api()
    catalog = cls(root, version="1", paths=["help/SKILL.md"])
    memory = r.InMemorySkillCatalog([r.SkillSpec("help", "Reference", "Original")], version="1")
    try:
        assert catalog.list(r.Scope()) == memory.list(r.Scope())
        assert catalog.get(r.Scope(), "help") == memory.get(r.Scope(), "help")
        identity = catalog.identity
        assert identity["kind"] == "file-skill-document-catalog"
        assert identity["parser"]["identity"]["kind"] == "yaml-skill-document-parser"
        catalog.close()
        resumed = cls(root, version="1", paths=["help/SKILL.md"])
        try:
            assert resumed.identity == identity
        finally:
            resumed.close()
    finally:
        catalog.close()
        memory.close()


def test_root_level_skill_uses_fixed_original_root_basename(tmp_path):
    cls = api()
    root = tmp_path / "help"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: help\ndescription: Reference\n---\nRoot body")
    port = cls(root, version="1")
    try:
        assert port.get(r.Scope(), "help")["skill"]["instructions"] == "Root body"
    finally:
        port.close()


def test_explicit_multiple_paths_and_metadata_pin(root):
    cls = api()
    write(root, "second", metadata="license: Apache-2.0\nmetadata:\n  version: '2'\n")
    port = cls(root, version="1", paths=["second/SKILL.md", "help/SKILL.md"])
    try:
        assert [i["name"] for i in port.list(r.Scope())["skills"]] == ["help", "second"]
        assert port.get(r.Scope(), "second")["skill"]["version"] == "2"
        assert "Apache-2.0" in str(port.identity)
    finally:
        port.close()


@pytest.mark.parametrize(
    "change",
    ["body", "metadata", "equal_foreign_inode", "missing", "root_moved", "hardlink", "symlink"],
)
def test_original_files_refuse_silent_refresh(root, change):
    cls = api()
    port = cls(root, version="1", paths=["help/SKILL.md"])
    file = root / "help/SKILL.md"
    if change == "body":
        file.write_text(file.read_text().replace("Original", "Changed"))
    elif change == "metadata":
        file.write_text(
            file.read_text().replace(
                "description: Reference", "description: Reference\nlicense: Apache-2.0"
            )
        )
    elif change == "equal_foreign_inode":
        other = root / "replacement"
        other.write_bytes(file.read_bytes())
        os.replace(other, file)
    elif change == "missing":
        file.unlink()
    elif change == "root_moved":
        root.rename(root.with_name("moved"))
    elif change == "hardlink":
        os.link(file, root / "another-link")
    else:
        other = root / "foreign"
        other.write_text(file.read_text())
        file.unlink()
        file.symlink_to(other)
    try:
        with pytest.raises(DefinitionMismatch):
            port.get(r.Scope(), "help")
    finally:
        port.close()


@pytest.mark.parametrize(
    "paths",
    [
        [],
        "help/SKILL.md",
        [True],
        ["../SKILL.md"],
        ["help/not-skill.md"],
        ["help/SKILL.md", "help/SKILL.md"],
        ["help/SKILL.md"] * 1001,
    ],
)
def test_invalid_paths_refuse_before_workspace_allocation(monkeypatch, root, paths):
    cls = api()
    import relf_agent.filesystem_skill_documents as module

    calls = []
    monkeypatch.setattr(module, "FileSystemWorkspace", lambda *a, **k: calls.append(True))
    with pytest.raises(RalfError):
        cls(root, version="1", paths=paths)
    assert calls == []


def test_missing_optional_yaml_refuses_before_root_allocation(monkeypatch, root):
    cls = api()
    import relf_agent.filesystem_skill_documents as module

    calls = []
    original = builtins.__import__

    def import_module(name, *args, **kwargs):
        if name == "yaml":
            raise ModuleNotFoundError("optional unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_module)
    monkeypatch.setattr(module, "FileSystemWorkspace", lambda *a, **k: calls.append(True))
    with pytest.raises(ValidationError):
        cls(root, version="1", paths=["help/SKILL.md"])
    assert calls == []


class Custom:
    identity = {"kind": "custom-pure-skill-parser", "version": "1"}

    def parse(self, text, *, parent_name):
        return r.ParsedSkillDocument(
            r.SkillSpec(parent_name, "Custom", "Parsed body"), {"license": "App"}
        )

    def close(self):
        raise AssertionError("borrowed pure parser must not be closed")


@pytest.mark.parametrize(
    "identity", [{"kind": "custom-pure-skill-parser", "version": "2"}, {"bad": float("nan")}]
)
def test_sdk_custom_parser_borrowed_and_identity_drift_refuses(root, identity):
    cls = api()
    parser = Custom()
    port = cls(root, version="1", paths=["help/SKILL.md"], parser=parser)
    try:
        assert port.get(r.Scope(), "help")["skill"]["instructions"] == "Parsed body"
        parser.identity = identity
        with pytest.raises(DefinitionMismatch):
            port.list(r.Scope())
    finally:
        port.close()


@pytest.mark.parametrize(
    "kind", ["async", "generator", "context", "wrong_value", "wrong_name", "metadata_hook"]
)
def test_custom_parser_lazy_invalid_value_refuses_and_closes_root(root, monkeypatch, kind):
    cls = api()
    import relf_agent.filesystem_skill_documents as module

    original = module.FileSystemWorkspace
    allocated = []
    touched = []

    def allocate(*args, **kwargs):
        value = original(*args, **kwargs)
        allocated.append(value)
        return value

    monkeypatch.setattr(module, "FileSystemWorkspace", allocate)

    class Parser(Custom):
        def parse(self, text, *, parent_name):
            if kind == "wrong_value":
                return {"name": "help"}
            if kind == "wrong_name":
                return r.ParsedSkillDocument(r.SkillSpec("other", "Reference", "Body"))
            if kind == "metadata_hook":

                class Deferred(str):
                    def __deepcopy__(self, memo):
                        touched.append(True)
                        return "forged"

                return r.ParsedSkillDocument(
                    r.SkillSpec("help", "Reference", "Body"), {"license": Deferred("App")}
                )
            if kind == "context":
                from contextlib import contextmanager

                @contextmanager
                def context():
                    touched.append(True)
                    yield None

                return context()
            if kind == "generator":

                def generate():
                    touched.append(True)
                    yield None

                return generate()

            async def delayed():
                touched.append(True)
                return None

            return delayed()

    with pytest.raises(RalfError):
        cls(root, version="1", paths=["help/SKILL.md"], parser=Parser())
    assert touched == []
    assert all(value._root_fd is None for value in allocated)


def test_denied_scope_and_blocked_real_handler_retains_original_fd(root, monkeypatch):
    cls = api()
    port = cls(root, version="1", paths=["help/SKILL.md"])
    with pytest.raises(AuthorizationDenied):
        port.get(r.Scope("foreign", "owner"), "help")
    entered, release = Event(), Event()
    original = port._workspace.stat

    def stat(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(port._workspace, "stat", stat)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(port.get, r.Scope(), "help")
        assert entered.wait(5)
        try:
            with pytest.raises(RalfError):
                port.close()
            assert port._workspace._root_fd is not None
        finally:
            release.set()
        with pytest.raises(RalfError):
            future.result()
    port.close()
    assert port._workspace._root_fd is None


@pytest.mark.parametrize("kind", ["missing", "malformed", "wrong_parent"])
def test_constructor_failure_closes_original_root(root, monkeypatch, kind):
    cls = api()
    import relf_agent.filesystem_skill_documents as module

    original, allocated = module.FileSystemWorkspace, []

    def allocate(*args, **kwargs):
        value = original(*args, **kwargs)
        allocated.append(value)
        return value

    monkeypatch.setattr(module, "FileSystemWorkspace", allocate)
    path = root / "help/SKILL.md"
    if kind == "missing":
        path.unlink()
    elif kind == "malformed":
        path.write_text("Broken frontmatter")
    else:
        path.write_text("---\nname: other\ndescription: Reference\n---\nBody")
    with pytest.raises(RalfError):
        cls(root, version="1", paths=["help/SKILL.md"])
    assert len(allocated) == 1 and allocated[0]._root_fd is None


@pytest.mark.parametrize("kind", ["async", "generator", "identity"])
def test_invalid_parser_configuration_refuses_before_root(root, monkeypatch, kind):
    cls = api()
    import relf_agent.filesystem_skill_documents as module

    allocated = []
    monkeypatch.setattr(module, "FileSystemWorkspace", lambda *a, **k: allocated.append(True))
    parser = Custom()
    if kind == "async":

        async def parse(*a, **k):
            return None

        parser.parse = parse
    elif kind == "generator":

        def parse(*a, **k):
            yield None

        parser.parse = parse
    else:
        parser.identity = {"bad": float("nan")}
    with pytest.raises(RalfError):
        cls(root, version="1", paths=["help/SKILL.md"], parser=parser)
    assert allocated == []


def test_parser_implementation_change_refuses_cached_snapshot(root):
    cls = api()
    parser = Custom()
    port = cls(root, version="1", paths=["help/SKILL.md"], parser=parser)
    try:
        parser.parse = lambda text, *, parent_name: r.ParsedSkillDocument(
            r.SkillSpec(parent_name, "Different", "Body")
        )
        with pytest.raises(DefinitionMismatch):
            port.get(r.Scope(), "help")
    finally:
        port.close()


def test_aggregate_raw_document_limit_refuses_before_fifth_read(tmp_path, monkeypatch):
    cls = api()
    import relf_agent.filesystem_skill_documents as module

    root = tmp_path / "skills"
    paths = []
    for number in range(5):
        name = f"skill-{number}"
        path = write(root, name, body="x" * 16777216)
        path.write_bytes(path.read_bytes()[:16777216])
        paths.append(f"{name}/SKILL.md")
    calls, allocated = [], []
    original = module.FileSystemWorkspace

    def allocate(*args, **kwargs):
        value = original(*args, **kwargs)
        read = value.read_text

        def read_text(scope, path, **options):
            calls.append((path, options["max_bytes"]))
            return read(scope, path, **options)

        value.read_text = read_text
        allocated.append(value)
        return value

    monkeypatch.setattr(module, "FileSystemWorkspace", allocate)
    with pytest.raises(RalfError):
        cls(root, version="1", paths=paths, max_bytes=16777216, parser=Custom())
    assert calls == [(path, 16777216) for path in paths[:4]]
    assert allocated[0]._root_fd is None
