"""Single-coordinator native Agents, sequences and durable serial static graphs."""

from __future__ import annotations

import asyncio
import copy
import inspect
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator

from .context import ContextAssembler
from .decisions import final_output, validate_call_ids, validate_decision
from .errors import (
    AuthorizationDenied,
    CoordinatorBusy,
    DefinitionMismatch,
    RalfError,
    ValidationError,
)
from .executors import DispatchEnvelope, EffectObservation, PythonToolExecutor, ToolExecutor
from .harness import DecisionProposal, Harness, ModelRequest, NativeHarness
from .memory import _validate_expires_at, memory_call
from .model_continuation import (
    assistant_message,
    decode_received_response,
    provider_continuation_identity,
    validate_continuation,
)
from .model_evidence import (
    settlement_usage,
    snapshot_model_response,
    validate_model_usage,
    validate_received_response,
)
from .ports import (
    ContextBuilder,
    CoordinatorLease,
    ExecutionStore,
    _complete_sync_none,
    _invoke_sync_none,
    is_sync_callable,
)
from .tools import (
    ThreadExecutionTracker,
    ToolSpec,
    current_thread_group,
    current_thread_tracker,
)
from .types import (
    AgentSpec,
    InvocationContext,
    ModelResponse,
    RunDiagnostics,
    RunHandle,
    RunSnapshot,
    Scope,
    ToolCall,
    canonical,
    digest,
    runtime_profile_identity,
    submission_request,
)
from .workflow_runtime import StaticWorkflowRuntime, agent_step, is_graph, workflow_details

TERMINAL = {"succeeded", "failed", "cancelled"}

if TYPE_CHECKING:
    from .recall import MemoryRecallPolicy, RecallPlanner
    from .retrieval import KnowledgeContextPort


