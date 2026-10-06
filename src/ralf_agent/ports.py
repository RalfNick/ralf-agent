"""Version 1 local runtime ports; no SQL, credentials or scheduling in adapters."""

import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from .errors import ValidationError
from .types import CommandReceipt, RunDiagnostics, RunEvent, RunHandle, RunSnapshot, Scope


@runtime_checkable
class ExecutionEngine(Protocol):
    """Public control contract; resource ownership ends only after close succeeds."""

    def submit(self, spec, input, *, command_id, budget=32, session_id=None) -> RunHandle: ...
    async def drive(self, run_id: str) -> RunSnapshot: ...
    def status(self, run_id: str) -> RunSnapshot: ...
    def events(self, run_id: str, *, after=0, limit=1000) -> list[RunEvent]: ...
    def approve(
        self, run_id, action_id, target_digest, *, command_id, approved=True
    ) -> CommandReceipt: ...
    def cancel(self, run_id, *, command_id) -> CommandReceipt: ...
    def reconcile(self, run_id, action_id, result, *, command_id) -> CommandReceipt: ...
    async def wait_for_threads(self) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class RuntimeDiagnostics(Protocol):
    def diagnostics(self, run_id: str) -> RunDiagnostics: ...


def validate_engine(engine):
    # Method-based checks support delegation without requiring inheritance.
    for name in vars(ExecutionEngine):
        if name.startswith("_"):
            continue
        method = getattr(engine, name, None)
        if not callable(method):
            raise ValidationError(f"ExecutionEngine requires {name}")
        if name in {"drive", "wait_for_threads"}:
            if not inspect.iscoroutinefunction(method):
                raise ValidationError(f"ExecutionEngine.{name} must be async")
        elif not is_sync_callable(method):
            raise ValidationError(f"ExecutionEngine.{name} must be synchronous")
    return engine


def is_sync_callable(method):
    candidate = getattr(method, "__call__", None)  # noqa: B004
    return callable(method) and not any(
        inspect.iscoroutinefunction(item)
        or inspect.isgeneratorfunction(item)
        or inspect.isasyncgenfunction(item)
        for item in (method, candidate)
    )


def close_engine(engine):
    close = getattr(engine, "close", None)
    if not is_sync_callable(close):
        raise ValidationError("ExecutionEngine.close must be synchronous")
    result = close()
    if result is not None:
        if inspect.iscoroutine(result) or inspect.isgenerator(result):
            result.close()
        raise ValidationError("ExecutionEngine.close must return None after completion")


@runtime_checkable
class ExecutionStore(Protocol):
    """One authority with atomic transactions, commands, CAS, events and credits.

    Methods run on the coordinator thread. Transactions must not suspend or do
    external asynchronous I/O. This port does not make LocalEngine distributed.
    """

    def transaction(self) -> AbstractContextManager: ...
    def command(
        self,
        scope: Scope,
        command_id: str,
        kind: str,
        payload: dict,
        run_id: str,
        apply: Callable[[], dict],
    ) -> CommandReceipt: ...
    def insert_run(self, data: dict) -> None: ...
    def run(self, run_id: str) -> dict: ...
    def save_run(self, data: dict) -> None: ...
    def emit(self, run_id: str, kind: str, data: dict | None = None) -> None: ...
    def events(self, run_id: str, after: int = 0, limit: int = 1000) -> list[RunEvent]: ...
    def session_owner(self, scope: Scope, session_id: str) -> str | None:
        """Owner of accepted session_ids, retained while workflow.quiescent is False.

        A terminal Run may still have a real worker completing Session I/O.
        """
        ...

    def unresolved_effect(
        self, scope: Scope, tool: str, arguments: dict, exclude_action_id: str
    ) -> dict | None: ...
    def create_budget(self, run_id: str, allowance: int) -> None: ...
    def budget(self, run_id: str) -> dict: ...
    def reserve(self, run_id: str, reservation_id: str, amount: int) -> None: ...
    def mark_unknown(self, reservation_id: str) -> None: ...
    def settle(self, reservation_id: str, actual: int, usage: dict) -> None: ...
    def close(self) -> None:
        """Close owned resources; a partial failure must permit safe retry."""
        ...


@runtime_checkable
class CoordinatorLease(Protocol):
    """Exclusive ownership of the same execution authority until release.

    A host-provided lease must never let a second LocalEngine enter while an old
    process can still dispatch or commit. TTL alone cannot provide that guarantee.
    """

    def acquire(self) -> None: ...
    def release(self) -> None:
        """Idempotently release this owner's lease, including after partial failure."""
        ...


@runtime_checkable
class ContextBuilder(Protocol):
    identity: dict

    def assemble(
        self, history: list[dict], references: list[dict], max_chars: int
    ) -> tuple[list[dict], dict]: ...
