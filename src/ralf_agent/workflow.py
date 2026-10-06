"""Finite, versioned static plans and pure compilation/selection contracts."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as SchemaValidationError

from .errors import ValidationError
from .types import AgentSpec, WorkflowSpec, _require_text, canonical, digest


def _schema(schema):
    if schema is not None:
        canonical(schema)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValidationError("Invalid Workflow output Schema") from exc
    return copy.deepcopy(schema)


def validate_output(value, schema):
    canonical(value)
    if schema is not None:
        try:
            Draft202012Validator(schema).validate(value)
        except SchemaValidationError as exc:
            raise ValidationError("Workflow output does not match its Schema") from exc
    return copy.deepcopy(value)


@dataclass(frozen=True)
class ValueRef:
    source: str = "input"
    path: tuple[str | int, ...] = ()
    required: bool = True
    default: Any = None

    def __post_init__(self):
        _require_text(self.source, "Value reference source")
        if (
            not isinstance(self.path, (tuple, list))
            or len(self.path) > 32
            or any(not isinstance(p, str) and not (type(p) is int and p >= 0) for p in self.path)
            or type(self.required) is not bool
        ):
            raise ValidationError("Invalid value reference path or required flag")
        canonical(self.default)
        object.__setattr__(self, "path", tuple(self.path))
        object.__setattr__(self, "default", copy.deepcopy(self.default))


@dataclass(frozen=True)
class Literal:
    value: Any

    def __post_init__(self):
        canonical(self.value)
        object.__setattr__(self, "value", copy.deepcopy(self.value))


@dataclass(frozen=True)
class InputMap:
    fields: dict[str, ValueRef | Literal]

    def __post_init__(self):
        if not isinstance(self.fields, dict) or any(
            not isinstance(key, str) or not isinstance(value, (ValueRef, Literal))
            for key, value in self.fields.items()
        ):
            raise ValidationError("InputMap requires string fields with ValueRef or Literal")
        object.__setattr__(self, "fields", copy.deepcopy(self.fields))


Binding = ValueRef | Literal | InputMap


def encode_binding(value):
    if isinstance(value, ValueRef):
        return {"kind": "ref", **asdict(value)}
    if isinstance(value, Literal):
        return {"kind": "literal", "value": copy.deepcopy(value.value)}
    if isinstance(value, InputMap):
        return {"kind": "object", "fields": {k: encode_binding(v) for k, v in value.fields.items()}}
    raise ValidationError("Workflow values require an explicit binding")


def decode_binding(value):
    if not isinstance(value, dict):
        raise ValidationError("Workflow binding must be an object")
    value = copy.deepcopy(value)
    kind = value.pop("kind", None)
    try:
        if kind == "ref":
            return ValueRef(**value)
        if kind == "literal":
            return Literal(**value)
        if kind == "object" and set(value) == {"fields"} and isinstance(value["fields"], dict):
            return InputMap({key: decode_binding(item) for key, item in value["fields"].items()})
    except TypeError as exc:
        raise ValidationError("Invalid Workflow binding fields") from exc
    raise ValidationError("Unknown or invalid Workflow binding kind")


@dataclass(frozen=True)
class BranchCondition:
    value: ValueRef
    equals: Any
    negate: bool = False

    def __post_init__(self):
        if not isinstance(self.value, ValueRef) or type(self.negate) is not bool:
            raise ValidationError("Condition requires a ValueRef and boolean negate")
        canonical(self.equals)
        object.__setattr__(self, "value", copy.deepcopy(self.value))
        object.__setattr__(self, "equals", copy.deepcopy(self.equals))


@dataclass(frozen=True)
class GraphNode:
    id: str
    agent: AgentSpec | None = None
    transform: str | None = None
    depends_on: tuple[str, ...] = ()
    input: Binding = field(default_factory=ValueRef)
    when: BranchCondition | None = None
    allow_skipped_dependencies: bool = False
    config: dict = field(default_factory=dict)
    output_schema: dict | bool | None = None

    def __post_init__(self):
        if (
            not isinstance(self.id, str)
            or self.id == "input"
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", self.id)
        ):
            raise ValidationError("Node requires a stable identifier (input is reserved)")
        if (self.agent is None) == (self.transform is None):
            raise ValidationError("Node requires exactly one Agent or pure transform")
        if self.agent is not None and not isinstance(self.agent, AgentSpec):
            raise ValidationError("Agent node requires AgentSpec")
        if self.transform is not None:
            _require_text(self.transform, "Transform name")
        if (
            not isinstance(self.depends_on, (tuple, list))
            or any(not isinstance(name, str) or not name for name in self.depends_on)
            or type(self.allow_skipped_dependencies) is not bool
            or not isinstance(self.config, dict)
            or (self.agent is not None and self.config)
            or (self.when is not None and not isinstance(self.when, BranchCondition))
        ):
            raise ValidationError("Invalid Workflow node configuration")
        encode_binding(self.input)
        canonical(self.config)
        object.__setattr__(self, "depends_on", tuple(self.depends_on))
        for name in ("agent", "input", "when", "config"):
            object.__setattr__(self, name, copy.deepcopy(getattr(self, name)))
        object.__setattr__(self, "output_schema", _schema(self.output_schema))

    def to_dict(self):
        return {
            "id": self.id,
            "agent": None if self.agent is None else asdict(self.agent),
            "transform": self.transform,
            "depends_on": list(self.depends_on),
            "input": encode_binding(self.input),
            "when": None
            if self.when is None
            else {
                "value": encode_binding(self.when.value),
                "equals": copy.deepcopy(self.when.equals),
                "negate": self.when.negate,
            },
            "allow_skipped_dependencies": self.allow_skipped_dependencies,
            "config": copy.deepcopy(self.config),
            "output_schema": copy.deepcopy(self.output_schema),
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValidationError("Workflow node must be an object")
        value = copy.deepcopy(value)
        try:
            if value.get("agent") is not None:
                value["agent"] = AgentSpec(**value["agent"])
            if "input" in value:
                value["input"] = decode_binding(value["input"])
            if value.get("when") is not None:
                when = value["when"]
                value["when"] = BranchCondition(**{**when, "value": decode_binding(when["value"])})
            return cls(**value)
        except (TypeError, KeyError) as exc:
            raise ValidationError("Invalid Workflow node declaration") from exc


def _references(binding):
    if isinstance(binding, ValueRef):
        return {binding.source} - {"input"}
    if isinstance(binding, InputMap):
        return set().union(*(_references(value) for value in binding.fields.values()))
    return set()


def _validate_nodes(nodes, output):
    if (
        not isinstance(nodes, (tuple, list))
        or not 1 <= len(nodes) <= 256
        or any(not isinstance(n, GraphNode) for n in nodes)
    ):
        raise ValidationError("Workflow requires 1 to 256 GraphNodes")
    by_id = {node.id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValidationError("Duplicate Workflow node identifier")
    for node in nodes:
        if len(set(node.depends_on)) != len(node.depends_on) or set(node.depends_on) - by_id.keys():
            raise ValidationError("Duplicate or unknown Workflow dependency")
    ancestors = {}
    remaining = list(nodes)
    while remaining:
        ready = [node for node in remaining if all(dep in ancestors for dep in node.depends_on)]
        if not ready:
            raise ValidationError("Workflow dependency cycle")
        for node in ready:
            ancestors[node.id] = set(node.depends_on).union(
                *(ancestors[dep] for dep in node.depends_on)
            )
            refs = _references(node.input)
            if node.when is not None:
                refs |= _references(node.when.value)
            if refs - ancestors[node.id]:
                raise ValidationError("Node reference must name a dependency ancestor")
            remaining.remove(node)
    if output is not None and _references(output) - by_id.keys():
        raise ValidationError("Output reference names an unknown node")


@dataclass(frozen=True, init=False)
class ExecutionPlan:
    _data_json: str

    def __init__(self, value):
        fields = {"format", "schema_version", "name", "version", "nodes", "output", "output_schema"}
        if (
            not isinstance(value, dict)
            or set(value) != fields
            or value["format"] != "ralf-static-plan"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise ValidationError("Unsupported static execution plan format")
        _require_text(value["name"], "Workflow name")
        _require_text(value["version"], "Workflow version")
        if not isinstance(value["nodes"], (list, tuple)):
            raise ValidationError("Plan nodes must be a list")
        nodes = [GraphNode.from_dict(node) for node in value["nodes"]]
        output = None if value["output"] is None else decode_binding(value["output"])
        _validate_nodes(nodes, output)
        normalized = {
            **value,
            "nodes": [node.to_dict() for node in nodes],
            "output": None if output is None else encode_binding(output),
            "output_schema": _schema(value["output_schema"]),
        }
        encoded = canonical(normalized)
        if len(encoded.encode("utf-8")) > 1048576:
            raise ValidationError("Static execution plan exceeds 1 MiB")
        object.__setattr__(self, "_data_json", encoded)

    def to_dict(self):
        return json.loads(self._data_json)

    @property
    def identity(self):
        return {"format": "ralf-static-plan", "schema_version": 1, "digest": digest(self.to_dict())}


@dataclass(frozen=True, init=False)
class GraphWorkflowSpec:
    _data_json: str

    def __init__(self, name, nodes, version="1", output=None, output_schema=None):
        _validate_nodes(nodes, output)
        plan = ExecutionPlan(
            {
                "format": "ralf-static-plan",
                "schema_version": 1,
                "name": name,
                "version": version,
                "nodes": [node.to_dict() for node in nodes],
                "output": None if output is None else encode_binding(output),
                "output_schema": output_schema,
            }
        )
        value = plan.to_dict()
        value.pop("format")
        value.pop("schema_version")
        object.__setattr__(self, "_data_json", canonical({"kind": "graph", **value}))

    def to_dict(self):
        return json.loads(self._data_json)

    @property
    def name(self):
        return self.to_dict()["name"]

    @property
    def version(self):
        return self.to_dict()["version"]

    @property
    def nodes(self):
        return tuple(GraphNode.from_dict(value) for value in self.to_dict()["nodes"])

    @classmethod
    def from_plan(cls, plan):
        if not isinstance(plan, ExecutionPlan):
            raise ValidationError("Convert an ExecutionPlan to a graph declaration")
        value = plan.to_dict()
        value.pop("format")
        value.pop("schema_version")
        return cls.from_dict(value)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValidationError("Graph declaration must be an object")
        value = copy.deepcopy(value)
        try:
            if value.pop("kind", "graph") != "graph":
                raise ValidationError("Graph declaration kind must be graph")
            value["nodes"] = [GraphNode.from_dict(node) for node in value["nodes"]]
            if value.get("output") is not None:
                value["output"] = decode_binding(value["output"])
            return cls(**value)
        except (TypeError, KeyError) as exc:
            raise ValidationError("Invalid Graph Workflow declaration") from exc


class WorkflowCompiler(Protocol):
    identity: dict

    def compile(self, spec: AgentSpec | WorkflowSpec | GraphWorkflowSpec) -> ExecutionPlan: ...


class StaticWorkflowCompiler:
    identity = {"kind": "static-workflow-compiler", "version": "1"}

    def compile(self, spec):
        if isinstance(spec, GraphWorkflowSpec):
            value = spec.to_dict()
            value.pop("kind")
            return ExecutionPlan({"format": "ralf-static-plan", "schema_version": 1, **value})
        if isinstance(spec, AgentSpec):
            name, version, steps = spec.name, spec.version, (spec,)
        elif isinstance(spec, WorkflowSpec):
            name, version, steps = spec.name, spec.version, spec.steps
        else:
            raise ValidationError("Compile an Agent, sequence or Graph Workflow")
        nodes = [
            GraphNode(
                f"step-{i}",
                agent=step,
                depends_on=() if i == 0 else (f"step-{i - 1}",),
                input=ValueRef() if i == 0 else ValueRef(f"step-{i - 1}"),
            )
            for i, step in enumerate(steps)
        ]
        return self.compile(GraphWorkflowSpec(name, nodes, version, ValueRef(nodes[-1].id)))


def _resolve(binding, root_input, states):
    if isinstance(binding, Literal):
        return copy.deepcopy(binding.value)
    if isinstance(binding, InputMap):
        return {key: _resolve(item, root_input, states) for key, item in binding.fields.items()}
    missing = object()
    if binding.source == "input":
        result = root_input
    else:
        record = states.get(binding.source, {})
        result = record.get("result", missing) if record.get("state") == "completed" else missing
    for key in binding.path:
        if isinstance(key, str) and isinstance(result, dict):
            result = result.get(key, missing)
        elif type(key) is int and isinstance(result, list) and key < len(result):
            result = result[key]
        else:
            result = missing
        if result is missing:
            break
    if result is missing:
        if binding.required:
            raise ValidationError("Required Workflow value reference is missing")
        result = binding.default
    return copy.deepcopy(result)


@dataclass(frozen=True)
class WorkflowSelection:
    node_id: str | None = None
    input: Any = None
    skipped: tuple[str, ...] = ()
    done: bool = False
    result: Any = None

    def __post_init__(self):
        if (
            type(self.done) is not bool
            or (self.node_id is not None and not isinstance(self.node_id, str))
            or not isinstance(self.skipped, (tuple, list))
            or any(not isinstance(n, str) for n in self.skipped)
        ):
            raise ValidationError("Invalid Workflow selection")
        canonical(self.input)
        canonical(self.result)
        object.__setattr__(self, "input", copy.deepcopy(self.input))
        object.__setattr__(self, "result", copy.deepcopy(self.result))
        object.__setattr__(self, "skipped", tuple(self.skipped))


def _choices(plan, root_input, states):
    if not isinstance(plan, ExecutionPlan):
        raise ValidationError("Interpreter requires ExecutionPlan")
    value = plan.to_dict()
    nodes = [GraphNode.from_dict(node) for node in value["nodes"]]
    if not isinstance(states, dict) or set(states) != {node.id for node in nodes}:
        raise ValidationError("Workflow state must include every node")
    state = copy.deepcopy(states)
    for record in state.values():
        if (
            not isinstance(record, dict)
            or record.get("state") not in {"pending", "completed", "skipped"}
            or (record["state"] == "completed" and "result" not in record)
        ):
            raise ValidationError("Workflow selection requires settled or pending nodes")
        canonical(record)
    skipped = []
    while True:
        ready, newly_skipped = [], []
        for node in nodes:
            if state[node.id]["state"] != "pending" or any(
                state[dep]["state"] == "pending" for dep in node.depends_on
            ):
                continue
            skip = not node.allow_skipped_dependencies and any(
                state[dep]["state"] == "skipped" for dep in node.depends_on
            )
            if not skip and node.when is not None:
                matched = canonical(_resolve(node.when.value, root_input, state)) == canonical(
                    node.when.equals
                )
                skip = matched == node.when.negate
            if skip:
                state[node.id] = {"state": "skipped"}
                newly_skipped.append(node.id)
            else:
                ready.append(node)
        skipped.extend(newly_skipped)
        if not newly_skipped:
            break
    if ready:
        return ready, tuple(skipped), state, None
    if any(record["state"] == "pending" for record in state.values()):
        raise ValidationError("Workflow has no eligible node")
    result = (
        {key: record["result"] for key, record in state.items() if record["state"] == "completed"}
        if value["output"] is None
        else _resolve(decode_binding(value["output"]), root_input, state)
    )
    return [], tuple(skipped), state, validate_output(result, value["output_schema"])


class WorkflowInterpreter(Protocol):
    identity: dict

    def select(self, plan: ExecutionPlan, input: Any, states: dict) -> WorkflowSelection: ...


class StaticWorkflowInterpreter:
    identity = {"kind": "static-workflow-interpreter", "version": "1"}

    def select(self, plan, input, states):
        ready, skipped, settled, result = _choices(plan, input, states)
        if not ready:
            return WorkflowSelection(skipped=skipped, done=True, result=result)
        node = ready[0]
        return WorkflowSelection(node.id, _resolve(node.input, input, settled), skipped)


def validate_selection(plan, root_input, states, selection):
    """Host strategies may choose a ready node, never rewrite plan semantics."""
    ready, skipped, settled, result = _choices(plan, root_input, states)
    if len(selection.skipped) != len(skipped) or set(selection.skipped) != set(skipped):
        raise ValidationError("Interpreter returned invalid skipped nodes")
    if not ready:
        if (
            not selection.done
            or selection.node_id is not None
            or selection.input is not None
            or canonical(selection.result) != canonical(result)
        ):
            raise ValidationError("Interpreter returned invalid Workflow completion")
    else:
        node = next((node for node in ready if node.id == selection.node_id), None)
        if (
            node is None
            or selection.done
            or selection.result is not None
            or canonical(selection.input) != canonical(_resolve(node.input, root_input, settled))
        ):
            raise ValidationError("Interpreter returned an ineligible node or input")


class NodeTransform(Protocol):
    identity: dict

    def transform(self, input: Any, config: dict) -> Any: ...


class IdentityTransform:
    identity = {"kind": "identity-transform", "version": "1"}

    def transform(self, input, config):
        if config:
            raise ValidationError("IdentityTransform accepts an empty config")
        canonical(input)
        return copy.deepcopy(input)
