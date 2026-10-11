"""Optional, explicitly asynchronous Temporal execution facade and worker factory."""

import asyncio
import uuid
from dataclasses import asdict
from datetime import timedelta

from .errors import (
    AuthorizationDenied,
    DefinitionMismatch,
    IdempotencyConflict,
    NotFound,
    RalfError,
    ValidationError,
)
from .temporal_state import (
    COMMAND_REGISTRY_NAME,
    WORKFLOW_NAME,
    detached,
    temporal_capabilities,
    text,
    validate_manifest,
    validate_request,
    validate_schema_references,
)
from .types import (
    AgentSpec,
    CommandReceipt,
    RunDiagnostics,
    RunEvent,
    RunHandle,
    RunSnapshot,
    Scope,
    credits,
    digest,
    submission_request,
)

_ERRORS = {
    cls.code: cls
    for cls in (
        AuthorizationDenied,
        DefinitionMismatch,
        IdempotencyConflict,
        NotFound,
        ValidationError,
    )
}


def _sdk():
    try:
        from temporalio.client import Client, WorkflowUpdateFailedError
        from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
        from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
        from temporalio.service import RPCError, RPCStatusCode
    except ImportError as exc:
        raise ValidationError(
            "Temporal execution requires the optional temporal dependency"
        ) from exc
    return (
        Client,
        WorkflowUpdateFailedError,
        WorkflowIDConflictPolicy,
        WorkflowIDReusePolicy,
        ApplicationError,
        WorkflowAlreadyStartedError,
        RPCError,
        RPCStatusCode,
    )


def _raise_code(code):
    raise _ERRORS.get(code, RalfError)("Temporal operation was rejected")


def _snapshot(value):
    return RunSnapshot(
        **{**value, "pending": tuple(value["pending"]), "actions": tuple(value["actions"])}
    )


