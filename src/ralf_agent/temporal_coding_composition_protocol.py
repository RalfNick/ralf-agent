"""Explicit finite composition publication over the shared original Coding authority."""

from .errors import DefinitionMismatch, ValidationError


# Every group has an explicit callable inventory. History resolves only these
# pure groups; SDK/runtime groups are opaque SHA records until Worker checking.
def _pure_sources():
    return {
        "protocol": (
            "temporal_coding_composition_protocol",
            (
                "enabled",
                "validate_topology",
                "_topology_definitions",
                "_direct_agents",
                "_recursive_definitions",
                "_validate_hidden_agents",
                "validate_protocol",
                "validate_implementation",
                "_fingerprints",
                "_resolve",
                "implementation",
                "_pure_sources",
                "_worker_sources",
                "_fields",
            ),
        ),
        "history": (
            "temporal_coding_composition_state",
            (
                "_link_fields",
                "_view_fields",
                "enabled",
                "orchestration_enabled",
                "recursive_enabled",
                "child_capacity_released",
                "coding_runner_keys",
                "occupied_runner_keys",
                "_require",
                "_namespace",
                "initialize",
                "initialize_namespace",
                "project_child_link",
                "_link",
                "validate_child_link",
                "_proof",
                "_child",
                "pin_child_execution",
                "_owners_stopped",
                "_children_stopped",
                "request_parent_stop",
                "refresh_parent_stop",
                "physical_stop_view",
                "adopt_child_stop",
                "coding_requests",
                "original_children",
                "validate_parent_update",
                "adopt_admission",
            ),
        ),
        "acceptance": (
            "temporal_state",
            (
                "validate_manifest",
                "validate_request",
                "validate_coding_selection",
                "TemporalRunState.__init__",
                "TemporalRunState.command",
                "TemporalRunState._apply",
                "TemporalRunState.next_operation",
                "TemporalRunState.diagnostics",
                "TemporalRunState.retry_blocked",
                "TemporalCommandRegistryState.__init__",
                "TemporalCommandRegistryState.reserve",
                "TemporalCommandRegistryState.composition_candidates",
                "TemporalCommandRegistryState.close_composition_submissions",
                "TemporalCommandRegistryState.composition_admission",
                "TemporalCommandRegistryState.bind_composition_submission",
            ),
        ),
        "parent": (
            "temporal_parent_state",
            (
                "TemporalParentState.__init__",
                "TemporalParentState._emit",
                "TemporalParentState.quiescent",
                "TemporalParentState.children_quiescent",
                "TemporalParentState.next_session_operation",
                "TemporalParentState.accept_session_root",
                "TemporalParentState._complete_parent",
                "TemporalParentState._complete_node",
                "TemporalParentState._native_capacity",
                "TemporalParentState.retry_blocked",
                "TemporalParentState.prepare_parent_completion",
                "TemporalParentState.next_parent_completion_operation",
                "TemporalParentState.accept_parent_completion",
                "TemporalParentState.budget",
                "TemporalParentState.snapshot",
                "TemporalParentState.diagnostics",
                "TemporalParentState.command",
                "TemporalParentState._apply",
                "TemporalParentState._adopt_graph",
                "TemporalParentState.accept_selection",
                "TemporalParentState._member",
                "TemporalParentState._project_call_request",
                "TemporalParentState._call_runner_keys",
                "TemporalParentState._adopt_child_result",
                "TemporalParentState.delegate",
                "TemporalParentState.next_calls",
                "TemporalParentState.mark_started",
                "TemporalParentState.observe",
                "TemporalParentState.patch",
                "TemporalParentState.planning_request",
                "TemporalParentState.accept_verification",
            ),
        ),
        "bindings": (
            "temporal_bindings",
            (
                "coding_enabled",
                "reject_runner_descriptor",
                "normalize_request",
                "validate_descriptor",
                "_plain_binding_inputs",
                "validate_bindings",
                "effective_manifest",
                "_effective_manifest",
                "effective_step",
                "validate_runner_tools",
                "project_child",
                "request_release_digest",
                "capabilities",
            ),
        ),
        "coding_protocol": ("temporal_coding_protocol", ("validate_protocol",)),
        "joint_context": ("temporal_context_read_protocol", ("validate_protocol",)),
        "joint_tools": ("temporal_tool_execution", ("validate_protocol",)),
        "joint_sandbox": ("binding_sandbox", ("validate_sandbox_protocol",)),
        "joint_artifacts": ("temporal_artifact_bindings", ("validate_protocol",)),
        "joint_decision": (
            "temporal_decision_state",
            ("validate_continuation_protocol", "validate_model_history_protocol"),
        ),
        "joint_parent_completion": ("temporal_parent_completion_state", ("validate_protocol",)),
        "parent_completion_history": (
            "temporal_parent_completion_state",
            (
                "initialize",
                "_actual_messages",
                "_input_consumed",
                "_current_messages",
                "_worker_path",
                "_source_children",
                "source",
                "_business_plan",
                "_restore_root_session_budget",
                "check_source",
                "prepare",
                "next_operation",
                "observe_verifier",
                "adopt",
                "accept",
            ),
        ),
        "joint_user_input": ("temporal_user_input", ("validate_protocol",)),
        "context_history": ("temporal_context_read_state", ("observe", "recreate_unadmitted")),
        "session_model_history": ("temporal_session_model_history", ("validate_native_request",)),
        "managed_context": ("temporal_managed_context", ("accept_stage",)),
    }


