"""Composite binding routing through real SQLite authority and native effects."""

import asyncio

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryMemory,
    Literal,
    ModelResponse,
    Scope,
    ToolRegistry,
    ToolSpec,
)
from relf_agent.cli_views import diagnostics_inspection
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.retrieval import (
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
)
from relf_agent.types import ToolCall
from relf_agent.workflow import ExecutionPlan, StaticWorkflowCompiler

from .helpers import ScriptedProvider
from .test_binding_execution import RecordingProvider, TaggedContext, bound_catalog, choice, engine


@pytest.mark.parametrize("concurrency", [1, 2])
def test_graph_routes_by_node_id_with_independent_context_memory_and_knowledge(
    tmp_path, concurrency
):
    catalog = bound_catalog()
    for color in ("red", "blue"):
        catalog.register("provider", color, "1", RecordingProvider(color))
        catalog.register("context", color, "1", TaggedContext(color))
        facts = InMemoryMemory(backend_id="facts-" + color)
        facts.put_fact(Scope(), "shared", "favorite", color, expected_version=0)
        catalog.register("facts", color, "1", facts)
        knowledge = InMemoryKnowledgeStore(backend_id="docs-" + color)
        knowledge.put(Scope(), "docs", Document("guide", "pool " + color), expected_version=0)
        catalog.register(
            "knowledge", color, "1", KnowledgeContext(LexicalRetriever(knowledge), namespace="docs")
        )
    spec = GraphWorkflowSpec(
        "colors",
        [GraphNode("copy", transform="identity")]
        + [
            GraphNode(color, agent=AgentSpec("shared", "Answer"), depends_on=("copy",))
            for color in ("red", "blue")
        ],
        max_concurrency=concurrency,
    )
    wrapped = BoundDefinition(
        spec,
        {
            f"graph/nodes/{color}": AgentBindingDescriptor(
                **{role: choice(color) for role in ("provider", "context", "facts", "knowledge")},
                session=BindingSelection.disabled(),
            )
            for color in ("red", "blue")
        },
    )
    with engine(tmp_path / "graph.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "pool", command_id="submit")
        result = asyncio.run(runtime.drive(handle.run_id))
        assert result.state == "succeeded", result.error
        for color, other in (("red", "blue"), ("blue", "red")):
            output = result.result[color]
            assert output["provider"] == color
            assert "context:" + color in output["request"]
            assert "pool " + color in output["request"]
            assert "pool " + other not in output["request"]
        assert runtime.providers["default"].label == "host"
        details = runtime.diagnostics(handle.run_id)
        assert details.manifest["kernel"] == "local-bindings-2"
        inspection = diagnostics_inspection(details, "graph.sqlite")
        assert set(inspection["agent_bindings"]) == {"graph/nodes/red", "graph/nodes/blue"}


@pytest.mark.parametrize("concurrency", [1, 2])
def test_bound_graph_direct_tool_preserves_approval_and_cli_effect(tmp_path, concurrency):
    catalog = bound_catalog()
    catalog.register("provider", "chosen", "1", RecordingProvider("chosen"))
    writes, tools = [], ToolRegistry()
    tools.register(
        ToolSpec(
            "write", "Write", {"type": "object"}, effect="unqueryable_write", requires_approval=True
        ),
        lambda args, ctx: writes.append(ctx.effect_key) or "written",
    )
    wrapped = BoundDefinition(
        GraphWorkflowSpec(
            "mixed",
            [
                GraphNode("write", tool="write", input=Literal({})),
                GraphNode("answer", agent=AgentSpec("a", "Answer"), depends_on=("write",)),
            ],
            max_concurrency=concurrency,
        ),
        {"graph/nodes/answer": AgentBindingDescriptor(provider=choice("chosen"))},
    )
    with engine(tmp_path / "mixed.sqlite", catalog, tools=tools) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="submit")
        waiting = asyncio.run(runtime.drive(handle.run_id))
        assert waiting.state == "waiting_approval" and not writes
        details = runtime.diagnostics(handle.run_id)
        report = diagnostics_inspection(details, "mixed.sqlite")
        assert report["pending"][0]["effect"] == "unqueryable_write"
        action = runtime.store.run(handle.run_id)["actions"][-1]
        runtime.approve(handle.run_id, action["id"], action["digest"], command_id="approve")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert done.result["answer"]["provider"] == "chosen"
        assert len(writes) == 1


@pytest.mark.parametrize("concurrency", [1, 2])
def test_bound_graph_tool_subset_does_not_expand_host_grants(tmp_path, concurrency):
    catalog = bound_catalog()
    catalog.register("tool_set", "none", "1", [])
    catalog.register(
        "provider",
        "chosen",
        "1",
        ScriptedProvider([ModelResponse(tool_calls=(ToolCall("write", {}),))]),
    )
    writes, tools = [], ToolRegistry()
    tools.register(
        ToolSpec("write", "Write", {"type": "object"}), lambda a, c: writes.append("write")
    )
    wrapped = BoundDefinition(
        GraphWorkflowSpec(
            "deny",
            [GraphNode("a", agent=AgentSpec("a", "Answer", tools=("write",)))],
            max_concurrency=concurrency,
        ),
        {
            "graph/nodes/a": AgentBindingDescriptor(
                provider=choice("chosen"), tool_set=choice("none")
            ),
        },
    )
    with engine(tmp_path / "deny.sqlite", catalog, tools=tools) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "authorization_denied"
        assert writes == []


