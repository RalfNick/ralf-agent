"""Local task hosting and resource lifecycle, with observation-only waiters."""

import asyncio
import math
import time
from dataclasses import dataclass

from .agent_harness import AgentHarness
from .agent_run import RunRef, WaitResult
from .engine import LocalEngine
from .errors import (
    AuthorizationDenied,
    CloseIncomplete,
    DefinitionMismatch,
    RuntimeClosed,
    ValidationError,
)
from .run_supervisor import PAUSED, TERMINAL, RunTaskSupervisor
from .runtime_lifecycle import RuntimeInstance
from .types import digest


def seconds(value, label):
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValidationError(f"{label} must be finite non-negative seconds")
    return value


@dataclass(frozen=True)
class CloseReport:
    state: str
    parked: tuple[RunRef, ...]
    owned: bool


class Runtime:
    def __init__(
        self, engine, *, owned=False, authority_locator=None, close_timeout=30, close_policy="drain"
    ):
        local = engine._engine if isinstance(engine, RuntimeInstance) else engine
        if not isinstance(local, LocalEngine) or type(owned) is not bool:
            raise ValidationError(
                "H2a Runtime requires a Local execution authority and explicit ownership"
            )
        if close_policy not in {"drain", "cancel"}:
            raise ValidationError(
                "Local close policy supports drain/cancel; handoff is unsupported"
            )
        self._engine, self._owned = engine, owned
        backend = getattr(local.store, "backend_id", None)
        if authority_locator is None and not isinstance(backend, str):
            raise ValidationError(
                "Custom execution stores require a stable opaque authority locator"
            )
        self._authority_locator = (
            "local-" + digest(["local-facade", backend])
            if authority_locator is None
            else authority_locator
        )
        # Validate the locator before any business acceptance.
        RunRef(
            self.authority_locator,
            local.scope.workspace,
            local.scope.principal,
            "preflight",
            "0" * 64,
        )
        self._scope, self._local = local.scope, local
        self.close_timeout, self.close_policy = (
            seconds(close_timeout, "Close timeout"),
            close_policy,
        )
        self.state, self._loop = "open", None
        self._supervisor = RunTaskSupervisor(engine, unresolved=self._pending_controls)
        self._close_task, self.close_report = None, None
        self._drained = False

    @property
    def engine(self):
        return self._engine

    @property
    def owned(self):
        return self._owned

    @property
    def scope(self):
        return self._scope

    @property
    def authority_locator(self):
        return self._authority_locator

    def _check(self, *, accepting=False):
        if self.state == "closed" or accepting and self.state != "open":
            raise RuntimeClosed("Runtime is closed or no longer accepting work")
        if self._local.scope != self._scope:
            raise DefinitionMismatch("The hosted execution Scope changed")
        if isinstance(self.engine, RuntimeInstance):
            # Refuse before binding this facade or accepting intent on a loop
            # that cannot use or clean up its already-created async resources.
            self.engine._context._check_loop()
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif loop is not self._loop:
            raise ValidationError("Runtime must use its hosting event loop")

    @property
    def capabilities(self):
        return {
            "schema_version": 1,
            "local_hosting": True,
            "observation_only_wait": True,
            "shared_sessions": callable(
                getattr(self._local.store, "create_session_admission", None)
            ),
            "durable_turns": callable(getattr(self._local.store, "create_session_admission", None)),
            "session_definitions": ["agent", "sequence"]
            + (
                ["graph", "team", "dynamic"]
                if type(getattr(self._local.store, "session_admission_version", 1)) is int
                and self._local.store.session_admission_version in {2, 3}
                else []
            ),
            "session_storage": "colocated-sqlite",
            "conversation_namespaces": type(
                getattr(self._local.store, "session_admission_version", 1)
            )
            is int
            and self._local.store.session_admission_version == 3,
            "queue": False,
            "deadline": False,
            "handoff": False,
            "temporal_facade": False,
        }

    @property
    def hosting_status(self):
        self._check()
        return self._supervisor.status

    @classmethod
    def from_profile(cls, profile, db_path, *, builder=None, scope=None, **options):
        from .runtime_builder import RuntimeBuilder

        cls._profile_options(options)
        built = (builder or RuntimeBuilder()).build(profile, db_path, scope=scope)
        try:
            return cls(built, owned=True, **options)
        except BaseException as error:
            try:
                built.close()
            except BaseException:
                from .runtime_builder import RuntimeBuildError

                raise RuntimeBuildError(built) from error
            raise

    @classmethod
    def from_temporal(cls, engine, **options):
        from .temporal_agent_runtime import TemporalClientRuntime

        return TemporalClientRuntime(engine, **options)

    @classmethod
    async def afrom_profile(cls, profile, db_path, *, builder=None, scope=None, **options):
        from .runtime_builder import RuntimeBuilder

        cls._profile_options(options)
        built = await (builder or RuntimeBuilder()).abuild(profile, db_path, scope=scope)
        try:
            return cls(built, owned=True, **options)
        except BaseException as error:
            try:
                await built.aclose()
            except BaseException:
                from .runtime_builder import RuntimeBuildError

                raise RuntimeBuildError(built) from error
            raise

    @staticmethod
    def _profile_options(options):
        if set(options) - {"authority_locator", "close_timeout", "close_policy"}:
            raise ValidationError("Unknown Runtime profile options")
        seconds(options.get("close_timeout", 30), "Close timeout")
        if options.get("close_policy", "drain") not in {"drain", "cancel"}:
            raise ValidationError("Unsupported Local close policy")
        locator = options.get("authority_locator")
        if locator is not None:
            RunRef(locator, "default", "local-owner", "preflight", "0" * 64)

    def _session_authority(self):
        from .local_sessions import LocalSessionAuthority

        if not hasattr(self, "_session_host"):
            self._session_host = LocalSessionAuthority(
                self._local,
                self.authority_locator,
                hosting=lambda run_id: (
                    run_id in self._supervisor.tasks and not self._supervisor.tasks[run_id].done()
                ),
            )
        return self._session_host

    async def open_session(self, harness, session_id, *, command_id, **options):
        from .agent_session import AgentSession
        from .session_types import SessionRef

        self._check(accepting=True)
        receipt = self._session_authority().open(
            harness, session_id, command_id=command_id, **options
        )
        ref = SessionRef.from_dict(receipt.outcome["session_ref"])
        self._session_authority().validate(ref)
        return AgentSession(self, ref, receipt=receipt)

    def attach_session(self, ref):
        from .agent_session import AgentSession

        self._check()
        if self._drained:
            raise RuntimeClosed("Execution resources are closing")
        self._session_authority().validate(ref)
        return AgentSession(self, ref)

    def create_agent(self, definition):
        from .agent import Agent

        if self.state != "open":
            raise RuntimeClosed("Runtime is not accepting new Agent entries")
        return Agent(runtime=self, definition=definition)

    def reference(self, run_id):
        self._check()
        info = self.engine.diagnostics(run_id)
        return RunRef(
            self.authority_locator,
            self.scope.workspace,
            self.scope.principal,
            run_id,
            info.release_digest,
        )

    def _validate(self, ref):
        self._check()
        if self._drained:
            raise RuntimeClosed(
                "Execution resources are closing; retry cleanup or explicitly reconnect"
            )
        if not isinstance(ref, RunRef):
            raise ValidationError("Attach requires an immutable RunRef")
        if (ref.workspace, ref.principal) != (self.scope.workspace, self.scope.principal):
            raise AuthorizationDenied("RunRef belongs to another trusted Scope")
        if (
            ref.authority_locator != self.authority_locator
            or self.engine.diagnostics(ref.run_id).release_digest != ref.release_digest
        ):
            raise DefinitionMismatch("RunRef differs from the original authority or release")

    def attach(self, ref):
        self._validate(ref)
        return AgentRun(self, ref)

    async def areference(self, run_id):
        return self.reference(run_id)

    async def aattach(self, ref):
        return self.attach(ref)

    async def _aobserve(self, ref, kind, **options):
        self._validate(ref)
        return getattr(self.engine, kind)(ref.run_id, **options)

    async def _apending(self, ref):
        return self._pending_controls(ref)

    async def _await_root(self, ref):
        return self._root_reference(ref)

    def _check_wait_errors(self, ref, root):
        self._supervisor.check_error(ref.run_id)
        self._supervisor.check_error(root.run_id)

    async def _acontrol(self, ref, method, *args, **kwargs):
        self._validate(ref)
        root = self._root_reference(ref)
        receipt = getattr(self.engine, method)(ref.run_id, *args, **kwargs)
        self._supervisor.start(root)
        return receipt

    def _root_reference(self, ref):
        seen = set()
        while ref.run_id not in seen:
            seen.add(ref.run_id)
            parent = self.engine.parent_run_id(ref.run_id)
            if parent is None:
                return ref
            if len(seen) > 16:
                break
            ref = self.reference(parent)
        raise DefinitionMismatch("Managed parent references are cyclic or exceed depth")

    def _pending_controls(self, ref):
        pending, todo, seen = [], [ref], set()
        while todo:
            owner = todo.pop()
            if owner.run_id in seen or len(seen) >= 4096:
                raise DefinitionMismatch("Managed controls exceed bounded ownership traversal")
            seen.add(owner.run_id)
            self._validate(owner)
            info = self.engine.diagnostics(owner.run_id)
            for action in info.snapshot.pending:
                pending.append({"kind": "approval", "ref": owner.to_dict(), **action})
            for action in info.snapshot.actions:
                if action["kind"] == "tool" and action["status"] == "outcome_unknown":
                    pending.append(
                        {
                            "kind": "reconciliation",
                            "ref": owner.to_dict(),
                            "action_id": action["id"],
                            "digest": action["digest"],
                        }
                    )
            for child in (info.workflow or {}).get("children", []):
                todo.append(self.reference(child["run_id"]))
        return pending

    async def submit(
        self,
        harness,
        input,
        *,
        command_id,
        budget=32,
        session_id=None,
        deadline_at=None,
        queue=False,
    ):
        self._check(accepting=True)
        if session_id is not None or deadline_at is not None or queue is not False:
            raise ValidationError(
                "H2a supports stateless Local runs; Session/Turn/queue/deadline are unsupported"
            )
        harness = harness if isinstance(harness, AgentHarness) else AgentHarness(harness)
        receipt = self.engine.submit(
            harness.definition, input, command_id=command_id, budget=budget
        )
        ref = self.reference(receipt.run_id)
        self._supervisor.start(ref)
        return AgentRun(self, ref, receipt=receipt.receipt)

    async def resume(self, ref):
        self._validate(ref)
        self._supervisor.start(self._root_reference(ref))
        return AgentRun(self, ref)

    async def __aenter__(self):
        self._check(accepting=True)
        return self

    async def __aexit__(self, kind, error, trace):
        try:
            await self.aclose()
        except BaseException as closing:
            if error is None:
                raise
            error.add_note("Runtime close is incomplete; retain the Runtime and retry aclose")
            raise error.with_traceback(trace) from closing

    async def _shutdown(self):
        try:
            if not self._drained:
                if self.close_policy == "cancel":
                    for ref in tuple(self._supervisor.refs.values()):
                        self.engine.cancel(
                            ref.run_id, command_id="facade-close-cancel:" + ref.run_id
                        )
                        self._supervisor.start(ref)
                await self._supervisor.drain()
                self._drained = True
            parked = tuple(self._supervisor.refs.values())
            if self.owned:
                if isinstance(self.engine, RuntimeInstance):
                    await self.engine.aclose()
                else:
                    self.engine.close()
            self.close_report = CloseReport("closed", parked, self.owned)
            self.state = "closed"
            self._supervisor.refs.clear()
            return self.close_report
        except BaseException:
            self.state = "close_failed"
            raise

    async def aclose(self, *, close_timeout=None):
        if self.state == "closed":
            return self.close_report
        self._check()
        timeout = (
            self.close_timeout if close_timeout is None else seconds(close_timeout, "Close timeout")
        )
        if self._close_task is None or self._close_task.done():
            if self._close_task is not None and not self._close_task.cancelled():
                self._close_task.exception()
            self.state = "quiescing"
            self._close_task = asyncio.create_task(self._shutdown())
            self._close_task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        try:
            return await asyncio.wait_for(asyncio.shield(self._close_task), timeout=timeout)
        except Exception as exc:
            report = CloseReport(self.state, tuple(self._supervisor.refs.values()), self.owned)
            raise CloseIncomplete(report) from exc


