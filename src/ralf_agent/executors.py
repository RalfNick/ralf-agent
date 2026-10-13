"""Tool dispatch and observations; Run authority remains with the engine."""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .tools import ToolRegistry, invoke
from .types import InvocationContext, Scope, canonical, digest


@dataclass(frozen=True, init=False)
class DispatchEnvelope:
    """Immutable dispatch data for one approved, budgeted tool attempt.

    Manifest and argument views are detached JSON snapshots. Possession of an
    envelope is not authorization: the engine owns approvals and dispatch intent.
    """

    context: InvocationContext
    operation_digest: str
    _tool_manifest_json: str = field(repr=False)
    _arguments_json: str = field(repr=False)

    def __init__(
        self,
        context: InvocationContext,
        tool_manifest: dict,
        arguments: dict,
        operation_digest: str,
    ):
        if not isinstance(context, InvocationContext) or not isinstance(context.scope, Scope):
            raise ValidationError("Dispatch context must be an InvocationContext with a Scope")
        identifiers = (
            context.run_id,
            context.action_id,
            context.attempt_id,
            context.effect_key,
            context.execution_epoch,
        )
        if any(not isinstance(value, str) for value in identifiers):
            raise ValidationError("Dispatch context identifiers must be strings")
        if not isinstance(tool_manifest, dict):
            raise ValidationError("Dispatch tool manifest must be a JSON object")
        name = tool_manifest.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("Dispatch manifest must name a tool")
        if not isinstance(arguments, dict):
            raise ValidationError("Dispatch arguments must be a JSON object")
        if not isinstance(operation_digest, str) or not operation_digest.strip():
            raise ValidationError("Dispatch operation digest must be a non-empty string")
        # Scope and identifier fields are immutable; copying also strips any
        # additional mutable state supplied by a caller's Scope subclass.
        snapshot = InvocationContext(
            Scope(context.scope.workspace, context.scope.principal), *identifiers
        )
        object.__setattr__(self, "context", snapshot)
        object.__setattr__(self, "operation_digest", operation_digest)
        object.__setattr__(self, "_tool_manifest_json", canonical(tool_manifest))
        object.__setattr__(self, "_arguments_json", canonical(arguments))

    @property
    def tool_manifest(self) -> dict:
        return json.loads(self._tool_manifest_json)

    @property
    def arguments(self) -> dict:
        return json.loads(self._arguments_json)

    @property
    def tool_name(self) -> str:
        return self.tool_manifest["name"]


@dataclass(frozen=True, init=False)
class EffectObservation:
    """Finite JSON evidence, awaiting adoption by the execution authority."""

    source: str
    _result_json: str = field(repr=False)

    def __init__(self, result: Any, source: str = "tool-handler"):
        if not isinstance(source, str) or not source.strip():
            raise ValidationError("Effect observation source must be a non-empty string")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "_result_json", canonical(result))

    @property
    def result(self) -> Any:
        return json.loads(self._result_json)


@runtime_checkable
class ToolExecutor(Protocol):
    """Dispatch tools and query receipts without owning approvals or Run state."""

    identity: dict

    async def execute(self, envelope: DispatchEnvelope) -> EffectObservation: ...

    async def reconcile(self, envelope: DispatchEnvelope) -> EffectObservation | None: ...


class PythonToolExecutor:
    """Execute registered, trusted Python functions using their pinned manifest."""

    def __init__(self, registry: ToolRegistry):
        if not isinstance(registry, ToolRegistry):
            raise ValidationError("PythonToolExecutor requires a ToolRegistry")
        self.registry = registry

    @property
    def identity(self) -> dict:
        return {"kind": "python-tool-executor", "version": "1"}

    def _registered(self, envelope):
        if not isinstance(envelope, DispatchEnvelope):
            raise ValidationError("Tool executor requires a DispatchEnvelope")
        tool = self.registry.get(envelope.tool_name)
        if digest(tool.manifest) != digest(envelope.tool_manifest):
            raise DefinitionMismatch("Tool executor differs from the pinned tool manifest")
        tool.validate(envelope.arguments)
        from .delegated_coding import registered_coding_tool

        if registered_coding_tool(tool) is not None:
            raise AuthorizationDenied("Native Coding cannot use the ordinary ToolExecutor")
        return tool

    async def execute(self, envelope: DispatchEnvelope) -> EffectObservation:
        tool = self._registered(envelope)
        result = await invoke(tool.handler, envelope.arguments, envelope.context)
        return EffectObservation(result)

    async def reconcile(self, envelope: DispatchEnvelope) -> EffectObservation | None:
        tool = self._registered(envelope)
        if tool.reconciler is None:
            return None
        result = await invoke(tool.reconciler, envelope.arguments, envelope.context)
        return None if result is None else EffectObservation(result, source="tool-reconciler")
