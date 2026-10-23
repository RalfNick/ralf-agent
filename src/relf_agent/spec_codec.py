"""Finite definition trees; codecs never import arbitrary application code."""

import json
from dataclasses import asdict

from .errors import ValidationError
from .types import AgentSpec, WorkflowSpec, canonical


def validate_definition_tree(value):
    encoded = canonical(value)
    if len(encoded.encode("utf-8")) > 1_048_576:
        raise ValidationError("Nested definitions exceed 1 MiB")
    stack, count = [(value, 0)], 0
    while stack:
        definition, depth = stack.pop()
        count += 1
        if depth > 8 or count > 256 or not isinstance(definition, dict):
            raise ValidationError("Definitions require at most 8 levels and 256 components")
        kind = definition.get("kind", "agent")
        if kind in {"team", "dynamic"}:
            members = definition.get("members")
            if not isinstance(members, dict):
                raise ValidationError("Nested members require an object")
            stack.extend((member, depth + 1) for member in members.values())
        elif kind == "sequence":
            steps = definition.get("steps")
            if not isinstance(steps, list):
                raise ValidationError("Nested sequence requires Agent steps")
            stack.extend((step, depth + 1) for step in steps)
        elif kind == "graph":
            nodes = definition.get("nodes")
            if not isinstance(nodes, list):
                raise ValidationError("Nested graph requires nodes")
            for node in nodes:
                if not isinstance(node, dict):
                    raise ValidationError("Nested graph requires object nodes")
                if node.get("agent") is not None:
                    stack.append((node["agent"], depth + 1))
        elif kind != "agent":
            raise ValidationError("Unsupported nested definition kind")
    return json.loads(encoded)


def encode_spec(spec):
    from .orchestration_types import DynamicWorkflowSpec, TeamSpec
    from .workflow import GraphWorkflowSpec

    if isinstance(spec, AgentSpec):
        return asdict(spec)  # Preserve the original flat-member representation.
    if isinstance(spec, WorkflowSpec):
        return {
            "kind": "sequence",
            "name": spec.name,
            "version": spec.version,
            "steps": [asdict(step) for step in spec.steps],
        }
    if isinstance(spec, (GraphWorkflowSpec, TeamSpec, DynamicWorkflowSpec)):
        return spec.to_dict()
    raise ValidationError("Members require Agent, sequence, graph, team or dynamic definitions")


def decode_spec(value):
    from .orchestration_types import DynamicWorkflowSpec, TeamSpec
    from .workflow import GraphWorkflowSpec

    value = validate_definition_tree(value)
    kind = value.pop("kind", "agent")
    try:
        if kind == "agent":
            return AgentSpec(**value)
        if kind == "sequence":
            return WorkflowSpec(
                **{**value, "steps": [AgentSpec(**step) for step in value["steps"]]}
            )
        if kind == "graph":
            return GraphWorkflowSpec.from_dict(value)
        if kind in {"team", "dynamic"}:
            return (TeamSpec if kind == "team" else DynamicWorkflowSpec).from_dict(value)
    except (TypeError, KeyError) as exc:
        raise ValidationError("Invalid nested definition fields") from exc
    raise ValidationError("Unsupported nested definition kind")


def agent_steps(definition):
    """Find every native capability without changing child execution semantics."""
    kind = definition.get("kind", "agent")
    if kind == "agent":
        return [definition] if "steps" not in definition else list(definition["steps"])
    if kind == "sequence":
        return list(definition["steps"])
    if kind == "graph":
        return [node["agent"] for node in definition["nodes"] if node["agent"] is not None]
    return [step for member in definition["members"].values() for step in agent_steps(member)]