class TemporalEngine:
    """Trusted-scope facade; all network controls are async.

    The runtime manifest is a published, non-secret immutable release identity.
    The borrowed Client remains caller-owned. Agents and sequential Workflows
    are supported; Graph/Team/Dynamic/nested definitions are refused preflight.
    """

    def __init__(
        self,
        client,
        *,
        task_queue,
        release,
        scope=None,
        namespace=None,
        activity_timeout=60,
        drive_timeout=120,
    ):
        text(task_queue, "Temporal task queue")
        if scope is not None and not isinstance(scope, Scope):
            raise ValidationError("TemporalEngine requires a trusted Scope")
        for value in (activity_timeout, drive_timeout):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 < value <= 86400
            ):
                raise ValidationError("Temporal timeouts must be positive seconds up to 86400")
        configured_namespace = getattr(client, "namespace", None)
        if (
            namespace is not None
            and configured_namespace is not None
            and namespace != configured_namespace
        ):
            raise DefinitionMismatch("Temporal Client belongs to a different namespace")
        self.client, self.task_queue = client, task_queue
        self.scope, self.namespace = (
            scope or Scope(),
            namespace or configured_namespace or "default",
        )
        self._release = validate_manifest(release)
        self.activity_timeout, self.drive_timeout = activity_timeout, drive_timeout
        self._closed = False
        self._registry = None

    @property
    def capabilities(self):
        from .temporal_bindings import capabilities

        extended = "orchestration" in self._release
        return {
            **temporal_capabilities(),
            "shared_session": self._release.get("session_protocol") == 1,
            **{name: extended for name in ("graph", "team", "dag", "nesting")},
            "rag": "knowledge_context" in self._release,
            **capabilities(self._release),
        }

    @property
    def binding_capabilities(self):
        from .temporal_bindings import ROLES

        return {
            "schema_version": 1,
            "supported_definition_kinds": ["agent", "sequence"]
            + (["graph", "team", "dynamic"] if "orchestration" in self._release else [])
            if self._release["kernel"] == "temporal-3"
            else [],
            "supported_binding_roles": sorted(ROLES)
            if self._release["kernel"] == "temporal-3"
            else [],
            "session_modes": ["history-conversation"]
            if self._release.get("session_protocol") == 1
            else [],
            "resource_selectors": self._release["kernel"] == "temporal-3",
            "resource_selector_roles": {"facts": ["namespace"], "knowledge": ["namespace"]}
            if self._release["kernel"] == "temporal-3"
            else [],
            "required_stage_kinds": [],
            "session_admission": self._release.get("session_protocol") == 1,
        }

    @property
    def release(self):
        return detached(self._release)

    @classmethod
    async def connect(cls, address, *, namespace="default", **kwargs):
        Client = _sdk()[0]
        client = await Client.connect(address, namespace=namespace)
        return cls(client, namespace=namespace, **kwargs)

    def _handle(self, run_id):
        if self._closed:
            raise ValidationError("TemporalEngine is closed")
        text(run_id, "Run ID")
        return self.client.get_workflow_handle(run_id)

    async def _view(self, run_id, kind, **values):
        sdk = _sdk()
        try:
            result = await self._handle(run_id).query(
                "view", {"scope": asdict(self.scope), "kind": kind, **values}
            )
        except sdk[6] as exc:
            if exc.status == sdk[7].NOT_FOUND:
                raise NotFound("Temporal Run was not found") from None
            raise
        if isinstance(result, dict) and "error" in result and set(result) == {"error"}:
            _raise_code(result["error"])
        return result

    @property
    def command_registry_id(self):
        return "ralf-temporal-commands-" + digest(asdict(self.scope))

    async def _guard(self, kind, command_id, target, payload):
        sdk = _sdk()
        if self._closed:
            raise ValidationError("TemporalEngine is closed")
        if self._registry is None:
            try:
                await self.client.start_workflow(
                    COMMAND_REGISTRY_NAME,
                    {"scope": asdict(self.scope)},
                    id=self.command_registry_id,
                    task_queue=self.task_queue,
                    id_reuse_policy=sdk[3].REJECT_DUPLICATE,
                    id_conflict_policy=sdk[2].FAIL,
                )
            except sdk[5]:
                pass
            # Temporal retains the first accepted task queue in this Workflow's
            # History; a later facade configuration cannot move the registry.
            self._registry = self.client.get_workflow_handle(self.command_registry_id)
        try:
            await self._registry.execute_update(
                "reserve",
                {
                    "scope": asdict(self.scope),
                    "command_id": command_id,
                    "kind": kind,
                    "target": target,
                    "payload_digest": digest(payload),
                },
            )
        except sdk[1] as exc:
            cause = exc.cause
            if isinstance(cause, sdk[4]):
                _raise_code(cause.type)
            raise
        # Registry acceptance is deliberately not returned as a Run receipt.

    async def submit(self, spec, input, *, command_id, budget=32, session_id=None):
        from .binding_definitions import AgentDefinition, BoundDefinition
        from .temporal_managed_context import check_scope

        if (
            isinstance(spec, (AgentDefinition, BoundDefinition))
            and self._release["kernel"] != "temporal-3"
        ):
            raise ValidationError("Per-Agent bindings require temporal-3")
        check_scope(self._release, asdict(self.scope))
        if session_id is not None:
            raise ValidationError("Temporal shared sessions are not supported")
        from .orchestration_types import DynamicWorkflowSpec, TeamSpec
        from .workflow import GraphWorkflowSpec

        composite = isinstance(spec, (GraphWorkflowSpec, TeamSpec, DynamicWorkflowSpec))
        if composite and "orchestration" not in self._release:
            raise ValidationError(
                "Temporal supports native AgentSpec or sequential WorkflowSpec; registered orchestration release required"
            )
        if not isinstance(spec, (AgentSpec, AgentDefinition, BoundDefinition)) and not composite:
            from .types import WorkflowSpec

            if not isinstance(spec, WorkflowSpec):
                raise ValidationError(
                    "Temporal supports native AgentSpec or sequential WorkflowSpec"
                )
        text(command_id, "Command ID")
        credits(budget)
        request = submission_request(spec, input, budget=budget, session_id=session_id)
        from .temporal_bindings import normalize_request

        request = normalize_request(request)
        composite = request["definition"]["kind"] in {"graph", "team", "dynamic"}
        from .spec_codec import agent_steps

        for step in agent_steps(request["definition"]):
            validate_schema_references(step["output_schema"])
        # This stable ID isolates tenant/principal and caller command identity.
        # Runtime aliases/releases are resolved only on first acceptance.
        run_id = "ralf-temporal-" + digest([asdict(self.scope), command_id])
        await self._guard("submit", command_id, run_id, request)
        try:
            receipt = await self._view(run_id, "submission", request=request, command_id=command_id)
            return RunHandle(run_id, CommandReceipt(**receipt))
        except NotFound:
            pass
        validate_request(request, self._release)
        from .temporal_bindings import validate_bindings

        validate_bindings(request, self._release, asdict(self.scope))
        from .temporal_session_tree import require_tree_admission

        require_tree_admission(request, self._release)
        sdk = _sdk()
        try:
            from .temporal_parent_state import PARENT_WORKFLOW_NAME

            await self.client.start_workflow(
                PARENT_WORKFLOW_NAME if composite else WORKFLOW_NAME,
                {
                    "scope": asdict(self.scope),
                    "command_id": command_id,
                    "request": request,
                    "manifest": self.release,
                    "activity_timeout": self.activity_timeout,
                },
                id=run_id,
                task_queue=self.task_queue,
                id_reuse_policy=sdk[3].REJECT_DUPLICATE,
                id_conflict_policy=sdk[2].FAIL,
                retry_policy=None,
            )
        except sdk[5]:
            pass
        receipt = await self._view(run_id, "submission", request=request, command_id=command_id)
        return RunHandle(run_id, CommandReceipt(**receipt))

    async def status(self, run_id):
        return _snapshot(await self._view(run_id, "status"))

    async def events(self, run_id, *, after=0, limit=1000):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 10000:
            raise ValidationError("Events require non-negative after and limit from 1 to 10000")
        return [
            RunEvent(**event)
            for event in await self._view(run_id, "events", after=after, limit=limit)
        ]

    async def diagnostics(self, run_id):
        value = await self._view(run_id, "diagnostics")
        return RunDiagnostics(
            _snapshot(value["snapshot"]),
            value["manifest"],
            value["release_digest"],
            value["budget"],
            value["workflow"],
        )

    async def memory_stages(self, run_id):
        """Pure History evidence; no backend reads or implicit recovery."""
        return await self._view(run_id, "memory_stages")

    async def session_stages(self, run_id):
        """Pure original Session save evidence, without data I/O or recovery."""
        return await self._view(run_id, "session_stages")

    async def completion_stages(self, run_id):
        """Observe original completion intents/verdicts; never invoke the verifier."""
        return await self._view(run_id, "completion_stages")

    async def context_stages(self, run_id):
        """Read this Run's original History evidence; no Activity or child traversal."""
        return await self._view(run_id, "context_stages")

    async def context_artifacts(self, run_id):
        """Read artifact dispatch/receipt proofs without accessing storage."""
        return await self._view(run_id, "context_artifacts")

    async def _command(self, run_id, kind, command_id, **values):
        text(command_id, "Command ID")
        sdk = _sdk()
        payload = {"kind": kind, "scope": asdict(self.scope), **values}
        await self._view(run_id, "status")
        await self._guard(kind, command_id, run_id, payload)
        try:
            receipt = await self._handle(run_id).execute_update(
                "command", {"command_id": command_id, "payload": payload}
            )
        except sdk[1] as exc:
            cause = exc.cause
            if isinstance(cause, sdk[4]):
                _raise_code(cause.type)
            raise
        except sdk[6] as exc:
            if exc.status == sdk[7].NOT_FOUND:
                raise NotFound("Temporal Run was not found") from None
            raise
        if receipt["apply_state"] == "rejected":
            _raise_code(receipt["outcome"]["error"])
        return CommandReceipt(**receipt)

    async def approve(self, run_id, action_id, target_digest, *, command_id, approved=True):
        return await self._command(
            run_id,
            "approve",
            command_id,
            action_id=action_id,
            digest=target_digest,
            approved=approved,
        )

    async def cancel(self, run_id, *, command_id):
        return await self._command(run_id, "cancel", command_id)

    async def reconcile(self, run_id, action_id, result=None, *, command_id, query=False):
        if type(query) is not bool:
            raise ValidationError("Reconciliation query must be a boolean")
        values = {"action_id": action_id, "query": query}
        if not query:
            values["result"] = detached(result)
        return await self._command(run_id, "reconcile", command_id, **values)

    async def patch_plan(self, run_id, proposal, *, expected_plan_revision, command_id):
        from .dag_planning import DAGProposal

        if (
            not isinstance(proposal, DAGProposal)
            or type(expected_plan_revision) is not int
            or expected_plan_revision < 0
        ):
            raise ValidationError("DAG patch requires typed proposal and nonnegative revision")
        return await self._command(
            run_id,
            "patch",
            command_id,
            proposal=proposal.to_dict(),
            expected_plan_revision=expected_plan_revision,
        )

    async def drive(self, run_id, *, wait_seconds=None):
        await self._command(run_id, "drive", "drive:" + uuid.uuid4().hex)
        deadline = asyncio.get_running_loop().time() + (
            self.drive_timeout if wait_seconds is None else wait_seconds
        )
        while True:
            diagnostics = await self.diagnostics(run_id)
            snapshot = diagnostics.snapshot
            pending = (
                diagnostics.workflow["reconciliation_pending"]
                or diagnostics.workflow["evidence_ack_pending"]
            )
            if (
                snapshot.state not in {"queued", "running"} and not pending
            ) or asyncio.get_running_loop().time() >= deadline:
                return snapshot
            await asyncio.sleep(0.05)

    async def aclose(self):
        # Client is borrowed; the SDK manages its transport lifetime.
        self._closed = True


