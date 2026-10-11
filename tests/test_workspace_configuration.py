"""Pure Workspace declarations and original Local accepted-read recovery."""

import asyncio

import pytest

from ralf_agent import (
    ComponentRegistry,
    GraphNode,
    GraphWorkflowSpec,
    RuntimeBuilder,
    RuntimeProfile,
    Scope,
    ValueRef,
)
from ralf_agent.errors import AuthorizationDenied, ValidationError


def config(root, **options):
    return {"root": str(root), "version": "files-v1", **options}


def profile(root, **options):
    return RuntimeProfile(
        "workspace",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {"tools": {"adapter": "workspace-read", "config": config(root, **options)}},
    )


def test_workspace_declaration_pure_preflight_without_open_or_stat(monkeypatch):
    import os

    def unexpected(*args, **kwargs):
        raise AssertionError("Pure declaration performed filesystem I/O")

    registry = ComponentRegistry()
    with monkeypatch.context() as guard:
        guard.setattr(os, "open", unexpected)
        guard.setattr(os, "stat", unexpected)
        factory, options = registry.prepare(
            "tools", {"adapter": "workspace-read", "config": config("not-created")}
        )
    assert asyncio.iscoroutinefunction(factory) and options["root"] == "not-created"


@pytest.mark.parametrize(
    "mutation",
    [
        {"unknown": 1},
        {"version": ""},
        {"root": "x\x00y"},
        {"root": 1},
        {"scopes": []},
        {"scopes": [{"workspace": "a", "principal": "b", "extra": 1}]},
        {"scopes": [{"workspace": "a", "principal": "b"}] * 2},
        {"max_bytes": True},
        {"max_entries": 1001},
        {"cost": -1},
        {"requires_approval": 1},
        {"prefix": 1},
    ],
)
def test_workspace_bad_declaration_refuses_before_allocation(tmp_path, mutation):
    declared = config(tmp_path)
    declared.update(mutation)
    with pytest.raises(ValidationError):
        ComponentRegistry().prepare("tools", {"adapter": "workspace-read", "config": declared})
    assert list(tmp_path.iterdir()) == []


def test_workspace_sync_builder_refuses_before_store(tmp_path):
    with pytest.raises(ValidationError, match="abuild"):
        RuntimeBuilder().build(profile(tmp_path), tmp_path / "runs.sqlite")
    assert not (tmp_path / "runs.sqlite").exists()


def test_declared_workspace_approval_restart_adopts_read_once(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    leaf = root / "note"
    leaf.write_text("original")
    flow = GraphWorkflowSpec(
        "read-file", [GraphNode("read", tool="workspace_read_text")], output=ValueRef("read")
    )
    declared = profile(root, requires_approval=True)

    async def run():
        async with await RuntimeBuilder().abuild(declared, tmp_path / "runs.sqlite") as runtime:
            handle = runtime.submit(flow, {"path": "note"}, command_id="same")
            status = await runtime.drive(handle.run_id)
            assert status.state == "waiting_approval", status.error
            pending = status.pending[0]
        async with await RuntimeBuilder().abuild(declared, tmp_path / "runs.sqlite") as runtime:
            assert runtime.submit(flow, {"path": "note"}, command_id="same") == handle
            receipt = runtime.approve(
                handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
            )
            assert (
                runtime.approve(
                    handle.run_id, pending["action_id"], pending["digest"], command_id="approve"
                )
                == receipt
            )
            status = await runtime.drive(handle.run_id)
            assert status.state == "succeeded" and status.result["text"] == "original", status.error
        leaf.write_text("changed after committed read")
        async with await RuntimeBuilder().abuild(declared, tmp_path / "runs.sqlite") as runtime:
            assert (await runtime.drive(handle.run_id)).result["text"] == "original"

    asyncio.run(run())


def test_declared_workspace_host_scope_refuses_before_file_allocation(tmp_path, monkeypatch):
    import ralf_agent.workspace_factories as factories

    declared = profile(tmp_path, scopes=[{"workspace": "allowed", "principal": "owner"}])
    allocations = []
    original = factories.FileSystemWorkspace

    def allocated(*args, **kwargs):
        allocations.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(factories, "FileSystemWorkspace", allocated)

    async def run():
        with pytest.raises(AuthorizationDenied):
            async with await RuntimeBuilder().abuild(
                declared, tmp_path / "runs.sqlite", scope=Scope("other", "owner")
            ):
                pass

    asyncio.run(run())
    assert allocations == []


def test_workspace_factory_rejects_symlink_root_without_normalizing_away_policy(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(root, target_is_directory=True)

    async def run():
        with pytest.raises(ValidationError):
            await RuntimeBuilder().abuild(profile(link), tmp_path / "runs.sqlite")

    asyncio.run(run())


def test_workspace_factory_partial_failure_closes_original_owned_resources(tmp_path, monkeypatch):
    import ralf_agent.workspace_factories as factories
    from ralf_agent import FileSystemWorkspace, WorkspaceError

    owned = []

    class Captured(FileSystemWorkspace):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            owned.append(self)

    async def failed(*args, **kwargs):
        raise ValidationError("fixture discovery failure")

    monkeypatch.setattr(factories, "FileSystemWorkspace", Captured)
    monkeypatch.setattr(factories, "register_tool_source", failed)

    async def run():
        with pytest.raises(ValidationError, match="fixture discovery"):
            await RuntimeBuilder().abuild(profile(tmp_path), tmp_path / "runs.sqlite")

    asyncio.run(run())
    assert len(owned) == 1
    with pytest.raises(WorkspaceError):
        owned[0].stat(Scope(), "")
    owned[0].close()


def test_workspace_native_agent_recovery_preserves_accepted_text(tmp_path):
    from ralf_agent import AgentSpec

    from .test_workspace_temporal_service import Reader

    root = tmp_path / "files"
    root.mkdir()
    (root / "note").write_text("original")
    registry = ComponentRegistry()
    registry.register("provider", "workspace-reader", lambda config, context: Reader())
    declared = RuntimeProfile(
        "files",
        "1",
        {"default": {"adapter": "workspace-reader"}},
        {"tools": {"adapter": "workspace-read", "config": config(root)}},
    )

    async def run():
        async with await RuntimeBuilder(registry).abuild(
            declared, tmp_path / "runs.sqlite"
        ) as runtime:
            handle = runtime.submit(
                AgentSpec("reader", "Read a file", tools=("workspace_read_text",)),
                "read",
                command_id="same",
            )
            done = await runtime.drive(handle.run_id)
            assert done.state == "succeeded" and done.result["text"] == "original", done
        (root / "note").write_text("changed after accepted text")
        async with await RuntimeBuilder(registry).abuild(
            declared, tmp_path / "runs.sqlite"
        ) as runtime:
            assert (await runtime.drive(handle.run_id)).result["text"] == "original"

    asyncio.run(run())
