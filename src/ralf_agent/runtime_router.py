"""Select original accepted profiles without mutating an executing local engine."""

import copy
import json
from pathlib import Path
from typing import Protocol

from .errors import (
    AuthorizationDenied,
    DefinitionMismatch,
    IdempotencyConflict,
    NotFound,
    ValidationError,
)
from .ports import validate_engine
from .runtime_builder import RuntimeBuilder, _close_complete, _synchronous
from .runtime_config import RuntimeCatalog
from .storage import SQLiteStore
from .types import (
    CommandReceipt,
    RunDiagnostics,
    RunHandle,
    RunSnapshot,
    Scope,
    digest,
    submission_request,
)
from .workflow_runtime import workflow_details


class RunReader(Protocol):
    def status(self, run_id): ...
    def events(self, run_id, *, after=0, limit=1000): ...
    def profile_identity(self, run_id): ...
    def submit_receipt(self, command_id, payload): ...


class CommandReceiptReader(Protocol):
    """Optional scoped lookup that never constructs an execution runtime."""

    def command_receipt(self, command_id, kind, payload): ...


class SQLiteRunReader:
    def __init__(self, db_path, *, scope=None):
        self.db_path = str(Path(db_path).resolve())
        self.scope = Scope() if scope is None else scope
        if not isinstance(self.scope, Scope):
            raise ValidationError("Read scope must be supplied by a trusted host")

    def _run(self, store, run_id):
        from dataclasses import asdict

        run = store.run(run_id)
        if run["scope"] != asdict(self.scope):
            raise AuthorizationDenied("Run belongs to another workspace or principal")
        return run

    def status(self, run_id):
        with SQLiteStore(self.db_path, readonly=True) as store:
            return RunSnapshot.from_record(self._run(store, run_id))

    def events(self, run_id, *, after=0, limit=1000):
        with SQLiteStore(self.db_path, readonly=True) as store:
            store.conn.execute("BEGIN")
            self._run(store, run_id)
            return store.events(run_id, after, limit)

    def profile_identity(self, run_id):
        with SQLiteStore(self.db_path, readonly=True) as store:
            return copy.deepcopy(self._run(store, run_id)["manifest"].get("runtime_profile"))

    def diagnostics(self, run_id):
        with SQLiteStore(self.db_path, readonly=True) as store:
            store.conn.execute("BEGIN")
            run = self._run(store, run_id)
            return RunDiagnostics(
                RunSnapshot.from_record(run),
                run["manifest"],
                run["release_digest"],
                store.budget(run_id),
                workflow_details(run, store),
            )

    def submit_receipt(self, command_id, payload):
        return self.command_receipt(command_id, "submit", payload)

    def command_receipt(self, command_id, kind, payload):
        if not isinstance(command_id, str) or not command_id:
            raise ValidationError("A non-empty command_id is required")
        try:
            store = SQLiteStore(self.db_path, readonly=True)
        except NotFound:
            return None
        with store:
            if kind != "submit":
                self._run(store, payload["run_id"])
            row = store.conn.execute(
                "SELECT digest,receipt FROM commands WHERE workspace=? AND principal=? AND id=?",
                (self.scope.workspace, self.scope.principal, command_id),
            ).fetchone()
            if row is None:
                return None
            if row["digest"] != digest({"kind": kind, "payload": payload}):
                raise IdempotencyConflict("command_id was already used for a different request")
            return CommandReceipt(**json.loads(row["receipt"]))


