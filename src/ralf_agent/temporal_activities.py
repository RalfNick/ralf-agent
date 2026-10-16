"""Explicit Temporal worker dependencies and safe, single-attempt Activities.

Importing this module does not require the optional Temporal SDK. Activities
return observations; they never instantiate a local execution engine/store.
"""

import inspect
from dataclasses import asdict
from weakref import WeakKeyDictionary

from .context import ContextAssembler
from .decisions import validate_decision
from .errors import DefinitionMismatch, RalfError, ValidationError
from .executors import DispatchEnvelope, EffectObservation, PythonToolExecutor
from .harness import DecisionProposal, ModelRequest, NativeHarness
from .model_evidence import (
    snapshot_model_response,
    validate_model_usage,
    validate_received_response,
)
from .ports import is_async_callable, is_sync_callable
from .temporal_state import (
    ACK_ACTIVITY,
    MODEL_ACTIVITY,
    MODEL_ADOPTION_ACTIVITY,
    RECONCILE_ACTIVITY,
    TOOL_ACTIVITY,
    detached,
    temporal_capabilities,
    validate_manifest,
)
from .tools import ToolRegistry
from .types import AgentSpec, InvocationContext, ModelResponse, Scope, ToolCall, canonical, digest

_EVIDENCE_REGISTRATIONS = WeakKeyDictionary()


def _register_evidence_wrapper(runtime, client, original, wrapped):
    registration = _EVIDENCE_REGISTRATIONS.get(original)
    if registration is None or registration[0] is not runtime or registration[1] is not client:
        raise DefinitionMismatch("Original evidence factory registration changed")
    _EVIDENCE_REGISTRATIONS[wrapped] = (runtime, client, original)


def component_identity(component, methods, *, synchronous=False):
    identity = getattr(component, "identity", None)
    if not isinstance(identity, dict) or not identity:
        raise ValidationError("Temporal components require an explicit non-empty JSON identity")
    for name in methods:
        method = getattr(component, name, None)
        if not (is_sync_callable(method) if synchronous else is_async_callable(method)):
            raise ValidationError(
                f"Temporal component {name} must be {'synchronous' if synchronous else 'async'}"
            )
    return detached(identity)