def _worker_sources():
    return {
        "execution_end_transport": (
            "temporal_execution_end_transport",
            ("_identity", "accept", "observe", "_receipt", "execute"),
        ),
        "scoped_manual_transport": (
            "temporal_scoped_manual_transport",
            ("_identity", "accept", "observe", "execute"),
        ),
        "run_command_transport": (
            "temporal_command_transport",
            (
                "supports",
                "_identity",
                "accept",
                "observe",
                "_legacy_snapshot",
                "_receipt",
                "execute",
            ),
        ),
        "publication": (
            "temporal_activities",
            (
                "TemporalRuntime.__init__",
                "TemporalRuntime._current_manifest",
                "TemporalRuntime.validate_release",
            ),
        ),
        "worker_protocol": (
            "temporal_coding_composition_protocol",
            ("publish", "check", "require_sdk"),
        ),
        "control": (
            "temporal_coding_composition_control",
            (
                "selected",
                "_root_kind",
                "_registry",
                "_actual",
                "_validate_admission",
                "_bind_submission",
                "_namespace",
                "_validate_proof",
                "_proof",
                "root_admission",
                "validate_activity",
                "_discover",
                "_command",
                "_child_update",
                "_adopt",
                "_child_proof",
                "_validate_child_intent",
                "_children",
                "_ancestry",
                "_activity_root_command",
                "_ancestry_admission",
                "control",
                "_initialize_root",
                "_fence_leaf",
                "_is_notfound",
                "_resources",
                "_leaf_requests",
                "_resource_request",
                "_closed_subtree",
                "_close_child",
                "_close_subtree",
                "_adopt_resource_ancestry",
                "close",
            ),
        ),
        "activities": (
            "temporal_control_activities",
            (
                "control",
                "_record_control_failure",
                "registered_parent_activities",
                "select",
                "_RecordedCaller.__init__",
                "_RecordedCaller.call",
            ),
        ),
        "tree_activity": ("temporal_session_activities", ("validate_tree_activity",)),
        "lifecycle": (
            "temporal_assembly_lifecycle",
            (
                "TemporalRuntimeAssembly.__init__",
                "TemporalRuntimeAssembly.create_engine",
                "TemporalRuntimeAssembly._begin_close",
                "TemporalRuntimeAssembly._drain_execution",
                "TemporalRuntimeAssembly._worker_finished",
                "TemporalRuntimeAssembly._close_unused_composition",
            ),
        ),
        "submissions": (
            "temporal_coding_composition_submissions",
            (
                "CompositionSubmissionOwner.__init__",
                "CompositionSubmissionOwner.execute",
                "CompositionSubmissionOwner.stop_admission",
                "CompositionSubmissionOwner.wait",
                "CompositionSubmissionOwner.aclose",
            ),
        ),
        "resources": ("postgres_runner_journal", ("PostgresRunnerJournal.composition_resources",)),
        "run_workflow": (
            "temporal_workflow",
            (
                "TemporalRunWorkflow.__init__",
                "TemporalRunWorkflow._check_session_parent",
                "TemporalRunWorkflow._check_composition_parent",
                "TemporalRunWorkflow.run",
                "TemporalRunWorkflow._deadline",
                "TemporalRunWorkflow.command",
                "TemporalRunWorkflow.control_command",
                "TemporalRunWorkflow.execution_ended",
                "TemporalRunWorkflow.view",
                "TemporalRunWorkflow.coding_composition_namespace",
                "TemporalRunWorkflow.coding_composition_child_epoch",
                "TemporalRunWorkflow.coding_composition_child_stopped",
                "TemporalCommandRegistryWorkflow.__init__",
                "TemporalCommandRegistryWorkflow.reserve",
                "TemporalCommandRegistryWorkflow.reserve_scoped_manual",
                "TemporalCommandRegistryWorkflow.view",
                "TemporalCommandRegistryWorkflow.close_coding_composition_submissions",
                "TemporalCommandRegistryWorkflow.admit_coding_composition_submission",
            ),
        ),
        "parent_workflow": (
            "temporal_parent_workflow",
            (
                "TemporalParentWorkflow.__init__",
                "TemporalParentWorkflow._activity",
                "TemporalParentWorkflow._control",
                "TemporalParentWorkflow._admit_composition",
                "TemporalParentWorkflow._observe_composition",
                "TemporalParentWorkflow._deadline",
                "TemporalParentWorkflow.run",
                "TemporalParentWorkflow.command",
                "TemporalParentWorkflow.view",
            ),
        ),
        "root_submission": (
            "temporal",
            (
                "TemporalEngine._guard",
                "TemporalEngine.submit",
                "TemporalEngine._submit",
                "TemporalEngine.capabilities",
                "TemporalEngine.binding_capabilities",
                "_workflow_runner",
                "replay_temporal_history",
                "build_temporal_worker",
            ),
        ),
        "profile": ("temporal_profile", ("TemporalProfile.__init__",)),
        "builder": (
            "temporal_builder",
            ("TemporalRuntimeBuilder._prepare", "TemporalRuntimeBuilder._construct_profile"),
        ),
        "factories": ("temporal_coding_factories", ("preflight_coding_references",)),
    }


