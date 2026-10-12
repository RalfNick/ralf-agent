"""Regressions from the one whole-batch Skills review."""

import asyncio
import json

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, RalfError, ValidationError
from ralf_agent.skills import validate_skill_get, validate_skill_list
from ralf_agent.types import InvocationContext


def catalog():
    return r.InMemorySkillCatalog([r.SkillSpec("help", "Reference", "Original")], version="1")


def invoke(port, operation, arguments):
    async def run():
        source = r.SkillToolSource(port, version="1", max_entries=1)
        try:
            descriptor = next(d for d in await source.list_tools() if d.name == operation)
            context = InvocationContext(r.Scope(), "run", "action", "attempt", "effect", "epoch")
            return await source.call_tool(descriptor, arguments, context)
        finally:
            await source.aclose()

    return asyncio.run(run())


@pytest.mark.parametrize("operation", ["skill_list", "skill_get"])
def test_changed_metadata_or_body_cannot_reuse_original_catalog_digest(operation):
    class Changed(r.InMemorySkillCatalog):
        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            value["skill"] = r.SkillSpec("help", "Changed", "Different", "2").to_dict()
            return value

        def list(self, *args, **kwargs):
            value = super().list(*args, **kwargs)
            if operation == "skill_list":
                value["skills"] = [
                    {
                        k: v
                        for k, v in r.SkillSpec("help", "Changed", "Different", "2")
                        .to_dict()
                        .items()
                        if k != "instructions"
                    }
                ]
            return value

    port = Changed([r.SkillSpec("help", "Reference", "Original")], version="1")
    try:
        with pytest.raises(r.SkillError):
            invoke(port, operation, {} if operation == "skill_list" else {"name": "help"})
    finally:
        port.close()


def test_complete_list_metadata_digest_must_match_envelope():
    port = catalog()
    try:
        value = port.list(r.Scope())
        value["skills"][0]["description"] = "Different"
        with pytest.raises(r.SkillError):
            validate_skill_list(
                value,
                r.Scope(),
                catalog_digest=port.identity["catalog_digest"],
                max_entries=100,
                offset=0,
            )
    finally:
        port.close()


@pytest.mark.parametrize("field", ["kind", "version", "scope", "key"])
@pytest.mark.parametrize("operation", ["skill_list", "skill_get"])
def test_snapshot_subclasses_never_execute_copy_hooks(field, operation):
    touched = []

    class Deferred(str):
        def __deepcopy__(self, memo):
            touched.append(True)
            return "changed-after-validation"

    port = catalog()
    try:
        value = port.list(r.Scope()) if operation == "skill_list" else port.get(r.Scope(), "help")
        if field == "scope":
            value["scope"]["workspace"] = Deferred("default")
        elif field == "key":
            value[Deferred("kind")] = value.pop("kind")
        else:
            value[field] = Deferred(value[field])
        with pytest.raises(r.SkillError):
            if operation == "skill_list":
                validate_skill_list(
                    value,
                    r.Scope(),
                    catalog_digest=port.identity["catalog_digest"],
                    max_entries=100,
                    offset=0,
                )
            else:
                validate_skill_get(
                    value,
                    r.Scope(),
                    "help",
                    catalog_digest=port.identity["catalog_digest"],
                    max_bytes=100,
                )
        assert touched == []
    finally:
        port.close()


@pytest.mark.parametrize("foreign", ["string", "tuple", "key"])
def test_catalog_identity_is_plain_data_before_any_copy(foreign):
    touched = []

    class Deferred(str):
        def __deepcopy__(self, memo):
            touched.append(True)
            return "copied"

    original = catalog()
    identity = original.identity
    if foreign == "tuple":
        identity["custom"] = ("x",)
    elif foreign == "key":
        identity[Deferred("custom")] = "x"
    else:
        identity["custom"] = Deferred("x")

    class Port:
        def list(self, *args, **kwargs):
            return original.list(*args, **kwargs)

        def get(self, *args, **kwargs):
            return original.get(*args, **kwargs)

        def close(self):
            pass

    port = Port()
    port.identity = identity
    try:
        with pytest.raises((ValidationError, r.SkillError)):
            r.SkillToolSource(port, version="1")
        assert touched == []
    finally:
        original.close()