class ProfiledEngine:
    """One local runtime at a time; original profiles own continuation and control."""

    def __init__(
        self, catalog, db_path, *, builder=None, scope=None, reader=None, legacy_factory=None
    ):
        if not isinstance(catalog, RuntimeCatalog):
            raise ValidationError("ProfiledEngine requires a RuntimeCatalog")
        self.catalog = catalog
        self.db_path = str(Path(db_path).resolve())
        self.scope = Scope() if scope is None else scope
        if not isinstance(self.scope, Scope):
            raise ValidationError("Runtime scope must be supplied by a trusted host")
        self.builder = RuntimeBuilder(base_dir=catalog.base_dir) if builder is None else builder
        if not _synchronous(getattr(self.builder, "build", None)):
            raise ValidationError("Runtime builder requires build")
        self.reader = SQLiteRunReader(self.db_path, scope=self.scope) if reader is None else reader
        if any(
            not _synchronous(getattr(self.reader, name, None))
            for name in ("status", "events", "profile_identity", "submit_receipt")
        ):
            raise ValidationError("Run reader does not implement the public read contract")
        if legacy_factory is not None and not _synchronous(legacy_factory):
            raise ValidationError("legacy_factory must be an explicit trusted factory")
        self.legacy_factory = legacy_factory
        self._active = None
        self._identity = None
        self._lifecycle = "open"

    def _ensure_open(self):
        if self._lifecycle != "open":
            raise ValidationError("Profiled engine is closed; retry close only")

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *args):
        self.close()

    def _activate(self, profile):
        self._ensure_open()
        identity = profile.identity if profile is not None else {"kind": "explicit-legacy-factory"}
        if self._active is not None and self._identity == identity:
            return self._active
        if self._active is not None:
            _close_complete(self._active.close(), "Runtime close")
            self._active, self._identity = None, None
        runtime = (
            self.builder.build(profile, self.db_path, scope=self.scope)
            if profile is not None
            else self.legacy_factory(self.db_path)
        )
        try:
            validate_engine(runtime)
        except Exception:
            close = getattr(runtime, "close", None)
            if callable(close):
                self._active = runtime
                try:
                    _close_complete(close(), "Rejected runtime close")
                except BaseException:
                    self._lifecycle = "close_failed"
                    raise
                self._active = None
            raise
        self._active, self._identity = runtime, identity
        return runtime

    def _for_run(self, run_id):
        self._ensure_open()
        identity = self.reader.profile_identity(run_id)
        if identity is None:
            if self.legacy_factory is None:
                raise DefinitionMismatch(
                    "An unprofiled Run requires its explicit original legacy_factory"
                )
            return self._activate(None)
        return self._activate(self.catalog.resolve(identity))

    def submit(self, spec, input, *, command_id, budget=32, session_id=None):
        self._ensure_open()
        payload = submission_request(spec, input, budget=budget, session_id=session_id)
        receipt = self.reader.submit_receipt(command_id, payload)
        if receipt is not None:
            return RunHandle(receipt.run_id, receipt)
        runtime = self._activate(self.catalog.default)
        return runtime.submit(
            spec, input, command_id=command_id, budget=budget, session_id=session_id
        )

    async def drive(self, run_id):
        runtime = self._for_run(run_id)
        return await runtime.drive(run_id)

    def status(self, run_id):
        self._ensure_open()
        return self.reader.status(run_id)

    def events(self, run_id, *, after=0, limit=1000):
        self._ensure_open()
        return self.reader.events(run_id, after=after, limit=limit)

    def __getattr__(self, name):
        if name == "diagnostics":
            method = getattr(self.reader, "diagnostics", None)
            if _synchronous(method):

                def diagnostics(run_id):
                    self._ensure_open()
                    return method(run_id)

                return diagnostics
        raise AttributeError(name)

    def _control_receipt(self, command_id, kind, payload):
        self._ensure_open()
        method = getattr(self.reader, "command_receipt", None)
        if _synchronous(method):
            return method(command_id, kind, payload)
        return None

    def approve(self, run_id, action_id, target_digest, *, command_id, approved=True):
        receipt = self._control_receipt(
            command_id,
            "approve",
            {
                "run_id": run_id,
                "action_id": action_id,
                "digest": target_digest,
                "approved": approved,
            },
        )
        if receipt is not None:
            return receipt
        return self._for_run(run_id).approve(
            run_id, action_id, target_digest, command_id=command_id, approved=approved
        )

    def cancel(self, run_id, *, command_id):
        receipt = self._control_receipt(command_id, "cancel", {"run_id": run_id})
        if receipt is not None:
            return receipt
        return self._for_run(run_id).cancel(run_id, command_id=command_id)

    def reconcile(self, run_id, action_id, result, *, command_id):
        receipt = self._control_receipt(
            command_id, "reconcile", {"run_id": run_id, "action_id": action_id, "result": result}
        )
        if receipt is not None:
            return receipt
        return self._for_run(run_id).reconcile(run_id, action_id, result, command_id=command_id)

    async def wait_for_threads(self):
        if self._active is not None:
            await self._active.wait_for_threads()

    def close(self):
        if self._lifecycle == "closed":
            return
        self._lifecycle = "closing"
        try:
            if self._active is not None:
                _close_complete(self._active.close(), "Runtime close")
        except BaseException:
            self._lifecycle = "close_failed"
            raise
        self._lifecycle = "closed"
