"""Explicit Temporal worker dependencies and safe, single-attempt Activities.

Importing this module does not require the optional Temporal SDK. Activities
return observations; they never instantiate a local execution engine/store.
"""

import inspect
from dataclasses import asdict

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
    RECONCILE_ACTIVITY,
    TOOL_ACTIVITY,
    detached,
    temporal_capabilities,
    validate_manifest,
)
from .tools import ToolRegistry
from .types import AgentSpec, InvocationContext, ModelResponse, Scope, ToolCall, canonical, digest


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
        knowledge=None,
        execution_policy=None,
        binding_catalog=None,
        stage_policy=None,
        facts=None,
        recall_policy=None,
        recall_planner=None,
        enable_sessions=False,
        limits=None,
        verifier=None,
        session_store=None,
        session_query=None,
        session_writes=False,
    ):
        if type(enable_sessions) is not bool:
            raise ValidationError("enable_sessions requires an explicit boolean")
        self.enable_sessions = enable_sessions
        if type(session_writes) is not bool:
            raise ValidationError("Session writes require an explicit boolean")
        self.session_writes = session_writes
        from .temporal_session_execution import SessionExecutionOwner

        self.session_execution = SessionExecutionOwner() if session_writes else None
        from .fact_index_ports import _FixedPorts

        self._session_execution_owner = self.session_execution
        self._session_execution_ports = (
            _FixedPorts(
                {"execution": (self.session_execution, ["append", "wait", "aclose"], False)}
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
        self._decision_enabled = not default_policy(self.harness) or any(
            k[0] == "decision_policy" for k in self._catalog_objects
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
            if memory is not None:
                result["managed_memory"] = memory
        return result

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
        from .task_controls import _binding
        from .temporal_components import orchestration_identity

        host = getattr(self, "_selected_host", None)
        if host is not None:
            host.validate_release(expected)
            return self.manifest
        if self.session_store is not self._session_owner:
            raise DefinitionMismatch("Temporal Session source owner changed")
        if self.session_execution is not self._session_execution_owner:
            raise DefinitionMismatch("Temporal Session execution owner changed")
        if self._session_execution_ports is not None:
            self._session_execution_ports.check()
            if self.session_execution._closed:
                raise DefinitionMismatch("Temporal Session execution owner closed")
        for pin in self._session_read_pins:
            pin.check()
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
        return self.manifest

    async def propose_limits(self, request: dict) -> dict:
        from .temporal_limits import evaluate

        return await evaluate(self, request)

    async def verify_completion(self, request: dict) -> dict:
        from .temporal_completion import evaluate

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
            self.validate_release(request["runtime_manifest"])
            from .temporal_session_state import validate_context_evidence, validate_history

            validate_history(request, request["runtime_manifest"], request.get("scope"))
            from .temporal_session_data import verify_dataset

            await verify_dataset(self, request)
            if "context" in request:
                validate_context_evidence(request["context"], request)
                from .temporal_session_data_state import (
                    validate_snapshot as validate_session_snapshot,
                )

                validate_session_snapshot(request["context"], self._manifest, request)
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
                messages, context_identity = self.context.assemble(
                    detached(request["messages"]), [], step.max_context_chars
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
            prepared_evidence = (
                detached({"messages": frozen.messages, "tools": frozen.tools})
                if self._manifest.get("decision_protocol") == 1
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
            proposal = self.harness.propose(step, response)
            if not isinstance(proposal, DecisionProposal):
                _close_lazy(proposal)
                raise ValidationError("Harness.propose must return DecisionProposal")
            if (
                self._manifest.get("decision_protocol") == 1
                and type(proposal) is not DecisionProposal
            ):
                raise ValidationError("Pure Harness.propose requires concrete DecisionProposal")
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
                **decision,
                "usage": usage,
            }
        except Exception as exc:
            failure = {"ok": False, "code": _code(exc, "provider_error"), "dispatched": dispatched}
            if received is not None:
                failure.update(model_evidence_version=2, received_response=received)
            return failure

    async def prepare_context(self, request):
        from .temporal_bindings import selected_runtime

        if not getattr(self, "_selected_host", None) and self._manifest["kernel"] == "temporal-3":
            return await selected_runtime(self, request).prepare_context(request)
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
            scope, step = Scope(**request["scope"]), AgentSpec(**request["step"])
            references = (
                []
                if self.knowledge is None
                else await self.knowledge.references(scope, request["messages"][1]["content"])
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
            from .temporal_context import assemble_context

            messages, identity = assemble_context(
                self.context,
                detached(request["messages"]),
                evidence["references"]
                + evidence.get("session_references", [])
                + evidence.get("session_data_references", []),
                step.max_context_chars,
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

    async def manage_context(self, request, *, dispatch_guard=None):
        from .temporal_bindings import selected_runtime

        if not getattr(self, "_selected_host", None) and self._manifest["kernel"] == "temporal-3":
            return await selected_runtime(self, request).manage_context(
                request, dispatch_guard=dispatch_guard
            )
        from .temporal_managed_context import execute

        return await execute(self, request, dispatch_guard=dispatch_guard)

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

    async def execute_tool(self, request: dict) -> dict:
        dispatched = False
        try:
            envelope, tool = self._envelope(request)
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

    async def dispatch_guard(request):
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
        return await runtime.complete_model(request, dispatch_guard=dispatch_guard)

    @activity.defn(name=TOOL_ACTIVITY)
    async def tool(request: dict) -> dict:
        return await runtime.execute_tool(request)

    @activity.defn(name=RECONCILE_ACTIVITY)
    async def reconcile(request: dict) -> dict:
        return await runtime.reconcile_tool(request)

    @activity.defn(name=ACK_ACTIVITY)
    async def evidence(request: dict) -> dict:
        return await runtime.acknowledge_evidence(request)

    from .temporal_managed_context import ACTIVITY

    @activity.defn(name=ACTIVITY)
    async def managed_context(request: dict) -> dict:
        return await runtime.manage_context(request, dispatch_guard=dispatch_guard)

    from .temporal_memory import ACTIVITY as MEMORY_ACTIVITY

    @activity.defn(name=MEMORY_ACTIVITY)
    async def managed_memory(request: dict) -> dict:
        return await runtime.manage_memory(request, dispatch_guard=dispatch_guard)

    from .temporal_session_save_state import ACTIVITY as SESSION_SAVE_ACTIVITY

    @activity.defn(name=SESSION_SAVE_ACTIVITY)
    async def managed_session(request: dict) -> dict:
        async def ended(proof):
            if client is None:
                raise ValidationError("Original Session execution proof requires its client")
            await client.get_workflow_handle(request["run_id"]).execute_update(
                "session_execution_ended", proof, id="ralf-session-end:" + proof["action_id"]
            )

        return await runtime.manage_session(request, dispatch_guard=dispatch_guard, on_end=ended)

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
        tool,
        reconcile,
        evidence,
        managed_context,
        managed_memory,
        managed_session,
        agent_limits,
        agent_completion,
    ]