def _fields(sources):
    return {group: frozenset(names) for group, (_, names) in sources.items()}


PURE_FIELDS = _fields(_pure_sources())
WORKER_FIELDS = _fields(_worker_sources())


def enabled(manifest):
    return isinstance(manifest, dict) and "coding_composition_protocol" in manifest


def _direct_agents(definition):
    from .orchestration_types import DynamicWorkflowSpec, TeamSpec
    from .workflow import GraphWorkflowSpec

    kind = definition["kind"]
    if kind == "graph":
        graph = GraphWorkflowSpec.from_dict(definition)
        if any(node.agent is None for node in graph.nodes):
            raise ValidationError("Coding composition supports original Agent nodes only")
    elif kind in {"team", "dynamic"}:
        members = definition.get("members")
        if not isinstance(members, dict) or any(
            not isinstance(member, dict) or member.get("kind", "agent") != "agent"
            for member in members.values()
        ):
            raise ValidationError("Coding composition requires direct Agent members")
        (TeamSpec if kind == "team" else DynamicWorkflowSpec).from_dict(definition)
    else:
        raise ValidationError("Coding composition requires bounded Agent orchestration")


def _validate_hidden_agents(definition, manifest):
    from .binding_types import AgentBindingDescriptor
    from .temporal_bindings import effective_step
    from .types import AgentSpec

    hidden = []
    if definition["kind"] == "dynamic":
        planner = (
            manifest.get("orchestration", {}).get("planners", {}).get(definition["planner"], {})
        )
        if planner.get("agent") is not None:
            hidden.append((planner["agent"], AgentBindingDescriptor().to_dict()))
    policy = definition.get("completion_policy")
    if policy is not None:
        stage = (
            manifest.get("parent_completion_policies", {})
            .get(policy, {})
            .get("effective_agent_release")
        )
        if stage is not None:
            declaration = stage.get("definition", {})
            if declaration.get("kind") != "agent" or len(declaration.get("steps", [])) != 1:
                raise ValidationError("Hidden verifier requires one fixed Agent")
            hidden.append(
                (
                    declaration["steps"][0],
                    stage.get("agent_bindings", {}).get(
                        "agent", AgentBindingDescriptor().to_dict()
                    ),
                )
            )
    for step, descriptor in hidden:
        if not isinstance(step, dict) or step.get("kind", "agent") != "agent":
            raise ValidationError("Hidden planner/verifier requires one fixed Agent")
        try:
            AgentSpec(**step)
        except TypeError:
            raise ValidationError("Hidden planner/verifier requires one fixed Agent") from None
        selected = effective_step(step, manifest, descriptor)
        if any(
            "delegated_runner" in manifest.get("tools", {}).get(name, {}).get("config", {})
            for name in selected["tools"]
        ):
            raise ValidationError("Hidden planner/verifier cannot receive Coding grants")


