"""DAG proposals reuse the static graph's pure dependency/binding validator."""

from dataclasses import asdict

from .errors import ValidationError
from .orchestration_types import _identifier, _JsonValue
from .types import AgentSpec, _require_text, canonical
from .workflow import (
    BranchCondition,
    GraphNode,
    GraphWorkflowSpec,
    ValueRef,
    decode_binding,
    encode_binding,
)


class DAGNode(_JsonValue):
    def __init__(
        self,
        id,
        member,
        *,
        depends_on=(),
        input=None,
        when=None,
        allow_skipped_dependencies=False,
        output_schema=None,
    ):
        _identifier(member)
        node = GraphNode(
            id,
            agent=AgentSpec(member, "Delegated capability"),
            depends_on=depends_on,
            input=ValueRef() if input is None else input,
            when=when,
            allow_skipped_dependencies=allow_skipped_dependencies,
            output_schema=output_schema,
        ).to_dict()
        for field in ("agent", "transform", "config"):
            node.pop(field)
        node.pop("tool", None)
        self._data_json = canonical({**node, "member": member})

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValidationError("DAG nodes must be JSON objects")
        value = dict(value)
        try:
            value["input"] = decode_binding(value["input"])
            if value.get("when") is not None:
                condition = value["when"]
                if not isinstance(condition, dict) or set(condition) - {
                    "value",
                    "equals",
                    "negate",
                }:
                    raise ValidationError("Invalid DAG condition fields")
                value["when"] = BranchCondition(
                    decode_binding(condition["value"]),
                    condition["equals"],
                    condition.get("negate", False),
                )
            return cls(**value)
        except (TypeError, KeyError) as exc:
            raise ValidationError("Invalid DAG node fields") from exc

    def as_graph_node(self):
        value = self.to_dict()
        member = value.pop("member")
        return GraphNode.from_dict(
            {
                **value,
                "agent": asdict(AgentSpec(member, "Delegated capability")),
                "transform": None,
                "config": {},
            }
        )


class DAGProposal(_JsonValue):
    def __init__(self, nodes, *, output=None, output_schema=None):
        if (
            not isinstance(nodes, (tuple, list))
            or not 1 <= len(nodes) <= 256
            or any(not isinstance(node, DAGNode) for node in nodes)
        ):
            raise ValidationError("DAG proposals require 1 to 256 typed nodes")
        # The same static validator checks cycles, ancestor references and Schemas.
        GraphWorkflowSpec(
            "dag-proposal",
            [node.as_graph_node() for node in nodes],
            output=output,
            output_schema=output_schema,
        )
        self._data_json = canonical(
            {
                "status": "plan",
                "nodes": [node.to_dict() for node in nodes],
                "output": None if output is None else encode_binding(output),
                "output_schema": output_schema,
            }
        )

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValidationError("DAG proposal requires an object")
        value = dict(value)
        if value.pop("status", "plan") != "plan":
            raise ValidationError("DAG proposal status must be plan")
        try:
            value["nodes"] = [DAGNode.from_dict(node) for node in value["nodes"]]
            if value.get("output") is not None:
                value["output"] = decode_binding(value["output"])
            return cls(**value)
        except (TypeError, KeyError) as exc:
            raise ValidationError("Invalid DAG proposal fields") from exc

    def validate_members(self, members):
        if any(node["member"] not in members for node in self.nodes):
            raise ValidationError("DAG nodes must reference registered members")

    def graph(self):
        return GraphWorkflowSpec(
            "dag-proposal",
            [DAGNode.from_dict(node).as_graph_node() for node in self.nodes],
            output=None if self.output is None else decode_binding(self.output),
            output_schema=self.output_schema,
        )


class PlanningConclusion(_JsonValue):
    def __init__(self, status, reason):
        if status not in {"refused", "needs_input"}:
            raise ValidationError("Planning conclusion must refuse or request input")
        _require_text(reason, "Planning conclusion reason")
        self._data_json = canonical({"status": status, "reason": reason})


class RuleDAGPlanner:
    identity = {"kind": "rule-dag-planner", "version": "1"}

    async def plan(self, request, caller):
        nodes = []
        for index, member in enumerate(request.members):
            previous = None if index == 0 else f"step-{index - 1}"
            nodes.append(
                DAGNode(
                    f"step-{index}",
                    member,
                    depends_on=() if previous is None else (previous,),
                    input=ValueRef() if previous is None else ValueRef(previous),
                )
            )
        return DAGProposal(nodes, output=ValueRef(nodes[-1].id))


def dag_output_schema():
    binding = {
        "type": "object",
        "required": ["kind"],
        "properties": {"kind": {"enum": ["ref", "literal", "object"]}},
    }
    node = {
        "type": "object",
        "required": ["id", "member", "depends_on", "input"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string"},
            "member": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
            "input": binding,
            "when": {"type": ["object", "null"]},
            "allow_skipped_dependencies": {"type": "boolean"},
            "output_schema": {},
        },
    }
    return {
        "oneOf": [
            {
                "type": "object",
                "required": ["status", "nodes", "output"],
                "additionalProperties": False,
                "properties": {
                    "status": {"const": "plan"},
                    "nodes": {"type": "array", "minItems": 1, "maxItems": 256, "items": node},
                    "output": {"anyOf": [binding, {"type": "null"}]},
                    "output_schema": {},
                },
            },
            {
                "type": "object",
                "required": ["status", "reason"],
                "additionalProperties": False,
                "properties": {
                    "status": {"enum": ["refused", "needs_input"]},
                    "reason": {"type": "string", "minLength": 1},
                },
            },
        ]
    }


class ModelDAGPlanner:
    def __init__(self, *, provider="default", instructions=None, version="1"):
        self.agent = AgentSpec(
            "dag-planner",
            instructions
            or (
                "Return a JSON DAG using only registered member names. Return status plan with "
                "nodes (id, member, depends_on, input binding) and output binding. "
                "Bindings are {kind:ref,source:input|node_id,path:[],required:true,default:null}, "
                "{kind:literal,value:...}, or {kind:object,fields:{key:binding}}. "
                "Node value references must name a dependency ancestor. "
                "For unsafe tasks return {status:refused,reason:...}; when evidence/target is "
                "missing return {status:needs_input,reason:...}. Never execute tools."
            ),
            provider=provider,
            version=version,
            max_decisions=1,
            output_schema=dag_output_schema(),
        )

    @property
    def identity(self):
        return {"kind": "model-dag-planner", "version": "1", "agent": asdict(self.agent)}

    async def plan(self, request, caller):
        snapshot = await caller.call("planner", "@planner", request.to_dict())
        if snapshot.state not in {"succeeded", "failed", "cancelled"}:
            return None
        if snapshot.state != "succeeded":
            raise ValidationError("Managed DAG planner did not succeed")
        value = snapshot.result
        if value.get("status") in {"refused", "needs_input"}:
            return PlanningConclusion(**value)
        proposal = DAGProposal.from_dict(value)
        proposal.validate_members(request.members)
        return proposal
