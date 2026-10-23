"""Borrowed original Workspace grants; no binding I/O or extra execution authority."""

import asyncio
import copy

import pytest

import relf_agent
from relf_agent import (
    BindingCatalog,
    BindingSelection,
    InMemoryWorkspace,
    Scope,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
    WorkspaceToolSource,
    register_tool_source,
)
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError


def api():
    value = getattr(relf_agent, "WorkspaceBindingResource", None)
    assert value is not None, "WorkspaceBindingResource public API is missing"
    from relf_agent.binding_workspace import select_workspace_tools

    return value, select_workspace_tools


@pytest.fixture
def registered():
    source_a = WorkspaceToolSource(InMemoryWorkspace({"note": "alpha"}, version="a"), version="1")
    source_b = WorkspaceToolSource(InMemoryWorkspace({"note": "beta"}, version="b"), version="1")
    registry = ToolRegistry()

    async def assemble():
        for source, prefix in ((source_a, "a_"), (source_b, "b_")):
            await register_tool_source(
                registry,
                source,
                prefix=prefix,
                policies={
                    "workspace_read_text": ToolPolicy("1", effect="read_only"),
                    "workspace_stat": ToolPolicy("1", effect="read_only"),
                },
            )

    asyncio.run(assemble())
    registry.register(
        ToolSpec("business", "Business", {"type": "object"}, "1", "read_only"), lambda a, c: "ok"
    )
    yield registry
    asyncio.run(source_a.aclose())
    asyncio.run(source_b.aclose())


def test_selected_root_filters_only_workspace_grants_in_original_order(registered):
    resource, select = api()
    binding = resource(registered, names=["a_workspace_read_text", "a_workspace_stat"])
    names = ("b_workspace_read_text", "business", "a_workspace_stat", "a_workspace_read_text")
    assert select(names, registered.manifests(names), binding.identity) == (
        "business",
        "a_workspace_stat",
        "a_workspace_read_text",
    )


def test_disabled_workspace_preserves_business_grant(registered):
    _, select = api()
    names = ("a_workspace_read_text", "business", "b_workspace_stat")
    assert select(names, registered.manifests(names)) == ("business",)


def test_workspace_choice_does_not_apply_name_caps_to_unrelated_business_tools(registered):
    resource, select = api()
    long_name = "business_" + "x" * 150
    registered.register(ToolSpec(long_name, "Business", {"type": "object"}), lambda a, c: "ok")
    binding = resource(registered, names=["a_workspace_read_text"])
    names = (long_name, "a_workspace_read_text", "b_workspace_read_text")
    assert select(names, registered.manifests(names), binding.identity) == (
        long_name,
        "a_workspace_read_text",
    )


def test_async_registry_snapshot_refused_without_creating_coroutine():
    resource, _ = api()

    class Lazy(ToolRegistry):
        async def manifests(self, names):
            raise AssertionError("lazy registry executed")

    with pytest.raises(ValidationError):
        resource(Lazy(), names=["workspace_read_text"])


def test_reference_cannot_add_a_missing_or_ungranted_tool(registered):
    resource, select = api()
    binding = resource(registered, names=["a_workspace_read_text"])
    names = ("business", "b_workspace_read_text")
    with pytest.raises(AuthorizationDenied):
        select(names, registered.manifests(names), binding.identity)


def test_mixed_root_registrations_are_refused(registered):
    resource, _ = api()
    with pytest.raises(ValidationError):
        resource(registered, names=["a_workspace_read_text", "b_workspace_read_text"])


def test_same_root_with_different_source_caps_is_not_one_resource(registered):
    resource, _ = api()
    source = WorkspaceToolSource(
        InMemoryWorkspace({"note": "alpha"}, version="a"), version="1", max_bytes=10
    )
    try:
        asyncio.run(
            register_tool_source(
                registered,
                source,
                prefix="small_",
                policies={"workspace_read_text": ToolPolicy("1", effect="read_only")},
            )
        )
        with pytest.raises(ValidationError):
            resource(registered, names=["a_workspace_read_text", "small_workspace_read_text"])
    finally:
        asyncio.run(source.aclose())


def test_non_workspace_or_unregistered_names_are_refused(registered):
    resource, _ = api()
    with pytest.raises(ValidationError):
        resource(registered, names=["business"])
    with pytest.raises(DefinitionMismatch):
        resource(registered, names=["absent"])


