"""Temporal specialization of the application Runtime; History owns Runs."""

import asyncio
import copy
import inspect
import json
import time
from dataclasses import asdict

from .agent_harness import AgentHarness
from .agent_run import RunRef, WaitResult
from .agent_runtime import AgentRun, CloseReport, Runtime, seconds
from .errors import AuthorizationDenied, DefinitionMismatch, RuntimeClosed, ValidationError
from .ports import is_async_callable
from .rpc_supervisor import RpcTaskSupervisor
from .run_supervisor import PAUSED, TERMINAL
from .temporal import TemporalEngine
from .temporal_state import text
from .types import (
    CommandReceipt,
    RunDiagnostics,
    RunHandle,
    RunSnapshot,
    canonical,
    credits,
    digest,
    submission_request,
)

REMOTE_PAUSED = PAUSED | {"outcome_unknown"}


def refuse_lazy(value):
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()


def receipt_result(receipt, run_id, kind, command_id, *, allow_rejected=False):
    if (
        not isinstance(receipt, CommandReceipt)
        or (receipt.run_id, receipt.kind, receipt.command_id) != (run_id, kind, command_id)
        or receipt.record_state != "durably_recorded"
        or receipt.apply_state not in ({"applied", "rejected"} if allow_rejected else {"applied"})
        or not isinstance(receipt.outcome, dict)
    ):
        refuse_lazy(receipt)
        raise ValidationError("Async authority requires its original completed command receipt")
    canonical(receipt.outcome)
    return receipt


def snapshot_result(value, run_id):
    if (
        not isinstance(value, RunSnapshot)
        or value.run_id != run_id
        or value.state not in TERMINAL | REMOTE_PAUSED | {"queued", "running", "cancelling"}
        or type(value.state_revision) is not int
        or value.state_revision < 0
        or value.consistency != "authoritative"
    ):
        refuse_lazy(value)
        raise ValidationError("Async drive requires a completed authoritative target RunSnapshot")
    canonical(asdict(value))
    return value