def build_temporal_worker(client, *, task_queue, runtime, release=None, **worker_options):
    """Explicit worker registration with fixed identity and no hidden fallbacks."""
    from .temporal_activities import TemporalRuntime, registered_activities

    _sdk()
    from temporalio.worker import Worker

    from .temporal_control_activities import registered_parent_activities
    from .temporal_parent_workflow import TemporalParentWorkflow
    from .temporal_session_activities import registered_session_activities
    from .temporal_session_workflow import TemporalSessionWorkflow
    from .temporal_workflow import TemporalCommandRegistryWorkflow, TemporalRunWorkflow

    text(task_queue, "Temporal task queue")
    if not isinstance(runtime, TemporalRuntime):
        raise ValidationError("Worker requires explicit TemporalRuntime dependencies")
    runtime.validate_release(release)
    manifest = runtime.manifest if release is None else detached(release)
    if worker_options.get("build_id", digest(manifest)) != digest(manifest):
        raise DefinitionMismatch("Worker build identity must match its pinned release")
    worker_options.setdefault("workflow_runner", _workflow_runner())
    worker_options.setdefault("identity", "ralf-temporal:" + digest(manifest))
    worker_options.setdefault("build_id", digest(manifest))
    worker_options.setdefault("sticky_queue_schedule_to_start_timeout", timedelta(seconds=1))
    worker_options.setdefault("disable_eager_activity_execution", True)
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[
            TemporalRunWorkflow,
            TemporalCommandRegistryWorkflow,
            TemporalParentWorkflow,
            TemporalSessionWorkflow,
        ],
        activities=registered_activities(runtime, client)
        + registered_parent_activities(runtime, client)
        + registered_session_activities(runtime, client),
        **worker_options,
    )