def _close_lazy(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()
    elif isinstance(value, dict):
        for item in value.values():
            _close_lazy(item, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _close_lazy(item, seen)


def _completed_none(value, label):
    if value is not None:
        _close_lazy(value)
        raise ValidationError(f"{label} must return None after completion")


def _observation(value, label):
    if value is not None and not isinstance(value, EffectObservation):
        _close_lazy(value)
        raise ValidationError(f"{label} must return EffectObservation or None")
    if value is not None:
        canonical(value.result)
    return value


def _journal_begin(value):
    try:
        if not isinstance(value, dict) or set(value) - {
            "execute",
            "observation",
            "blocked",
            "prior",
        }:
            raise ValidationError("EffectJournal.begin returned an invalid dispatch contract")
        if type(value.get("execute")) is not bool or type(value.get("blocked", False)) is not bool:
            raise ValidationError("EffectJournal.begin requires boolean dispatch/block flags")
        observation = _observation(value.get("observation"), "EffectJournal.begin observation")
        blocked, execute = value.get("blocked", False), value["execute"]
        if (execute and (blocked or observation is not None)) or (
            blocked and observation is not None
        ):
            raise ValidationError(
                "EffectJournal.begin dispatch, block and receipt are mutually exclusive"
            )
        if blocked:
            prior = value.get("prior")
            if not isinstance(prior, dict) or any(
                not isinstance(prior.get(key), str) or not prior[key].strip()
                for key in ("run_id", "action_id", "effect_key")
            ):
                raise ValidationError("EffectJournal.begin requires stable prior effect identities")
        elif "prior" in value:
            raise ValidationError("EffectJournal.begin prior identity requires a blocked dispatch")
        ordinary = {key: item for key, item in value.items() if key != "observation"}
        canonical(ordinary)
        return {**detached(ordinary), "observation": observation}
    except ValidationError:
        _close_lazy(value)
        raise


def _code(exc, default):
    return exc.code if isinstance(exc, RalfError) else default


class TemporalRuntime:
    """Worker-owned, explicitly registered execution components.

    Custom policies require a caller-supplied immutable policy identity. No
    provider, tool, journal connection, or credential is serialized in History.
    """

    def __init__(
        self,
        *,
        providers,
        tools,
        policy=None,
        policy_identity=None,
        harness=None,
        context_builder=None,
        tool_executor=None,
        journal=None,
        team_strategies=None,
        planners=None,
        plan_verifiers=None,
        parent_completion_policies=None,
        knowledge=None,
        execution_policy=None,
        binding_catalog=None,
        stage_policy=None,
        facts=None,
        recall_policy=None,
        recall_planner=None,
        enable_sessions=False,
        deployment_sessions=False,
        limits=None,
        verifier=None,
        session_store=None,
        session_query=None,
        session_writes=False,
        session_topology=None,
        context_reads=False,
        artifact_bindings=False,
        context_execution=None,
        tool_execution=None,
        runtime_profile=None,
        model_continuation=False,
        model_history=None,
        user_input_policies=None,
        coding_execution=False,
        coding_composition=False,
        _deployment_admission_policy=None,
        admission_policy=None,
    ):
        from .governance import DeploymentAdmissionPolicy

        if (
            type(deployment_sessions) is not bool
            or deployment_sessions
            and (enable_sessions is not True or admission_policy is None)
        ):
            raise ValidationError(
                "Session deployment requires explicit public admission and Sessions"
            )
        self.deployment_sessions = self._deployment_sessions_pin = deployment_sessions
        if admission_policy is not None and _deployment_admission_policy is not None:
            raise ValidationError("Select one public or internal deployment admission policy")
        self._deployment_public_execution = self._deployment_public_execution_pin = (
            admission_policy is not None
        )
        if admission_policy is not None:
            _deployment_admission_policy = admission_policy
        if _deployment_admission_policy is not None:
            if type(_deployment_admission_policy) is not DeploymentAdmissionPolicy:
                raise ValidationError(
                    "Internal deployment Worker requires an exact immutable policy"
                )
            DeploymentAdmissionPolicy.from_identity(_deployment_admission_policy.identity)
            if not self._deployment_public_execution and (coding_execution or coding_composition):
                raise ValidationError(
                    "Internal deployment Coding requires its physical-close integration"
                )
        self._deployment_admission_policy = self._deployment_admission_policy_pin = (
            _deployment_admission_policy
        )
        self._deployment_admission_identity = (
            None
            if _deployment_admission_policy is None
            else detached(_deployment_admission_policy.identity)
        )
        from .task_controls import _binding
        from .temporal_context_execution import ContextExecutionOwner

        self._deployment_execution_owner = self._deployment_execution_owner_pin = (
            ContextExecutionOwner(max_calls=256) if self._deployment_public_execution else None
        )
        self._deployment_execution_identity = (
            detached(self._deployment_execution_owner.identity)
            if self._deployment_execution_owner is not None
            else None
        )
        self._deployment_execution_methods = (
            {
                name: _binding(getattr(self._deployment_execution_owner, name))
                for name in ("execute", "wait", "aclose")
            }
            if self._deployment_public_execution
            else {}
        )
        if type(coding_execution) is not bool:
            raise ValidationError("Coding execution opt-in requires an ordinary boolean")
        if type(coding_composition) is not bool:
            raise ValidationError("Coding composition opt-in requires an ordinary boolean")
        if coding_composition and not coding_execution:
            raise ValidationError("Coding composition requires explicit Coding execution")
        if coding_composition:
            from .temporal_coding_composition_protocol import require_sdk

            require_sdk()
        self.coding_execution = self._coding_execution_pin = coding_execution
        self.coding_composition = self._coding_composition_pin = coding_composition
        from .user_input import UserInputPolicy

        if user_input_policies is not None and type(user_input_policies) is not dict:
            raise ValidationError("User input policies require a named ordinary registry")
        self.user_input_policies = dict(user_input_policies or {})
        for name, component in self.user_input_policies.items():
            if (
                type(name) is not str
                or not name.strip()
                or len(name) > 256
                or type(component) is not UserInputPolicy
            ):
                raise ValidationError(
                    "User input policies require bounded names and concrete policies"
                )
            UserInputPolicy.from_dict(component.to_dict())
        self._user_input_registry = self.user_input_policies
        self._user_input_pins = tuple(self.user_input_policies.items())
        from .types import runtime_profile_identity

        if type(model_continuation) is not bool:
            raise ValidationError("Model continuation opt-in requires an ordinary boolean")
        self.model_continuation = self._model_continuation_pin = model_continuation
        if model_history is not None and not model_continuation:
            raise ValidationError("Complete model history requires model continuation enablement")
        self.model_history = self._model_history_pin = model_history
        from .task_controls import _binding

        self._model_history_methods = (
            None
            if model_history is None
            else {
                name: _binding(getattr(model_history, name, None))
                for name in (
                    ("assemble", "validate", "assemble_frame", "validate_frame")
                    if model_history.identity.get("scope") == "session"
                    else ("assemble", "validate")
                )
            }
        )
        if model_history is not None:
            from .model_history import model_history_registration

            self._model_history_registration = model_history_registration(model_history)
        if type(artifact_bindings) is not bool:
            raise ValidationError("Artifact binding opt-in requires an ordinary boolean")
        if artifact_bindings and binding_catalog is None:
            raise ValidationError("Artifact binding opt-in requires a trusted BindingCatalog")
        self.artifact_bindings = self._artifact_bindings_pin = artifact_bindings
        self.runtime_profile = (
            None if runtime_profile is None else runtime_profile_identity(runtime_profile)
        )
        from .temporal_context_execution import ContextExecutionOwner
        from .temporal_context_read_protocol import ContextExecutionRegistration

        if type(context_reads) is not bool:
            raise ValidationError("Context reads require an explicit boolean")
        if context_execution is not None and not context_reads:
            raise ValidationError("Context execution owner requires enabled read ownership")
        context_reads = context_reads or (
            model_history is not None
            and model_history.identity.get("scope") == "session"
            and session_store is not None
        )
        self.context_reads = context_reads
        self.context_execution = (
            ContextExecutionOwner()
            if context_reads and context_execution is None
            else context_execution
        )
        self._context_execution_owner = self.context_execution
        self._context_execution_owned = context_reads and context_execution is None
        self._context_execution_pin = (
            ContextExecutionRegistration(self.context_execution) if context_reads else None
        )
        self._context_read_closing = False
        from .binding_sandbox import has_sandbox_tools
        from .temporal_tool_execution import ToolExecutionRegistration

        if tool_execution is None and (
            coding_execution or has_sandbox_tools(tools.manifests(tuple(tools._tools)))
        ):
            from .tool_execution import ToolExecutionOwner

            tool_execution = ToolExecutionOwner(version="sandbox-default-1", max_calls=16)

        self.tool_execution = self._tool_execution_owner = tool_execution
        self._tool_execution_pin = (
            ToolExecutionRegistration(tool_execution) if tool_execution is not None else None
        )
        self._tool_execution_closing = False
        self._tool_notifications = (
            ContextExecutionOwner(max_calls=256) if tool_execution is not None else None
        )
        if type(enable_sessions) is not bool:
            raise ValidationError("enable_sessions requires an explicit boolean")
        self.enable_sessions = enable_sessions
        if type(session_writes) is not bool:
            raise ValidationError("Session writes require an explicit boolean")
        self.session_writes = session_writes
        from .temporal_session_topology import SessionTopologyRegistration

        if session_topology is not None and (not enable_sessions or not session_writes):
            raise ValidationError("Session topology requires original Session admission and writes")
        self.session_topology = self._session_topology_owner = session_topology
        self._session_topology_pin = (
            SessionTopologyRegistration(session_topology) if session_topology is not None else None
        )
        from .temporal_session_execution import SessionExecutionOwner

        self.session_execution = SessionExecutionOwner() if session_writes else None
        from .fact_index_ports import _FixedPorts

        self._session_execution_owner = self.session_execution
        self._session_execution_ports = (
            _FixedPorts(
                {
                    "execution": (
                        self.session_execution,
                        ["append", "wait", "aclose", "_own"]
                        + (["read"] if session_topology is not None else []),
                        False,
                    )
                }
            )
            if session_writes
            else None
        )
        from .recall import RecallQuery
        from .temporal_session_data import SessionReadRegistration

        self.session_store = session_store
        self.session_query = RecallQuery(max_items=20) if session_query is None else session_query
        self._session_owner = session_store
        self._session_read_pins = (
            [SessionReadRegistration(session_store, self.session_query)]
            if session_store is not None
            else []
        )
        if not isinstance(providers, dict) or not providers:
            raise ValidationError("Temporal requires explicit model providers")
        if not isinstance(tools, ToolRegistry):
            raise ValidationError("Temporal requires an explicit ToolRegistry")
        if policy is not None and not is_sync_callable(policy):
            raise ValidationError("Authorization policy must execute synchronously")
        if harness is not None:
            try:
                component_identity(harness, ("prepare", "propose"), synchronous=True)
            except ValidationError as exc:
                raise ValidationError(
                    "Temporal native harness or registered pure Harness required"
                ) from exc
        if context_builder is not None:
            from .temporal_context import context_registration

            try:
                context_registration(context_builder)
            except (ValidationError, AttributeError):
                raise ValidationError(
                    "Temporal default History context or registered synchronous ContextBuilder required"
                ) from None
        from .binding_catalog import BindingCatalog

        if binding_catalog is not None and not isinstance(binding_catalog, BindingCatalog):
            raise ValidationError("Temporal bindings require a scoped BindingCatalog")
        self._session_read_pins.extend(
            SessionReadRegistration(component, self.session_query)
            for (role, _, _), (component, _) in (
                binding_catalog._entries.items() if binding_catalog is not None else []
            )
            if role == "session"
        )
        if not self._session_read_pins and session_query is not None:
            raise ValidationError("An explicit Session query requires a registered source")
        if session_writes and not self._session_read_pins:
            raise ValidationError("Session writes require an original registered source")
        from .temporal_facts import pins, recall_registration

        self.facts, self.recall_policy, self.recall_planner = facts, recall_policy, recall_planner
        self._facts_owner = facts
        self._recall_owners = recall_policy, recall_planner
        self._facts_pins = ([pins(facts)] if facts is not None else []) + [
            pins(component)
            for (role, _, _), (component, _) in (
                binding_catalog._entries.items() if binding_catalog is not None else []
            )
            if role == "facts"
        ]
        self._recall_registration = recall_registration(recall_policy, recall_planner)
        from .task_controls import _binding

        self._recall_method = None if recall_planner is None else _binding(recall_planner.plan)
        from .binding_data import FactsBindingResource, FactsView

        if isinstance(facts, (FactsBindingResource, FactsView)):
            raise ValidationError(
                "Global Temporal Facts require the original backend; select scoped resources through BindingCatalog"
            )
        self.binding_catalog, self.stage_policy = binding_catalog, stage_policy
        from .temporal_completion import pin as completion_pin

        self.verifier, self._verifier_owner = verifier, verifier
        self._verifier_pins = ([completion_pin(verifier)] if verifier is not None else []) + [
            completion_pin(component)
            for (role, _, _), (component, _) in (
                binding_catalog._entries.items() if binding_catalog is not None else []
            )
            if role == "verifier"
        ]
        from .temporal_limits import pin

        self.limits, self._limits_owner = limits, limits
        self._limits_pins = ([pin(limits)] if limits is not None else []) + [
            pin(component)
            for (role, _, _), (component, _) in (
                binding_catalog._entries.items() if binding_catalog is not None else []
            )
            if role == "limits"
        ]
        self._catalog_pin, self._stage_pin = binding_catalog, stage_policy
        self.providers, self.tools, self.policy = dict(providers), tools, policy
        if binding_catalog is not None:
            from .binding_types import BindingSelection
            from .temporal_bindings import provider_alias

            for (role, cid, version), (component, _) in binding_catalog._entries.items():
                if role == "provider":
                    self.providers[provider_alias(BindingSelection.ref(cid, version))] = component
        self._provider_pins = dict(self.providers)
        from .model_continuation import provider_continuation_identity

        self._provider_continuation_pins = (
            {n: provider_continuation_identity(p) for n, p in self.providers.items()}
            if model_continuation
            else None
        )
        from .task_controls import _binding

        self._provider_method_pins = {n: _binding(p.complete) for n, p in self.providers.items()}
        self._catalog_objects = (
            {}
            if binding_catalog is None
            else {k: v[0] for k, v in binding_catalog._entries.items()}
        )
        self._catalog_method_pins = [
            (component, method, _binding(getattr(component, method)))
            for (role, _, _), component in self._catalog_objects.items()
            for method in (
                ("references", "validate")
                if role == "knowledge"
                else ("assemble", "validate_request")
                if role == "context"
                else ()
            )
            if getattr(component, method, None) is not None
        ]
        self.harness = NativeHarness() if harness is None else harness
        from .temporal_decision import default_policy
        from .temporal_decision import pin as decision_pin

        self._harness_owner = self.harness
        self._decision_pins = [decision_pin(self.harness)] + [
            decision_pin(component)
            for (role, _, _), component in self._catalog_objects.items()
            if role == "decision_policy"
        ]
        self._decision_enabled = (
            self.model_continuation
            or bool(parent_completion_policies)
            or not default_policy(self.harness)
            or any(k[0] == "decision_policy" for k in self._catalog_objects)
        )
        self.context = context_builder or ContextAssembler()
        self.executor = tool_executor or PythonToolExecutor(tools)
        self.journal = journal
        self.knowledge = knowledge
        from .temporal_knowledge import KnowledgeRegistration

        self._knowledge_pins = (
            [KnowledgeRegistration(knowledge)] if knowledge is not None else []
        ) + [
            KnowledgeRegistration(component)
            for (role, _, _), component in self._catalog_objects.items()
            if role == "knowledge"
        ]
        if knowledge is not None:
            component_identity(knowledge, ("references", "validate"))
            for name in ("limit", "max_chars"):
                if type(getattr(knowledge, name, None)) is not int or getattr(knowledge, name) < 1:
                    raise ValidationError("Knowledge requires positive bounded limits")
        from .governance import TemporalExecutionPolicy

        if execution_policy is not None and not isinstance(
            execution_policy, TemporalExecutionPolicy
        ):
            raise ValidationError("Temporal execution policy requires immutable limits")
        self.execution_policy = execution_policy
        from .task_controls import _binding
        from .temporal_components import default_components, orchestration_identity

        teams, plans, verifiers = default_components()
        self.teams = {**teams, **(team_strategies or {})}
        self.planners = {**plans, **(planners or {})}
        self.verifiers = {**verifiers, **(plan_verifiers or {})}
        self.parent_completion_policies = dict(parent_completion_policies or {})
        self._parent_completion_registry = self.parent_completion_policies
        self._parent_completion_pins = [
            (
                name,
                component,
                _binding(component.gate.verify),
                None
                if component.model_stage is None
                else (
                    _binding(component.model_stage.prepare),
                    _binding(component.model_stage.interpret),
                ),
            )
            for name, component in self.parent_completion_policies.items()
        ]
        self._orchestration = orchestration_identity(self.teams, self.planners, self.verifiers)
        self._registrations = [
            (attribute, registry, name, component, method, _binding(getattr(component, method)))
            for attribute, registry, method in (
                ("teams", self.teams, "select"),
                ("planners", self.planners, "plan"),
                ("verifiers", self.verifiers, "verify"),
            )
            for name, component in registry.items()
        ]
        self._knowledge_binding = (
            None
            if knowledge is None
            else (knowledge, _binding(knowledge.references), _binding(knowledge.validate))
        )
        self._context_binding = (
            self.context,
            _binding(self.context.assemble),
            None
            if getattr(self.context, "validate_request", None) is None
            else _binding(self.context.validate_request),
        )
        from .binding_artifacts import _method_binding

        self._artifact_binding_methods = (
            [
                (context, name, _method_binding(getattr(context, name)))
                for context in [self.context]
                + [
                    component
                    for (role, _, _), component in self._catalog_objects.items()
                    if role == "context"
                ]
                for name in ("artifact_binding_identity", "bind_artifacts")
                if callable(getattr(context, name, None))
            ]
            if self.artifact_bindings
            or any(role == "artifacts" for role, _, _ in self._catalog_objects)
            else []
        )
        if policy is None:
            self.policy_identity = {"kind": "allow-all", "version": "1"}
        else:
            self.policy_identity = detached(policy_identity or getattr(policy, "identity", None))
            if not isinstance(self.policy_identity, dict) or not self.policy_identity:
                raise ValidationError(
                    "Custom Temporal policies require an explicit policy identity"
                )
        self._manifest = validate_manifest(self._current_manifest())

    def _current_manifest(self):
        if self.deployment_sessions is not self._deployment_sessions_pin:
            raise DefinitionMismatch("Original Session deployment selection changed")
        if self.coding_composition:
            from .temporal_coding_composition_protocol import require_sdk

            require_sdk()
        # The registry is deliberately snapshotted in full. Worker queue/release
        # registrations must change when any executable definition changes.
        names = sorted(self.tools._tools)
        for name in names:
            tool = self.tools.get(name)
            if tool.spec.effect != "read_only" and self.journal is None:
                raise ValidationError("Temporal writes require a durable EffectJournal")
        result = {
            "kernel": "temporal-1",
            "tools": self.tools.manifests(names),
            "providers": {
                name: component_identity(p, ("complete",))
                for name, p in sorted(self.providers.items())
            },
            "harness": component_identity(self.harness, ("prepare", "propose"), synchronous=True),
            "context_builder": component_identity(self.context, ("assemble",), synchronous=True),
            "tool_executor": component_identity(self.executor, ("execute", "reconcile")),
            "policy": detached(self.policy_identity),
            "effect_journal": None
            if self.journal is None
            else component_identity(
                self.journal, ("begin", "received", "observation", "acknowledge")
            ),
        }
        if self.runtime_profile is not None:
            from .types import runtime_profile_identity

            result["runtime_profile"] = runtime_profile_identity(self.runtime_profile)
        if self.enable_sessions:
            result["session_protocol"] = 1
            result["dispatch_admission"] = "history-1"
        if self._session_read_pins:
            from .temporal_session_data import registration as session_registration

            result["session_data_protocol"] = 1
            if self.session_writes:
                result["session_save_protocol"] = {
                    "version": 1,
                    "write_credits": 1,
                    "max_message_chars": 65536,
                    "dataset_ids": {
                        digest(pin.physical): pin.dataset_id for pin in self._session_read_pins
                    },
                    "dataset_ports": {
                        digest(pin.physical): pin.dataset_port for pin in self._session_read_pins
                    },
                }
            if self.session_store is not None:
                result["session_data"] = session_registration(
                    self.session_store, self.session_query
                )
        if self._limits_pins:
            from .temporal_limits import registration as limits_registration

            result.update(limits_protocol=1, dispatch_admission="history-1")
            if self.limits is not None:
                result["host_limits"] = limits_registration(self.limits)
        if self._verifier_pins:
            from .temporal_completion import registration as completion_registration

            result["completion_protocol"] = 1
            if self.verifier is not None:
                result["completion_verifier"] = completion_registration(self.verifier)
        if self._decision_enabled:
            from .temporal_decision import registration as decision_registration

            result.update(
                decision_protocol=1, decision_registration=decision_registration(self.harness)
            )
        if self.knowledge is not None:
            result["knowledge_context"] = component_identity(
                self.knowledge, ("references", "validate")
            )
        if type(self.context) is not ContextAssembler:
            from .temporal_context import context_registration

            result["context_registration"] = context_registration(self.context)
        if self.execution_policy is not None:
            result["execution_policy"] = self.execution_policy.identity
        from .temporal_managed_context import registration

        managed = registration(self)
        if managed is not None:
            result.update(kernel="temporal-2", managed_context=managed)
        from .temporal_bindings import catalog_registration, memory_registration

        catalog = catalog_registration(self)
        from .binding_data import KnowledgeBindingResource

        if any(
            isinstance(component, KnowledgeBindingResource)
            for (role, _, _), component in self._catalog_objects.items()
            if role == "knowledge"
        ):
            result["knowledge_protocol"] = 1
        if self.facts is not None:
            from .temporal_facts import registration as facts_registration

            result["facts_context"] = facts_registration(self.facts)
        has_facts = self.facts is not None or any(k[0] == "facts" for k in self._catalog_objects)
        if has_facts:
            from .temporal_facts import recall_registration

            result["facts_recall"] = recall_registration(self.recall_policy, self.recall_planner)
            result["facts_protocol"] = 1
        memory = memory_registration(self.stage_policy, self.providers)
        if (
            catalog is not None
            or memory is not None
            or has_facts
            or self._limits_pins
            or self._verifier_pins
            or self._decision_enabled
            or self._session_read_pins
        ):
            result.update(kernel="temporal-3", binding_protocol=1, dispatch_admission="history-1")
            if catalog is not None:
                result["binding_catalog"] = catalog
                if any(record["role"] == "workspace" for record in catalog["records"].values()):
                    result["workspace_binding_protocol"] = 1
                if any(record["role"] == "skills" for record in catalog["records"].values()):
                    result["skills_binding_protocol"] = 1
            if memory is not None:
                result["managed_memory"] = memory
        from .binding_workspace import has_writable_workspace

        if has_writable_workspace(result["tools"]):
            result.update(
                kernel="temporal-3",
                binding_protocol=1,
                dispatch_admission="history-1",
                workspace_binding_protocol=2,
            )
        from .binding_sandbox import has_sandbox_tools

        sandbox_enabled = has_sandbox_tools(result["tools"]) or any(
            record["role"] == "sandbox"
            for record in result.get("binding_catalog", {}).get("records", {}).values()
        )
        artifact_enabled = self.artifact_bindings or any(
            record["role"] == "artifacts"
            for record in result.get("binding_catalog", {}).get("records", {}).values()
        )
        if self.context_reads:
            from .temporal_context_read_protocol import propose, publish

            result = (propose if sandbox_enabled or artifact_enabled else publish)(
                result, self._context_execution_pin
            )
            bridges = {
                digest(pin.physical): pin.dataset_bridge_fixed.identity
                for pin in self._session_read_pins
                if self.session_writes and pin.dataset_bridge_fixed is not None
            }
            if bridges:
                result["context_read_metadata_bridges"] = bridges
        if self._tool_execution_pin is not None:
            from .temporal_tool_execution import propose as propose_tool_execution
            from .temporal_tool_execution import publish as publish_tool_execution

            result = (
                propose_tool_execution
                if sandbox_enabled or artifact_enabled
                else publish_tool_execution
            )(result, self._tool_execution_pin)

        if sandbox_enabled:
            result.update(
                kernel="temporal-3",
                binding_protocol=4,
                dispatch_admission="history-1",
                sandbox_binding_protocol=1,
            )
            if not artifact_enabled:
                validate_manifest(result)
        from .temporal_artifact_bindings import registration as artifact_registration

        artifacts = artifact_registration(self, catalog)
        if artifacts is not None:
            result.update(
                kernel="temporal-3",
                binding_protocol=5,
                dispatch_admission="history-1",
                artifacts_binding_protocol=1,
                artifact_contexts=artifacts,
            )
            validate_manifest(result)
        if self.model_continuation:
            from .model_continuation import provider_continuation_identity
            from .temporal_decision_state import tool_defaults_registration

            result.update(
                kernel="temporal-3",
                binding_protocol=6,
                dispatch_admission="history-1",
                model_continuation_protocol=1,
                provider_continuations={
                    n: provider_continuation_identity(p) for n, p in sorted(self.providers.items())
                },
                continuation_tool_defaults=tool_defaults_registration(self.tools),
            )
        if self.model_history is not None:
            from .model_history import model_history_registration

            session_mode = self.model_history.identity.get("scope") == "session"
            if session_mode and self.session_store is None and not self.enable_sessions:
                raise ValidationError(
                    "Session model history requires a registered Session source or Session History"
                )
            result.update(
                binding_protocol=8 if session_mode else 7,
                model_history_protocol=2 if session_mode else 1,
                model_history=model_history_registration(self.model_history),
            )
        native = [
            r
            for r in result.get("binding_catalog", {}).get("records", {}).values()
            if r.get("role") == "model_history"
        ]
        if native:
            if not self.model_continuation:
                raise ValidationError("Model history bindings require model_continuation=True")
            session_mode = result.get("model_history", {}).get("identity", {}).get(
                "scope"
            ) == "session" or any(
                r["identity"]["identity"].get("scope") == "session" for r in native
            )
            if session_mode and self.session_store is None and not self.enable_sessions:
                raise ValidationError("Session model history requires a Session source or History")
            result.update(
                kernel="temporal-3",
                binding_protocol=8 if session_mode else 7,
                model_history_protocol=2 if session_mode else 1,
            )
        if self._session_topology_pin is not None:
            from .temporal_session_tree_protocol import propose_manifest

            result = propose_manifest(result, self._session_topology_pin)
        if self.parent_completion_policies:
            from .temporal_parent_completion import registrations

            result.update(
                kernel="temporal-3",
                binding_protocol=9,
                dispatch_admission="history-1",
                parent_completion_protocol=1,
            )
            result["parent_completion_policies"] = registrations(
                self.parent_completion_policies, result, self
            )
        from .temporal_user_input import registration as input_registration

        inputs = input_registration(self)
        if inputs:
            result.update(
                kernel="temporal-3", binding_protocol=10, dispatch_admission="history-1", **inputs
            )
        if self.coding_execution != self._coding_execution_pin:
            raise DefinitionMismatch("Coding execution opt-in changed")
        owned_publication = (
            self.coding_execution is True
            and self._deployment_public_execution is True
            and self._deployment_admission_identity is not None
        )
        if self.coding_execution:
            from .temporal_coding_protocol import publish

            result = (
                publish(result, self, _validate=False, _copy=False)
                if owned_publication
                else publish(result, self)
            )
        if self.coding_composition is not self._coding_composition_pin:
            raise DefinitionMismatch("Coding composition opt-in changed")
        if self.coding_composition:
            from .temporal_coding_composition_protocol import publish as publish_composition

            result = (
                publish_composition(result, self, _validate=False, _copy=False)
                if owned_publication
                else publish_composition(result, self)
            )
        from .temporal_deployment_protocol import publish as publish_deployment

        return publish_deployment(
            result,
            self._deployment_admission_identity,
            public=self._deployment_public_execution,
            **({"session_deployment": True} if self.deployment_sessions else {}),
            **({"_copy": False} if owned_publication else {}),
        )

    async def close_deployment_execution(self, *, wait_timeout=30):
        """Drain actual public deployment calls and their original durable end ACKs."""
        from .temporal_deployment_release import close_owner

        await close_owner(self, wait_timeout=wait_timeout)

    @property
    def capabilities(self):
        from .temporal_bindings import capabilities

        return {**temporal_capabilities(), **capabilities(self._manifest)}

    @property
    def manifest(self):
        return detached(self._manifest)

    @property
    def orchestration_release(self):
        self.validate_release()
        return {**self.manifest, "orchestration": detached(self._orchestration)}

    def validate_release(self, expected=None):
        from .binding_artifacts import _method_matches
        from .task_controls import _binding
        from .temporal_components import orchestration_identity

        if (
            self._deployment_admission_policy is not self._deployment_admission_policy_pin
            or (
                None
                if self._deployment_admission_policy is None
                else self._deployment_admission_policy.identity
            )
            != self._deployment_admission_identity
        ):
            raise DefinitionMismatch("Original deployment Worker policy changed")

        if (
            self._deployment_public_execution is not self._deployment_public_execution_pin
            or self._deployment_execution_owner is not self._deployment_execution_owner_pin
            or (
                None
                if self._deployment_execution_owner is None
                else self._deployment_execution_owner.identity
            )
            != self._deployment_execution_identity
            or any(
                _binding(getattr(self._deployment_execution_owner, name, None)) != pin
                for name, pin in self._deployment_execution_methods.items()
            )
        ):
            raise DefinitionMismatch("Original deployment actual execution owner changed")

        if (
            self.user_input_policies is not self._user_input_registry
            or tuple(self.user_input_policies.items()) != self._user_input_pins
        ):
            raise DefinitionMismatch("Original user input policy registry changed")

        if self.parent_completion_policies is not self._parent_completion_registry or set(
            self.parent_completion_policies
        ) != {p[0] for p in self._parent_completion_pins}:
            raise DefinitionMismatch("Parent completion registry changed")
        for name, component, gate, stage in self._parent_completion_pins:
            current_stage = (
                None
                if component.model_stage is None
                else (
                    _binding(component.model_stage.prepare),
                    _binding(component.model_stage.interpret),
                )
            )
            if (
                self.parent_completion_policies[name] is not component
                or _binding(component.gate.verify) != gate
                or current_stage != stage
            ):
                raise DefinitionMismatch("Parent completion registration changed")

        if self.model_history is not self._model_history_pin:
            raise DefinitionMismatch("Model history policy changed")
        if self.model_history is not None:
            from .model_history import model_history_registration

            if (
                any(
                    _binding(getattr(self.model_history, name, None)) != method
                    for name, method in self._model_history_methods.items()
                )
                or model_history_registration(self.model_history)
                != self._model_history_registration
            ):
                raise DefinitionMismatch("Model history policy registration changed")
        if self.model_continuation is not self._model_continuation_pin:
            raise DefinitionMismatch("Model continuation enablement changed")
        if self.model_continuation:
            from .model_continuation import provider_continuation_identity

            if {
                n: provider_continuation_identity(p) for n, p in self.providers.items()
            } != self._provider_continuation_pins:
                raise DefinitionMismatch("Pinned Provider continuation identity changed")
        host = getattr(self, "_selected_host", None)
        if host is not None:
            host.validate_release(expected)
            if self._manifest.get("artifacts_binding_protocol") == 1 and not (
                self._manifest.get("parent_completion_protocol") == 1
                and "artifact_binding" not in self.context.identity
            ):
                self.context.check()
                if self.context.identity != self._manifest["context_builder"]:
                    raise DefinitionMismatch("Selected Artifact Context changed")
            return self.manifest
        if self.artifact_bindings is not self._artifact_bindings_pin or any(
            not _method_matches(getattr(context, name, None), method)
            for context, name, method in self._artifact_binding_methods
        ):
            raise DefinitionMismatch("Original Artifact Context binding port changed")
        from .temporal_context_read_runtime import owner as context_owner

        context_owner(self)
        if self.session_store is not self._session_owner:
            raise DefinitionMismatch("Temporal Session source owner changed")
        if self.session_topology is not self._session_topology_owner:
            raise DefinitionMismatch("Temporal Session topology owner changed")
        if self._session_topology_pin is not None:
            self._session_topology_pin.check()
        if self.session_execution is not self._session_execution_owner:
            raise DefinitionMismatch("Temporal Session execution owner changed")
        if self._session_execution_ports is not None:
            self._session_execution_ports.check()
            if self.session_execution._closed:
                raise DefinitionMismatch("Temporal Session execution owner closed")
        for pin in self._session_read_pins:
            pin.check()
            if self.context_reads and pin.dataset_bridge_fixed is not None:
                pin.dataset_bridge_fixed.check()
        from .temporal_decision import check_pin as check_decision_pin

        if self.harness is not self._harness_owner:
            raise DefinitionMismatch("Temporal DecisionPolicy owner changed")
        for original in self._decision_pins:
            check_decision_pin(original)
        from .temporal_completion import check_pin as check_completion_pin

        if self.verifier is not self._verifier_owner:
            raise DefinitionMismatch("Temporal completion verifier owner changed")
        for original in self._verifier_pins:
            check_completion_pin(original)
        from .temporal_limits import check_pin as check_limits_pin

        if self.limits is not self._limits_owner:
            raise DefinitionMismatch("Temporal host limits owner changed")
        for original in self._limits_pins:
            check_limits_pin(original)
        from .temporal_facts import check_pin, recall_registration

        if self.facts is not self._facts_owner or any(
            current is not original
            for current, original in zip(
                (self.recall_policy, self.recall_planner), self._recall_owners, strict=True
            )
        ):
            raise DefinitionMismatch("Temporal Facts recall owner changed")
        for pin in self._facts_pins:
            check_pin(pin)
        for pin in self._knowledge_pins:
            pin.check()
        if digest(recall_registration(self.recall_policy, self.recall_planner)) != digest(
            self._recall_registration
        ) or (
            self.recall_planner is not None
            and _binding(self.recall_planner.plan) != self._recall_method
        ):
            raise DefinitionMismatch("Temporal recall planner changed")

        def check_capability_bindings():
            if (
                self.binding_catalog is not self._catalog_pin
                or self.stage_policy is not self._stage_pin
            ):
                raise DefinitionMismatch("Temporal capability owner changed")
            if self._manifest["kernel"] == "temporal-3" and any(
                self.providers.get(n) is not p for n, p in self._provider_pins.items()
            ):
                raise DefinitionMismatch("Temporal provider instance changed")
            if self._manifest["kernel"] == "temporal-3":
                if any(
                    _binding(self.providers[n].complete) != b
                    for n, b in self._provider_method_pins.items()
                ):
                    raise DefinitionMismatch("Temporal provider method changed")
                if self.binding_catalog is not None and any(
                    self.binding_catalog._entries.get(k, (None,))[0] is not c
                    for k, c in self._catalog_objects.items()
                ):
                    raise DefinitionMismatch("Temporal catalog instance changed")
                if any(
                    _binding(getattr(component, method, None)) != original
                    for component, method, original in self._catalog_method_pins
                ):
                    raise DefinitionMismatch("Temporal catalog method changed")
            context, assemble, validator = self._context_binding
            current_validator = getattr(self.context, "validate_request", None)
            if (
                self.context is not context
                or _binding(self.context.assemble) != assemble
                or (None if current_validator is None else _binding(current_validator)) != validator
            ):
                raise DefinitionMismatch("Context registration changed")

            if self._knowledge_binding is not None:
                knowledge, references, validate = self._knowledge_binding
                if self.knowledge is not knowledge or (
                    _binding(knowledge.references),
                    _binding(knowledge.validate),
                ) != (references, validate):
                    raise DefinitionMismatch("Knowledge registration changed")

            for attribute, registry, name, component, method, binding in self._registrations:
                if (
                    getattr(self, attribute) is not registry
                    or registry.get(name) is not component
                    or _binding(getattr(component, method)) != binding
                ):
                    raise DefinitionMismatch("Orchestration registration changed")

        check_capability_bindings()

        def static_port(component, name):
            # Reading a descriptor must not invoke another plugin getter while
            # checking whether the preceding getter changed an earlier port.
            from types import FunctionType, MethodType

            raw = inspect.getattr_static(component, name, None)
            targets, functions, seen = [raw], [], set()
            while targets:
                target = targets.pop()
                if target is None or id(target) in seen:
                    continue
                seen.add(id(target))
                if type(target) is FunctionType:
                    wrapped = dict.get(target.__dict__, "__wrapped__")
                    functions.append((target, target.__code__, wrapped))
                    targets.append(wrapped)
                else:
                    functions.append((target, None, None))
                    if type(target) in (MethodType, staticmethod, classmethod):
                        targets.append(target.__func__)
                    elif type(target) is property:
                        targets.extend((target.fget, target.fset, target.fdel))
                    else:
                        targets.append(inspect.getattr_static(type(target), "__call__", None))
            return raw, functions

        ports = [(self._context_binding[0], name) for name in ("assemble", "validate_request")]
        if self._manifest["kernel"] == "temporal-3":
            ports.extend((provider, "complete") for provider in self._provider_pins.values())
            ports.extend((component, method) for component, method, _ in self._catalog_method_pins)
        if self._knowledge_binding is not None:
            ports.extend((self._knowledge_binding[0], name) for name in ("references", "validate"))
        ports.extend((component, method) for _, _, _, component, method, _ in self._registrations)
        port_pins = [(component, name, static_port(component, name)) for component, name in ports]
        if digest(orchestration_identity(self.teams, self.planners, self.verifiers)) != digest(
            self._orchestration
        ):
            raise DefinitionMismatch("Orchestration configuration changed")
        if digest(self._current_manifest()) != digest(self._manifest):
            raise DefinitionMismatch(
                "Executing Temporal runtime differs from its pinned registration"
            )
        if expected is not None and "orchestration" in expected:
            if digest(expected["orchestration"]) != digest(self._orchestration):
                raise DefinitionMismatch("Orchestration release differs from registered worker")
            expected = {key: value for key, value in expected.items() if key != "orchestration"}
        if expected is not None and digest(expected) != digest(self._manifest):
            raise DefinitionMismatch("Worker registration differs from this Run's pinned release")
        # Identity/registration getters above are integrator code. A matching
        # declaration does not prove they left the previously checked owners or
        # callable bindings intact. Check after copying the public result too,
        # without evaluating those identity getters again.
        result = self.manifest
        check_capability_bindings()
        for component, name, (raw, functions) in port_pins:
            current, live_functions = static_port(component, name)
            if (
                current is not raw
                or len(live_functions) != len(functions)
                or any(
                    any(
                        current is not original
                        for current, original in zip(live, fixed, strict=True)
                    )
                    for live, fixed in zip(live_functions, functions, strict=True)
                )
            ):
                raise DefinitionMismatch("Temporal callable changed during release validation")
        if self._manifest["kernel"] == "temporal-3":
            # The callback-based checks have finished. Inspect the real registry
            # contents directly, including owners changed by the final getter.
            if (
                type(self.providers) is not dict
                or len(self.providers) != len(self._provider_pins)
                or any(
                    dict.get(self.providers, name) is not provider
                    for name, provider in self._provider_pins.items()
                )
            ):
                raise DefinitionMismatch("Temporal provider instance changed")
            if self.binding_catalog is not None:
                entries = inspect.getattr_static(self.binding_catalog, "_entries", None)
                if type(entries) is not dict or len(entries) != len(self._catalog_objects):
                    raise DefinitionMismatch("Temporal catalog instance changed")
                for key, component in self._catalog_objects.items():
                    entry = dict.get(entries, key)
                    if type(entry) is not tuple or len(entry) != 2 or entry[0] is not component:
                        raise DefinitionMismatch("Temporal catalog instance changed")
        if any(
            current is not original
            for current, original in (
                (self._deployment_admission_policy, self._deployment_admission_policy_pin),
                (self._deployment_public_execution, self._deployment_public_execution_pin),
                (self._deployment_execution_owner, self._deployment_execution_owner_pin),
                (self.user_input_policies, self._user_input_registry),
                (self.parent_completion_policies, self._parent_completion_registry),
                (self.model_history, self._model_history_pin),
                (self.model_continuation, self._model_continuation_pin),
                (self.artifact_bindings, self._artifact_bindings_pin),
                (self.context_execution, self._context_execution_owner),
                (self.session_store, self._session_owner),
                (self.session_topology, self._session_topology_owner),
                (self.session_execution, self._session_execution_owner),
                (self.tool_execution, self._tool_execution_owner),
                (self.harness, self._harness_owner),
                (self.verifier, self._verifier_owner),
                (self.limits, self._limits_owner),
                (self.facts, self._facts_owner),
                (self.recall_policy, self._recall_owners[0]),
                (self.recall_planner, self._recall_owners[1]),
                (self.binding_catalog, self._catalog_pin),
                (self.stage_policy, self._stage_pin),
                (self.context, self._context_binding[0]),
                (
                    self.knowledge,
                    None if self._knowledge_binding is None else self._knowledge_binding[0],
                ),
            )
        ):
            raise DefinitionMismatch("Temporal resource owner changed during release validation")
        return result

    async def propose_limits(self, request: dict) -> dict:
        from .temporal_limits import evaluate

        return await evaluate(self, request)

    async def verify_completion(self, request: dict) -> dict:
        from .temporal_completion import evaluate

        return await evaluate(self, request)

    async def verify_parent_completion(self, request: dict) -> dict:
        from .temporal_parent_completion import evaluate

        return await evaluate(self, request)

    async def complete_model(self, request: dict, *, dispatch_guard=None) -> dict:
        from .temporal_bindings import selected_runtime

        if not getattr(self, "_selected_host", None) and self._manifest["kernel"] == "temporal-3":
            return await selected_runtime(self, request).complete_model(
                request, dispatch_guard=dispatch_guard
            )
        dispatched = False
        received = None
        try:
            from .temporal_bindings import reject_runner_descriptor

            reject_runner_descriptor(request.get("step_bindings"), request["runtime_manifest"])
            self.validate_release(request["runtime_manifest"])
            from .temporal_state import validate_coding_selection

            validate_coding_selection(
                request["runtime_manifest"], AgentSpec(**request["step"]).tools
            )
            from .temporal_session_state import validate_context_evidence, validate_history

            validate_history(request, request["runtime_manifest"], request.get("scope"))
            if self._manifest.get("model_history_protocol") == 2:
                from .temporal_session_model_history import before_model, validate_request_frame

                validate_request_frame(request)
                before_model(request)
            from .temporal_session_data import verify_dataset

            await verify_dataset(self, request)
            if "context" in request:
                validate_context_evidence(request["context"], request)
                from .temporal_session_data_state import (
                    validate_snapshot as validate_session_snapshot,
                )

                validate_session_snapshot(request["context"], self._manifest, request)
                from .temporal_session_model_history import validate_native_snapshot

                validate_native_snapshot(request["context"], self._manifest, request)
            step = AgentSpec(**request["step"])
            provider = self.providers[step.provider]
            complete = provider.complete
            if (
                self.facts is not None
                or self.session_store is not None
                or self.knowledge is not None
                or "context_registration" in self._manifest
                or self.enable_sessions
                and "context" in request
            ):
                evidence = request["context"]
                from .temporal_knowledge_state import (
                    validate_snapshot as validate_knowledge_snapshot,
                )

                validate_knowledge_snapshot(evidence, self._manifest, request["scope"])
                from .temporal_managed_context import validate_snapshot

                await validate_snapshot(self, request)
                if self.knowledge is not None:
                    _completed_none(
                        await self.knowledge.validate(
                            Scope(**request["scope"]),
                            detached(evidence.get("knowledge_references", evidence["references"])),
                        ),
                        "Knowledge validation",
                    )
                if self.facts is not None:
                    from .temporal_facts import validate as validate_facts

                    await validate_facts(self, request, request["context"])
                self.validate_release(request["runtime_manifest"])
                messages, context_identity = (
                    detached(evidence["messages"]),
                    detached(evidence["context_identity"]),
                )
            else:
                from .temporal_context import assemble_history

                messages, context_identity = assemble_history(
                    self,
                    detached(request["messages"]),
                    [],
                    step.max_context_chars,
                    frame=request.get("model_history_frame"),
                )
            if (
                not isinstance(messages, list)
                or not isinstance(context_identity, dict)
                or len(canonical(messages)) > step.max_context_chars
            ):
                raise ValidationError("Invalid Temporal model context")
            prepared = self.harness.prepare(step, messages, self.tools.descriptions(step.tools))
            if not isinstance(prepared, ModelRequest):
                _close_lazy(prepared)
                raise ValidationError("Harness.prepare must return ModelRequest")
            if self._manifest.get("decision_protocol") == 1:
                from .temporal_decision import validate_prepared_tools

                if type(prepared) is not ModelRequest:
                    raise ValidationError("Pure Harness.prepare requires concrete ModelRequest")
                validate_prepared_tools(prepared.tools, self.tools.descriptions(step.tools))
            frozen = ModelRequest(prepared.messages, prepared.tools)
            if self.model_history is not None:
                from .temporal_context import protect_history

                protect_history(
                    self, request.get("model_history_frame", request["messages"]), frozen.messages
                )
            prepared_evidence = (
                detached({"messages": frozen.messages, "tools": frozen.tools})
                if self._manifest.get("decision_protocol") == 1 or self.model_continuation
                else None
            )
            from .temporal_context import validate_prepared

            validate_prepared(self.context, frozen.messages, step.max_context_chars)
            self.validate_release(request["runtime_manifest"])
            if "managed_context" in self._manifest and (
                self.providers.get(step.provider) is not provider or provider.complete != complete
            ):
                raise DefinitionMismatch("Executing business provider changed before dispatch")
            from .temporal_managed_context import admit_dispatch

            if self.facts is not None:
                from .temporal_facts import validate as validate_facts

                await validate_facts(self, request, request["context"])
            if self.knowledge is not None and (
                "managed_context" in self._manifest or "knowledge_registration" in self._manifest
            ):
                _completed_none(
                    await self.knowledge.validate(
                        Scope(**request["scope"]),
                        detached(evidence.get("knowledge_references", evidence["references"])),
                    ),
                    "Knowledge validation",
                )
            self.validate_release(request["runtime_manifest"])
            await admit_dispatch(request, dispatch_guard)
            self.validate_release(request["runtime_manifest"])
            if "managed_context" in self._manifest and (
                self.providers.get(step.provider) is not provider or provider.complete != complete
            ):
                raise DefinitionMismatch("Executing business provider changed during admission")
            dispatched = True
            response = await complete(frozen.messages, frozen.tools)
            if not isinstance(response, ModelResponse):
                _close_lazy(response)
                raise ValidationError("ModelProvider.complete must return ModelResponse")
            received = snapshot_model_response(response)
            validate_received_response(received)
            usage = validate_model_usage(received["usage"])
            self.validate_release(request["runtime_manifest"])
            if "managed_context" in self._manifest and (
                self.providers.get(step.provider) is not provider or provider.complete != complete
            ):
                raise DefinitionMismatch("Executing business provider changed")
            if self.model_continuation:
                return {
                    "ok": True,
                    "model_receipt_version": 1,
                    "model_evidence_version": 2,
                    "received_response": received,
                    "prepared_request": prepared_evidence,
                    "decision_registration": detached(self._manifest["decision_registration"]),
                    "request_digest": digest(request),
                }
            proposal = self.harness.propose(step, response)
            if not isinstance(proposal, DecisionProposal):
                _close_lazy(proposal)
                raise ValidationError("Harness.propose must return DecisionProposal")
            if (
                self._manifest.get("decision_protocol") == 1
                and type(proposal) is not DecisionProposal
            ):
                raise ValidationError("Pure Harness.propose requires concrete DecisionProposal")
            from .model_continuation import validate_continuation

            continuation = validate_continuation(
                received,
                proposal,
                self._manifest.get("provider_continuations", {}).get(step.provider),
                enabled=self.model_continuation,
            )
            raw_proposal = (
                detached(
                    {
                        "output": proposal.output,
                        "tool_calls": [asdict(call) for call in proposal.tool_calls],
                    }
                )
                if continuation is not None
                else None
            )
            calls = []
            for call in proposal.tool_calls:
                if call.name not in step.tools:
                    from .errors import AuthorizationDenied

                    raise AuthorizationDenied("Model proposed undeclared tool")
                calls.append(
                    ToolCall(
                        call.name,
                        self.tools.get(call.name).resolve_arguments(call.arguments),
                        call.call_id,
                    )
                )
            proposal = validate_decision(
                step,
                DecisionProposal(proposal.output, tuple(calls)),
                self.tools.manifests(step.tools),
            )
            self.validate_release(request["runtime_manifest"])
            selected_proposal = {
                "output": detached(proposal.output),
                "tool_calls": [asdict(call) for call in proposal.tool_calls],
            }
            from .temporal_user_input import authorize_proposal

            input_authorization = authorize_proposal(self, proposal, request)
            decision = {}
            if self._manifest.get("decision_protocol") == 1:
                from .temporal_decision import evidence as decision_evidence

                decision["decision_evidence"] = decision_evidence(
                    self, request, prepared_evidence, received, selected_proposal
                )
            return {
                "ok": True,
                "model_evidence_version": 2,
                "received_response": received,
                **selected_proposal,
                **({"continuation_proposal": raw_proposal} if continuation is not None else {}),
                **decision,
                **input_authorization,
                "usage": usage,
            }
        except Exception as exc:
            failure = {"ok": False, "code": _code(exc, "provider_error"), "dispatched": dispatched}
            if received is not None:
                failure.update(model_evidence_version=2, received_response=received)
            return failure

    async def adopt_model(self, request: dict) -> dict:
        """Pure decision processing of a receipt already persisted by original History."""
        from .model_continuation import decode_received_response, validate_continuation
        from .temporal_bindings import selected_runtime

        if not getattr(self, "_selected_host", None):
            return await selected_runtime(self, request).adopt_model(request)
        receipt = request["model_receipt"]
        received = receipt["received_response"]
        base = {
            "model_adoption_version": 1,
            "model_action_id": request["model_action_id"],
            "receipt_digest": digest(receipt),
            "model_evidence_version": 2,
            "received_response": detached(received),
        }
        try:
            if not self.model_continuation:
                raise DefinitionMismatch(
                    "Pure model adoption requires the joint continuation release"
                )
            original = request["original_request"]
            self.validate_release(original["runtime_manifest"])
            if receipt.get("model_receipt_version") != 1 or receipt.get("request_digest") != digest(
                original
            ):
                raise DefinitionMismatch("Model adoption lost its original dispatch request")
            step = AgentSpec(**original["step"])
            response = decode_received_response(received)
            usage = validate_model_usage(received["usage"])
            proposal = self.harness.propose(step, response)
            if type(proposal) is not DecisionProposal:
                _close_lazy(proposal)
                raise ValidationError("Pure Harness.propose requires concrete DecisionProposal")
            continuation = validate_continuation(
                received,
                proposal,
                self._manifest.get("provider_continuations", {}).get(step.provider),
                enabled=True,
            )
            raw_proposal = detached(
                {
                    "output": proposal.output,
                    "tool_calls": [asdict(call) for call in proposal.tool_calls],
                }
            )
            calls = []
            for call in proposal.tool_calls:
                if call.name not in step.tools:
                    from .errors import AuthorizationDenied

                    raise AuthorizationDenied("Model proposed undeclared tool")
                calls.append(
                    ToolCall(
                        call.name,
                        self.tools.get(call.name).resolve_arguments(call.arguments),
                        call.call_id,
                    )
                )
            proposal = validate_decision(
                step,
                DecisionProposal(proposal.output, tuple(calls)),
                self.tools.manifests(step.tools),
            )
            self.validate_release(original["runtime_manifest"])
            selected = {
                "output": detached(proposal.output),
                "tool_calls": [asdict(call) for call in proposal.tool_calls],
            }
            from .temporal_user_input import authorize_proposal

            input_authorization = authorize_proposal(self, proposal, original)
            evidence = {}
            if self._manifest.get("decision_protocol") == 1:
                from .temporal_decision import evidence as decision_evidence

                evidence["decision_evidence"] = decision_evidence(
                    self, original, receipt["prepared_request"], received, selected
                )
            return {
                "ok": True,
                **base,
                **selected,
                **evidence,
                **input_authorization,
                "usage": usage,
                **({"continuation_proposal": raw_proposal} if continuation is not None else {}),
                **({"history_proposal": raw_proposal} if self.model_history is not None else {}),
            }
        except Exception as exc:
            return {"ok": False, **base, "code": _code(exc, "validation_error")}

    async def prepare_session_root(self, request, *, dispatch_guard=None, on_end=None):
        """Read the original Parent root; its History alone adopts the snapshot."""
        handler_started = False
        try:
            self.validate_release(request["runtime_manifest"])
            if self._session_topology_pin is None or request.get("session_source") != "root":
                raise DefinitionMismatch("Root read requires its fixed original tree registration")
            from .temporal_managed_context import admit_dispatch
            from .temporal_session_data import load
            from .temporal_session_data_state import expected_read

            expected_read(request["runtime_manifest"], request)
            from .session_types import SessionRef

            address = self._session_topology_pin.root_address(
                SessionRef.from_dict(request["session_lineage"]["root_turn"]["session_ref"])
            )
            if address != request["address"]:
                raise DefinitionMismatch("Root proposal changed its original accepted address")
            await admit_dispatch(request, dispatch_guard)
            from .temporal_session_data import selected_registration

            original = selected_registration(self, request)

            async def read_body():
                nonlocal handler_started
                handler_started = True
                return await load(self, request)

            result = {
                "ok": True,
                **await self.session_execution.read(
                    original,
                    read_body,
                    proof={k: request[k] for k in ("scope", "action_id", "release_digest")}
                    | {"request_digest": digest(request)},
                    on_end=on_end,
                ),
            }
            self.validate_release(request["runtime_manifest"])
            return result
        except Exception as exc:
            return {
                "ok": False,
                "code": _code(exc, "session_root_read_failed"),
                "handler_not_started": not handler_started
                and request.get("action_id") not in self.session_execution._entries,
            }

    async def prepare_context(self, request, *, dispatch_guard=None, on_end=None):
        from .temporal_bindings import selected_runtime

        if not getattr(self, "_selected_host", None) and self._manifest["kernel"] == "temporal-3":
            return await selected_runtime(self, request).prepare_context(
                request, dispatch_guard=dispatch_guard, on_end=on_end
            )
        if "context_read_protocol" in self._manifest:
            from .temporal_context_read_runtime import execute

            return await execute(
                self, request, self._prepare_context, dispatch_guard=dispatch_guard, on_end=on_end
            )
        return await self._prepare_context(request)

    async def _prepare_context(self, request):
        try:
            self.validate_release(request["runtime_manifest"])
            from .temporal_session_state import validate_history

            validate_history(request, request["runtime_manifest"], request.get("scope"))
            if (
                self.facts is None
                and self.session_store is None
                and self.knowledge is None
                and "context_registration" not in self._manifest
                and "session_history" not in request
            ):
                raise ValidationError("No registered custom or knowledge context")
            if self._manifest.get("model_history_protocol") == 2:
                from .temporal_session_model_history import validate_request_frame

                validate_request_frame(request)
            scope, step = Scope(**request["scope"]), AgentSpec(**request["step"])
            references = (
                []
                if self.knowledge is None
                else await self.knowledge.references(
                    scope,
                    (
                        request.get("current_task")
                        if isinstance(request.get("current_task"), str)
                        else canonical(request["current_task"])
                        if "current_task" in request
                        else request["messages"][1]["content"]
                    ),
                )
            )
            self.validate_release(request["runtime_manifest"])
            if (
                not isinstance(references, list)
                or any(not isinstance(item, dict) for item in references)
                or len(references) > (256 if self.knowledge is None else self.knowledge.limit)
                or len(canonical(references))
                > (65536 if self.knowledge is None else self.knowledge.max_chars)
            ):
                _close_lazy(references)
                raise ValidationError("Knowledge returned unbounded references")
            frozen = detached(references)
            if self.knowledge is not None:
                _completed_none(
                    await self.knowledge.validate(scope, frozen), "Knowledge validation"
                )
            self.validate_release(request["runtime_manifest"])
            from .temporal_facts import load

            evidence = await load(self, request, frozen)
            from .temporal_session_state import context_evidence

            evidence.update(context_evidence(request))
            from .temporal_session_data import load as load_session

            evidence.update(await load_session(self, request))
            from .temporal_session_model_history import load_native

            evidence.update(await load_native(self, request))
            from .temporal_context import assemble_history

            messages, identity = assemble_history(
                self,
                detached(request["messages"]),
                evidence["references"]
                + evidence.get("session_references", [])
                + evidence.get("session_data_references", []),
                step.max_context_chars,
                frame=request.get("model_history_frame"),
            )
            from .temporal_context import validate_context, validate_prepared

            validate_context(messages, identity, step.max_context_chars)
            validate_prepared(self.context, messages, step.max_context_chars)
            result = {
                "ok": True,
                "messages": messages,
                **evidence,
                "context_identity": identity,
            }
            canonical(result)
            self.validate_release(request["runtime_manifest"])
            return result
        except Exception as exc:
            return {"ok": False, "code": _code(exc, "context_failed")}

    async def manage_context(self, request, *, dispatch_guard=None, on_end=None):
        from .temporal_bindings import selected_runtime

        if not getattr(self, "_selected_host", None) and self._manifest["kernel"] == "temporal-3":
            return await selected_runtime(self, request).manage_context(
                request, dispatch_guard=dispatch_guard, on_end=on_end
            )
        from .temporal_managed_context import execute

        if "context_read_protocol" in self._manifest:
            from .temporal_context_read_protocol import PHASES
            from .temporal_context_read_runtime import execute as read_execute

            if request.get("phase") in PHASES:

                async def read(value):
                    return await execute(self, value, dispatch_guard=dispatch_guard)

                return await read_execute(
                    self, request, read, dispatch_guard=dispatch_guard, on_end=on_end
                )

        return await execute(self, request, dispatch_guard=dispatch_guard)

    async def wait_context_executions(self, *, wait_timeout=30):
        from .temporal_context_read_runtime import wait
        from .temporal_tool_execution_runtime import wait as wait_tools

        return await wait(self, wait_timeout=wait_timeout) and await wait_tools(
            self, wait_timeout=wait_timeout
        )

    async def close_context_execution(self, *, wait_timeout=30):
        from .temporal_context_read_runtime import close
        from .temporal_tool_execution_runtime import close as close_tools

        await close_tools(self, wait_timeout=wait_timeout)
        return await close(self, wait_timeout=wait_timeout)

    async def manage_session(self, request, *, dispatch_guard=None, on_end=None):
        from .temporal_bindings import selected_runtime
        from .temporal_session_save import execute

        return await execute(
            selected_runtime(self, request), request, dispatch_guard=dispatch_guard, on_end=on_end
        )

    async def wait_session_executions(self, *, wait_timeout=30):
        return (
            True
            if self.session_execution is None
            else await self.session_execution.wait(wait_timeout=wait_timeout)
        )

    async def close_session_execution(self, *, wait_timeout=30):
        if self.session_execution is not None:
            await self.session_execution.aclose(wait_timeout=wait_timeout)

    async def manage_memory(self, request, *, dispatch_guard=None):
        from .temporal_bindings import selected_runtime
        from .temporal_memory import execute

        return await execute(
            selected_runtime(self, request), request, dispatch_guard=dispatch_guard
        )

    def _envelope(self, request):
        self.validate_release(request["runtime_manifest"])
        from .temporal_state import validate_coding_selection

        validate_coding_selection(request["runtime_manifest"], (request["tool"],))
        context = InvocationContext(
            Scope(**request["scope"]),
            request["run_id"],
            request["action_id"],
            request["attempt_id"],
            request["effect_key"],
            request["execution_epoch"],
        )
        envelope = DispatchEnvelope(
            context, request["tool_manifest"], request["arguments"], request["operation_digest"]
        )
        tool = self.tools.get(request["tool"])
        if envelope.tool_name != request["tool"] or digest(tool.manifest) != digest(
            envelope.tool_manifest
        ):
            raise DefinitionMismatch("Tool differs from fixed Temporal manifest")
        tool.validate(envelope.arguments)
        if self.policy is not None:
            if not is_sync_callable(self.policy):
                raise ValidationError("Authorization policy must execute synchronously")
            result = self.policy(context.scope, tool.spec, envelope.arguments)
            if result is not None:
                _close_lazy(result)
                raise ValidationError("Synchronous authorization policy must return None")
        self.validate_release(request["runtime_manifest"])
        return envelope, tool

    async def execute_tool(
        self, request: dict, *, dispatch_guard=None, on_end=None, coding_callbacks=None
    ) -> dict:
        if "tool_execution_protocol" in self._manifest:
            from .temporal_tool_execution_runtime import execute

            return await execute(
                self,
                request,
                dispatch_guard=dispatch_guard,
                on_end=on_end,
                coding_callbacks=coding_callbacks,
            )
        return await self._execute_tool(request)

    async def _execute_tool(self, request: dict, *, coding_authority=None) -> dict:
        dispatched = False
        try:
            envelope, tool = self._envelope(request)
            from .temporal_coding_protocol import owns

            if owns(request["runtime_manifest"], request["tool"]):
                from .temporal_coding_runtime import execute

                dispatched = True
                return await execute(self, request, coding_authority)
            if self.journal is not None:
                begun = _journal_begin(await self.journal.begin(envelope))
                if begun.get("blocked"):
                    return {
                        "ok": False,
                        "code": "prior_effect_unknown",
                        "dispatched": False,
                        "blocked": True,
                        "prior": begun["prior"],
                    }
                if begun.get("observation") is not None:
                    observation = begun["observation"]
                    return {"ok": True, "result": observation.result, "source": observation.source}
                if not begun["execute"]:
                    return {"ok": False, "code": "effect_outcome_unknown", "dispatched": True}
            self.validate_release(request["runtime_manifest"])
            dispatched = True
            observation = _observation(
                await self.executor.execute(envelope), "ToolExecutor.execute"
            )
            if not isinstance(observation, EffectObservation):
                raise ValidationError("ToolExecutor.execute must return EffectObservation")
            # Preserve genuine evidence even if the executable registration drifted
            # during the handler. Adoption is History-owned; subsequent dispatches
            # still recheck the fixed registration.
            if self.journal is not None:
                _completed_none(
                    await self.journal.received(envelope, observation), "EffectJournal.received"
                )
            return {"ok": True, "result": observation.result, "source": observation.source}
        except Exception as exc:
            return {"ok": False, "code": _code(exc, "tool_error"), "dispatched": dispatched}

    async def reconcile_tool(self, request: dict) -> dict:
        try:
            envelope, tool = self._envelope(request)
            observation = (
                None
                if self.journal is None
                else _observation(
                    await self.journal.observation(envelope), "EffectJournal.observation"
                )
            )
            if observation is None:
                # Query only. Never execute the original handler for an unknown
                # read/write, including tools advertised as idempotent.
                observation = _observation(
                    await self.executor.reconcile(envelope), "ToolExecutor.reconcile"
                )
            if observation is None:
                return {"ok": False, "code": "effect_unverified", "dispatched": False}
            if not isinstance(observation, EffectObservation):
                raise ValidationError(
                    "ToolExecutor.reconcile must return EffectObservation or None"
                )
            if self.journal is not None:
                _completed_none(
                    await self.journal.received(envelope, observation), "EffectJournal.received"
                )
            return {"ok": True, "result": observation.result, "source": observation.source}
        except Exception as exc:
            return {"ok": False, "code": _code(exc, "reconciliation_error"), "dispatched": False}

    async def acknowledge_evidence(self, request: dict) -> dict:
        try:
            # Manual evidence does not run Policy, model, or original handler.
            self.validate_release(request["runtime_manifest"])
            if self.journal is not None:
                context = InvocationContext(
                    Scope(**request["scope"]),
                    request["run_id"],
                    request["action_id"],
                    request["attempt_id"],
                    request["effect_key"],
                    request["execution_epoch"],
                )
                envelope = DispatchEnvelope(
                    context,
                    request["tool_manifest"],
                    request["arguments"],
                    request["operation_digest"],
                )
                _completed_none(
                    await self.journal.acknowledge(
                        envelope, EffectObservation(request["result"], request["source"])
                    ),
                    "EffectJournal.acknowledge",
                )
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "code": _code(exc, "effect_journal_error")}


def registered_activities(runtime, client=None):
    """Register only these four fixed names, with explicit captured dependencies."""
    try:
        from temporalio import activity
    except ImportError as exc:
        raise ValidationError("Temporal workers require the optional temporal dependency") from exc
    runtime.validate_release()
    from .temporal_managed_context import ADMISSION_UPDATE
    from .temporal_session_activities import validate_tree_activity

    async def tree_guard(request):
        await validate_tree_activity(client, request, workflow_id=activity.info().workflow_id)

    async def dispatch_guard(request):
        await tree_guard(request)
        if client is None:
            raise ValidationError("Managed worker requires its original Temporal client")
        return await client.get_workflow_handle(request["run_id"]).execute_update(
            ADMISSION_UPDATE,
            {
                "scope": request["scope"],
                "action_id": request["action_id"],
                "release_digest": request["release_digest"],
                "phase": request.get("phase", "model"),
                "request_digest": digest(request),
            },
            id="ralf-context-dispatch:" + request["action_id"],
        )

    @activity.defn(name=MODEL_ACTIVITY)
    async def model(request: dict) -> dict:
        await tree_guard(request)
        return await runtime.complete_model(request, dispatch_guard=dispatch_guard)

    @activity.defn(name=MODEL_ADOPTION_ACTIVITY)
    async def model_adoption(request: dict) -> dict:
        await tree_guard(request["original_request"])
        return await runtime.adopt_model(request)

    @activity.defn(name=TOOL_ACTIVITY)
    async def tool(request: dict) -> dict:
        if "tool_execution_protocol" in request["runtime_manifest"]:
            from .temporal_tool_execution_activities import callbacks

            guard, ended = callbacks(client, request, activity.info())
            coding = None
            if "coding_request" in request:
                from .temporal_coding_runtime import callbacks as coding_callbacks

                coding = coding_callbacks(client, request, activity.info(), runtime)
            return await runtime.execute_tool(
                request, dispatch_guard=guard, on_end=ended, coding_callbacks=coding
            )
        return await runtime.execute_tool(request)

    from .temporal_coding_state import CODING_STOP_ACTIVITY

    @activity.defn(name=CODING_STOP_ACTIVITY)
    async def coding_stop(request: dict) -> dict:
        from .temporal_bindings import selected_runtime
        from .temporal_coding_runtime import callbacks as coding_callbacks
        from .temporal_coding_runtime import stop

        await tree_guard(request)
        return await stop(
            selected_runtime(runtime, request),
            request,
            coding_callbacks(client, request, activity.info(), runtime),
        )

    @activity.defn(name=RECONCILE_ACTIVITY)
    async def reconcile(request: dict) -> dict:
        return await runtime.reconcile_tool(request)

    @activity.defn(name=ACK_ACTIVITY)
    async def evidence(request: dict) -> dict:
        return await runtime.acknowledge_evidence(request)

    _EVIDENCE_REGISTRATIONS[evidence] = (runtime, client)

    from .temporal_managed_context import ACTIVITY

    @activity.defn(name=ACTIVITY)
    async def managed_context(request: dict) -> dict:
        from .temporal_context_read_protocol import PHASES

        if (
            "context_read_protocol" in request["runtime_manifest"]
            and request.get("phase") in PHASES
        ):
            from .temporal_context_read_activities import callbacks

            guard, ended = callbacks(client, request, activity.info())
            return await runtime.manage_context(request, dispatch_guard=guard, on_end=ended)
        await tree_guard(request)
        return await runtime.manage_context(request, dispatch_guard=dispatch_guard)

    from .temporal_memory import ACTIVITY as MEMORY_ACTIVITY

    @activity.defn(name=MEMORY_ACTIVITY)
    async def managed_memory(request: dict) -> dict:
        return await runtime.manage_memory(request, dispatch_guard=dispatch_guard)

    from .temporal_session_save_state import ACTIVITY as SESSION_SAVE_ACTIVITY

    def session_end_callback(request, info):
        from .temporal_deployment_protocol import public_selected, selected
        from .temporal_execution_end_transport import execute

        fixed = detached(request)
        workflow_id, epoch, namespace = (
            info.workflow_id,
            info.workflow_run_id,
            info.workflow_namespace,
        )
        expected = {name: fixed[name] for name in ("scope", "action_id", "release_digest")} | {
            "request_digest": digest(fixed)
        }

        async def check():
            if client is None or workflow_id != fixed["run_id"] or client.namespace != namespace:
                raise DefinitionMismatch("Session end changed original SDK identity")
            # This is old end evidence, never a new dispatch authorization.
            lineage = fixed.get("session_lineage")
            if lineage is not None:
                from .temporal_session_activities import namespace_id

                if await namespace_id(client) != lineage["namespace_id"]:
                    raise DefinitionMismatch("Session end changed original namespace resource")
            if client.namespace != namespace:
                raise DefinitionMismatch("Session end namespace changed during verification")

        async def ended(proof):
            if type(proof) is not dict or digest(proof) != digest(expected):
                raise DefinitionMismatch("Session end lost original complete request proof")
            await check()
            update_id = "ralf-session-end:" + proof["action_id"]
            if selected(fixed["runtime_manifest"]) and not public_selected(
                fixed["runtime_manifest"]
            ):
                result = await client.get_workflow_handle(workflow_id, run_id=epoch).execute_update(
                    "session_execution_ended", proof, id=update_id
                )
            else:
                result = await execute(
                    client,
                    workflow_id,
                    "session_execution_ended",
                    proof,
                    execution_epoch=epoch,
                    legacy_update_id=update_id,
                )
            await check()
            if (
                type(result) is not dict
                or set(result) != {"action_id", "execution_stopped"}
                or result["action_id"] != proof["action_id"]
                or result["execution_stopped"] is not True
            ):
                raise DefinitionMismatch("Session end requires original completed acknowledgement")

        return ended

    @activity.defn(name=SESSION_SAVE_ACTIVITY)
    async def managed_session(request: dict) -> dict:
        await tree_guard(request)
        ended = session_end_callback(request, activity.info())
        return await runtime.manage_session(request, dispatch_guard=dispatch_guard, on_end=ended)

    from .temporal_parent_session import ROOT_READ_ACTIVITY

    @activity.defn(name=ROOT_READ_ACTIVITY)
    async def session_root_read(request: dict) -> dict:
        await tree_guard(request)
        ended = session_end_callback(request, activity.info())
        result = await runtime.prepare_session_root(
            request, dispatch_guard=dispatch_guard, on_end=ended
        )
        await tree_guard(request)
        return result

    from .temporal_limits_state import ACTIVITY as LIMITS_ACTIVITY

    @activity.defn(name=LIMITS_ACTIVITY)
    async def agent_limits(request: dict) -> dict:
        return await runtime.propose_limits(request)

    from .temporal_completion_state import ACTIVITY as COMPLETION_ACTIVITY

    @activity.defn(name=COMPLETION_ACTIVITY)
    async def agent_completion(request: dict) -> dict:
        return await runtime.verify_completion(request)

    return [
        model,
        *([model_adoption] if runtime.model_continuation else []),
        tool,
        *([coding_stop] if runtime.coding_execution else []),
        reconcile,
        evidence,
        managed_context,
        managed_memory,
        managed_session,
        agent_limits,
        agent_completion,
        session_root_read,
    ]
