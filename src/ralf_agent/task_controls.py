"""Borrowed completed controls; the selected Engine retains execution authority."""

import copy
import inspect
from dataclasses import asdict
from typing import Protocol, runtime_checkable

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .handoff import _completed
from .ports import is_async_callable, is_sync_callable
from .types import CommandReceipt, RunHandle, RunSnapshot, Scope, _require_text, canonical


@runtime_checkable
class SyncTaskControls(Protocol):
    scope: Scope

    def submit(self, spec, input, *, command_id, budget=32, session_id=None) -> RunHandle: ...
    def status(self, run_id) -> RunSnapshot: ...
    def cancel(self, run_id, *, command_id) -> CommandReceipt: ...


@runtime_checkable
class AsyncTaskControls(Protocol):
    scope: Scope

    async def submit(self, spec, input, *, command_id, budget=32, session_id=None) -> RunHandle: ...
    async def status(self, run_id) -> RunSnapshot: ...
    async def cancel(self, run_id, *, command_id) -> CommandReceipt: ...


def _binding(method):
    # RuntimeInstance returns fresh @wraps wrappers on attribute access. Keep
    # wrapper code plus the original bound operation stable, not wrapper allocation.
    layers, seen = [], set()
    while hasattr(method, "__wrapped__"):
        if id(method) in seen:
            raise ValidationError("Task control wrapper cycle")
        seen.add(id(method))
        layers.append(getattr(method, "__code__", type(method)))
        method = method.__wrapped__
    if not callable(method):
        raise ValidationError("Task control wrapper has no callable target")
    implementation = getattr(method, "__func__", method)
    call = None
    if not inspect.isroutine(implementation):
        # Callable objects are valid ports. Pin their actual type-level entry
        # point as well as the object, including in-place function body changes.
        entry = type(implementation).__call__
        call = (entry, getattr(entry, "__code__", None))
    return (
        tuple(layers),
        getattr(method, "__self__", None),
        implementation,
        getattr(implementation, "__code__", None),
        call,
    )


class TaskControlBridge:
    """Pin one mode, Scope and control bindings on a borrowed authority.

    Sync controls finish on the coordinating thread; only native async work is
    awaited. The bridge never drives/closes/transfers Engine ownership. Refusal
    after a real call is not proof nothing happened: recover the original command.
    """

    def __init__(self, engine, scope):
        if not isinstance(scope, Scope) or getattr(engine, "scope", None) != scope:
            raise AuthorizationDenied("Trusted task control Scope mismatch")
        self._engine, self._scope = engine, scope
        self._async = is_async_callable(getattr(engine, "submit", None))
        predicate = is_async_callable if self._async else is_sync_callable
        names = ("submit", "status", "cancel")
        if not all(predicate(getattr(engine, name, None)) for name in names):
            raise ValidationError("Task controls must use one synchronous or native async mode")
        self._bindings = {name: _binding(getattr(engine, name)) for name in names}

    @property
    def scope(self):
        return self._scope

    def _check(self):
        if getattr(self._engine, "scope", None) != self.scope:
            raise AuthorizationDenied("Trusted task control Scope changed")
        predicate = is_async_callable if self._async else is_sync_callable
        for name, expected in self._bindings.items():
            current = getattr(self._engine, name, None)
            if not predicate(current) or _binding(current) != expected:
                raise DefinitionMismatch("Task control registration changed")

    def verify(self):
        """Revalidate before a host wakeup following other asynchronous I/O."""
        self._check()

    async def _call(self, name, *args, **kwargs):
        self._check()
        operation = getattr(self._engine, name)
        value = await operation(*args, **kwargs) if self._async else operation(*args, **kwargs)
        value = await _completed(value, "Task control " + name)
        self._check()
        return value

    @staticmethod
    def _receipt(value, command_id, kind, run_id=None):
        if not isinstance(value, CommandReceipt):
            raise ValidationError("Task control must return a CommandReceipt")
        if (
            value.command_id != command_id
            or value.kind != kind
            or run_id is not None
            and value.run_id != run_id
            or value.record_state != "durably_recorded"
            or value.apply_state not in {"applied", "pending"}
            or not isinstance(value.outcome, dict)
        ):
            raise ValidationError("Task control receipt does not match the request")
        _require_text(value.run_id, "Receipt Run ID")
        canonical(asdict(value))

    async def submit(self, spec, input, *, command_id, budget=32, session_id=None):
        _require_text(command_id, "Command ID")
        value = await self._call(
            "submit", spec, input, command_id=command_id, budget=budget, session_id=session_id
        )
        if not isinstance(value, RunHandle):
            raise ValidationError("Task submit must return a RunHandle")
        _require_text(value.run_id, "Run ID")
        self._receipt(value.receipt, command_id, "submit", value.run_id)
        return copy.deepcopy(value)

    async def status(self, run_id):
        _require_text(run_id, "Run ID")
        value = await self._call("status", run_id)
        if (
            not isinstance(value, RunSnapshot)
            or value.run_id != run_id
            or value.state
            not in {
                "queued",
                "running",
                "waiting_approval",
                "waiting_reconciliation",
                "outcome_unknown",
                "cancelling",
                "succeeded",
                "failed",
                "cancelled",
            }
            or type(value.state_revision) is not int
            or value.state_revision < 0
            or value.error is not None
            and not isinstance(value.error, dict)
            or not isinstance(value.pending, tuple)
            or not isinstance(value.actions, tuple)
            or any(not isinstance(item, dict) for item in (*value.pending, *value.actions))
        ):
            raise ValidationError("Task status returned an invalid snapshot")
        canonical(asdict(value))
        return copy.deepcopy(value)

    async def cancel(self, run_id, *, command_id):
        _require_text(run_id, "Run ID")
        _require_text(command_id, "Command ID")
        value = await self._call("cancel", run_id, command_id=command_id)
        self._receipt(value, command_id, "cancel", run_id)
        return copy.deepcopy(value)