async def replay_temporal_history(history):
    """Replay actual service History against this fixed Workflow implementation."""
    _sdk()
    from temporalio.worker import Replayer

    from .temporal_parent_workflow import TemporalParentWorkflow
    from .temporal_session_workflow import TemporalSessionWorkflow
    from .temporal_workflow import TemporalCommandRegistryWorkflow, TemporalRunWorkflow

    await Replayer(
        workflows=[
            TemporalRunWorkflow,
            TemporalCommandRegistryWorkflow,
            TemporalParentWorkflow,
            TemporalSessionWorkflow,
        ],
        workflow_runner=_workflow_runner(),
    ).replay_workflow(history)


def _workflow_runner():
    from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

    # The package public exports import HTTP provider definitions. They are
    # never called from Workflow code; passing these third-party definitions
    # through avoids replay-time import side effects while retaining the
    # SDK sandbox around our Workflow implementation.
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "httpx",
            "jsonschema",
            "ralf_agent.temporal_bindings",
            "ralf_agent.temporal_memory_state",
            "ralf_agent.temporal_facts_state",
            "ralf_agent.temporal_knowledge_state",
            "ralf_agent.temporal_session_state",
            "ralf_agent.session_types",
            "ralf_agent.temporal_session_data_state",
            "ralf_agent.temporal_session_tree",
            "ralf_agent.temporal_session_tree_reads",
            "ralf_agent.temporal_session_tree_protocol",
            "ralf_agent.temporal_session_topology",
            "ralf_agent.temporal_session_identity",
            "ralf_agent.temporal_parent_session",
            "ralf_agent.temporal_managed_context",
            "ralf_agent.temporal_limits_state",
            "ralf_agent.temporal_completion_state",
            "ralf_agent.temporal_decision_state",
        )
    )