class TemporalClientRuntime(Runtime):
    def __init__(
        self,
        engine,
        *,
        owned=False,
        authority_locator=None,
        close_timeout=30,
        close_policy="detach",
    ):
        if not isinstance(engine, TemporalEngine) or type(owned) is not bool:
            raise ValidationError(
                "Temporal facade requires a TemporalEngine and explicit ownership"
            )
        if engine.release.get("user_input_protocol") == 1 and not is_async_callable(
            getattr(engine, "send_input", None)
        ):
            raise ValidationError("Selected user input requires async send_input controls")
        if close_policy != "detach":
            raise ValidationError(
                "Temporal client Runtime supports detach only; Workers are borrowed"
            )
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            raise ValidationError("Create Temporal Runtime on its hosting event loop") from None
        self._engine, self._owned, self._scope = engine, owned, engine.scope
        self._client = engine.client
        self._route = self._current_route()
        if authority_locator is not None:
            RunRef(
                authority_locator, self.scope.workspace, self.scope.principal, "preflight", "0" * 64
            )
        self._authority_locator = "temporal-" + digest(
            ["temporal-agent-facade-v1", *self._route, authority_locator]
        )
        self.close_timeout, self.close_policy = (
            seconds(close_timeout, "Close timeout"),
            close_policy,
        )
        self.state, self._drained = "open", False
        self._close_task, self.close_report = None, None
        self._supervisor = RpcTaskSupervisor()
        self._session_locator = None

    def _current_route(self):
        address = getattr(
            getattr(getattr(self.engine.client, "service_client", None), "config", None),
            "target_host",
            None,
        )
        text(address, "Temporal service endpoint")
        namespace = getattr(self.engine.client, "namespace", None)
        if namespace != self.engine.namespace:
            raise DefinitionMismatch("Temporal namespace differs from its actual Client")
        return address, namespace

    def _check(self, *, accepting=False):
        if self.state == "closed" or accepting and self.state != "open":
            raise RuntimeClosed("Runtime is closed or no longer accepting work")
        if (
            self.engine.scope != self.scope
            or self.engine.client is not self._client
            or self._current_route() != self._route
        ):
            raise DefinitionMismatch("Temporal Runtime Scope or actual resource changed")
        if asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Runtime must use its hosting event loop")

    @property
    def capabilities(self):
        from .temporal_deployment_protocol import public_selected

        sessions = self.engine.release.get("session_protocol") == 1 and not public_selected(
            self.engine.release
        )
        return {
            "schema_version": 1,
            "local_hosting": False,
            "observation_only_wait": True,
            "shared_sessions": sessions,
            "durable_turns": sessions,
            "session_definitions": (
                ["agent", "sequence"]
                + (["graph", "team", "dynamic"] if "orchestration" in self.engine.release else [])
            )
            if sessions
            else [],
            "session_storage": "temporal-history" if sessions else None,
            "queue": False,
            "deadline": False,
            "handoff": False,
            "temporal_facade": True,
            "supported_definition_kinds": ["agent", "sequence"]
            + (["graph", "team", "dynamic"] if "orchestration" in self.engine.release else []),
            "async_attachment": True,
            "client_close_policy": "detach",
        }

    def _session_authority(self):
        raise ValidationError("Temporal client facade does not support shared Sessions")

    async def _session_client(self):
        self._check()
        from .temporal_deployment_protocol import public_selected

        if public_selected(self.engine.release):
            raise ValidationError(
                "Temporal deployment Session coordinator admission is unavailable"
            )
        if self.engine.release.get("session_protocol") != 1:
            raise ValidationError(
                "Temporal Sessions require an explicitly registered Session release"
            )
        view = self._dispatch_engine()
        from .temporal_session_activities import namespace_id
        from .temporal_session_client import TemporalSessionClient
        from .temporal_session_state import locator

        value = await namespace_id(view.client)
        self._check()
        if self._drained:
            raise RuntimeClosed("Client resources are closing")
        current = locator(value)
        if self._session_locator is not None and self._session_locator != current:
            raise DefinitionMismatch("Temporal Session namespace resource changed")
        self._session_locator = current
        return TemporalSessionClient(view, value)

    async def open_session(self, harness, session_id, *, command_id, namespace=None, **options):
        self._check(accepting=True)
        if options:
            raise ValidationError("Temporal Sessions support only namespace selection")
        from .session_types import SessionRef
        from .temporal_agent_session import TemporalAgentSession

        harness = harness if isinstance(harness, AgentHarness) else AgentHarness(harness)
        text(command_id, "Command ID")

        async def operation():
            client = await self._session_client()
            receipt = await client.open(
                harness, session_id, command_id=command_id, namespace=namespace
            )
            ref = SessionRef.from_dict(receipt.outcome["session_ref"])
            client.validate(ref)
            self._check()
            return TemporalAgentSession(self, ref, receipt=receipt)

        return await self._supervisor.call(operation())

    def attach_session(self, ref):
        raise ValidationError("Temporal Session attachment requires await runtime.aattach_session")

    async def aattach_session(self, ref):
        from .temporal_agent_session import TemporalAgentSession

        client = await self._session_client()
        await client.status(ref)
        self._check()
        return TemporalAgentSession(self, ref)

    def _dispatch_engine(self):
        self._check()
        # A call owns its configuration. Default methods bind to this view so
        # internal awaits cannot switch their eventual server/Scope or release.
        if self.engine.release.get("deployment_admission_protocol", {}).get("version") == 2:
            vars(self.engine).setdefault("_deployment_namespace_binding", {"namespace": None})
        view = copy.copy(self.engine)
        for name, value in vars(self.engine).items():
            if inspect.ismethod(value) and value.__self__ is self.engine:
                setattr(view, name, value.__func__.__get__(view, type(view)))
        view.client, view.scope, view.namespace = self._client, self.scope, self._route[1]
        view._release = self.engine.release
        # Registry handles are client-specific; obtain them from the pinned view.
        view._registry = None
        return view

    def reference(self, run_id):
        raise ValidationError("Temporal reference requires await runtime.areference")

    def attach(self, ref):
        raise ValidationError("Temporal attachment requires await runtime.aattach")

    def _validate(self, ref):
        self._check()
        if self._drained:
            raise RuntimeClosed("Client resources are closing; retry cleanup or reconnect")
        if not isinstance(ref, RunRef):
            raise ValidationError("Attachment requires immutable RunRef")
        if (ref.workspace, ref.principal) != (self.scope.workspace, self.scope.principal):
            raise AuthorizationDenied("RunRef belongs to another trusted Scope")
        if ref.authority_locator not in {self.authority_locator, self._session_locator}:
            raise DefinitionMismatch("RunRef belongs to another actual Temporal resource")

    @staticmethod
    def _info(info, run_id):
        if (
            not isinstance(info, RunDiagnostics)
            or not isinstance(info.snapshot, RunSnapshot)
            or info.snapshot.run_id != run_id
            or not isinstance(info.workflow, dict)
            or (info.workflow or {}).get("backend") not in {"temporal", "temporal-parent"}
        ):
            refuse_lazy(info)
            raise ValidationError("Temporal facade requires original native/parent diagnostics")
        if info.workflow["backend"] == "temporal-parent" and (
            info.workflow.get("kind") not in {"graph", "team", "dynamic"}
            or not isinstance(info.workflow.get("children"), list)
        ):
            raise ValidationError("Temporal parent requires typed orchestration evidence")
        snapshot_result(info.snapshot, run_id)
        return info

    def _ref(self, info):
        return RunRef(
            self.authority_locator,
            self.scope.workspace,
            self.scope.principal,
            info.snapshot.run_id,
            info.release_digest,
        )

    async def areference(self, run_id):
        self._check()
        if self._drained:
            raise RuntimeClosed("Client resources are closing")
        view = self._dispatch_engine()
        info = self._info(await view.diagnostics(run_id), run_id)
        self._check()
        if self._drained:
            raise RuntimeClosed("Client resources are closing")
        return self._ref(info)

    async def aattach(self, ref):
        if isinstance(ref, RunRef) and ref.authority_locator.startswith("temporal-session-"):
            await self._session_client()
        info = await self._aobserve(ref, "diagnostics")
        return TemporalAgentRun(self, ref, info.snapshot)

    async def _aobserve(self, ref, kind, **options):
        return await self._observe_with(self._dispatch_engine(), ref, kind, **options)

    async def _observe_with(self, view, ref, kind, **options):
        self._validate(ref)
        info = self._info(await view.diagnostics(ref.run_id), ref.run_id)
        self._validate(ref)
        if info.release_digest != ref.release_digest:
            raise DefinitionMismatch("RunRef differs from the original Temporal release")
        if kind == "diagnostics":
            return info
        if kind == "status":
            return info.snapshot
        value = await getattr(view, kind)(ref.run_id, **options)
        self._validate(ref)
        return value

    async def _apending(self, ref):
        from .temporal_agent_controls import pending_controls

        return await pending_controls(self, ref, self._dispatch_engine())

    async def _await_root(self, ref):
        self._validate(ref)
        return ref

    def _check_wait_errors(self, ref, root):
        pass  # Workers own execution; this client does not infer their health.

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
            raise ValidationError("Temporal facade refuses Session/queue/deadline")
        harness = harness if isinstance(harness, AgentHarness) else AgentHarness(harness)
        declaration = json.loads(harness._definition_json)
        from .temporal_bindings import normalize_request

        public_deployment = (
            self.engine.release.get("deployment_admission_protocol", {}).get("version") == 2
        )
        if not public_deployment and declaration["kind"] in {"bound_agent", "bound_definition"}:
            if self.engine.release["kernel"] != "temporal-3":
                raise ValidationError("Temporal bindings require their explicit registered release")
            declaration = normalize_request(
                submission_request(harness.definition, None), self.engine.release
            )["definition"]
        if (
            not public_deployment
            and declaration["kind"] not in self.capabilities["supported_definition_kinds"]
        ):
            raise ValidationError("Temporal definition requires its supported registered release")
        input = json.loads(canonical(input))
        text(command_id, "Command ID")
        credits(budget)
        view = self._dispatch_engine()

        async def accept():
            self._check()
            handle = await view.submit(
                harness.definition, input, command_id=command_id, budget=budget
            )
            if not isinstance(handle, RunHandle):
                refuse_lazy(handle)
                raise ValidationError("Async authority requires a completed RunHandle")
            receipt_result(handle.receipt, handle.run_id, "submit", command_id)
            info = self._info(await view.diagnostics(handle.run_id), handle.run_id)
            self._check()
            return TemporalAgentRun(self, self._ref(info), info.snapshot, receipt=handle.receipt)

        return await self._supervisor.call(accept())

    async def resume(self, ref):
        self._validate(ref)
        view = self._dispatch_engine()

        async def operation():
            await self._observe_with(view, ref, "diagnostics")
            snapshot_result(await view.drive(ref.run_id, wait_seconds=0), ref.run_id)
            info = await self._observe_with(view, ref, "diagnostics")
            return TemporalAgentRun(self, ref, info.snapshot)

        return await self._supervisor.call(operation())

    async def _acontrol(self, ref, method, *args, **kwargs):
        self._validate(ref)
        args, kwargs = json.loads(canonical(args)), json.loads(canonical(kwargs))
        view = self._dispatch_engine()

        async def operation():
            await self._observe_with(view, ref, "diagnostics")
            receipt = await getattr(view, method)(ref.run_id, *args, **kwargs)
            self._validate(ref)
            return receipt_result(
                receipt,
                ref.run_id,
                method,
                kwargs["command_id"],
                allow_rejected=method == "send_input",
            )

        return await self._supervisor.call(operation())

    async def _shutdown(self):
        try:
            if not self._drained:
                await self._supervisor.drain()
                self._drained = True
            if self.owned:
                result = await self.engine.aclose()
                if result is not None:
                    refuse_lazy(result)
                    raise ValidationError("Owned async facade close requires completed None")
            self.close_report = CloseReport("closed", (), self.owned)
            self.state = "closed"
            return self.close_report
        except BaseException:
            self.state = "close_failed"
            raise


