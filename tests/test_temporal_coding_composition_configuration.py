"""Composition publication is explicit and keeps the original leaf release."""

import asyncio
import importlib.util
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, BindingSelection, Scope, TemporalProfile, TemporalRuntime
from ralf_agent.binding_definitions import BoundDefinition
from ralf_agent.binding_types import AgentBindingDescriptor
from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from ralf_agent.temporal_bindings import normalize_request, project_child
from ralf_agent.types import digest, submission_request
from tests.test_sandbox_bindings import registered as registered
from tests.test_temporal_coding_configuration import manifest as leaf_manifest
from tests.test_temporal_engine import Provider


def profile(execution=None):
    return TemporalProfile(
        "composition", "1", {"default": {"adapter": "offline-echo"}}, execution=execution
    )


def protocol():
    assert importlib.util.find_spec("ralf_agent.temporal_coding_composition_protocol") is not None
    from ralf_agent import temporal_coding_composition_protocol

    return temporal_coding_composition_protocol


def manifest():
    value = leaf_manifest()
    value["context_builder"] = {"kind": "default", "version": "1"}
    return value


def test_false_composition_is_sparse_and_keeps_original_profile_identity():
    original = profile({"coding_execution": True})
    disabled = profile({"coding_execution": True, "coding_composition": False})
    assert original.to_dict() == disabled.to_dict()
    assert original.identity == disabled.identity
    selected = profile({"coding_execution": True, "coding_composition": True})
    assert selected.execution["coding_composition"] is True


@pytest.mark.parametrize(
    "execution",
    [{"coding_composition": True}, {"coding_execution": False, "coding_composition": True}],
)
def test_composition_requires_original_coding_before_factory_io(execution):
    with pytest.raises(ValidationError, match="requires.*Coding execution"):
        profile(execution)


@pytest.mark.parametrize("value", [None, 1, "true", {}])
def test_sdk_composition_boolean_and_dependency_are_checked_before_resources(value):
    with pytest.raises(ValidationError, match="boolean"):
        TemporalRuntime(providers={"default": Provider()}, tools=None, coding_composition=value)


def test_sdk_composition_requires_coding_before_resource_access():
    with pytest.raises(ValidationError, match="requires.*Coding execution"):
        TemporalRuntime(providers={"default": Provider()}, tools=None, coding_composition=True)


def test_disabled_sdk_composition_keeps_original_default_release():
    from ralf_agent import ToolRegistry

    ordinary = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry())
    disabled = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), coding_composition=False
    )
    assert ordinary.manifest == disabled.manifest
    assert "coding_composition_protocol" not in disabled.manifest


def hide_original_execution_field(monkeypatch):
    from temporalio import workflow

    fields = {
        name: field
        for name, field in workflow.Info.__dataclass_fields__.items()
        if name != "original_execution_run_id"
    }
    monkeypatch.setattr(workflow.Info, "__dataclass_fields__", fields)


def test_selected_sdk_requires_original_execution_identity_before_resource_access(monkeypatch):
    hide_original_execution_field(monkeypatch)
    with pytest.raises(ValidationError, match="SDK.*original_execution_run_id"):
        TemporalRuntime(
            providers=object(), tools=None, coding_execution=True, coding_composition=True
        )


def test_selected_builder_rejects_missing_sdk_identity_before_any_factory(monkeypatch, tmp_path):
    from ralf_agent import TemporalRuntimeBuilder, ToolRegistry
    from ralf_agent.runtime_builder import ComponentRegistry

    hide_original_execution_field(monkeypatch)
    acquired = []
    registry = ComponentRegistry()

    def provider_factory(config, context):
        acquired.append("provider")
        return Provider()

    def tools_factory(config, context):
        acquired.append("tools")
        return ToolRegistry()

    registry.register("provider", "sdk-preflight-provider", provider_factory)
    registry.register("tools", "sdk-preflight-tools", tools_factory)
    declaration = TemporalProfile(
        "sdk-preflight",
        "1",
        {"default": {"adapter": "sdk-preflight-provider"}},
        components={"tools": {"adapter": "sdk-preflight-tools"}},
        execution={"coding_execution": True, "coding_composition": True},
    )
    with pytest.raises(ValidationError, match="SDK.*original_execution_run_id"):
        asyncio.run(TemporalRuntimeBuilder(registry, base_dir=tmp_path).abuild(declaration))
    assert acquired == []