class LocalEngine:
    def __init__(
        self,
        store: ExecutionStore,
        *,
        providers,
        tools,
        scope=None,
        session_store=None,
        memory_store=None,
        policy: Callable[[Scope, ToolSpec, dict], None] | None = None,
        coordinator: CoordinatorLease | None = None,
        context_assembler: ContextBuilder | None = None,
        harness: Harness | None = None,
        tool_executor: ToolExecutor | None = None,
        recall_policy: MemoryRecallPolicy | None = None,
        knowledge: KnowledgeContextPort | None = None,
        recall_planner: RecallPlanner | None = None,
        runtime_profile: dict | None = None,
        workflow_compiler=None,
        workflow_interpreter=None,
        workflow_transforms=None,
        workflow_scheduler=None,
        team_strategies=None,
        planners=None,
        plan_verifiers=None,
        binding_catalog=None,
        verifier=None,
        limits=None,
        conversation_resource=None,
        stage_policy=None,
        model_continuation=False,
        model_history=None,
    ):
        # Python 3.12's Protocol isinstance check ignores proxy __getattr__.
        # Validate the declared public operations so delegating adapters work too.
        if any(
            not is_sync_callable(getattr(store, name, None))
            for name in vars(ExecutionStore)
            if not name.startswith("_")
        ):
            raise ValidationError("Store must implement the version 1 ExecutionStore port")
        self._validate_policy(policy)
        if type(model_continuation) is not bool:
            raise ValidationError("model_continuation must be boolean")
        self.model_continuation = model_continuation
        if model_history is not None and not model_continuation:
            raise ValidationError("Model history requires explicit model continuation")
        from .model_history import model_history_registration

        self.model_history = self._model_history_pin = model_history
        self._model_history_registration = (
            model_history_registration(model_history) if model_history is not None else None
        )
        from .task_controls import _binding

        self._model_history_bindings = (
            {name: _binding(getattr(model_history, name)) for name in ("assemble", "validate")}
            if model_history is not None
            else {}
        )
        self.store = store
        self.conversation_resource = conversation_resource
        self.providers = dict(providers)
        self.tools = tools
        self.harness = NativeHarness() if harness is None else harness
        self.verifier = verifier
        self.limits = limits
        self.stage_policy = stage_policy
        if limits is not None:
            self._component_identity(limits, ("propose",), True, "Agent limits")
        if verifier is not None:
            self._component_identity(verifier, ("verify",), True, "Completion verifier")
        self.tool_executor = PythonToolExecutor(tools) if tool_executor is None else tool_executor
        self._component_identity(self.harness, ("prepare", "propose"), True, "Harness")
        self._component_identity(self.tool_executor, ("execute", "reconcile"), False, "Executor")
        if recall_policy is not None:
            from .recall import MemoryRecallPolicy

            if not isinstance(recall_policy, MemoryRecallPolicy):
                raise ValidationError("recall_policy must be a MemoryRecallPolicy")
        if knowledge is not None:
            from .recall import _integer

            _integer(getattr(knowledge, "limit", None), "Knowledge reference limit", 1)
            _integer(getattr(knowledge, "max_chars", None), "Knowledge character limit", 2)
        if recall_policy is not None and recall_planner is not None:
            raise ValidationError("Configure a recall policy or planner, not both")
        if recall_planner is not None:
            self._component_identity(recall_planner, ("plan",), True, "Recall planner")
        self.recall_policy = recall_policy
        self.recall_planner = recall_planner
        self.runtime_profile = (
            None if runtime_profile is None else runtime_profile_identity(runtime_profile)
        )
        self.knowledge = knowledge
        if recall_policy is not None:
            self._component_identity(recall_policy, (), True, "Recall policy")
        if knowledge is not None:
            self._component_identity(knowledge, ("references", "validate"), False, "Knowledge")
        self._workflow = StaticWorkflowRuntime(
            self, workflow_compiler, workflow_interpreter, workflow_transforms
        )
        from .workflow_scheduler import StaticWorkflowScheduler

        self.workflow_scheduler = (
            StaticWorkflowScheduler() if workflow_scheduler is None else workflow_scheduler
        )
        self._component_identity(self.workflow_scheduler, ("select",), True, "Workflow scheduler")
        from .orchestration import OrchestrationRuntime

        self._orchestration = OrchestrationRuntime(
            self, team_strategies=team_strategies, planners=planners, plan_verifiers=plan_verifiers
        )
        self.scope = scope or Scope()
        from .binding_catalog import BindingCatalog
        from .binding_runtime import AgentBindingResolver

        if binding_catalog is not None and (
            not isinstance(binding_catalog, BindingCatalog) or binding_catalog.scope != self.scope
        ):
            raise ValidationError("BindingCatalog must match the trusted Engine Scope")
        self.binding_catalog = binding_catalog
        self._bindings = AgentBindingResolver(self)
        self.policy = policy
        self.owner = uuid.uuid4().hex
        self._active = set()
        self._inflight = {}
        self._parallel_tasks = {}
        self._quiescing_runs = set()
        self._locks = {}
        self._drive_users = {}
        self._threads = ThreadExecutionTracker()
        self._lifecycle = "open"
        if coordinator is None:
            factory = getattr(store, "create_coordinator", None)
            if factory is None:
                raise ValidationError(
                    "Custom execution stores require an explicit coordinator lease"
                )
            coordinator = factory()
        acquire = getattr(coordinator, "acquire", None)
        if not is_sync_callable(acquire) or not is_sync_callable(
            getattr(coordinator, "release", None)
        ):
            raise ValidationError("Coordinator must implement synchronous acquire and release")
        self.coordinator = coordinator
        # A failed acquire may be a reused lease's existing owner. Its adapter
        # owns partial-failure cleanup; this constructor must never release it.
        acquired = acquire()
        try:
            _complete_sync_none(acquired, "Coordinator.acquire")
            self._default_memory = None
            if session_store is None or memory_store is None:
                factory = getattr(store, "create_memory", None)
                if factory is None:
                    raise ValidationError(
                        "Custom stores require explicit session_store and memory_store"
                    )
                self._default_memory = factory()
            self.sessions = self._default_memory if session_store is None else session_store
            self.memory = self._default_memory if memory_store is None else memory_store
            from .binding_data import FactsView, KnowledgeView
            from .binding_sessions import SessionView

            if isinstance(self.sessions, SessionView):
                raise ValidationError(
                    "Host Session defaults require an original backend, not a view"
                )
            if conversation_resource is not None:
                from .session_conversations import select_conversation

                select_conversation(self)
            if isinstance(self.memory, FactsView) or isinstance(self.knowledge, KnowledgeView):
                raise ValidationError(
                    "Host data defaults require original components, not scoped views"
                )
            for backend, methods in (
                (self.sessions, ("read", "append")),
                (self.memory, ("facts",)),
            ):
                if (
                    not isinstance(getattr(backend, "backend_id", None), str)
                    or not backend.backend_id
                ):
                    raise ValidationError("Memory backends require a non-empty stable backend_id")
                if any(not callable(getattr(backend, name, None)) for name in methods):
                    raise ValidationError("Memory backend does not implement its configured port")
            self.context = ContextAssembler() if context_assembler is None else context_assembler
            if (
                not callable(getattr(self.context, "assemble", None))
                or not isinstance(getattr(self.context, "identity", None), dict)
                or not self.context.identity
            ):
                raise ValidationError("Context assembler requires identity and assemble")
            canonical(self.context.identity)
            self._bindings._pin_artifact_ports(self.context)
        except BaseException:
            _invoke_sync_none(self.coordinator.release, "Coordinator.release")
            raise

    def __enter__(self):
        self._ensure_open()
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._lifecycle == "closed":
            return
        if self._lifecycle == "closing":
            raise ValidationError("Engine is already closing")
        if (
            self._drive_users
            or any(not task.done() for task in self._inflight.values())
            or any(not task.done() for tasks in self._parallel_tasks.values() for task in tasks)
            or self._threads.has_active
        ):
            raise ValidationError(
                "Finish active drive tasks and synchronous calls before closing the coordinator"
            )
        if self._lifecycle != "store_closed":
            if self._lifecycle == "open":
                for run_id in tuple(self._quiescing_runs):
                    self._mark_workflow_quiescent(run_id)
            self._lifecycle = "closing"
            try:
                _invoke_sync_none(self.store.close, "ExecutionStore.close")
            except BaseException:
                self._lifecycle = "close_failed"
                raise
            self._lifecycle = "store_closed"
        # A failed close keeps ownership and permits only a close retry. Once
        # storage is closed, a failed lease release must not reopen the Engine.
        _invoke_sync_none(self.coordinator.release, "Coordinator.release")
        self._lifecycle = "closed"

    async def wait_for_threads(self):
        """Wait for owned synchronous calls; this does not cancel drive tasks."""
        await self._threads.drain()
        for run_id in tuple(self._quiescing_runs):
            self._mark_workflow_quiescent(run_id)

    def _mark_workflow_quiescent(self, run_id, *, supervisor=False):
        if (
            self._threads.has_active_for(run_id)
            or any(not t.done() for t in self._parallel_tasks.get(run_id, ()))
            or (not supervisor and self._operation_active(run_id))
        ):
            return
        with self.store.transaction():
            run = self._authorized(run_id)
            if (
                run.get("plan", {}).get("schema_version") == 3
                and run["workflow"].get("quiescent") is False
            ):
                run["workflow"]["quiescent"] = True
                self._commit(run, "workflow_quiesced")
        self._quiescing_runs.discard(run_id)

    def _ensure_open(self):
        if self._lifecycle != "open":
            raise ValidationError("Engine is not open; only close may be retried")

    def _operation_active(self, run_id):
        task = self._inflight.get(run_id)
        return (
            (task is not None and not task.done())
            or any(not t.done() for t in self._parallel_tasks.get(run_id, ()))
            or self._threads.has_active_for(run_id)
        )

    def _authorized(self, run_id):
        self._ensure_open()
        run = self.store.run(run_id)
        if run["scope"] != asdict(self.scope):
            raise AuthorizationDenied("Run belongs to another workspace or principal")
        return run

    @staticmethod
    def _validate_policy(policy):
        # Inspect async callable instances as well as ordinary async functions.
        method = getattr(policy, "__call__", None)  # noqa: B004
        if policy is not None and (
            not callable(policy)
            or any(
                inspect.iscoroutinefunction(candidate)
                or inspect.isasyncgenfunction(candidate)
                or inspect.isgeneratorfunction(candidate)
                for candidate in (policy, method)
            )
        ):
            raise ValidationError("Authorization policy must execute synchronously")

    def status(self, run_id):
        return RunSnapshot.from_record(self._authorized(run_id))

    @staticmethod
    def _component_identity(component, methods, synchronous, label):
        try:
            identity = component.identity
            if not isinstance(identity, dict) or not identity:
                raise ValidationError(f"{label} requires a non-empty JSON identity")
            canonical(identity)
            for name in methods:
                method = getattr(component, name, None)
                if not callable(method):
                    raise ValidationError(f"{label} does not implement {name}")
                if synchronous:
                    candidates = (method, getattr(method, "__call__", None))  # noqa: B004
                    if any(
                        inspect.iscoroutinefunction(value)
                        or inspect.isasyncgenfunction(value)
                        or inspect.isgeneratorfunction(value)
                        for value in candidates
                    ):
                        raise ValidationError(f"{label}.{name} must be synchronous")
                elif not inspect.iscoroutinefunction(method):
                    raise ValidationError(f"{label}.{name} must be an async method")
            return copy.deepcopy(identity)
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError(f"Cannot validate {label} configuration") from exc

    @staticmethod
    def _component_result(value, expected, label):
        if not isinstance(value, expected):
            if inspect.iscoroutine(value) or inspect.isgenerator(value):
                value.close()
            raise ValidationError(f"{label} returned an unsupported value")
        return value

    def events(self, run_id, *, after=0, limit=1000):
        self._authorized(run_id)
        return self.store.events(run_id, after, limit)

    def diagnostics(self, run_id):
        with self.store.transaction():
            run = self._authorized(run_id)
            return RunDiagnostics(
                RunSnapshot.from_record(run),
                run["manifest"],
                run["release_digest"],
                self.store.budget(run_id),
                workflow_details(run, self.store),
            )

    def parent_run_id(self, run_id):
        """Read the durable managed-call owner without resolving a new release."""
        with self.store.transaction():
            run = self._authorized(run_id)
            parent_id = run.get("parent_id")
            if parent_id is None:
                return None
            parent = self._authorized(parent_id)
            if not any(
                call["run_id"] == run_id and call["id"] == run.get("call_id")
                for call in parent.get("orchestration", {}).get("children", [])
            ):
                raise DefinitionMismatch("Managed child has no original parent ownership")
            return parent_id

    def memory_stages(self, run_id):
        """Scope-authorized immutable copy of auxiliary memory evidence, no I/O."""
        run = self._authorized(run_id)
        from .composite_context import query
        from .managed_memory_stage import validate_journal

        return query(self, run, "memory_stages", validate_journal)

    def context_stages(self, run_id):
        """Scope-authorized context preparation receipts, without model I/O."""
        from .context_preparation import validate_journal

        run = self._authorized(run_id)
        from .composite_context import query

        return query(self, run, "context_preparations", validate_journal)

    def context_artifacts(self, run_id):
        """Query original artifact evidence without touching live data storage."""
        from .context_artifacts import validate_journal

        run = self._authorized(run_id)
        from .composite_context import query

        return query(self, run, "context_artifacts", validate_journal)

    def patch_plan(self, run_id, proposal, *, expected_plan_revision, command_id):
        self._ensure_open()
        return self._orchestration._dag.patch(run_id, proposal, expected_plan_revision, command_id)

    @property
    def binding_capabilities(self):
        from .binding_runtime import binding_capabilities

        capabilities = binding_capabilities()
        available = is_sync_callable(getattr(self.store, "session_resource_owner", None))
        capabilities["session_resource_admission"] = available
        if not available:
            capabilities["supported_binding_roles"].remove("session")
            capabilities["session_modes"] = ["inherit", "disabled"]
            capabilities["resource_selector_roles"].pop("session")
        return capabilities

    def _components(self, run, index=None):
        return self._bindings.components(run, index)

    def _agent_step(self, run, index=None):
        return self._bindings.effective_step(run, index)

    @staticmethod
    def _step_manifest(run, index=None):
        from .binding_manifests import step_manifest

        return step_manifest(run["manifest"], run["node"] if index is None else index)

    def _manifest(self, steps, *, components=None):
        history_registration = self._history_registration()
        sessions = self.sessions if components is None else components.sessions
        memory = self.memory if components is None else components.memory
        context = self.context if components is None else components.context
        harness = self.harness if components is None else components.harness
        knowledge = self.knowledge if components is None else components.knowledge
        verifier = self.verifier if components is None else components.verifier
        names = sorted({name for step in steps for name in step["tools"]})
        providers = {}
        continuations = {}
        for step in steps:
            provider = (
                self.providers.get(step["provider"]) if components is None else components.provider
            )
            if provider is None:
                raise DefinitionMismatch(f"Model provider not configured: {step['provider']}")
            if not inspect.iscoroutinefunction(getattr(provider, "complete", None)):
                raise ValidationError("ModelProvider.complete must be an async method")
            if not isinstance(getattr(provider, "identity", None), dict) or not provider.identity:
                raise ValidationError("ModelProvider.identity must be a non-empty JSON object")
            providers[step["provider"]] = copy.deepcopy(provider.identity)
            continuation = provider_continuation_identity(provider)
            if continuation is not None and not self.model_continuation:
                raise ValidationError("This Provider requires explicit model continuation")
            continuations[step["provider"]] = continuation
            if step["output_schema"] is not None:
                Draft202012Validator.check_schema(step["output_schema"])
        manifest = {
            "kernel": "local-6"
            if history_registration is not None
            else "local-5"
            if self.model_continuation
            else "local-4",
            "tools": self.tools.manifests(names),
            "providers": providers,
            "session_backend": sessions.backend_id if sessions is not None else None,
            "memory_backend": memory.backend_id if memory is not None else None,
            "context_builder": copy.deepcopy(context.identity),
            "harness": self._component_identity(harness, ("prepare", "propose"), True, "Harness"),
            "tool_executor": self._component_identity(
                self.tool_executor, ("execute", "reconcile"), False, "Executor"
            ),
        }
        if self.model_continuation:
            manifest["model_continuation_protocol"] = 1
            manifest["provider_continuations"] = continuations
        if history_registration is not None:
            manifest["model_history_protocol"] = 1
            manifest["model_history"] = history_registration
        if self.recall_policy is not None:
            manifest["memory_recall"] = self._component_identity(
                self.recall_policy, (), True, "Recall policy"
            )
        if knowledge is not None:
            manifest["knowledge"] = self._component_identity(
                knowledge, ("references", "validate"), False, "Knowledge"
            )
        if self.recall_planner is not None:
            manifest["recall_planner"] = self._component_identity(
                self.recall_planner, ("plan",), True, "Recall planner"
            )
        if verifier is not None:
            manifest["completion_verifier"] = self._component_identity(
                verifier, ("verify",), True, "Completion verifier"
            )
        stage = self.stage_policy if components is None else components.stage_policy
        if stage is not None:
            from .managed_memory import stage_identity

            manifest["managed_memory"] = stage_identity(stage, self.scope, engine=self)
        from .agent_limits import limit_manifest

        caps = limit_manifest(self, steps, None if components is None else components.limits)
        if caps is not None:
            manifest["agent_limits"] = caps
        if self.runtime_profile is not None:
            manifest["runtime_profile"] = runtime_profile_identity(self.runtime_profile)
        from .managed_context import context_stage_manifest

        context_stage = context_stage_manifest(self, context)
        if context_stage is not None:
            manifest["managed_context"] = context_stage
        return manifest

    def _history_registration(self):
        from .model_history import model_history_registration

        if self.model_history is not self._model_history_pin:
            raise DefinitionMismatch("The executing model history policy changed")
        if self.model_history is None:
            return None
        from .task_controls import _binding

        registration = model_history_registration(self.model_history)
        if (
            registration != self._model_history_registration
            or not self.model_continuation
            or any(
                _binding(getattr(self.model_history, name)) != binding
                for name, binding in self._model_history_bindings.items()
            )
        ):
            raise DefinitionMismatch("The model history policy differs from its fixed identity")
        return registration

    def _validate_model_history(self, history, messages):
        from .model_history import validate_model_history

        registration = self._history_registration()
        if registration is None:
            return
        validate_model_history(
            history,
            messages,
            allow_tool_result_projection=registration["identity"].get(
                "allow_tool_result_projection", False
            ),
        )
        self._component_result(
            self.model_history.validate(copy.deepcopy(history), copy.deepcopy(messages)),
            type(None),
            "ModelHistoryPolicy.validate",
        )
        self._history_registration()

    def _assemble_context(self, history, references, max_chars, *, context=None):
        context = self.context if context is None else context
        registration = self._history_registration()
        try:
            if registration is None:
                value = context.assemble(history, references, max_chars)
            else:
                from .data_context import ManagedDataContext
                from .model_history import validate_reference_evidence

                validate_reference_evidence(references)
                projected, refs = copy.deepcopy(history), copy.deepcopy(references)
                artifacts, coverage = [], []
                if isinstance(context, ManagedDataContext):
                    if registration["identity"].get("allow_tool_result_projection", False):
                        projected, artifacts = context.project_history(projected)
                    refs, coverage = context.project_references(refs)
                value = self.model_history.assemble(projected, refs, max_chars, context=context)
            value = self._component_result(value, (tuple, list), "Context assembly")
            if len(value) != 2:
                raise ValidationError("Context assembler must return a messages/manifest pair")
            messages, manifest = value
            if registration is not None:
                self._validate_model_history(history, messages)
                manifest = {
                    **manifest,
                    "model_history": copy.deepcopy(registration),
                    "model_history_protocol": 1,
                }
                if isinstance(context, ManagedDataContext):
                    manifest.update(artifact_projection=artifacts, reference_compression=coverage)
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Context assembler failed to build a valid snapshot") from exc
        if not isinstance(messages, list) or not isinstance(manifest, dict):
            raise ValidationError("Context assembler must return messages and a JSON manifest")
        size = len(canonical(messages))
        if size > max_chars:
            raise ValidationError("Context assembler exceeded the configured character limit")
        manifest = {**manifest, "digest": digest(messages), "chars": size}
        canonical(manifest)
        return messages, manifest

    def submit(self, spec, input, *, command_id, budget=32, session_id=None, _parent_call=None):
        self._ensure_open()
        payload = submission_request(spec, input, budget=budget, session_id=session_id)
        definition = payload["definition"]
        if definition["kind"] in {"bound_agent", "bound_definition"}:
            from .binding_runtime import unwrap_definition

            definition = unwrap_definition(definition)
        if _parent_call is not None:
            if not isinstance(_parent_call, dict) or set(_parent_call) not in (
                {"parent_id", "call_id", "reservation"},
                {"parent_id", "call_id", "reservation", "limits_member"},
            ):
                raise ValidationError("Invalid managed parent call binding")
            for value in _parent_call.values():
                if not isinstance(value, str) or not value.strip():
                    raise ValidationError(
                        "Managed parent call identities must be non-empty strings"
                    )
            payload["parent_call"] = copy.deepcopy(_parent_call)
        run_id = uuid.uuid4().hex
        # Request identity contains only caller-controlled data. Configuration
        # aliases are resolved inside first acceptance, after receipt lookup.
        canonical(payload)

        def apply():
            return self._accept_submission(run_id, payload, _parent_call)

        receipt = self.store.command(self.scope, command_id, "submit", payload, run_id, apply)
        return RunHandle(receipt.run_id, receipt)

    def _accept_submission(self, run_id, payload, _parent_call=None):
        definition = payload["definition"]
        if definition["kind"] in {"bound_agent", "bound_definition"}:
            from .binding_runtime import unwrap_definition

            definition = unwrap_definition(definition)
        budget, session_id = payload["budget"], payload["session_id"]
        if definition["kind"] in {"team", "dynamic"}:
            return self._orchestration.accept(
                run_id, definition, payload["input"], budget, session_id, _parent_call
            )
        bound = "binding_definition" in definition
        graph = definition["kind"] == "graph"
        plan = self._workflow.compile(definition) if graph else None
        manifest = (
            self._bindings.manifest(definition, plan=plan)
            if bound
            else self._workflow.manifest(plan)
            if graph
            else self._manifest(definition["steps"])
        )
        if _parent_call is not None:
            parent = self._authorized(_parent_call["parent_id"])
            if (
                parent.get("orchestration") is None
                or parent["state"] in TERMINAL
                or parent["state"] == "cancelling"
            ):
                raise ValidationError("A managed child requires an active orchestration parent")
            self._check_parent_limits(parent, _parent_call, manifest)
            manifest["parent_call"] = copy.deepcopy(_parent_call)
        messages = [] if graph else self._initial_messages(definition["steps"][0], payload["input"])
        if (
            bound
            and session_id is not None
            and any(
                entry["manifest"]["session_backend"] is None
                for entry in manifest["agent_bindings"]["steps"].values()
            )
        ):
            raise ValidationError("Explicit Session requires a Session binding")
        if not graph:
            from .agent_limits import apply_pinned_limits
            from .binding_manifests import step_manifest

            if bound:
                from .binding_runtime import descriptor_for

                components = self._bindings.resolve(
                    definition["steps"][0], descriptor_for(definition, 0)
                )[0]
                self._assemble_context(
                    messages,
                    [],
                    apply_pinned_limits(
                        {**definition["steps"][0], "tools": list(components.tools)},
                        step_manifest(manifest, 0),
                    )["max_context_chars"],
                    context=components.context,
                )
            else:
                self._assemble_context(
                    messages,
                    [],
                    apply_pinned_limits(definition["steps"][0], manifest)["max_context_chars"],
                )
        execution_definition = definition
        if graph:
            # Old native kernels can read this shape and reject the new
            # workflow Manifest before scheduling. It is not a second plan
            # and never mutates the caller's idempotency payload.
            execution_definition = {
                **definition,
                "steps": [node["agent"] for node in plan["nodes"] if node["agent"] is not None],
            }
        session_ids = [session_id or run_id]
        parallel = graph and plan["schema_version"] == 3
        if parallel:
            session_ids += [f"{session_ids[0]}:node:{n['id']}" for n in plan["nodes"]]
        from .session_resources import admit_sessions

        session_claim_data = admit_sessions(self, manifest, session_ids, plan)
        from .managed_memory import admit_stages

        admit_stages(self, manifest, definition["kind"], _parent_call)
        from .managed_context import admit_context

        admit_context(self, manifest, definition["kind"], _parent_call)
        data = {
            "id": run_id,
            "revision": 0,
            "scope": asdict(self.scope),
            "state": "queued",
            "definition": execution_definition,
            "manifest": manifest,
            "release_digest": digest({"definition": execution_definition, "manifest": manifest}),
            "input": payload["input"],
            "result": None,
            "error": None,
            "node": None if graph else 0,
            "decisions": 0,
            "actions": [],
            "messages": messages,
            "session_id": session_id or run_id,
            **({"session_ids": session_ids} if parallel else {}),
            **session_claim_data,
            **(
                {
                    "parent_call": copy.deepcopy(_parent_call),
                    "parent_id": _parent_call["parent_id"],
                    "call_id": _parent_call["call_id"],
                }
                if _parent_call is not None
                else {}
            ),
        }
        if graph:
            data["plan"] = plan
            data["workflow"] = {
                "current": None,
                "nodes": {node["id"]: {"state": "pending"} for node in plan["nodes"]},
            }
        self.store.insert_run(data)
        self.store.create_budget(run_id, budget)
        self.store.emit(run_id, "run_submitted", {"release_digest": data["release_digest"]})
        return {"state_revision": 0}

    @staticmethod
    def _initial_messages(step, input):
        return [
            {"role": "system", "content": step["instructions"]},
            {"role": "user", "content": input if isinstance(input, str) else canonical(input)},
        ]

    def approve(self, run_id, action_id, target_digest, *, command_id, approved=True):
        self._authorized(run_id)

        def apply():
            run = self._authorized(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return {"rejected": True, "reason": "target_closed"}
            action = next((a for a in run["actions"] if a["id"] == action_id), None)
            if (
                action is None
                or action["status"] != "waiting_approval"
                or action["digest"] != target_digest
            ):
                raise ValidationError("Approval does not match the pending operation")
            action["approved"] = approved
            action["status"] = "ready" if approved else "failed"
            run["state"] = "running" if approved else "failed"
            if not approved:
                run["error"] = {"code": "approval_rejected"}
                if run.get("plan", {}).get("schema_version") == 3:
                    from .workflow_parallel import close_nodes

                    close_nodes(run, action["node"])
                    self.store.emit(run_id, "run_failed", {"code": "approval_rejected"})
            self.store.save_run(run)
            self.store.emit(
                run_id,
                "approval_applied",
                {"action_id": action_id, "digest": target_digest, "approved": approved},
            )
            return {"state_revision": run["revision"]}

        return self.store.command(
            self.scope,
            command_id,
            "approve",
            {
                "run_id": run_id,
                "action_id": action_id,
                "digest": target_digest,
                "approved": approved,
            },
            run_id,
            apply,
        )

    def cancel(self, run_id, *, command_id):
        self._authorized(run_id)

        def apply():
            run = self._authorized(run_id)
            active = run_id in self._active or self._operation_active(run_id)
            if not active and self._normalize_abandoned(run):
                self._commit(run, "abandoned_attempts_unknown")
            if run["state"] in {"succeeded", "failed"}:
                return {"rejected": True, "reason": "too_late"}
            if run["state"] in {"cancelled", "cancelling"}:
                return {
                    "reason": "already_terminal" if run["state"] == "cancelled" else "applied_noop"
                }
            run["state"] = "cancelling" if active else "cancelled"
            if run.get("orchestration") is not None:
                self._orchestration.cancel_children(run)
            if is_graph(run):
                for node in run["workflow"]["nodes"].values():
                    if node["state"] not in {"completed", "skipped", "failed", "cancelled"}:
                        node["state"] = "cancelled"
                if run.get("plan", {}).get("schema_version") == 3:
                    from .workflow_parallel import close_nodes

                    close_nodes(run)
            self.store.save_run(run)
            self.store.emit(run_id, "cancel_applied", {"state": run["state"]})
            return {"state_revision": run["revision"]}

        return self.store.command(
            self.scope, command_id, "cancel", {"run_id": run_id}, run_id, apply
        )

    def reconcile(self, run_id, action_id, result, *, command_id):
        """Local owner's explicit confirmation of an already-completed external effect."""
        run = self._authorized(run_id)
        if run.get("plan", {}).get("schema_version") == 3:
            from .workflow_parallel import ParallelWorkflowRuntime

            return ParallelWorkflowRuntime(self).reconcile(run_id, action_id, result, command_id)
        canonical(result)

        def apply():
            run = self._authorized(run_id)
            action = next((a for a in run["actions"] if a["id"] == action_id), None)
            if action is None or action["kind"] != "tool" or action["status"] != "outcome_unknown":
                raise ValidationError("No unknown tool effect to reconcile")
            self._tool_result(
                run, action, result, {"source": "local-owner", "command_id": command_id}
            )
            if run["state"] not in TERMINAL and run["state"] != "cancelling":
                run["state"] = "running"
            self.store.save_run(run)
            self.store.emit(
                run_id, "effect_reconciled", {"action_id": action_id, "source": "local-owner"}
            )
            return {"state_revision": run["revision"]}

        return self.store.command(
            self.scope,
            command_id,
            "reconcile",
            {"run_id": run_id, "action_id": action_id, "result": result},
            run_id,
            apply,
        )

    def _check_release(self, run):
        from .context_preparation import validate_journal

        parallel = run.get("plan", {}).get("schema_version") == 3
        journal_run = {**run, "actions": []} if parallel else run
        validate_journal(self, journal_run)
        from .context_artifacts import validate_journal as validate_artifacts

        validate_artifacts(self, journal_run)
        if parallel:
            from .composite_context import validate_frames

            validate_frames(self, run)
        from .remote_session_saves import check_remote_session_run

        check_remote_session_run(self, run)
        if "session_turn" in run:
            from .session_conversations import check_conversation_run

            check_conversation_run(self, run)
        manifest = (
            self._bindings.manifest(run["definition"], plan=run.get("plan"))
            if "binding_definition" in run["definition"]
            else self._orchestration.manifest(run["definition"])
            if run.get("orchestration") is not None
            else self._workflow.manifest(run["plan"])
            if is_graph(run)
            else self._manifest(run["definition"]["steps"])
        )
        if run.get("parent_call") is not None:
            binding = run["parent_call"]
            parent = self._authorized(binding["parent_id"])
            self._check_release(parent)
            if not any(
                call["id"] == binding["call_id"]
                and call["run_id"] == run["id"]
                and ("limits_member" not in binding or call["member"] == binding["limits_member"])
                for call in parent["orchestration"]["children"]
            ):
                raise DefinitionMismatch("The child's pinned parent release or ownership changed")
            self._check_parent_limits(parent, binding, manifest)
            manifest["parent_call"] = copy.deepcopy(binding)
        if digest(manifest) != digest(run["manifest"]):
            raise DefinitionMismatch(
                "Pinned tool, provider or memory backend differs from this Run"
            )

    def _check_parent_limits(self, parent, binding, manifest):
        from .agent_limits import has_agent_limits, validate_inherited_limits

        if not has_agent_limits(parent["manifest"]) and not has_agent_limits(manifest):
            return
        member = binding.get("limits_member")
        if member not in parent["definition"]["members"] and not (
            member == "@planner"
            and parent["manifest"]["orchestration"].get("planning_agent") is not None
        ):
            raise DefinitionMismatch("Child limits require the original declared member")
        source = (
            parent["manifest"]["orchestration"].get("members", {}).get(member, parent["manifest"])
        )
        validate_inherited_limits(manifest, source)

    def _commit(self, run, kind, data=None):
        self.store.save_run(run)
        self.store.emit(run["id"], kind, data)

    def _normalize_abandoned(self, run):
        changed = False
        for action in run["actions"]:
            if action["status"] == "executing":
                action["status"] = "outcome_unknown"
                action["attempts"][-1]["status"] = "unknown"
                self.store.mark_unknown(action["attempts"][-1]["id"])
                changed = True
        return changed

    def _fail(self, run_id, code):
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] not in TERMINAL:
                run["state"] = "cancelled" if run["state"] == "cancelling" else "failed"
                run["error"] = {"code": code}
                if run.get("orchestration") is not None:
                    self._orchestration.cancel_children(run)
                if run.get("plan", {}).get("schema_version") == 3:
                    from .workflow_parallel import close_nodes

                    close_nodes(run)
                if is_graph(run) and run["workflow"]["current"] is not None:
                    run["workflow"]["nodes"][run["workflow"]["current"]]["state"] = (
                        "failed" if run["state"] == "failed" else "cancelled"
                    )
                self._commit(run, "run_failed", {"code": code})

    async def drive(self, run_id):
        self._ensure_open()
        if self._operation_active(run_id):
            raise CoordinatorBusy("The previous Action is still running; wait for its result")
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        self._drive_users[run_id] = self._drive_users.get(run_id, 0) + 1
        try:
            async with lock:
                return await self._drive_locked(run_id)
        finally:
            users = self._drive_users[run_id] - 1
            if users:
                self._drive_users[run_id] = users
            else:
                self._drive_users.pop(run_id)
            self._cleanup_execution(run_id)

    def _cleanup_execution(self, run_id):
        task = self._inflight.get(run_id)
        if task is not None and task.done():
            self._inflight.pop(run_id)
        # Count owners and queued callers, including cancelled waiters. Removing
        # a lock with waiters would let a new caller create a second Run owner.
        if (
            run_id not in self._drive_users
            and run_id not in self._inflight
            and not any(not t.done() for t in self._parallel_tasks.get(run_id, ()))
        ):
            self._locks.pop(run_id, None)
        if run_id in self._quiescing_runs and self._lifecycle == "open":
            self._mark_workflow_quiescent(run_id)

    async def _drive_locked(self, run_id):
        # A queued caller may have passed the check between two Actions while
        # another drive still owned this lock. Recheck before recovery mutates
        # any attempt: a shielded executor may still be alive after caller cancellation.
        if self._operation_active(run_id):
            raise CoordinatorBusy("The previous Action is still running; wait for its result")
        run = self._authorized(run_id)
        if run["state"] in TERMINAL:
            if "context_preparations" in run or "context_preparation_markers" in run:
                from .context_preparation import recover_terminal_context

                await self._guarded(run_id, recover_terminal_context(self, run_id))
                run = self._authorized(run_id)
            if run.get("plan", {}).get("schema_version") != 3 and (
                "memory_stages" in run or any("memory_stage" in a for a in run["actions"])
            ):
                from .managed_memory_stage import recover_terminal_memory

                await self._guarded(run_id, recover_terminal_memory(self, run_id))
                run = self._authorized(run_id)
            if "remote_session_binding" in run or "remote_session_saves" in run:
                from .remote_session_saves import reconcile_terminal_saves

                await self._guarded(run_id, reconcile_terminal_saves(self, run_id))
            if run.get("orchestration") is not None:
                from .composite_memory import recover_terminal_children

                await self._guarded(run_id, recover_terminal_children(self, run_id))
                self._orchestration.terminal(run_id)
                return self.status(run_id)
            with self.store.transaction():
                if self._normalize_abandoned(run):
                    self._commit(run, "abandoned_attempts_unknown")
            self._adopt_received_evidence(run_id)
            if run.get("plan", {}).get("schema_version") == 3:
                from .composite_context import recover_terminal_frames

                await recover_terminal_frames(self, run_id)
                self._mark_workflow_quiescent(run_id)
            return self.status(run_id)
        self._check_release(run)
        self._active.add(run_id)
        try:
            with self.store.transaction():
                run = self._authorized(run_id)
                self._normalize_abandoned(run)
                if run["state"] != "cancelling":
                    run["state"] = "running"
                if run.get("plan", {}).get("schema_version") == 3:
                    run["workflow"]["quiescent"] = False
                    self._quiescing_runs.add(run_id)
                self._commit(run, "run_resumed")
            if run["definition"]["kind"] in {"graph", "team", "dynamic"} and "turn" in run.get(
                "remote_session_saves", {}
            ):
                from .remote_composite_saves import resume_result

                await self._guarded(run_id, resume_result(self, run_id))
                return self.status(run_id)
            if run.get("orchestration") is not None:
                return await self._guarded(run_id, self._orchestration.drive(run_id))
            if run.get("plan", {}).get("schema_version") == 3:
                from .workflow_parallel import ParallelWorkflowRuntime

                return await self._guarded(run_id, ParallelWorkflowRuntime(self).drive(run_id))
            while True:
                run = self._authorized(run_id)
                if run["state"] in TERMINAL:
                    self._adopt_received_evidence(run_id)
                    break
                if run["state"] == "cancelling":
                    with self.store.transaction():
                        run["state"] = "cancelled"
                        self._commit(run, "run_cancelled")
                    break
                if is_graph(run):
                    if not await self._guarded(run_id, self._workflow.prepare(run_id)):
                        if self._authorized(run_id)["state"] == "waiting_reconciliation":
                            break
                        continue
                    run = self._authorized(run_id)
                    if run["plan"]["nodes"][run["node"]]["transform"] is not None:
                        await self._guarded(run_id, self._workflow.transform(run_id))
                        continue
                    if run["plan"]["nodes"][run["node"]].get("tool") is not None:
                        if not await self._guarded(run_id, self._workflow.tool(run_id)):
                            if self._authorized(run_id)["state"] == "cancelling":
                                continue
                            break
                        continue
                pending = next(
                    (
                        a
                        for a in run["actions"]
                        if a["node"] == run["node"]
                        and a["kind"] == "tool"
                        and a["status"] != "completed"
                    ),
                    None,
                )
                if pending:
                    if not await self._guarded(run_id, self._tool(run_id, pending["id"])):
                        if self._authorized(run_id)["state"] == "cancelling":
                            continue
                        break
                else:
                    adopted = next(
                        (
                            a
                            for a in reversed(run["actions"])
                            if a["node"] == run["node"]
                            and a["kind"] == "model"
                            and a["status"] == "completed"
                        ),
                        None,
                    )
                    if (
                        adopted
                        and not adopted["response"]["tool_calls"]
                        and adopted.get("completion_verification", {})
                        .get("verdict", {})
                        .get("status")
                        != "retry"
                    ):
                        finished = await self._guarded(
                            run_id, self._finish_node(run_id, adopted["response"]["output"])
                        )
                        if finished is False:
                            if self._authorized(run_id)["state"] == "cancelling":
                                continue
                            break
                    else:
                        if not await self._guarded(run_id, self._model(run_id)):
                            if self._authorized(run_id)["state"] == "cancelling":
                                continue
                            break
            return self.status(run_id)
        except RalfError as exc:
            self._fail(run_id, exc.code)
            return self.status(run_id)
        finally:
            self._active.discard(run_id)

    async def _guarded(self, run_id, operation):
        # Caller cancellation must not discard an in-flight effect or free its coordinator.
        tracker_token = current_thread_tracker.set(self._threads)
        group_token = current_thread_group.set(run_id)
        try:
            task = asyncio.create_task(operation)
        finally:
            current_thread_group.reset(group_token)
            current_thread_tracker.reset(tracker_token)
        self._inflight[run_id] = task

        def completed(finished):
            if not finished.cancelled():
                finished.exception()
            if self._inflight.get(run_id) is finished:
                self._inflight.pop(run_id)
            self._cleanup_execution(run_id)

        task.add_done_callback(completed)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self.cancel(run_id, command_id=f"drive-cancel:{uuid.uuid4().hex}")
            raise

    async def _finish_node(self, run_id, result):
        run = self._authorized(run_id)
        if run["state"] in TERMINAL or run["state"] == "cancelling":
            return
        step = self._agent_step(run)
        result = final_output(result, step["output_schema"])
        if is_graph(run):
            from .workflow import validate_output

            result = validate_output(result, run["plan"]["nodes"][run["node"]]["output_schema"])
        from .completion_runtime import verify_completion

        if not verify_completion(self, run_id, result):
            return
        sessions = self._components(run).sessions
        from .remote_session_saves import save_remote_result

        saved = await save_remote_result(self, run_id, result)
        if saved is False:
            return False
        revision, _ = (
            (await memory_call(sessions.read, self.scope, run["session_id"]))
            if saved is None and sessions is not None
            else (0, [])
        )

        current = self._authorized(run_id)
        if current["state"] in TERMINAL or current["state"] == "cancelling":
            return
        self._check_release(current)
        if (sessions.backend_id if sessions is not None else None) != self._step_manifest(current)[
            "session_backend"
        ]:
            raise DefinitionMismatch("The executing session backend differs from this Run")
        if saved is None and sessions is not None:
            await memory_call(
                sessions.append,
                self.scope,
                run["session_id"],
                {
                    "role": "assistant",
                    "content": result,
                    "agent": step["name"],
                    "task": run["workflow"]["nodes"][run["workflow"]["current"]]["input"]
                    if is_graph(run)
                    else run["input"],
                },
                expected_revision=revision,
                message_id=f"{run_id}:{run['node']}:result",
            )
        from .managed_memory_stage import finish_memory_stage

        await finish_memory_stage(self, run_id, result)
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return
            # An append may already have committed externally. A changed backend
            # cannot be silently confirmed as completing the pinned Release.
            self._check_release(run)
            if (sessions.backend_id if sessions is not None else None) != self._step_manifest(run)[
                "session_backend"
            ]:
                raise DefinitionMismatch("The executing session backend differs from this Run")
            if is_graph(run):
                self._workflow.complete(run, result)
                return
            run["node"] += 1
            if run["node"] == len(run["definition"]["steps"]):
                run["state"] = "succeeded"
                run["result"] = result
                self._commit(run, "run_succeeded")
            else:
                run["decisions"] = 0
                run["messages"] = self._initial_messages(self._agent_step(run), result)
                self._commit(run, "workflow_node_completed", {"node": run["node"] - 1})

    def _prepare_model_request(self, run, step, messages, context_manifest):
        components = self._components(run)
        harness = components.harness
        spec = AgentSpec(**copy.deepcopy(step))
        descriptions = self.tools.descriptions(step["tools"])
        try:
            prepared = self._component_result(
                harness.prepare(spec, copy.deepcopy(messages), copy.deepcopy(descriptions)),
                ModelRequest,
                "Harness.prepare",
            )
            # A custom policy may retain its DTO. Freeze the actual request now.
            request = ModelRequest(prepared.messages, prepared.tools)
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Harness failed to prepare a model request") from exc
        self._check_release(self._authorized(run["id"]))
        self._validate_model_history(run["messages"], request.messages)
        if digest(
            self._component_identity(harness, ("prepare", "propose"), True, "Harness")
        ) != digest(self._step_manifest(run)["harness"]):
            raise DefinitionMismatch("The preparing Harness differs from this Run")
        if not request.messages or len(canonical(request.messages)) > step["max_context_chars"]:
            raise ValidationError("Harness request exceeded the context limit or has no messages")
        request_measurement = None
        validate_request = getattr(components.context, "validate_request", None)
        if validate_request is not None:
            from .context_budget import ContextMeasure

            if not is_sync_callable(validate_request):
                raise ValidationError("Context request validation must be synchronous")
            measurement = self._component_result(
                validate_request(copy.deepcopy(request.messages), step["max_context_chars"]),
                ContextMeasure,
                "Context request validation",
            )
            request_measurement = asdict(
                ContextMeasure(measurement.units, measurement.unit, measurement.estimated)
            )
            self._check_release(self._authorized(run["id"]))
            if not request.messages or len(canonical(request.messages)) > step["max_context_chars"]:
                raise ValidationError("Prepared request exceeded the final context limit")
        allowed = {item["function"]["name"]: item for item in descriptions}
        offered = set()
        for description in request.tools:
            function = description.get("function")
            name = function.get("name") if isinstance(function, dict) else None
            if name not in allowed:
                raise AuthorizationDenied("Harness offered a tool outside AgentSpec")
            if name in offered or digest(description) != digest(allowed[name]):
                raise ValidationError("Harness changed or duplicated a registered tool descriptor")
            offered.add(name)
        changed = digest(request.messages) != digest(messages)
        manifest = {
            **context_manifest,
            "digest": digest(request.messages),
            "chars": len(canonical(request.messages)),
            "assembly": copy.deepcopy(context_manifest),
            "harness_transformed": changed,
        }
        if request_measurement is not None:
            manifest["measurement"] = request_measurement
        if changed:
            # Preserve assembly provenance without claiming the transformed
            # request still contains each selected reference.
            manifest["reference_versions"] = []
        return request, manifest

    def _record_model_response(self, run_id, action_id, attempt_id, encoded):
        with self.store.transaction():
            run = self._authorized(run_id)
            action = next(item for item in run["actions"] if item["id"] == action_id)
            if action.get("received_response") is not None:
                if digest(action["received_response"]) != digest(encoded):
                    raise ValidationError("Model response identity conflict")
                return
            action["received_response"] = copy.deepcopy(encoded)
            action["status"] = "response_received"
            action["attempts"][-1]["status"] = "completed"
            # Receiving evidence must not resolve live bindings: drift or removal
            # is checked only after the completed response is durable.
            step = agent_step(run, action["node"])
            self.store.settle(
                attempt_id, step["model_credits"], settlement_usage(encoded.get("usage"))
            )
            self._commit(
                run,
                "model_response_recorded",
                {
                    "action_id": action_id,
                    "attempt_id": attempt_id,
                    "response_digest": digest(encoded),
                },
            )

    def _adopt_model_response(self, run_id, action_id):
        run = self._authorized(run_id)
        action = next(item for item in run["actions"] if item["id"] == action_id)
        if action["status"] != "response_received":
            return True
        received = copy.deepcopy(action["received_response"])
        encoded = copy.deepcopy(received)
        continuation = None
        closed = run["state"] in TERMINAL or run["state"] == "cancelling"
        proposals = []
        history_proposals = None
        if not closed:
            self._check_release(run)
            step = self._agent_step(run, action["node"])
            harness = self._components(run, action["node"]).harness
            try:
                validate_received_response(encoded)
                response = decode_received_response(encoded)
                proposed = self._component_result(
                    harness.propose(AgentSpec(**copy.deepcopy(step)), response),
                    DecisionProposal,
                    "Harness.propose",
                )
                continuation = validate_continuation(
                    received,
                    proposed,
                    self._step_manifest(run)
                    .get("provider_continuations", {})
                    .get(step["provider"]),
                    enabled=self.model_continuation,
                )
                validate_model_usage(encoded["usage"])
                effective_calls = []
                for call in proposed.tool_calls:
                    if call.name not in step["tools"]:
                        raise AuthorizationDenied("Harness requested a tool outside AgentSpec")
                    effective_calls.append(
                        ToolCall(
                            call.name,
                            self.tools.get(call.name).resolve_arguments(call.arguments),
                            call.call_id,
                        )
                    )
                proposal = validate_decision(
                    AgentSpec(**copy.deepcopy(step)),
                    DecisionProposal(proposed.output, tuple(effective_calls)),
                    self.tools.manifests(step["tools"]),
                )
                current = self._authorized(run_id)
                self._check_release(current)
                if digest(
                    self._component_identity(harness, ("prepare", "propose"), True, "Harness")
                ) != digest(self._step_manifest(run)["harness"]):
                    raise DefinitionMismatch("The proposing Harness differs from this Run")
                closed = current["state"] in TERMINAL or current["state"] == "cancelling"
                if not closed:
                    from .errors import AgentLimitExceeded

                    maximum = self._bindings.tool_action_limit(current, action["node"])
                    used = sum(
                        a["kind"] == "tool" and a["node"] == action["node"]
                        for a in current["actions"]
                    )
                    if maximum is not None and used + len(proposal.tool_calls) > maximum:
                        raise AgentLimitExceeded("Agent tool Action limit reached")
                    proposals = [
                        self._tool_proposal(
                            run_id, action["node"], call.name, call.arguments, call.call_id
                        )
                        for call in proposal.tool_calls
                    ]
                    validate_call_ids([item["call_id"] for item in proposals])
                    if self.model_history is not None:
                        history_proposals = [
                            {
                                "tool": call.name,
                                "arguments": copy.deepcopy(call.arguments),
                                "call_id": actual["call_id"],
                            }
                            for call, actual in zip(proposed.tool_calls, proposals, strict=True)
                        ]
                    encoded = {**asdict(proposal), "usage": encoded["usage"]}
                    if continuation is not None:
                        encoded["continuation"] = copy.deepcopy(continuation)
            except Exception as exc:
                error = (
                    exc
                    if isinstance(exc, RalfError)
                    else ValidationError("Harness failed to produce a valid decision")
                )
                with self.store.transaction():
                    current = self._authorized(run_id)
                    target = next(item for item in current["actions"] if item["id"] == action_id)
                    target["status"] = "rejected"
                    target["decision_error"] = {"code": error.code}
                    self._commit(
                        current, "decision_rejected", {"action_id": action_id, "code": error.code}
                    )
                if error is exc:
                    raise
                raise error from exc
        with self.store.transaction():
            run = self._authorized(run_id)
            action = next(item for item in run["actions"] if item["id"] == action_id)
            if action["status"] != "response_received":
                return True
            closed = run["state"] in TERMINAL or run["state"] == "cancelling"
            action["response"] = encoded
            action["status"] = "completed"
            action["decision_skipped"] = closed
            if not closed and not proposals and "managed_memory" in self._step_manifest(run):
                action["memory_stage"] = {"schema_version": 1, "required": True}
            if not closed:
                run["actions"].extend(proposals)
                if proposals or self.model_history is not None:
                    message = assistant_message(
                        encoded["output"],
                        history_proposals if history_proposals is not None else proposals,
                        received=received,
                        continuation=continuation,
                    )
                    if (
                        self.model_history is not None
                        and encoded["output"] is not None
                        and not isinstance(encoded["output"], str)
                    ):
                        message["content"] = canonical(encoded["output"])
                    run["messages"].append(message)
            self._commit(
                run,
                "decision_adopted",
                {
                    "action_id": action_id,
                    "proposed_actions": [] if closed else [item["id"] for item in proposals],
                    "decision_skipped": closed,
                },
            )
        return True

    def _tool_proposal(self, run_id, node, name, arguments, call_id=None):
        tool = self.tools.get(name)
        arguments = tool.resolve_arguments(arguments)
        proposed_id = uuid.uuid4().hex
        operation = {
            "run_id": run_id,
            "action_id": proposed_id,
            "tool": tool.manifest,
            "arguments": arguments,
            "scope": asdict(self.scope),
        }
        return {
            "id": proposed_id,
            "kind": "tool",
            "node": node,
            "tool": name,
            "arguments": copy.deepcopy(arguments),
            "digest": digest(operation),
            "effect_key": f"{self.scope.workspace}:{run_id}:{proposed_id}",
            "call_id": call_id or proposed_id,
            "approved": False,
            "status": "ready",
            "attempts": [],
        }

    def _adopt_received_evidence(self, run_id):
        if self._authorized(run_id).get("plan", {}).get("schema_version") == 3:
            from .workflow_parallel import ParallelWorkflowRuntime

            ParallelWorkflowRuntime(self).adopt(run_id)
            return
        for action in self._authorized(run_id)["actions"]:
            if action["status"] == "response_received":
                self._adopt_model_response(run_id, action["id"])
            elif action["status"] == "receipt_received":
                self._adopt_tool_observation(run_id, action["id"])

    async def _recall_pages(self, backend, operation, name, query, max_pages):
        from .recall import LegacyMemoryRecallAdapter, RecallPage, _method_backend

        method = getattr(backend, operation, None)
        if not callable(method):
            method = getattr(LegacyMemoryRecallAdapter(backend), operation)
        owner, backend_id = _method_backend(method)
        pages = min(max_pages, query.max_items, query.max_chars // 2)
        # Keep the per-page query fixed because it is part of cursor identity.
        # Allocate all limits before the first call so pagination cannot spend
        # the entire original allowance again on every page.
        page_query = replace(
            query,
            max_items=query.max_items // pages,
            max_chars=query.max_chars // pages,
            scan_limit=query.scan_limit // pages,
        )
        items = []
        cursor = None
        seen = set()
        summary = {
            "pages": 0,
            "items": 0,
            "used_chars": 2,
            "scanned": 0,
            "skipped": 0,
            "snapshot_id": None,
            "backend_bounded": True,
        }
        for _ in range(pages):
            result = self._component_result(
                await memory_call(method, self.scope, name, replace(page_query, cursor=cursor)),
                RecallPage,
                "Memory recall",
            )
            if owner is not None and owner.backend_id != backend_id:
                raise DefinitionMismatch("The actual recalling memory backend changed")
            result = RecallPage(**asdict(result))
            if (
                len(result.items) > page_query.max_items
                or result.used_chars > page_query.max_chars
                or result.scanned > page_query.scan_limit
            ):
                raise ValidationError("Memory backend exceeded the recall allowance")
            if summary["snapshot_id"] is not None and summary["snapshot_id"] != result.snapshot_id:
                raise ValidationError("Memory backend changed pagination snapshot")
            summary["snapshot_id"] = result.snapshot_id
            summary["pages"] += 1
            summary["scanned"] += result.scanned
            summary["skipped"] += result.skipped
            summary["backend_bounded"] &= result.backend_bounded
            items = result.items + items if operation == "read_page" else items + result.items
            cursor = result.next_cursor
            if cursor is None:
                break
            if cursor in seen:
                raise ValidationError("Memory backend repeated a pagination cursor")
            seen.add(cursor)
        summary["items"] = len(items)
        summary["used_chars"] = len(canonical(items))
        if (
            len(items) > query.max_items
            or summary["used_chars"] > query.max_chars
            or summary["scanned"] > query.scan_limit
        ):
            raise ValidationError("Combined memory pages exceeded the recall allowance")
        return items, summary

    async def _load_references(self, run, step):
        components = self._components(run)
        sessions, memory, policy, knowledge = (
            components.sessions,
            components.memory,
            self.recall_policy,
            components.knowledge,
        )
        recall_manifest = None
        planner = self.recall_planner
        if planner is not None:
            from .recall import MemoryRecallPolicy, RecallQuery

            proposed = self._component_result(
                planner.plan(
                    self.scope, step["name"], run["session_id"], run["messages"][1]["content"]
                ),
                MemoryRecallPolicy,
                "Recall planner",
            )
            policy = MemoryRecallPolicy(
                facts=RecallQuery(**asdict(proposed.facts)),
                session=RecallQuery(**asdict(proposed.session)),
                max_pages=proposed.max_pages,
            )
            self._check_release(self._authorized(run["id"]))
            if digest(
                self._component_identity(planner, ("plan",), True, "Recall planner")
            ) != digest(self._step_manifest(run)["recall_planner"]):
                raise DefinitionMismatch("The executing recall planner changed")
        if sessions is None:
            session, session_manifest = [], {"disabled": True}
        elif policy is None:
            _, session = await memory_call(sessions.read, self.scope, run["session_id"])
        else:
            session, session_manifest = await self._recall_pages(
                sessions, "read_page", run["session_id"], policy.session, policy.max_pages
            )
        current = self._authorized(run["id"])
        if current["state"] in TERMINAL or current["state"] == "cancelling":
            return None
        if memory is None:
            facts, facts_manifest = [], {"disabled": True}
        elif policy is None:
            facts = await memory_call(memory.facts, self.scope, step["name"])
        else:
            facts, facts_manifest = await self._recall_pages(
                memory, "recall", step["name"], policy.facts, policy.max_pages
            )
        if policy is not None:
            recall_manifest = {"session": session_manifest, "facts": facts_manifest}
        current = self._authorized(run["id"])
        self._check_release(current)
        if (sessions.backend_id if sessions is not None else None) != self._step_manifest(run)[
            "session_backend"
        ] or (memory.backend_id if memory is not None else None) != self._step_manifest(run)[
            "memory_backend"
        ]:
            raise DefinitionMismatch("The executing memory backend differs from this Run")
        if (
            policy is not None
            and planner is None
            and digest(self._component_identity(policy, (), True, "Recall policy"))
            != digest(self._step_manifest(run)["memory_recall"])
        ):
            raise DefinitionMismatch("The executing recall policy differs from this Run")
        if current["state"] in TERMINAL or current["state"] == "cancelling":
            return None
        knowledge_refs = []
        if knowledge is not None:
            knowledge_refs = await memory_call(
                knowledge.references, self.scope, run["messages"][1]["content"]
            )
            if not isinstance(knowledge_refs, list) or any(
                not isinstance(item, dict) for item in knowledge_refs
            ):
                raise ValidationError("Knowledge context must return JSON reference objects")
            if (
                len(knowledge_refs) > knowledge.limit
                or len(canonical(knowledge_refs)) > knowledge.max_chars
            ):
                raise ValidationError("Knowledge context exceeded its reference allowance")
            knowledge_refs = copy.deepcopy(knowledge_refs)
            self._check_knowledge_release(self._authorized(run["id"]), knowledge)
        references = knowledge_refs + facts + ([{"session": session}] if session else [])
        return references, recall_manifest, knowledge_refs, knowledge, copy.deepcopy(facts), policy

    def _check_knowledge_release(self, run, knowledge):
        self._check_release(run)
        if digest(
            self._component_identity(knowledge, ("references", "validate"), False, "Knowledge")
        ) != digest(self._step_manifest(run)["knowledge"]):
            raise DefinitionMismatch("The executing knowledge context differs from this Run")

    async def _validate_knowledge(self, run_id, knowledge, references):
        run = self._authorized(run_id)
        if "knowledge" not in self._step_manifest(run):
            return
        self._check_knowledge_release(run, knowledge)
        result = await memory_call(knowledge.validate, self.scope, copy.deepcopy(references))
        self._component_result(result, type(None), "Knowledge validation")
        self._check_knowledge_release(self._authorized(run_id), knowledge)

    async def _validate_memory_references(self, run_id, references, memory):
        if not references:
            return
        from .recall import LegacyMemoryRecallAdapter, _method_backend

        run = self._authorized(run_id)
        self._check_release(run)
        if memory.backend_id != self._step_manifest(run)["memory_backend"]:
            raise DefinitionMismatch("The validating memory backend differs from this Run")
        self._check_reference_expiry(references)
        method = getattr(memory, "validate_facts", None)
        if not callable(method):
            method = LegacyMemoryRecallAdapter(memory).validate_facts
        owner, backend_id = _method_backend(method)
        namespace = self._agent_step(run)["name"]
        result = await memory_call(method, self.scope, namespace, copy.deepcopy(references))
        self._component_result(result, type(None), "Memory reference validation")
        if owner is not None and owner.backend_id != backend_id:
            raise DefinitionMismatch("The actual validating memory backend changed")
        self._check_release(self._authorized(run_id))
        if memory.backend_id != self._step_manifest(run)["memory_backend"]:
            raise DefinitionMismatch("The validating memory backend differs from this Run")
        self._check_reference_expiry(references)

    @staticmethod
    def _check_reference_expiry(references, *, knowledge=False):
        for reference in references:
            if not isinstance(reference, dict):
                raise ValidationError("Context references must be JSON records")
            source = reference.get("_knowledge", {}) if knowledge else reference
            if not isinstance(source, dict):
                raise ValidationError("Context references require valid source metadata")
            expiry = _validate_expires_at(source.get("expires_at"))
            if expiry is not None and expiry <= time.time():
                raise ValidationError("Context source is no longer available")

    async def _validate_model_references(self, run_id, knowledge, action, memory):
        from .context_artifacts import validate_snapshot

        await validate_snapshot(self, run_id, action)
        await self._validate_knowledge(run_id, knowledge, action.get("knowledge_references", []))
        # Knowledge validation can suspend. Check facts after it, at the last
        # boundary before actual model disclosure, including snapshot retries.
        await self._validate_memory_references(run_id, action.get("memory_references", []), memory)
        self._check_reference_expiry(action.get("memory_references", []))
        self._check_reference_expiry(action.get("knowledge_references", []), knowledge=True)

    async def _model(self, run_id):
        run = self._authorized(run_id)
        if run["state"] in TERMINAL or run["state"] == "cancelling":
            return True
        step = self._agent_step(run)
        existing = next(
            (
                item
                for item in run["actions"]
                if item["node"] == run["node"]
                and item["kind"] == "model"
                and item["status"] != "completed"
            ),
            None,
        )
        if existing and existing["status"] == "response_received":
            return self._adopt_model_response(run_id, existing["id"])
        if existing is None and run["decisions"] >= step["max_decisions"]:
            raise ValidationError("Agent decision limit reached")
        self._check_release(run)
        components = self._components(run)
        knowledge, memory = components.knowledge, components.memory
        if existing:
            action = existing
            messages = copy.deepcopy(action["snapshot"])
            descriptions = copy.deepcopy(action["request"]["tools"])
        else:
            from .context_preparation import prepare_context

            prepared = await prepare_context(self, run_id, step, components.context)
            if prepared is None:
                return True
            messages, context_manifest, knowledge_refs, facts = prepared
            request, manifest = self._prepare_model_request(run, step, messages, context_manifest)
            messages, descriptions = request.messages, request.tools
            action = {
                "id": uuid.uuid4().hex,
                "kind": "model",
                "node": run["node"],
                "status": "ready",
                "snapshot": copy.deepcopy(messages),
                "request": {
                    "messages": copy.deepcopy(messages),
                    "tools": copy.deepcopy(descriptions),
                },
                "context_manifest": manifest,
                "attempts": [],
            }
            if "context_preparation" in context_manifest:
                action["context_preparation"] = copy.deepcopy(
                    context_manifest["context_preparation"]
                )
            if knowledge is not None:
                action["knowledge_references"] = knowledge_refs
            if (
                knowledge is not None
                or self.recall_policy is not None
                or self.recall_planner is not None
            ):
                action["memory_references"] = facts
        provider = components.provider
        self._preflight_provider_request(run_id, provider, step["provider"], messages, descriptions)
        await self._validate_model_references(run_id, knowledge, action, memory)
        attempt_id = f"{action['id']}:{len(action['attempts']) + 1}"
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] == "cancelling" or run["state"] in TERMINAL:
                return True
            self._check_release(run)
            if existing is not None:
                action = next(item for item in run["actions"] if item["id"] == action["id"])
            self.store.reserve(run_id, attempt_id, step["model_credits"])
            action["attempts"].append({"id": attempt_id, "status": "executing"})
            action["status"] = "executing"
            if existing is None:
                run["actions"].append(action)
                run["decisions"] += 1
            self._commit(
                run, "model_dispatched", {"action_id": action["id"], "attempt_id": attempt_id}
            )
        dispatch_started = False
        try:
            await self._validate_model_references(run_id, knowledge, action, memory)
            self._preflight_provider_request(
                run_id, provider, step["provider"], messages, descriptions
            )
            current = self._authorized(run_id)
            if current["state"] in TERMINAL or current["state"] == "cancelling":
                self._record_not_dispatched(run_id, action["id"], attempt_id, "cancelled")
                return True
            complete = provider.complete
            dispatch_started = True
            response = await complete(copy.deepcopy(messages), copy.deepcopy(descriptions))
            if not isinstance(response, ModelResponse):
                raise ValidationError("Model provider must return ModelResponse")
            encoded = snapshot_model_response(response)
            self._record_model_response(run_id, action["id"], attempt_id, encoded)
        except Exception as exc:
            if not dispatch_started:
                code = exc.code if isinstance(exc, RalfError) else "validation_error"
                self._record_not_dispatched(run_id, action["id"], attempt_id, code)
                if isinstance(exc, RalfError):
                    raise
                raise ValidationError("Cannot dispatch the pinned model request") from exc
            with self.store.transaction():
                run = self._authorized(run_id)
                action = next(item for item in run["actions"] if item["id"] == action["id"])
                if action.get("received_response") is not None:
                    self.store.emit(
                        run_id, "model_response_processing_error", {"action_id": action["id"]}
                    )
                    return False
                action["status"] = "outcome_unknown"
                action["attempts"][-1]["status"] = "unknown"
                self.store.mark_unknown(attempt_id)
                run["error"] = {
                    "code": exc.code if isinstance(exc, RalfError) else "model_call_unknown"
                }
                if run["state"] not in TERMINAL:
                    run["state"] = (
                        "cancelled"
                        if run["state"] == "cancelling"
                        else "failed"
                        if isinstance(
                            exc, (ValidationError, AuthorizationDenied, DefinitionMismatch)
                        )
                        else "waiting_reconciliation"
                    )
                self._commit(run, "model_attempt_unknown", {"action_id": action["id"]})
            return False
        self._check_provider_release(self._authorized(run_id), provider, step["provider"])
        return self._adopt_model_response(run_id, action["id"])

    def _check_provider_release(self, run, provider, name):
        self._check_release(run)
        if digest(self._component_identity(provider, ("complete",), False, "Provider")) != digest(
            self._step_manifest(run)["providers"][name]
        ):
            raise DefinitionMismatch("The executing model Provider differs from this Run")

    def _preflight_provider_request(self, run_id, provider, name, messages, descriptions):
        """Optional pure validation before reserving or starting a model call."""
        from .ports import is_sync_callable

        self._check_provider_release(self._authorized(run_id), provider, name)
        validate = getattr(provider, "validate_request", None)
        if validate is not None:
            if not is_sync_callable(validate):
                raise ValidationError("Model request validation must be synchronous")
            try:
                self._component_result(
                    validate(copy.deepcopy(messages), copy.deepcopy(descriptions)),
                    type(None),
                    "Model request validation",
                )
            except RalfError:
                raise
            except Exception as exc:
                raise ValidationError("Model request is unsupported by this Provider") from exc
        self._check_provider_release(self._authorized(run_id), provider, name)

    def _record_not_dispatched(self, run_id, action_id, attempt_id, code):
        with self.store.transaction():
            run = self._authorized(run_id)
            action = next(item for item in run["actions"] if item["id"] == action_id)
            action["attempts"][-1]["status"] = "not_dispatched"
            action["status"] = (
                "outcome_unknown"
                if any(attempt["status"] == "unknown" for attempt in action["attempts"])
                else "not_dispatched"
            )
            self.store.settle(attempt_id, 0, {"dispatch": "not_started"})
            self._commit(
                run,
                f"{action['kind']}_dispatch_rejected",
                {"action_id": action_id, "attempt_id": attempt_id, "code": code},
            )

    def _record_tool_observation(self, run_id, action_id, observation, receipt):
        self._component_result(observation, EffectObservation, "ToolExecutor")
        result = observation.result
        canonical(result)
        with self.store.transaction():
            run = self._authorized(run_id)
            action = next(item for item in run["actions"] if item["id"] == action_id)
            if action["status"] == "completed":
                self._tool_result(run, action, result, receipt)
                return False
            if "effect_observation" in action:
                known = action["effect_observation"]["result"]
                self.store.emit(
                    run_id,
                    "late_effect_evidence",
                    {
                        "action_id": action_id,
                        "source": receipt["source"],
                        "result_digest": digest(result),
                        "matches_committed_result": digest(result) == digest(known),
                    },
                )
                return True
            action["effect_observation"] = {
                "result": copy.deepcopy(result),
                "receipt": copy.deepcopy(receipt),
            }
            action["status"] = "receipt_received"
            attempt = self._last_dispatched_attempt(action)
            if attempt is not None:
                attempt["status"] = "receipt_received"
            self._commit(
                run,
                "tool_receipt_recorded",
                {
                    "action_id": action_id,
                    "source": receipt["source"],
                    "result_digest": digest(result),
                },
            )
        return True

    def _adopt_tool_observation(self, run_id, action_id):
        with self.store.transaction():
            run = self._authorized(run_id)
            action = next(item for item in run["actions"] if item["id"] == action_id)
            if action["status"] != "receipt_received":
                return False
            observation = action["effect_observation"]
            committed = self._tool_result(
                run, action, observation["result"], observation["receipt"]
            )
            if committed:
                self._commit(run, "tool_result_committed", {"action_id": action_id})
        return committed

    def _tool_result(self, run, action, result, receipt):
        canonical(result)
        if action["status"] == "completed":
            # Evidence can arrive from a handler, automatic query and operator
            # concurrently. The first ResultCommit is immutable; later evidence
            # is retained for audit without remerging the model's tool message.
            self.store.emit(
                run["id"],
                "late_effect_evidence",
                {
                    "action_id": action["id"],
                    "source": receipt["source"],
                    "result_digest": digest(result),
                    "matches_committed_result": digest(result) == digest(action["result"]),
                },
            )
            return False
        action["status"] = "completed"
        action["result"] = copy.deepcopy(result)
        action["receipt"] = receipt
        attempt = self._last_dispatched_attempt(action)
        if attempt is not None:
            attempt["status"] = "completed"
            self.store.settle(
                attempt["id"],
                self._step_manifest(run, action["node"])["tools"][action["tool"]]["cost"],
                {"effect": "confirmed"},
            )
        run["messages"].append(
            {"role": "tool", "tool_call_id": action["call_id"], "content": canonical(result)}
        )
        return True

    @staticmethod
    def _last_dispatched_attempt(action):
        return next(
            (item for item in reversed(action["attempts"]) if item["status"] != "not_dispatched"),
            None,
        )

    async def _tool(self, run_id, action_id):
        run = self._authorized(run_id)
        if run["state"] in TERMINAL or run["state"] == "cancelling":
            return True
        action = next(a for a in run["actions"] if a["id"] == action_id)
        if action["status"] == "completed":
            return True
        if action["status"] == "receipt_received":
            self._adopt_tool_observation(run_id, action_id)
            return True
        tool = self.tools.get(action["tool"])
        self._check_release(run)
        tool.validate(action["arguments"])
        if self.policy is not None:
            policy = self.policy
            self._validate_policy(policy)
            decision = policy(self.scope, tool.spec, copy.deepcopy(action["arguments"]))
            if decision is not None:
                if inspect.iscoroutine(decision) or inspect.isgenerator(decision):
                    decision.close()
                raise ValidationError("Synchronous authorization policy must return None")
            self._check_release(self._authorized(run_id))
            run = self._authorized(run_id)
            if run["state"] in TERMINAL or run["state"] == "cancelling":
                return True
            action = next(a for a in run["actions"] if a["id"] == action_id)
            if action["status"] == "completed":
                return True
            if action["status"] == "receipt_received":
                self._adopt_tool_observation(run_id, action_id)
                return True
        if tool.spec.effect != "read_only":
            unresolved = self.store.unresolved_effect(
                self.scope, action["tool"], action["arguments"], action_id
            )
            if unresolved:
                with self.store.transaction():
                    run["state"] = "waiting_reconciliation"
                    run["error"] = {"code": "prior_effect_unknown", **unresolved}
                    self._commit(run, "prior_effect_blocks_write", run["error"])
                return False
        if tool.spec.requires_approval and not action["approved"]:
            with self.store.transaction():
                action["status"] = "waiting_approval"
                run["state"] = "waiting_approval"
                self._commit(
                    run, "approval_requested", {"action_id": action_id, "digest": action["digest"]}
                )
            return False
        previous_attempt = self._last_dispatched_attempt(action)
        context = InvocationContext(
            self.scope,
            run_id,
            action_id,
            previous_attempt["id"] if previous_attempt is not None else "",
            action["effect_key"],
            self.owner,
        )
        executor = self.tool_executor
        manifest = self._step_manifest(run)["tools"][action["tool"]]
        if action["status"] == "outcome_unknown":
            try:
                observation = await executor.reconcile(
                    DispatchEnvelope(context, manifest, action["arguments"], action["digest"])
                )
            except RalfError:
                raise
            except Exception:
                observation = None
            if observation is not None:
                self._component_result(observation, EffectObservation, "ToolExecutor.reconcile")
                self._record_tool_observation(
                    run_id,
                    action_id,
                    observation,
                    {"source": observation.source, "attempt_id": context.attempt_id},
                )
            self._check_executor_release(self._authorized(run_id), executor)
            if observation is not None:
                self._adopt_tool_observation(run_id, action_id)
                return True
            current = next(a for a in self._authorized(run_id)["actions"] if a["id"] == action_id)
            if current["status"] == "completed":
                return True
            if tool.spec.effect not in {"read_only", "idempotent_write"}:
                with self.store.transaction():
                    run = self._authorized(run_id)
                    if run["state"] not in TERMINAL and run["state"] != "cancelling":
                        run["state"] = "waiting_reconciliation"
                    self._commit(run, "effect_unknown", {"action_id": action_id})
                return False
        attempt_id = f"{action_id}:{len(action['attempts']) + 1}"
        with self.store.transaction():
            run = self._authorized(run_id)
            if run["state"] == "cancelling" or run["state"] in TERMINAL:
                return True
            self._check_release(run)
            action = next(a for a in run["actions"] if a["id"] == action_id)
            # A callback or evidence confirmation may have settled the Action.
            # Reservation must never reopen an immutable ResultCommit.
            if action["status"] == "completed":
                return True
            if action["status"] == "receipt_received":
                self._adopt_tool_observation(run_id, action_id)
                return True
            self.store.reserve(run_id, attempt_id, tool.spec.cost)
            action["attempts"].append({"id": attempt_id, "status": "executing"})
            action["status"] = "executing"
            self._commit(
                run,
                "tool_dispatch_intent",
                {
                    "action_id": action_id,
                    "attempt_id": attempt_id,
                    "digest": action["digest"],
                    "effect_key": action["effect_key"],
                },
            )
        context = InvocationContext(
            self.scope, run_id, action_id, attempt_id, action["effect_key"], self.owner
        )
        dispatch_started = False
        try:
            envelope = DispatchEnvelope(context, manifest, action["arguments"], action["digest"])
            current = self._authorized(run_id)
            self._check_executor_release(current, executor)
            if current["state"] in TERMINAL or current["state"] == "cancelling":
                self._record_not_dispatched(run_id, action_id, attempt_id, "cancelled")
                return True
            execute = executor.execute
            dispatch_started = True
            observation = await execute(envelope)
            self._component_result(observation, EffectObservation, "ToolExecutor.execute")
            self._record_tool_observation(
                run_id,
                action_id,
                observation,
                {"source": observation.source, "attempt_id": attempt_id},
            )
            self._check_executor_release(self._authorized(run_id), executor)
            self._adopt_tool_observation(run_id, action_id)
            return True
        except Exception as exc:
            if not dispatch_started:
                code = exc.code if isinstance(exc, RalfError) else "validation_error"
                self._record_not_dispatched(run_id, action_id, attempt_id, code)
                if isinstance(exc, RalfError):
                    raise
                raise ValidationError("Cannot dispatch the pinned tool request") from exc
            with self.store.transaction():
                run = self._authorized(run_id)
                action = next(a for a in run["actions"] if a["id"] == action_id)
                if action["status"] == "completed":
                    self.store.emit(
                        run_id,
                        "late_effect_error",
                        {"action_id": action_id, "attempt_id": attempt_id},
                    )
                    return False
                if action["status"] == "receipt_received":
                    self.store.emit(
                        run_id,
                        "tool_receipt_processing_error",
                        {"action_id": action_id, "attempt_id": attempt_id},
                    )
                    raise
                action["status"] = "outcome_unknown"
                action["attempts"][-1]["status"] = "unknown"
                self.store.mark_unknown(attempt_id)
                if run["state"] not in TERMINAL:
                    run["state"] = (
                        "cancelled" if run["state"] == "cancelling" else "waiting_reconciliation"
                    )
                self._commit(run, "effect_unknown", {"action_id": action_id})
            return False

    def _check_executor_release(self, run, executor):
        self._check_release(run)
        if digest(
            self._component_identity(executor, ("execute", "reconcile"), False, "Executor")
        ) != digest(self._step_manifest(run)["tool_executor"]):
            raise DefinitionMismatch("The executing ToolExecutor differs from this Run")