class AgentRun:
    def __init__(self, runtime, ref, *, receipt=None, turn=None):
        self._runtime, self.ref, self.receipt, self.turn = runtime, ref, receipt, turn

    async def status(self):
        return await self._runtime._aobserve(self.ref, "status")

    async def events(self, *, after=0, limit=1000):
        return await self._runtime._aobserve(self.ref, "events", after=after, limit=limit)

    async def diagnostics(self):
        return await self._runtime._aobserve(self.ref, "diagnostics")

    async def pending(self):
        return await self._runtime._apending(self.ref)

    async def wait(self, *, wait_timeout=None, terminal_only=False):
        if type(terminal_only) is not bool:
            raise ValidationError("terminal_only must be bool")
        timeout = None if wait_timeout is None else seconds(wait_timeout, "Wait timeout")
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        root = await self._runtime._await_root(self.ref)
        while True:
            snapshot = await self.status()
            if snapshot.state in TERMINAL or not terminal_only and snapshot.state in PAUSED:
                return WaitResult(self.ref, snapshot, "state_reached", time.time())
            self._runtime._check_wait_errors(self.ref, root)
            if deadline is not None and loop.time() >= deadline:
                return WaitResult(self.ref, snapshot, "observation_timeout", time.time())
            await asyncio.sleep(
                0.01 if deadline is None else min(0.01, max(0, deadline - loop.time()))
            )

    async def resume(self):
        return await self._runtime.resume(self.ref)

    async def _control(self, method, *args, **kwargs):
        return await self._runtime._acontrol(self.ref, method, *args, **kwargs)

    async def approve(self, action_id, target_digest, *, command_id, approved=True):
        return await self._control(
            "approve", action_id, target_digest, command_id=command_id, approved=approved
        )

    async def cancel(self, *, command_id):
        return await self._control("cancel", command_id=command_id)

    async def reconcile(self, action_id, result, *, command_id):
        return await self._control("reconcile", action_id, result, command_id=command_id)