@pytest.mark.parametrize(
    "names",
    [
        [],
        (),
        "a_workspace_read_text",
        {},
        [1],
        [True],
        [""],
        [" "],
        ["x" * 129],
        ["bad\x00name"],
        ["bad\x7fname"],
        ["\ud800"],
        ["x"] * 257,
        ["a_workspace_read_text"] * 2,
    ],
)
def test_invalid_resource_names_fail_before_registry_access(registered, names):
    resource, _ = api()

    class NoAccess(ToolRegistry):
        def manifests(self, names):
            raise AssertionError("invalid names reached registry")

    with pytest.raises(ValidationError):
        resource(NoAccess(), names=names)


def test_name_subclass_cannot_override_scope_selection(registered):
    resource, _ = api()

    class Alias(str):
        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    with pytest.raises(ValidationError):
        resource(registered, names=[Alias("b_workspace_read_text")])


def test_resource_records_are_detached_and_catalog_remains_scoped(registered):
    resource, _ = api()
    binding = resource(registered, names=["a_workspace_read_text"])
    original = copy.deepcopy(binding.identity)
    changed = binding.identity
    changed["source"]["max_bytes"] = 1
    changed["tools"]["a_workspace_read_text"]["effect"] = "unqueryable_write"
    assert binding.identity == original
    catalog = BindingCatalog(scope=Scope())
    catalog.register("workspace", "alpha", "1", binding)
    selected, record = catalog.resolve("workspace", BindingSelection.ref("alpha", "1"), Scope())
    assert selected is binding and record["identity"] == original
    with pytest.raises(AuthorizationDenied):
        catalog.resolve("workspace", BindingSelection.ref("alpha", "1"), Scope("other", "caller"))
    with pytest.raises(ValidationError):
        catalog.resolve(
            "workspace", BindingSelection.ref("alpha", "1", selector={"path": "sub"}), Scope()
        )


def test_live_registered_manifest_drift_is_refused(registered):
    resource, _ = api()

    class DriftingRegistry(ToolRegistry):
        changed = False

        def manifests(self, names):
            result = registered.manifests(names)
            if self.changed:
                result["a_workspace_read_text"]["version"] = "2"
            return result

    registry = DriftingRegistry()
    binding = resource(registry, names=["a_workspace_read_text"])
    registry.changed = True
    with pytest.raises(DefinitionMismatch):
        _ = binding.identity


def test_same_tool_name_cannot_adopt_another_manifest(registered):
    resource, select = api()
    binding = resource(registered, names=["a_workspace_read_text"])
    names = ("a_workspace_read_text", "business")
    manifests = registered.manifests(names)
    manifests["a_workspace_read_text"]["config"]["source"]["max_bytes"] = 10
    with pytest.raises(DefinitionMismatch):
        select(names, manifests, binding.identity)


def test_write_manifest_cannot_be_registered_as_workspace_resource(registered):
    resource, _ = api()

    class WriteRegistry(ToolRegistry):
        def manifests(self, names):
            result = registered.manifests(names)
            result["a_workspace_read_text"]["effect"] = "unqueryable_write"
            return result

    with pytest.raises(ValidationError):
        resource(WriteRegistry(), names=["a_workspace_read_text"])


def test_binding_creation_and_selection_perform_no_port_io_or_close():
    resource, select = api()

    class NoIo(InMemoryWorkspace):
        def read_text(self, *args, **kwargs):
            raise AssertionError("binding performed a read")

        def stat(self, *args, **kwargs):
            raise AssertionError("binding performed stat")

        def list(self, *args, **kwargs):
            raise AssertionError("binding performed list")

        def close(self):
            raise AssertionError("borrowed port was closed")

    source = WorkspaceToolSource(NoIo({"note": "a"}, version="1"), version="1")
    registry = ToolRegistry()
    asyncio.run(
        register_tool_source(
            registry, source, policies={"workspace_read_text": ToolPolicy("1", effect="read_only")}
        )
    )
    try:
        binding = resource(registry, names=["workspace_read_text"])
        assert select(
            ("workspace_read_text",), registry.manifests(["workspace_read_text"]), binding.identity
        ) == ("workspace_read_text",)
        assert not hasattr(binding, "close")
    finally:
        asyncio.run(source.aclose())
