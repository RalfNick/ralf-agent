"""Distinct canonical JSON resource identities cannot adopt another root's data."""

import asyncio
import copy
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    InMemoryWorkspace,
    LocalEngine,
    Scope,
    SQLiteStore,
    ToolPolicy,
    ToolRegistry,
    WorkspaceBindingResource,
    WorkspaceToolSource,
    register_tool_source,
)
from ralf_agent.binding_workspace import select_workspace_tools
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request

from .test_workspace_binding_execution import Reader


class TypedRoot(InMemoryWorkspace):
    def __init__(self, root, text, observed):
        self.root = root
        self.observed = observed
        super().__init__({"note": text}, version="1")

    @property
    def identity(self):
        return {"kind": "typed-workspace-root", "root": self.root}

    def read_text(self, scope, path, *, max_bytes=1048576):
        result = super().read_text(scope, path, max_bytes=max_bytes)
        self.observed.append(result["text"])
        return result


@pytest.fixture(params=[(1, True), (1, 1.0)])
def roots(request):
    observed, sources, registries = [], [], []

    async def setup():
        for root, text in zip(request.param, ("selected-A", "unselected-B"), strict=True):
            source = WorkspaceToolSource(TypedRoot(root, text, observed), version="1")
            registry = ToolRegistry()
            await register_tool_source(
                registry,
                source,
                policies={
                    "workspace_read_text": ToolPolicy(
                        "1", effect="read_only", requires_approval=False
                    )
                },
            )
            sources.append(source)
            registries.append(registry)

    asyncio.run(setup())
    yield registries, observed
    for source in sources:
        asyncio.run(source.aclose())


def selected(registry):
    catalog = BindingCatalog(scope=Scope())
    catalog.register(
        "workspace", "A", "1", WorkspaceBindingResource(registry, names=["workspace_read_text"])
    )
    definition = AgentDefinition(
        AgentSpec("reader", "Read", tools=("workspace_read_text",)),
        AgentBindingDescriptor(workspace=BindingSelection.ref("A", "1")),
    )
    return catalog, definition


def test_mixed_numeric_type_source_identities_cannot_form_one_resource(roots):
    (a, b), _ = roots
    registry = ToolRegistry()
    for name, original in (("a", a), ("b", b)):
        tool = original.get("workspace_read_text")
        from dataclasses import replace

        registry.register(replace(tool.spec, name=name), tool.handler)
    with pytest.raises(ValidationError):
        WorkspaceBindingResource(registry, names=["a", "b"])


def test_same_name_cannot_match_canonically_distinct_root(roots):
    (a, b), _ = roots
    identity = WorkspaceBindingResource(a, names=["workspace_read_text"]).identity
    with pytest.raises(DefinitionMismatch):
        select_workspace_tools(
            ("workspace_read_text",), b.manifests(["workspace_read_text"]), identity
        )


def test_recorded_source_cannot_differ_from_its_tools_by_numeric_type(roots):
    (a, b), _ = roots
    identity = WorkspaceBindingResource(a, names=["workspace_read_text"]).identity
    identity["source"] = copy.deepcopy(b.get("workspace_read_text").spec.config["source"])
    with pytest.raises(ValidationError):
        select_workspace_tools(
            ("workspace_read_text",), a.manifests(["workspace_read_text"]), identity
        )


def test_actual_local_wrong_root_read_is_rejected_before_run_acceptance(tmp_path, roots):
    (a, b), observed = roots
    catalog, definition = selected(a)
    with LocalEngine(
        SQLiteStore(tmp_path / "wrong-root.sqlite"),
        providers={"default": Reader()},
        tools=b,
        binding_catalog=catalog,
    ) as engine:
        with pytest.raises(DefinitionMismatch):
            engine.submit(definition, "read", command_id="submit")
        assert observed == []
        assert engine.store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_temporal_history_cannot_accept_another_numeric_type_root(roots):
    (a, b), observed = roots
    catalog, definition = selected(a)
    execution = TemporalRuntime(providers={"default": Reader()}, tools=b, binding_catalog=catalog)
    request = normalize_request(submission_request(definition, "read"))
    with pytest.raises(DefinitionMismatch):
        TemporalRunState("run", asdict(Scope()), "submit", request, execution.manifest)
    assert observed == []
