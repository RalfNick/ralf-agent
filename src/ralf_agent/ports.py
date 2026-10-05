"""Version 1 local runtime ports; no SQL, credentials or scheduling in adapters."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from .types import CommandReceipt, RunEvent, Scope


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
    def session_owner(self, scope: Scope, session_id: str) -> str | None: ...
    def unresolved_effect(
        self, scope: Scope, tool: str, arguments: dict, exclude_action_id: str
    ) -> dict | None: ...
    def create_budget(self, run_id: str, allowance: int) -> None: ...
    def budget(self, run_id: str) -> dict: ...
    def reserve(self, run_id: str, reservation_id: str, amount: int) -> None: ...
    def mark_unknown(self, reservation_id: str) -> None: ...
    def settle(self, reservation_id: str, actual: int, usage: dict) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class CoordinatorLease(Protocol):
    """Exclusive ownership of the same execution authority until release.

    A host-provided lease must never let a second LocalEngine enter while an old
    process can still dispatch or commit. TTL alone cannot provide that guarantee.
    """

    def acquire(self) -> None: ...
    def release(self) -> None: ...


@runtime_checkable
class ContextBuilder(Protocol):
    identity: dict

    def assemble(
        self, history: list[dict], references: list[dict], max_chars: int
    ) -> tuple[list[dict], dict]: ...