@pytest.mark.parametrize("kind", ["local", "temporal"])
@pytest.mark.parametrize("allowed", [True, False])
def test_explicit_scope_declaration_builds_or_denies_original_scope(tmp_path, kind, allowed):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "help.md").write_text("Original")
    (root / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {"name": "help", "description": "Reference", "version": "1", "path": "help.md"}
                ],
            }
        )
    )
    scopes = [{"workspace": "default" if allowed else "foreign", "principal": "local-owner"}]
    profile_type = r.RuntimeProfile if kind == "local" else r.TemporalProfile
    profile = profile_type(
        "app",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "tools": {
                "adapter": "skills-file",
                "config": {"root": str(root), "version": "1", "scopes": scopes},
            }
        },
    )

    async def run():
        async def build():
            if kind == "local":
                return await r.RuntimeBuilder().abuild(profile, tmp_path / "runs.sqlite")
            return await r.TemporalRuntimeBuilder().abuild(profile, scope=r.Scope())

        if not allowed:
            with pytest.raises(AuthorizationDenied):
                await build()
        else:
            runtime = await build()
            try:
                registry = runtime.tools if kind == "local" else runtime._runtime.tools
                assert registry.get("skill_get").spec.effect == "read_only"
            finally:
                await runtime.aclose()

    asyncio.run(run())


def test_file_loading_stops_at_aggregate_bound_and_closes(monkeypatch):
    import ralf_agent.filesystem_skills as module

    reads, closed = [], []
    body = "x" * 1048576
    entries = [
        {"name": f"skill-{i}", "description": "Reference", "version": "1", "path": f"skill-{i}.md"}
        for i in range(70)
    ]

    class Workspace:
        def __init__(self, *args, **kwargs):
            pass

        def read_text(self, scope, path, *, max_bytes):
            reads.append((path, max_bytes))
            if path == "skills.json":
                return {
                    "text": json.dumps({"version": "1", "skills": entries}),
                    "version": "manifest",
                }
            assert max_bytes >= len(body), "must stop before attempting another full body"
            return {"text": body, "version": path}

        def close(self):
            closed.append(True)

    monkeypatch.setattr(module, "FileSystemWorkspace", Workspace)
    with pytest.raises(RalfError):
        r.FileSystemSkillCatalog("unused", version="1", max_skills=100, max_bytes=1048576)
    assert len(reads) <= 65
    assert closed == [True]


@pytest.mark.parametrize("operation", ["skill_list", "skill_get"])
def test_native_source_refuses_snapshot_hook_before_copy(operation):
    touched = []

    class Deferred(str):
        def __deepcopy__(self, memo):
            touched.append(True)
            return "forged"

    class Port(r.InMemorySkillCatalog):
        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            value["scope"]["workspace"] = Deferred("default")
            return value

        def list(self, *args, **kwargs):
            value = super().list(*args, **kwargs)
            value["kind"] = Deferred("skill-list")
            return value

    port = Port([r.SkillSpec("help", "Reference", "Original")], version="1")
    try:
        with pytest.raises(r.SkillError):
            invoke(port, operation, {} if operation == "skill_list" else {"name": "help"})
        assert touched == []
    finally:
        port.close()


def test_partial_page_cannot_refresh_after_membership_is_pinned():
    class Port(r.InMemorySkillCatalog):
        changed = False

        def list(self, *args, **kwargs):
            value = super().list(*args, **kwargs)
            if self.changed and value["skills"]:
                value["skills"][0]["description"] = "Changed"
            return value

    port = Port([r.SkillSpec("alpha", "A", "A"), r.SkillSpec("beta", "B", "B")], version="1")

    async def run():
        source = r.SkillToolSource(port, version="1", max_entries=1)
        try:
            descriptor = next(d for d in await source.list_tools() if d.name == "skill_list")
            context = InvocationContext(r.Scope(), "run", "action", "attempt", "effect", "epoch")
            await source.call_tool(descriptor, {}, context)
            port.changed = True
            with pytest.raises(r.SkillError):
                await source.call_tool(descriptor, {"offset": 1}, context)
        finally:
            await source.aclose()

    try:
        asyncio.run(run())
    finally:
        port.close()
