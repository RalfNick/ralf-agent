"""Borrowed async tool sources, explicit host policies and fixed registrations."""

import copy
import inspect
import json
from dataclasses import dataclass, field
from typing import Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .errors import DefinitionMismatch, RalfError, ValidationError
from .tools import ToolRegistry, ToolSpec
from .types import InvocationContext, canonical, credits, digest


class ToolSourceError(RalfError):
    code = "tool_source_error"


@dataclass(frozen=True, init=False)
class ToolDescriptor:
    name: str
    description: str
    _schema_json: str = field(repr=False)
    _output_json: str = field(repr=False)

    def __init__(self, name, description, input_schema, output_schema=None):
        if not isinstance(name, str) or not name.strip() or not isinstance(description, str):
            raise ValidationError("Tool descriptor requires a name and description")
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            raise ValidationError("Remote tool input Schema must describe an object")
        for schema in (input_schema, output_schema):
            canonical(schema)
            if schema is not None:
                try:
                    Draft202012Validator.check_schema(schema)
                except SchemaError as exc:
                    raise ValidationError("Invalid remote tool Schema") from exc
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "_schema_json", canonical(input_schema))
        object.__setattr__(self, "_output_json", canonical(output_schema))

    @property
    def input_schema(self):
        return json.loads(self._schema_json)

    @property
    def output_schema(self):
        return json.loads(self._output_json)

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


@dataclass(frozen=True)
class ToolPolicy:
    version: str
    effect: str = "unqueryable_write"
    requires_approval: bool = True
    cost: int = 1
    effect_key_argument: str | None = None
    reconciler: object = field(default=None, repr=False)

    def __post_init__(self):
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValidationError("Remote tool policy requires an explicit version")
        if self.effect not in {
            "read_only",
            "idempotent_write",
            "queryable_write",
            "unqueryable_write",
        }:
            raise ValidationError("Unknown remote effect category")
        if type(self.requires_approval) is not bool:
            raise ValidationError("Remote approval policy must be a boolean")
        credits(self.cost)
        if self.effect == "idempotent_write" and self.effect_key_argument is None:
            raise ValidationError(
                "Idempotent remote writes require an explicit effect-key argument"
            )
        if self.effect_key_argument is not None and (
            not isinstance(self.effect_key_argument, str) or not self.effect_key_argument.strip()
        ):
            raise ValidationError("Effect-key argument must be a non-empty string")
        if (self.reconciler is not None and not callable(self.reconciler)) or (
            self.effect == "queryable_write" and self.reconciler is None
        ):
            raise ValidationError("Queryable writes require an explicit reconciler")


class ToolSource(Protocol):
    identity: dict

    async def list_tools(self) -> tuple[ToolDescriptor, ...]: ...

    async def call_tool(
        self, descriptor: ToolDescriptor, arguments: dict, context: InvocationContext
    ): ...


def _identity(source):
    value = getattr(source, "identity", None)
    if not isinstance(value, dict) or not value:
        raise ValidationError("Tool source requires a stable JSON identity")
    canonical(value)
    return copy.deepcopy(value)


def _caller_schema(descriptor, policy):
    schema = descriptor.input_schema
    key = policy.effect_key_argument
    if key is None:
        return schema
    # General JSON Schema rewrites (conditionals, refs, minProperties) cannot
    # safely remove a reserved field. Require a flat object root explicitly.
    if set(schema) - {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "title",
        "description",
    }:
        raise ValidationError("Reserved effect keys require a flat object root Schema")
    properties = schema.get("properties", {})
    if (
        key not in properties
        or not isinstance(properties[key], dict)
        or properties[key].get("type") != "string"
    ):
        raise ValidationError("Reserved effect key must name a declared string property")
    properties.pop(key)
    # Removing a property alone does not forbid it when extra fields are allowed.
    schema["not"] = {"required": [key]}
    if "required" in schema:
        schema["required"] = [name for name in schema["required"] if name != key]
    return schema


class _SourceBinding:
    def __init__(self, source, identity, descriptor, policy, schema):
        self.source = source
        self._identity_json = canonical(identity)
        self.descriptor = descriptor
        self.policy = policy
        self._schema_json = canonical(schema)

    def _check(self):
        if canonical(_identity(self.source)) != self._identity_json:
            raise DefinitionMismatch("The executing tool source changed")

    async def call(self, arguments, context):
        self._check()
        values = copy.deepcopy(arguments)
        if not isinstance(values, dict) or not Draft202012Validator(
            json.loads(self._schema_json)
        ).is_valid(values):
            raise ValidationError("Tool source arguments do not match caller Schema")
        key = self.policy.effect_key_argument
        if key is not None:
            if key in values:
                raise ValidationError("Caller cannot supply the reserved effect key")
            values[key] = context.effect_key
        if not Draft202012Validator(self.descriptor.input_schema).is_valid(values):
            raise ValidationError("Tool source arguments do not match remote Schema")
        result = await self.source.call_tool(self.descriptor, values, context)
        if inspect.iscoroutine(result) or inspect.isgenerator(result):
            result.close()
        canonical(result)
        self._check()
        return copy.deepcopy(result)


async def register_tool_source(registry, source, *, policies, prefix=""):
    if not isinstance(registry, ToolRegistry) or not isinstance(prefix, str):
        raise ValidationError("Register a tool source into ToolRegistry with a string prefix")
    if (
        not isinstance(policies, dict)
        or not policies
        or any(
            not isinstance(name, str) or not name.strip() or not isinstance(policy, ToolPolicy)
            for name, policy in policies.items()
        )
    ):
        raise ValidationError("Select remote tools with explicit ToolPolicy values")
    for method in ("list_tools", "call_tool"):
        if not inspect.iscoroutinefunction(getattr(source, method, None)):
            raise ValidationError("Tool source methods must be async")
    identity = _identity(source)
    descriptors = await source.list_tools()
    if digest(identity) != digest(_identity(source)):
        raise DefinitionMismatch("The discovering tool source changed")
    if (
        not isinstance(descriptors, (tuple, list))
        or len(descriptors) > 256
        or any(not isinstance(item, ToolDescriptor) for item in descriptors)
    ):
        raise ValidationError("Tool source returned invalid descriptors")
    by_name = {item.name: item for item in descriptors}
    if len(by_name) != len(descriptors) or set(policies) - by_name.keys():
        raise ValidationError("Tool source has duplicate or missing selected names")
    entries, names = [], []
    for name, policy in policies.items():
        descriptor = ToolDescriptor(**by_name[name].to_dict())
        schema = _caller_schema(descriptor, policy)
        local_name = prefix + name
        binding = _SourceBinding(source, identity, descriptor, policy, schema)
        spec = ToolSpec(
            local_name,
            descriptor.description,
            schema,
            policy.version,
            policy.effect,
            policy.requires_approval,
            policy.cost,
            {
                "source": identity,
                "remote_tool": descriptor.to_dict(),
                "effect_key_argument": policy.effect_key_argument,
            },
        )
        entries.append((spec, binding.call, policy.reconciler))
        names.append(local_name)
    registry.register_many(entries)
    return tuple(names)