def test_profile_declaration_and_unselected_runtime_do_not_require_new_sdk_identity(monkeypatch):
    from ralf_agent import ToolRegistry
    from ralf_agent.temporal_coding_factories import preflight_coding_references

    expected = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry()).manifest
    hide_original_execution_field(monkeypatch)
    selected = profile({"coding_execution": True, "coding_composition": True})
    assert selected.execution["coding_composition"] is True
    legacy = profile({"coding_execution": True})
    preflight_coding_references(legacy)
    actual = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry()).manifest
    assert actual == expected


def test_selected_publication_rechecks_sdk_before_worker_implementation_discovery(monkeypatch):
    from types import SimpleNamespace

    hide_original_execution_field(monkeypatch)
    with pytest.raises(ValidationError, match="SDK.*original_execution_run_id"):
        protocol().publish(
            manifest(), SimpleNamespace(coding_execution=True, coding_composition=True)
        )


def test_selected_runtime_registration_rechecks_sdk_before_tool_registry_access(monkeypatch):
    value = object.__new__(TemporalRuntime)
    value.coding_composition = True
    hide_original_execution_field(monkeypatch)
    with pytest.raises(ValidationError, match="SDK.*original_execution_run_id"):
        value._current_manifest()


def test_missing_optional_sdk_only_blocks_selected_composition(monkeypatch):
    import builtins

    from ralf_agent import ToolRegistry

    original = builtins.__import__

    def absent(name, *args, **kwargs):
        if name.split(".")[0] == "temporalio":
            raise ImportError("optional SDK unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent)
    with pytest.raises(ValidationError, match="SDK.*original_execution_run_id"):
        TemporalRuntime(
            providers=object(), tools=None, coding_execution=True, coding_composition=True
        )
    assert (
        TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry()).manifest["kernel"]
        == "temporal-1"
    )


def graph_request(*, tools=("coding",), bindings=None, concurrency=1):
    from ralf_agent import GraphNode, GraphWorkflowSpec

    graph = GraphWorkflowSpec(
        "serial",
        (GraphNode("first", agent=AgentSpec("a", "Task", tools=tools)),),
        max_concurrency=concurrency,
    )
    definition = graph if bindings is None else BoundDefinition(graph, bindings)
    return normalize_request(submission_request(definition, "q"), manifest())


def test_finite_gate_checks_inherited_runner_uniqueness_for_every_leaf():
    value = graph_request(tools=("coding", "other"))
    with pytest.raises(ValidationError, match="unique"):
        protocol().validate_topology(value, manifest())


def test_finite_gate_accepts_ref_and_projects_original_leaf_descriptor():
    choice = AgentBindingDescriptor(runner=BindingSelection.ref("native", "1"))
    value = graph_request(bindings={"graph/nodes/first": choice})
    protocol().validate_topology(value, manifest())
    child = project_child(
        value, "first", submission_request(AgentSpec("a", "Task", tools=("coding",)), "q")
    )
    assert child["agent_bindings"] == {"agent": choice.to_dict()}


def test_finite_gate_accepts_bounded_parallel_without_selected_native_tool():
    protocol().validate_topology(graph_request(tools=("plain",), concurrency=2), manifest())


def test_finite_gate_disabled_runner_never_grants_selected_coding():
    value = graph_request(
        bindings={"graph/nodes/first": AgentBindingDescriptor(runner=BindingSelection.disabled())}
    )
    with pytest.raises(AuthorizationDenied, match="Disabled Runner"):
        protocol().validate_topology(value, manifest())


def test_coding_protocol_23_never_accepts_missing_composition_marker():
    from ralf_agent.temporal_coding_protocol import validate_protocol

    value = manifest()
    value["binding_protocol"] = 23
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)


def test_composition_marker_is_refused_on_current_leaf_22_release():
    value = manifest()
    value["coding_composition_protocol"] = {
        "version": 7,
        "topology": "bounded-recursive-orchestration",
        "implementation": {},
    }
    with pytest.raises(DefinitionMismatch):
        protocol().validate_protocol(value)


