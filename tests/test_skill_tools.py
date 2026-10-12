"""Original managed tool injection validates catalog snapshots and permissions."""

import asyncio
import copy

import pytest

import ralf_agent as r
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from ralf_agent.types import InvocationContext


def port():
    return r.InMemorySkillCatalog(
        [r.SkillSpec("help", "Reference", "Use allowed tools")], version="1"
    )


def source(catalog, **options):
    cls = getattr(r, "SkillToolSource", None)
    assert cls is not None, "public SkillToolSource is missing"
    return cls(catalog, version="1", **options)


def context(scope=None):
    return InvocationContext(scope or r.Scope(), "run", "action", "attempt", "effect", "epoch")


def test_native_catalog_source_registration_and_borrowed_close():
    catalog = port()
    original = source(catalog)

    async def run():
        registry = r.ToolRegistry()
        names = await r.register_tool_source(
            registry,
            original,
            policies={
                "skill_list": r.ToolPolicy("1", effect="read_only", requires_approval=False),
                "skill_get": r.ToolPolicy("1", effect="read_only", requires_approval=False),
            },
        )
        assert names == ("skill_list", "skill_get")
        assert (await registry.get("skill_list").handler({}, context()))["skills"][0][
            "name"
        ] == "help"
        assert (await registry.get("skill_get").handler({"name": "help"}, context()))["skill"][
            "instructions"
        ] == "Use allowed tools"
        await original.aclose()
        assert catalog.get(r.Scope(), "help")["skill"]["name"] == "help"
        with pytest.raises(r.SkillError):
            await original.list_tools()

    try:
        asyncio.run(run())
    finally:
        catalog.close()


@pytest.mark.parametrize("effect", ["idempotent_write", "unqueryable_write"])
def test_instruction_tools_cannot_be_registered_as_writes(effect):
    catalog = port()
    original = source(catalog)

    async def run():
        with pytest.raises(ValidationError):
            await r.register_tool_source(
                r.ToolRegistry(),
                original,
                policies={
                    "skill_get": r.ToolPolicy(
                        "1",
                        effect=effect,
                        effect_key_argument="effect_key" if effect == "idempotent_write" else None,
                    )
                },
            )
        await original.aclose()

    try:
        asyncio.run(run())
    finally:
        catalog.close()


@pytest.mark.parametrize("part", ["scope", "catalog_digest", "sha256", "bytes", "instructions"])
def test_custom_catalog_cannot_return_forged_scope_or_instruction_evidence(part):
    class Custom(r.InMemorySkillCatalog):
        def get(self, *args, **kwargs):
            value = super().get(*args, **kwargs)
            if part in {"scope", "catalog_digest"}:
                value[part] = (
                    {"workspace": "other", "principal": "owner"} if part == "scope" else "0" * 64
                )
            else:
                value["skill"][part] = True if part == "bytes" else "forged"
            return value

    catalog = Custom([r.SkillSpec("help", "Reference", "Instructions")], version="1")
    original = source(catalog)

    async def run():
        descriptor = next(d for d in await original.list_tools() if d.name == "skill_get")
        with pytest.raises(r.SkillError):
            await original.call_tool(descriptor, {"name": "help"}, context())
        await original.aclose()

    try:
        asyncio.run(run())
    finally:
        catalog.close()


@pytest.mark.parametrize("lazy", ["coroutine", "generator", "contextmanager"])
def test_lazy_custom_get_result_is_not_executed(lazy):
    touched = []

    class Custom(r.InMemorySkillCatalog):
        def get(self, *args, **kwargs):
            if lazy == "coroutine":

                async def value():
                    touched.append(True)

                return value()
            if lazy == "generator":

                def value():
                    touched.append(True)
                    yield None

                return value()
            from contextlib import contextmanager

            @contextmanager
            def value():
                touched.append(True)
                yield None

            return value()

    catalog = Custom([r.SkillSpec("help", "Reference", "Instructions")], version="1")
    original = source(catalog)

    async def run():
        descriptor = next(d for d in await original.list_tools() if d.name == "skill_get")
        with pytest.raises(r.SkillError):
            await original.call_tool(descriptor, {"name": "help"}, context())
        assert touched == []
        await original.aclose()

    try:
        asyncio.run(run())
    finally:
        catalog.close()


def test_host_caps_scope_and_pinned_identity_cannot_be_overridden():
    catalog = port()
    original = source(catalog, max_bytes=2)

    async def run():
        descriptor = next(d for d in await original.list_tools() if d.name == "skill_get")
        with pytest.raises(r.SkillError):
            await original.call_tool(descriptor, {"name": "help"}, context())
        with pytest.raises(AuthorizationDenied):
            await original.call_tool(
                descriptor, {"name": "help"}, context(r.Scope("other", "owner"))
            )
        with pytest.raises(ValidationError):
            await original.call_tool(descriptor, {"name": "help", "max_bytes": 100}, context())
        catalog._identity = {**catalog._identity, "catalog_digest": "0" * 64}
        with pytest.raises(DefinitionMismatch):
            await original.list_tools()
        await original.aclose()

    try:
        asyncio.run(run())
    finally:
        catalog.close()


def test_native_source_identity_is_detached_and_descriptors_are_original():
    catalog = port()
    original = source(catalog)
    identity = original.identity
    identity["catalog"]["catalog_digest"] = "changed"
    assert original.identity["catalog"]["catalog_digest"] == catalog.identity["catalog_digest"]

    async def run():
        descriptor = next(d for d in await original.list_tools() if d.name == "skill_get")
        wrong = copy.deepcopy(descriptor.to_dict())
        wrong["description"] = "changed"
        with pytest.raises(DefinitionMismatch):
            await original.call_tool(r.ToolDescriptor(**wrong), {"name": "help"}, context())
        await original.aclose()

    try:
        asyncio.run(run())
    finally:
        catalog.close()


def test_actual_file_handler_outlives_loop_cancellation_and_retains_owned_fd(tmp_path, monkeypatch):
    import json
    import threading

    from .test_thread_execution import wait_until_started

    (tmp_path / "help").mkdir()
    (tmp_path / "help/SKILL.md").write_text("Reference")
    (tmp_path / "skills.json").write_text(
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
    catalog = r.FileSystemSkillCatalog(tmp_path, version="1")
    original = source(catalog)
    ready, release = threading.Event(), threading.Event()
    stat = catalog._workspace.stat

    def blocked(scope, path):
        if path == "help/SKILL.md":
            ready.set()
            assert release.wait(10)
        return stat(scope, path)

    monkeypatch.setattr(catalog._workspace, "stat", blocked)
    loop = asyncio.new_event_loop()

    async def start():
        descriptor = next(d for d in await original.list_tools() if d.name == "skill_get")
        task = asyncio.create_task(original.call_tool(descriptor, {"name": "help"}, context()))
        await wait_until_started(ready)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    try:
        loop.run_until_complete(start())
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        with pytest.raises(r.WorkspaceError):
            catalog.close()
        assert catalog._workspace._root_fd is not None

        async def close():
            closing = asyncio.create_task(original.aclose())
            await asyncio.sleep(0.02)
            assert not closing.done()
            release.set()
            await closing

        asyncio.run(close())
    finally:
        release.set()
        if not loop.is_closed():
            loop.close()
        asyncio.run(original.aclose())
        catalog.close()
    assert catalog._workspace._root_fd is None