def _recursive_definitions(definition, policy):
    """Validate the fixed tree at the same depths as original SDK child Runs."""
    from .spec_codec import decode_spec, validate_definition_tree

    source = validate_definition_tree(definition)
    decode_spec(source)
    stack, composites = [(source, 0)], []
    while stack:
        current, depth = stack.pop()
        if depth >= policy.max_depth:
            raise ValidationError("Coding composition definition exceeds original depth policy")
        kind = current.get("kind", "agent")
        if kind in {"agent", "sequence"}:
            continue  # Native sequence steps share this original SDK execution.
        concurrency = current.get("max_concurrency", 1)
        if type(concurrency) is not int or not 1 <= concurrency <= policy.max_concurrency:
            raise ValidationError(
                "Coding composition concurrency exceeds original execution policy"
            )
        composites.append(current)
        if kind == "graph":
            _direct_agents(current)
            stack.extend((node["agent"], depth + 1) for node in current["nodes"])
        elif kind in {"team", "dynamic"}:
            stack.extend((member, depth + 1) for member in current["members"].values())
        else:
            raise ValidationError("Coding composition requires a registered definition kind")
    return composites


def _topology_definitions(definition, manifest):
    """Validate topology bounds independently of already resolved leaf grants."""
    concurrency = definition.get("max_concurrency", 1)
    from .governance import TemporalExecutionPolicy

    policy = (
        TemporalExecutionPolicy.from_identity(manifest["execution_policy"])
        if "execution_policy" in manifest
        else TemporalExecutionPolicy()
    )
    if type(concurrency) is not int or not 1 <= concurrency <= policy.max_concurrency:
        raise ValidationError("Coding composition concurrency exceeds original execution policy")
    from .temporal_coding_composition_state import recursive_enabled

    if recursive_enabled(manifest):
        composites = _recursive_definitions(definition, policy)
    else:
        _direct_agents(definition)
        composites = [definition]
    return composites


def validate_topology(request, manifest):
    """Check effective grants for every actual leaf before any child permission."""
    from .binding_paths import agent_paths
    from .binding_types import AgentBindingDescriptor
    from .temporal_bindings import effective_step, validate_bindings

    definition = request["definition"]
    if definition["kind"] in {"agent", "sequence"}:
        return
    composites = _topology_definitions(definition, manifest)
    validate_bindings(request, manifest)
    for path, step in agent_paths(definition).items():
        effective_step(
            step,
            manifest,
            request.get("agent_bindings", {}).get(path, AgentBindingDescriptor().to_dict()),
        )
    for composite in composites:
        _validate_hidden_agents(composite, manifest)


