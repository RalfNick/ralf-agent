"""Version 1 local runtime ports; no SQL, credentials or scheduling in adapters."""

import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from .errors import ValidationError
from .executors import DispatchEnvelope, EffectObservation
from .types import CommandReceipt, RunDiagnostics, RunEvent, RunHandle, RunSnapshot, Scope


class SessionResourceAdmission(Protocol):
    """Optional Local execution capability, atomic under command acceptance.

    Match trusted Scope/backend_id/actual storage key, including legacy Runs.
    Preserve ownership through approval/unknown/quiescent phases. The new
    session_resources array is durable Run data; aliases cannot bypass it.
    This is one execution authority's admission, not a remote database lease.
    """

    def session_resource_owner(self, scope: Scope, resource: dict) -> str | None: ...


class ManagedStageStore(Protocol):
    """Optional semantic gate; old readers must refuse newly accepted stage Runs.

    Activation is atomic with command acceptance under the original Store's
    transaction. It must not create an independent stage execution authority.
    """

    managed_stage_version: int

    def prepare_managed_stages(self) -> None: ...

    def managed_stage_reservation(self, run_id: str, reservation_id: str) -> dict | None: ...


class FactInspection(Protocol):
    """Optional exact scoped point lookup, including stored expiry metadata."""

    fact_inspection_version: int

    def inspect_fact(self, scope: Scope, namespace: str, key: str) -> dict | None: ...


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


@runtime_checkable
class AsyncExecutionEngine(Protocol):
    """Network authority controls; intentionally distinct from local sync ports."""

    async def submit(self, spec, input, *, command_id, budget=32, session_id=None) -> RunHandle: ...
    async def drive(self, run_id: str) -> RunSnapshot: ...
    async def status(self, run_id: str) -> RunSnapshot: ...
    async def events(self, run_id: str, *, after=0, limit=1000) -> list[RunEvent]: ...
    async def approve(
        self, run_id, action_id, target_digest, *, command_id, approved=True
    ) -> CommandReceipt: ...
    async def cancel(self, run_id, *, command_id) -> CommandReceipt: ...
    async def reconcile(self, run_id, action_id, result, *, command_id) -> CommandReceipt: ...
    async def aclose(self) -> None: ...


@runtime_checkable
class AsyncRuntimeDiagnostics(Protocol):
    async def diagnostics(self, run_id: str) -> RunDiagnostics: ...


@runtime_checkable
class EffectJournal(Protocol):
    """Durable effect evidence; Workflow History remains the execution authority.

    begin atomically retains dispatch intent and excludes another unresolved
    scoped target, returning execute or the original observation/block evidence.
    received commits immutable receipt evidence before returning None.
    acknowledge is called only after History adoption and must preserve the
    adopted result identity. Implementations must never dispatch business work.
    The host owns the journal lifetime; borrowed worker runtimes do not close it.
    """

    identity: dict

    async def begin(self, envelope: DispatchEnvelope) -> dict: ...
    async def received(
        self, envelope: DispatchEnvelope, observation: EffectObservation
    ) -> None: ...
    async def observation(self, envelope: DispatchEnvelope) -> EffectObservation | None: ...
    async def acknowledge(
        self, envelope: DispatchEnvelope, observation: EffectObservation
    ) -> None: ...
    async def aclose(self) -> None: ...


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


def is_async_callable(method):
    return callable(method) and any(
        inspect.iscoroutinefunction(item)
        for item in (method, getattr(method, "__call__", None))  # noqa: B004
    )


@runtime_checkable
class AsyncLifecycle(Protocol):
    """Owned client cleanup on its creation loop, complete and safely retriable."""

    async def aclose(self) -> None: ...


def _complete_sync_none(result, label):
    """Require completed lifecycle evidence, without entering lazy results."""
    if result is not None:
        if inspect.iscoroutine(result) or inspect.isgenerator(result):
            result.close()
        raise ValidationError(f"{label} must return None after completion")


def _invoke_sync_none(method, label):
    if not is_sync_callable(method):
        raise ValidationError(f"{label} must be synchronous")
    _complete_sync_none(method(), label)


def close_engine(engine):
    _invoke_sync_none(getattr(engine, "close", None), "ExecutionEngine.close")


@runtime_checkable
class ExecutionStore(Protocol):
    """One authority with atomic transactions, commands, CAS, events and credits.

    Methods run synchronously on the coordinator thread. Transactions must not
    suspend or do external asynchronous I/O. This port does not make LocalEngine
    distributed. close must return None only after owned resources are closed.
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
        """Owner of session_ids, retained while workflow/orchestration.quiescent is False.

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
    acquire/release complete synchronously and return None; lazy wrappers are
    invalid implementations, not operations the Engine will enter or await.
    If acquire raises, it must preserve any existing owner's lease and clean up
    resources from its own failed acquisition; the Engine must not release it.
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


class ContextRequestValidator(Protocol):
    """Optional pure measurement of the actual request after Harness.prepare."""

    def validate_request(self, messages: list[dict], max_chars: int):
        """Return a completed ContextMeasure; no tools, storage or model I/O."""
        ...