@pytest.mark.parametrize(
    "version,kind,linked,expected",
    [
        (23, "graph", False, True),
        (22, "graph", False, False),
        (23, "agent", False, False),
        (23, "graph", True, False),
    ],
)
def test_root_guard_only_records_selected_original_graph_admission(version, kind, linked, expected):
    from ralf_agent.temporal import TemporalEngine

    requests = []

    class Registry:
        async def execute_update(self, operation, request):
            assert operation == "reserve"
            requests.append(request)

    engine = object.__new__(TemporalEngine)
    engine._closed, engine._registry = False, Registry()
    engine.scope = Scope()
    engine._release = {"kernel": "temporal-3", "binding_protocol": version}
    if version == 23:
        engine._release["coding_composition_protocol"] = {"version": 7}
    request = {"definition": {"kind": kind}}
    if linked:
        request["coding_parent"] = {"original": "parent"}
    asyncio.run(engine._guard("submit", "first", "run", request))
    reservation = requests[0]
    assert reservation["scope"] == asdict(Scope())
    assert reservation["payload_digest"] == digest(request)
    if expected:
        assert reservation["coding_composition"] == {
            "version": 1,
            "manifest_digest": digest(engine.release),
            "request_digest": digest(request),
        }
    else:
        assert "coding_composition" not in reservation


@pytest.mark.parametrize(
    "kind",
    ["context", "tool", "artifacts", "continuation", "history", "parent", "input", "sandbox"],
)
def test_composition_joint_version_retains_original_optional_validation(kind, registered):
    import copy

    from ralf_agent import (
        temporal_artifact_bindings,
        temporal_context_read_protocol,
        temporal_decision_state,
        temporal_parent_completion_state,
        temporal_tool_execution,
        temporal_user_input,
    )
    from ralf_agent.binding_sandbox import validate_sandbox_protocol
    from tests.test_sandbox_temporal_protocol import runtime_for
    from tests.test_temporal_coding_joint_protocols import candidate

    validators = {
        "context": temporal_context_read_protocol.validate_protocol,
        "tool": temporal_tool_execution.validate_protocol,
        "artifacts": temporal_artifact_bindings.validate_protocol,
        "continuation": temporal_decision_state.validate_continuation_protocol,
        "history": temporal_decision_state.validate_model_history_protocol,
        "parent": temporal_parent_completion_state.validate_protocol,
        "input": temporal_user_input.validate_protocol,
        "sandbox": validate_sandbox_protocol,
    }
    value = copy.deepcopy(
        runtime_for(registered[0]).manifest if kind == "sandbox" else candidate(kind)
    )
    value.update(kernel="temporal-3", binding_protocol=23, dispatch_admission="history-1")
    validators[kind](value)


def composition_manifest():
    """History fixture: actual pure pins; opaque Worker pins cannot execute business."""
    module = protocol()
    value = manifest()
    value["binding_protocol"] = 23
    pins = module.implementation(history_only=True)
    pins.update(
        {
            group: {name: "a" * 64 for name in fields}
            for group, fields in module.WORKER_FIELDS.items()
        }
    )
    value["coding_composition_protocol"] = {
        "version": 7,
        "topology": "bounded-recursive-orchestration",
        "implementation": pins,
    }
    return value


def test_composition_history_validation_checks_complete_pure_groups():
    import copy

    from ralf_agent.temporal_coding_protocol import validate_protocol

    value = composition_manifest()
    validate_protocol(value)
    changed = copy.deepcopy(value)
    changed["coding_composition_protocol"]["implementation"]["protocol"]["validate_topology"] = (
        "b" * 64
    )
    with pytest.raises(DefinitionMismatch):
        validate_protocol(changed)


@pytest.mark.parametrize(
    "mutation", ["missing_group", "missing_method", "extra_method", "bad_sha", "future_marker"]
)
def test_composition_history_validation_refuses_incomplete_publication(mutation):
    value = composition_manifest()
    marker = value["coding_composition_protocol"]
    if mutation == "missing_group":
        marker["implementation"].pop("control")
    elif mutation == "missing_method":
        marker["implementation"]["control"].pop("close")
    elif mutation == "extra_method":
        marker["implementation"]["control"]["foreign"] = "a" * 64
    elif mutation == "bad_sha":
        marker["implementation"]["control"]["close"] = "unknown"
    else:
        marker["version"] = 8
    with pytest.raises(DefinitionMismatch):
        protocol().validate_protocol(value)