@pytest.mark.parametrize("concurrency", [1, 2])
def test_graph_model_response_survives_binding_identity_drift(tmp_path, concurrency):
    catalog = bound_catalog()

    class DriftingProvider(RecordingProvider):
        async def complete(self, messages, tools):
            self.label = "changed"
            return ModelResponse(output="received")

    catalog.register("provider", "chosen", "1", DriftingProvider("original"))
    wrapped = BoundDefinition(
        GraphWorkflowSpec(
            "drift", [GraphNode("a", agent=AgentSpec("a", "Answer"))], max_concurrency=concurrency
        ),
        {
            "graph/nodes/a": AgentBindingDescriptor(provider=choice("chosen")),
        },
    )
    with engine(tmp_path / "drift.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and done.error["code"] == "definition_mismatch"
        actions = runtime.store.run(handle.run_id)["actions"]
        assert actions[0]["received_response"]["output"] == "received"


def test_graph_refuses_explicit_session_with_stateless_node(tmp_path):
    wrapped = BoundDefinition(
        GraphWorkflowSpec("stateless", [GraphNode("a", agent=AgentSpec("a", "Answer"))]),
        {
            "graph/nodes/a": AgentBindingDescriptor(session=BindingSelection.disabled()),
        },
    )
    with engine(tmp_path / "session.sqlite", bound_catalog()) as runtime:
        with pytest.raises(ValidationError):
            runtime.submit(wrapped, "q", command_id="s", session_id="shared")


def test_bound_graph_compiler_cannot_change_agent_under_binding_path(tmp_path):
    class ChangingCompiler(StaticWorkflowCompiler):
        identity = {"kind": "changing-compiler", "version": "1"}

        def compile(self, spec):
            plan = super().compile(spec).to_dict()
            plan["nodes"][0]["agent"]["instructions"] = "Changed instructions"
            return ExecutionPlan(plan)

    wrapped = BoundDefinition(
        GraphWorkflowSpec("compiled", [GraphNode("a", agent=AgentSpec("a", "Answer"))]), {}
    )
    with engine(
        tmp_path / "compiler.sqlite", bound_catalog(), workflow_compiler=ChangingCompiler()
    ) as runtime:
        with pytest.raises(DefinitionMismatch):
            runtime.submit(wrapped, "q", command_id="s")


@pytest.mark.parametrize("concurrency", [1, 2])
def test_graph_reference_provider_does_not_require_unused_host_slot(tmp_path, concurrency):
    catalog = bound_catalog()
    catalog.register("provider", "chosen", "1", RecordingProvider("chosen"))
    wrapped = BoundDefinition(
        GraphWorkflowSpec(
            "selected",
            [GraphNode("a", agent=AgentSpec("a", "Answer", provider="not-configured"))],
            max_concurrency=concurrency,
        ),
        {
            "graph/nodes/a": AgentBindingDescriptor(provider=choice("chosen")),
        },
    )
    with engine(tmp_path / "provider.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert done.result["a"]["provider"] == "chosen"


def test_bound_graph_compiler_reordering_preserves_node_binding_identity(tmp_path):
    class ReorderingCompiler(StaticWorkflowCompiler):
        identity = {"kind": "reordering-compiler", "version": "1"}

        def compile(self, spec):
            plan = super().compile(spec).to_dict()
            plan["nodes"].reverse()
            return ExecutionPlan(plan)

    catalog = bound_catalog()
    for color in ("red", "blue"):
        catalog.register("provider", color, "1", RecordingProvider(color))
    wrapped = BoundDefinition(
        GraphWorkflowSpec(
            "reordered",
            [GraphNode(color, agent=AgentSpec("a", "Answer")) for color in ("red", "blue")],
            max_concurrency=2,
        ),
        {
            f"graph/nodes/{color}": AgentBindingDescriptor(provider=choice(color))
            for color in ("red", "blue")
        },
    )
    with engine(
        tmp_path / "reorder.sqlite", catalog, workflow_compiler=ReorderingCompiler()
    ) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert done.result["red"]["provider"] == "red" and done.result["blue"]["provider"] == "blue"


@pytest.mark.parametrize("concurrency", [1, 2])
def test_empty_binding_map_supports_tool_only_graph(tmp_path, concurrency):
    writes, tools = [], ToolRegistry()
    tools.register(
        ToolSpec("write", "Write", {"type": "object"}),
        lambda a, c: writes.append("one") or "written",
    )
    wrapped = BoundDefinition(
        GraphWorkflowSpec(
            "tools",
            [GraphNode("write", tool="write", input=Literal({}))],
            max_concurrency=concurrency,
        ),
        {},
    )
    with engine(tmp_path / "tools.sqlite", bound_catalog(), tools=tools) as runtime:
        handle = runtime.submit(wrapped, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert done.result == {"write": "written"} and writes == ["one"]
        diagnostics_inspection(runtime.diagnostics(handle.run_id), "tools.sqlite")
