"""Explicit finite composition publication over the unchanged original Coding loop."""

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
                "validate_bindings",
                "effective_manifest",
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
        "joint_user_input": ("temporal_user_input", ("validate_protocol",)),
        "context_history": ("temporal_context_read_state", ("observe", "recreate_unadmitted")),
        "session_model_history": ("temporal_session_model_history", ("validate_native_request",)),
        "managed_context": ("temporal_managed_context", ("accept_stage",)),
    }


def _worker_sources():
    return {
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
                "_children",
                "control",
                "_initialize_root",
                "_fence_leaf",
                "_is_notfound",
                "_resources",
                "close",
            ),
        ),
        "activities": ("temporal_control_activities", ("control", "registered_parent_activities")),
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
                "TemporalRunWorkflow.view",
                "TemporalRunWorkflow.coding_composition_namespace",
                "TemporalRunWorkflow.coding_composition_child_epoch",
                "TemporalRunWorkflow.coding_composition_child_stopped",
                "TemporalCommandRegistryWorkflow.__init__",
                "TemporalCommandRegistryWorkflow.reserve",
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


def validate_topology(request, manifest):
    """Check effective grants for every actual leaf before any child permission."""
    from .binding_paths import agent_paths
    from .binding_types import AgentBindingDescriptor
    from .temporal_bindings import effective_step, validate_bindings
    from .workflow import GraphWorkflowSpec

    definition = request["definition"]
    if definition["kind"] in {"agent", "sequence"}:
        return
    if definition["kind"] != "graph":
        raise ValidationError("Coding composition requires a static serial Agent graph")
    concurrency = definition.get("max_concurrency", 1)
    if type(concurrency) is not int or concurrency != 1:
        raise ValidationError("Coding composition requires a serial Agent graph")
    graph = GraphWorkflowSpec.from_dict(definition)
    if any(node.agent is None for node in graph.nodes):
        raise ValidationError("Coding composition supports original Agent nodes only")
    validate_bindings(request, manifest)
    for path, step in agent_paths(definition).items():
        effective_step(
            step,
            manifest,
            request.get("agent_bindings", {}).get(path, AgentBindingDescriptor().to_dict()),
        )


def validate_protocol(manifest):
    if not enabled(manifest):
        if manifest.get("binding_protocol") == 12:
            raise DefinitionMismatch("Original Coding composition publication is missing")
        return
    value = manifest["coding_composition_protocol"]
    if (
        manifest.get("kernel") != "temporal-3"
        or type(manifest.get("binding_protocol")) is not int
        or manifest["binding_protocol"] != 12
        or manifest.get("dispatch_admission") != "history-1"
        or "coding_execution_protocol" not in manifest
        or type(value) is not dict
        or set(value) != {"version", "topology", "implementation"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["topology"] != "serial-agent-graph"
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


def publish(manifest, runtime):
    from .temporal_state import detached

    if runtime.coding_execution is not True or runtime.coding_composition is not True:
        raise DefinitionMismatch("Original Coding composition opt-in is missing")
    require_sdk()
    result = detached(manifest)
    result["binding_protocol"] = 12
    result["coding_composition_protocol"] = {
        "version": 1,
        "topology": "serial-agent-graph",
        "implementation": implementation(),
    }
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
