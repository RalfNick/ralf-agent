"""Additive definition wrappers; legacy AgentSpec and parent encodings stay intact."""

import json
from dataclasses import asdict, dataclass

from .binding_paths import agent_paths
from .binding_types import AgentBindingDescriptor
from .errors import ValidationError
from .spec_codec import decode_spec, encode_spec
from .types import AgentSpec, canonical


@dataclass(frozen=True, init=False)
class AgentDefinition:
    _json: str

    def __init__(self, spec, bindings=None):
        bindings = AgentBindingDescriptor() if bindings is None else bindings
        if not isinstance(spec, AgentSpec) or not isinstance(bindings, AgentBindingDescriptor):
            raise ValidationError("AgentDefinition requires AgentSpec and AgentBindingDescriptor")
        object.__setattr__(
            self,
            "_json",
            canonical(
                {
                    "kind": "bound_agent",
                    "schema_version": 1,
                    "spec": asdict(spec),
                    "bindings": bindings.to_dict(),
                }
            ),
        )

    @property
    def spec(self):
        return AgentSpec(**json.loads(self._json)["spec"])

    @property
    def bindings(self):
        return AgentBindingDescriptor.from_dict(json.loads(self._json)["bindings"])

    def to_dict(self):
        return json.loads(self._json)


@dataclass(frozen=True, init=False)
class BoundDefinition:
    _json: str

    def __init__(self, definition, agent_bindings):
        encoded = encode_spec(definition)
        if encoded.get("kind") not in {"sequence", "graph", "team", "dynamic"}:
            raise ValidationError("BoundDefinition requires a Workflow, Graph, Team or Dynamic")
        if not isinstance(agent_bindings, dict):
            raise ValidationError("Agent bindings require a path mapping")
        known = set(agent_paths(encoded))
        if set(agent_bindings) - known:
            raise ValidationError("Binding path does not name a declared native Agent")
        if any(not isinstance(value, AgentBindingDescriptor) for value in agent_bindings.values()):
            raise ValidationError("Each binding path requires AgentBindingDescriptor")
        object.__setattr__(
            self,
            "_json",
            canonical(
                {
                    "kind": "bound_definition",
                    "schema_version": 1,
                    "definition": encoded,
                    "agent_bindings": {k: v.to_dict() for k, v in agent_bindings.items()},
                }
            ),
        )

    @property
    def definition(self):
        return decode_spec(json.loads(self._json)["definition"])

    @property
    def agent_bindings(self):
        return {
            k: AgentBindingDescriptor.from_dict(v)
            for k, v in json.loads(self._json)["agent_bindings"].items()
        }

    def to_dict(self):
        return json.loads(self._json)


def decode_definition(value):
    if not isinstance(value, dict):
        raise ValidationError("Definition requires a JSON object")
    value = json.loads(canonical(value))
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValidationError("Bound definition requires schema_version=1")
    try:
        if value.get("kind") == "bound_agent" and set(value) == {
            "kind",
            "schema_version",
            "spec",
            "bindings",
        }:
            return AgentDefinition(
                AgentSpec(**value["spec"]), AgentBindingDescriptor.from_dict(value["bindings"])
            )
        if value.get("kind") == "bound_definition" and set(value) == {
            "kind",
            "schema_version",
            "definition",
            "agent_bindings",
        }:
            return BoundDefinition(
                decode_spec(value["definition"]),
                {
                    k: AgentBindingDescriptor.from_dict(v)
                    for k, v in value["agent_bindings"].items()
                },
            )
    except (TypeError, AttributeError, KeyError) as exc:
        raise ValidationError("Invalid bound definition fields") from exc
    raise ValidationError("Unknown bound definition kind or fields")