class TemporalAgentRun(AgentRun):
    """Cache only validated observations; RPC deadlines never control the Run."""

    def __init__(self, runtime, ref, snapshot, *, receipt=None):
        super().__init__(runtime, ref, receipt=receipt)
        self._remember(snapshot)

    def _remember(self, snapshot):
        self._snapshot, self._observed_at = copy.deepcopy(snapshot), time.time()

    async def status(self):
        snapshot = await super().status()
        self._remember(snapshot)
        return snapshot

    async def diagnostics(self):
        info = await super().diagnostics()
        self._remember(info.snapshot)
        return info

    def _observation(self, reason):
        self._runtime._validate(self.ref)
        return WaitResult(self.ref, self._snapshot, reason, self._observed_at)

    async def wait(self, *, wait_timeout=None, terminal_only=False):
        if type(terminal_only) is not bool:
            raise ValidationError("terminal_only must be bool")
        timeout = None if wait_timeout is None else seconds(wait_timeout, "Wait timeout")
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout

        async def observe():
            snapshot = await self.status()
            available = (
                not terminal_only
                and snapshot.state not in TERMINAL | REMOTE_PAUSED
                and await self._input_available()
            )
            return snapshot, available

        while True:
            self._runtime._validate(self.ref)
            remaining = None if deadline is None else max(0, deadline - loop.time())
            if remaining == 0:
                reason = (
                    "state_reached"
                    if self._snapshot.state in TERMINAL
                    or not terminal_only
                    and self._snapshot.state in REMOTE_PAUSED
                    else "observation_timeout"
                )
                return self._observation(reason)
            if remaining is None:
                snapshot, available = await observe()
            else:
                observation_timeout = asyncio.timeout(remaining)
                try:
                    async with observation_timeout:
                        snapshot, available = await observe()
                except TimeoutError:
                    if not observation_timeout.expired():
                        raise
                    return self._observation("observation_timeout")
            if snapshot.state in TERMINAL or not terminal_only and snapshot.state in REMOTE_PAUSED:
                return self._observation("state_reached")
            if available:
                return self._observation("control_available")
            await asyncio.sleep(
                0.05 if deadline is None else min(0.05, max(0, deadline - loop.time()))
            )