def test_history_validation_never_imports_worker_modules(monkeypatch):
    import builtins

    value = composition_manifest()
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"psycopg", "temporalio"} or name.endswith(
            "temporal_coding_composition_control"
        ):
            raise AssertionError("History attempted Worker module discovery")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    protocol().validate_protocol(value)


def test_composition_history_pins_the_exact_worker_callable_inventory(monkeypatch):
    module = protocol()
    assert hasattr(module, "_worker_sources")
    value = composition_manifest()
    sources = module._worker_sources()
    group_module, fields = sources["control"]
    sources["control"] = (group_module, tuple(name for name in fields if name != "close"))

    def omit_original_close():
        return sources

    monkeypatch.setattr(module, "_worker_sources", omit_original_close)
    with pytest.raises(DefinitionMismatch):
        module.validate_protocol(value)


@pytest.mark.parametrize("helper", ["_link_fields", "_view_fields"])
def test_composition_history_pins_complete_link_and_stop_proof_shapes(monkeypatch, helper):
    from ralf_agent import temporal_coding_composition_state

    value = composition_manifest()

    def incomplete_original_fields():
        return {"version"}

    monkeypatch.setattr(temporal_coding_composition_state, helper, incomplete_original_fields)
    with pytest.raises(DefinitionMismatch):
        protocol().validate_protocol(value)


def test_composition_capability_requires_explicit_marker():
    from ralf_agent.temporal_bindings import capabilities

    assert "coding_composition" not in capabilities(manifest())
    assert (
        capabilities(composition_manifest())["coding_composition"]
        == "bounded-recursive-orchestration"
    )


def test_composition_capability_refuses_an_unverified_publication():
    from ralf_agent.temporal_bindings import capabilities

    value = manifest()
    value.update(binding_protocol=23, coding_composition_protocol={})
    with pytest.raises(DefinitionMismatch):
        capabilities(value)


def test_selected_engine_exposes_only_its_finite_original_topology():
    from ralf_agent.temporal import TemporalEngine

    engine = object.__new__(TemporalEngine)
    engine._release = {**composition_manifest(), "orchestration": {"version": "1"}}
    assert engine.capabilities["graph"] is True
    assert {name: engine.capabilities[name] for name in ("team", "dag", "nesting")} == {
        "team": True,
        "dag": True,
        "nesting": True,
    }
    assert engine.binding_capabilities["supported_definition_kinds"] == [
        "agent",
        "sequence",
        "graph",
        "team",
        "dynamic",
    ]


def test_original_engine_topology_exposure_is_preserved():
    from ralf_agent.temporal import TemporalEngine

    engine = object.__new__(TemporalEngine)
    engine._release = {**manifest(), "orchestration": {"version": "1"}}
    assert all(engine.capabilities[name] for name in ("graph", "team", "dag", "nesting"))
    assert engine.binding_capabilities["supported_definition_kinds"] == [
        "agent",
        "sequence",
        "graph",
        "team",
        "dynamic",
    ]


def test_owned_submit_keeps_original_submission_under_mechanical_owner():
    from ralf_agent import ToolRegistry
    from ralf_agent.temporal import TemporalEngine
    from ralf_agent.types import CommandReceipt

    metadata = []

    class Owner:
        async def execute(self, operation, **proof):
            metadata.append(proof)
            return await operation()

    class Registry:
        async def execute_update(self, name, value):
            return {"accepted": True}

    class Handle:
        async def query(self, name, value):
            return {
                "command_id": "original",
                "run_id": "run",
                "kind": "submit",
                "apply_state": "applied",
                "outcome": {},
            }

    class Client:
        def get_workflow_handle(self, run_id):
            return Handle()

    release = TemporalRuntime(providers={"default": Provider()}, tools=ToolRegistry()).manifest
    engine = TemporalEngine(Client(), task_queue="original", release=release)
    engine._registry, engine._coding_submission_owner = Registry(), Owner()
    spec = AgentSpec("a", "Original")
    result = asyncio.run(engine.submit(spec, "q", command_id="original", budget=8))
    assert isinstance(result.receipt, CommandReceipt)
    assert metadata == [
        {
            "scope": asdict(Scope()),
            "release_digest": digest(release),
            "request_digest": digest(submission_request(spec, "q", budget=8)),
        }
    ]


