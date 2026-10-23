"""Explicit native tool registration; only the execution authority may dispatch.

Resources are borrowed by this descriptor. A marker or DispatchEnvelope alone
never permits a native call. The generic Python executor cannot invoke it.
"""

import copy
import json

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .ports import is_async_callable
from .runner_journal_state import _json
from .task_controls import _binding
from .types import canonical

CODING_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"task": {"type": "string", "minLength": 1, "maxLength": 8192}},
    "required": ["task"],
    "additionalProperties": False,
}
_METHODS = ("execute", "reconcile", "stop_existing", "aclose")


class CodingToolHandler:
    """Pinned borrowed resource; callable only to reject ordinary execution."""

    def __init__(self, runner):
        if any(not is_async_callable(getattr(runner, name, None)) for name in _METHODS):
            raise ValidationError("Coding resource requires an explicit async lifecycle")
        self._runner = runner
        self._identity_json = _json(getattr(runner, "identity", None), "Coding resource identity")
        self._bindings = {name: _binding(getattr(runner, name)) for name in _METHODS}
        self.check()

    @property
    def identity(self):
        return json.loads(self._identity_json)

    @property
    def runner(self):
        self.check()
        return self._runner

    def check(self):
        from .binding_artifacts import _same_binding

        try:
            if _json(self._runner.identity, "Coding resource identity") != self._identity_json:
                raise DefinitionMismatch("Original Coding resource identity changed")
            for name, expected in self._bindings.items():
                method = getattr(self._runner, name, None)
                if not is_async_callable(method) or not _same_binding(_binding(method), expected):
                    raise DefinitionMismatch("Original Coding resource implementation changed")
            active = self._runner.active_operations
            if type(active) is not int or active < 0:
                raise DefinitionMismatch("Coding resource ownership count is invalid")
            # The ownership getter may change identity or receivers. Preserve
            # the entry checks and verify both again after that callback.
            if _json(self._runner.identity, "Coding resource identity") != self._identity_json:
                raise DefinitionMismatch("Original Coding resource identity changed")
            for name, expected in self._bindings.items():
                method = getattr(self._runner, name, None)
                if not is_async_callable(method) or not _same_binding(_binding(method), expected):
                    raise DefinitionMismatch("Original Coding resource implementation changed")
        except (AttributeError, TypeError, ValueError) as exc:
            if isinstance(exc, DefinitionMismatch):
                raise
            raise DefinitionMismatch("Original Coding resource is unavailable") from None

    @property
    def implementation_identity(self):
        from .tools import _callable_identity

        self.check()
        return {
            "kind": "delegated-coding-handler",
            "version": "1",
            "entry": _callable_identity(type(self).__call__),
            "runner_methods": {
                name: _callable_identity(getattr(self._runner, name)) for name in _METHODS
            },
        }

    def __call__(self, arguments, context):
        raise AuthorizationDenied("Native Coding requires original execution-authority dispatch")


def registered_coding_tool(tool):
    """Validate the complete opt-in marker and its actual resource provenance."""
    marker = tool.spec.config.get("delegated_runner")
    handler = tool.handler
    if marker is None and type(handler) is not CodingToolHandler:
        # A literal null marker is an invalid explicit declaration too.
        if "delegated_runner" in tool.spec.config:
            raise ValidationError("Coding declaration cannot be null")
        return None
    if type(handler) is not CodingToolHandler:
        raise ValidationError("Coding marker requires the explicit managed resource handler")
    handler.check()
    if (
        type(marker) is not dict
        or set(marker) != {"version", "runner"}
        or type(marker["version"]) is not int
        or marker["version"] != 1
        or canonical(marker["runner"]) != canonical(handler.identity)
        or tool.spec.effect != "queryable_write"
        or tool.spec.requires_approval is not True
        or canonical(tool.spec.input_schema) != canonical(CODING_INPUT_SCHEMA)
        or tool.reconciler is not None
    ):
        raise ValidationError(
            "Coding requires its exact input, resource, approval and effect contract"
        )
    return handler


def register_coding_tool(
    registry,
    runner,
    *,
    name="coding",
    description="Execute one approved contained Coding task.",
    cost=1,
):
    """Register one explicit Coding tool, leaving resource closure to its owner."""
    from .tools import ToolRegistry, ToolSpec

    if not isinstance(registry, ToolRegistry):
        raise ValidationError("Coding registration requires a ToolRegistry")
    handler = CodingToolHandler(runner)
    registry.register(
        ToolSpec(
            name,
            description,
            copy.deepcopy(CODING_INPUT_SCHEMA),
            effect="queryable_write",
            requires_approval=True,
            cost=cost,
            config={"delegated_runner": {"version": 1, "runner": handler.identity}},
        ),
        handler,
    )
    return handler
