"""Stable binding paths across original graph/team/dynamic declaration trees."""

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    TeamSpec,
    WorkflowSpec,
)
from relf_agent.binding_definitions import decode_definition
from relf_agent.errors import ValidationError
from relf_agent.types import submission_request


def selected(label="chosen", **roles):
    return AgentBindingDescriptor(provider=BindingSelection.ref(label, "1"), **roles)


def graph():
    return GraphWorkflowSpec("research", [GraphNode("read", agent=AgentSpec("reader", "Answer"))])


@pytest.mark.parametrize(
    ("spec", "path"),
    [
        (graph(), "graph/nodes/read"),
        (TeamSpec("team", {"reader": AgentSpec("reader", "Answer")}), "team/members/reader"),
        (
            DynamicWorkflowSpec("plan", {"worker": AgentSpec("worker", "Answer")}),
            "dynamic/members/worker",
        ),
        (
            TeamSpec("outer", {"research": graph()}),
            "team/members/research/graph/nodes/read",
        ),
        (
            DynamicWorkflowSpec(
                "outer", {"research": WorkflowSpec("steps", [AgentSpec("reader", "Answer")])}
            ),
            "dynamic/members/research/sequence/steps/0",
        ),
        (
            TeamSpec("outer", {"inner": TeamSpec("inner", {"worker": graph()})}),
            "team/members/inner/team/members/worker/graph/nodes/read",
        ),
    ],
)
def test_composite_codec_preserves_original_definition_and_stable_binding_path(spec, path):
    original = submission_request(spec, "question")
    bound = BoundDefinition(spec, {path: selected()})
    restored = decode_definition(bound.to_dict())
    assert restored.to_dict() == bound.to_dict()
    assert restored.agent_bindings[path].provider.component_id == "chosen"
    assert submission_request(spec, "question") == original
    changed = bound.to_dict()
    changed["agent_bindings"][path]["provider"]["component_id"] = "mutated"
    assert bound.agent_bindings[path].provider.component_id == "chosen"


@pytest.mark.parametrize(
    "path",
    ["graph/nodes/missing", "graph/nodes/read/agent", "sequence/steps/0", 1],
)
def test_graph_binding_rejects_nonexistent_or_ambiguous_paths(path):
    with pytest.raises(ValidationError):
        BoundDefinition(graph(), {path: selected()})


def test_binding_cannot_target_transform_or_container_or_planner():
    spec = GraphWorkflowSpec("pure", [GraphNode("copy", transform="identity")])
    with pytest.raises(ValidationError):
        BoundDefinition(spec, {"graph/nodes/copy": selected()})
    with pytest.raises(ValidationError):
        BoundDefinition(
            TeamSpec("outer", {"research": graph()}), {"team/members/research": selected()}
        )
    with pytest.raises(ValidationError):
        BoundDefinition(
            DynamicWorkflowSpec("plan", {"worker": AgentSpec("a", "Answer")}),
            {"dynamic/members/@planner": selected()},
        )


def test_composite_binding_values_must_be_descriptors():
    with pytest.raises(ValidationError):
        BoundDefinition(graph(), {"graph/nodes/read": None})