def validate_protocol(manifest):
    if not enabled(manifest):
        if manifest.get("binding_protocol") in (12, 13, 15, 17, 19, 21, 23):
            raise DefinitionMismatch("Original Coding composition publication is missing")
        return
    value = manifest["coding_composition_protocol"]
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] != 23
        or manifest.get("dispatch_admission") != "history-1"
        or "coding_execution_protocol" not in manifest
        or type(value) is not dict
        or set(value) != {"version", "topology", "implementation"}
        or type(value["version"]) is not int
        or value["version"] != 7
        or value["topology"] != "bounded-recursive-orchestration"
    ):
        raise DefinitionMismatch("Unsupported original Coding composition protocol")
    validate_implementation(value["implementation"])


def validate_implementation(value):
    from .session_types import sha

    fields = _fields({**_pure_sources(), **_worker_sources()})
    if type(value) is not dict or set(value) != set(fields):
        raise DefinitionMismatch("Original Coding composition implementation groups changed")
    try:
        for group, names in fields.items():
            if type(value[group]) is not dict or set(value[group]) != names:
                raise DefinitionMismatch("Original Coding composition callable inventory changed")
            for fingerprint in value[group].values():
                sha(fingerprint)
    except ValidationError:
        raise DefinitionMismatch(
            "Original Coding composition implementation fingerprint invalid"
        ) from None
    for group, expected in implementation(history_only=True).items():
        if value[group] != expected:
            raise DefinitionMismatch("Original pure Coding composition History changed")


def _resolve(module, name):
    for part in name.split("."):
        module = getattr(module, part)
    return module.fget if isinstance(module, property) else module


def _fingerprints(sources):
    from importlib import import_module

    from .component_fingerprint import executable_digest

    try:
        return {
            group: {
                name: executable_digest(_resolve(import_module("." + module, __package__), name))
                for name in names
            }
            for group, (module, names) in sources.items()
        }
    except (ImportError, AttributeError):
        raise DefinitionMismatch(
            "Original Coding composition implementation is incomplete"
        ) from None


def implementation(*, history_only=False):
    sources = _pure_sources() if history_only else {**_pure_sources(), **_worker_sources()}
    return _fingerprints(sources)


def require_sdk():
    """Check the selected API before acquiring or using original resources."""
    try:
        from temporalio import workflow
    except ImportError:
        raise ValidationError(
            "Coding composition requires Temporal SDK workflow.Info.original_execution_run_id"
        ) from None
    fields = getattr(workflow.Info, "__dataclass_fields__", None)
    if fields is None:
        fields = getattr(workflow.Info, "__annotations__", {})
    if "original_execution_run_id" not in fields:
        raise ValidationError(
            "Coding composition requires Temporal SDK workflow.Info.original_execution_run_id"
        )


def publish(manifest, runtime, *, _validate=True, _copy=True):
    from .temporal_state import detached
    from .types import canonical

    if runtime.coding_execution is not True or runtime.coding_composition is not True:
        raise DefinitionMismatch("Original Coding composition opt-in is missing")
    require_sdk()
    if not _copy:
        canonical(manifest)
    result = detached(manifest) if _copy else manifest
    result["binding_protocol"] = 23
    result["coding_composition_protocol"] = {
        "version": 7,
        "topology": "bounded-recursive-orchestration",
        "implementation": implementation(),
    }
    if _validate:
        validate_protocol(result)
    return result


def check(runtime, manifest):
    require_sdk()
    validate_protocol(manifest)
    if (
        getattr(runtime, "coding_execution", False) is not True
        or getattr(runtime, "coding_composition", False) is not True
        or (manifest["coding_composition_protocol"]["implementation"] != implementation())
    ):
        raise DefinitionMismatch("Original Coding composition Worker implementation changed")