def test_closed_owned_submit_refuses_before_encoding_or_owner_permission():
    from ralf_agent.temporal import TemporalEngine

    engine = object.__new__(TemporalEngine)
    engine._closed, engine._coding_submission_owner = True, object()
    with pytest.raises(ValidationError, match="closed"):
        asyncio.run(engine.submit(object(), "q", command_id="original"))


def test_serial_graph_distinct_original_leaf_resources_do_not_conflict():
    from ralf_agent import GraphNode, GraphWorkflowSpec

    request = submission_request(
        GraphWorkflowSpec(
            "serial",
            (
                GraphNode("a", agent=AgentSpec("a", "First", tools=("coding",))),
                GraphNode("b", agent=AgentSpec("b", "Second", tools=("other",))),
            ),
        ),
        "q",
    )
    protocol().validate_topology(request, manifest())


def test_excluded_coding_tools_never_acquire_runner_permission():
    value = graph_request(
        bindings={
            "graph/nodes/first": AgentBindingDescriptor(
                tool_set=BindingSelection.disabled(), runner=BindingSelection.disabled()
            )
        }
    )
    protocol().validate_topology(value, manifest())


@pytest.mark.parametrize("kind", ["team", "dynamic"])
def test_selected_composition_refuses_missing_direct_agent_members(kind):
    with pytest.raises(ValidationError, match="direct Agent"):
        protocol().validate_topology({"definition": {"kind": kind}}, manifest())


@pytest.mark.parametrize(
    "changed_helper",
    [
        "close",
        "_validate_admission",
        "_bind_submission",
        "_observe_composition",
        "_close_unused_composition",
        "_is_notfound",
        "_resources",
        "require_sdk",
    ],
)
def test_actual_factory_publication_keeps_leaf_group_and_pins_new_worker_helpers(
    tmp_path, monkeypatch, changed_helper
):
    from ralf_agent.runtime_lifecycle import BuildContext
    from ralf_agent.temporal_coding_factories import build
    from ralf_agent.temporal_journal import PostgresEffectJournal
    from tests.test_temporal_coding_factories import Connection, entry, publish_initialization

    events = []
    publish_initialization(monkeypatch, events)
    config = entry(tmp_path)

    async def run():
        context = BuildContext(None, tmp_path / "unused", Scope(), tmp_path, allow_async=True)
        effect = context.own_async(PostgresEffectJournal(Connection(events), owns_connection=True))
        context.effect_journal, context.coding_execution = effect, True
        try:
            tools = await build(config, context)
            with monkeypatch.context() as sdk_context:
                hide_original_execution_field(sdk_context)
                leaf = TemporalRuntime(
                    providers={"default": Provider()},
                    tools=tools,
                    journal=effect,
                    coding_execution=True,
                )
            selected = TemporalRuntime(
                providers={"default": Provider()},
                tools=tools,
                journal=effect,
                coding_execution=True,
                coding_composition=True,
            )
            assert leaf.manifest["binding_protocol"] == 22
            assert selected.manifest["binding_protocol"] == 23
            assert (
                selected.manifest["coding_execution_protocol"]
                == leaf.manifest["coding_execution_protocol"]
            )
            selected.validate_release()
            for field in ("coding_execution", "coding_composition"):
                setattr(selected, field, 1)
                with pytest.raises(DefinitionMismatch):
                    selected.validate_release()
                setattr(selected, field, True)
            # A substituted shutdown implementation has valid syntax but cannot
            # acquire permission on this actual registered Worker.
            from ralf_agent import temporal_coding_composition_control
            from ralf_agent.temporal_assembly_lifecycle import TemporalRuntimeAssembly
            from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow

            async def foreign_close(runtime, *, client, scope):
                return None

            def foreign_sdk():
                return None

            targets = {
                "_observe_composition": TemporalParentWorkflow,
                "_close_unused_composition": TemporalRuntimeAssembly,
                "require_sdk": protocol(),
            }
            target = targets.get(changed_helper, temporal_coding_composition_control)
            substitute = foreign_sdk if changed_helper == "require_sdk" else foreign_close
            monkeypatch.setattr(target, changed_helper, substitute)
            with pytest.raises(DefinitionMismatch):
                selected.validate_release()
            assert not (tmp_path / "native").exists()
        finally:
            await context.cleanup_async()

    asyncio.run(run())
