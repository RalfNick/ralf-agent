"""Trusted Python tools with explicit effect contracts and fixed definitions."""

import copy
import inspect
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .errors import DefinitionMismatch, ValidationError
from .types import credits, digest


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    version: str = "1"
    effect: str = "read_only"
    requires_approval: bool = False
    cost: int = 1
    config: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.name or not self.version:
            raise ValidationError("Tool name and version must be non-empty")
        if self.effect not in {
            "read_only",
            "idempotent_write",
            "queryable_write",
            "unqueryable_write",
        }:
            raise ValidationError("Unknown tool effect category")
        credits(self.cost)
        try:
            Draft202012Validator.check_schema(self.input_schema)
        except SchemaError as exc:
            raise ValidationError("Invalid tool input Schema") from exc


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    handler: Callable
    reconciler: Callable | None
    implementation_digest: str

    @property
    def manifest(self):
        return {**asdict(self.spec), "implementation_digest": self.implementation_digest}

    def validate(self, arguments):
        if not isinstance(arguments, dict) or not Draft202012Validator(
            self.spec.input_schema
        ).is_valid(arguments):
            raise ValidationError(f"Arguments do not match Schema for tool {self.spec.name}")


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: Callable, *, reconciler: Callable | None = None):
        if spec.name in self._tools:
            raise DefinitionMismatch(f"Tool already registered: {spec.name}")
        if not callable(handler) or (reconciler is not None and not callable(reconciler)):
            raise ValidationError("Tool handlers and reconcilers must be callable")
        identities = []
        for function in (handler, reconciler):
            if function is None:
                identities.append(None)
                continue
            try:
                source = inspect.getsource(function)
            except (OSError, TypeError):
                source = None
            identities.append(
                {"module": function.__module__, "name": function.__qualname__, "source": source}
            )
        self._tools[spec.name] = RegisteredTool(
            copy.deepcopy(spec), handler, reconciler, digest(identities)
        )
        return handler

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise DefinitionMismatch(f"Tool not registered: {name}") from exc

    def manifests(self, names):
        return {name: copy.deepcopy(self.get(name).manifest) for name in names}

    def descriptions(self, names):
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.spec.name,
                    "description": tool.spec.description,
                    "parameters": copy.deepcopy(tool.spec.input_schema),
                },
            }
            for tool in (self.get(name) for name in names)
        ]


async def invoke(function, arguments: dict, context) -> Any:
    import asyncio

    if inspect.iscoroutinefunction(function):
        return await function(copy.deepcopy(arguments), context)
    # A trusted sync handler cannot block the coordinator's event loop.
    result = await asyncio.to_thread(function, copy.deepcopy(arguments), context)
    if inspect.isawaitable(result):
        return await result
    return result
