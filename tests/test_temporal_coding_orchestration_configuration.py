"""Current finite Coding publication admits only fixed direct Agent members."""

import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, BindingSelection, DynamicWorkflowSpec, Scope, TeamSpec
from ralf_agent.binding_definitions import BoundDefinition
from ralf_agent.binding_types import AgentBindingDescriptor
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal import TemporalEngine
from ralf_agent.temporal_coding_composition_protocol import _worker_sources, validate_topology
from ralf_agent.temporal_coding_protocol import validate_protocol
from ralf_agent.types import submission_request
from tests.test_temporal_coding_configuration import manifest as leaf_manifest


def manifest():
    value = leaf_manifest()
    value["binding_protocol"] = 22
    value["coding_execution_protocol"]["version"] = 6
    value["context_builder"] = {"kind": "default", "version": "1"}
    value["orchestration"] = {
        "version": "1",
        "teams": {"sequential": {}},
        "planners": {"rule": {}, "dag-rule": {}},
        "verifiers": {"complete": {}},
    }
    return value


@pytest.mark.parametrize("spec", [TeamSpec, DynamicWorkflowSpec])
def test_direct_agent_orchestration_accepts_original_effective_coding_grants(spec):
    request = submission_request(
        spec("finite", {"worker": AgentSpec("a", "Task", tools=("coding",))}), "q"
    )
    validate_topology(request, manifest())


@pytest.mark.parametrize("spec", [TeamSpec, DynamicWorkflowSpec])
@pytest.mark.parametrize("kind", ["sequence", "team", "dynamic", "graph"])
def test_orchestration_refuses_every_non_agent_member(spec, kind):
    request = submission_request(spec("finite", {"worker": AgentSpec("a", "Task")}), "q")
    request["definition"]["members"]["worker"] = {"kind": kind}
    with pytest.raises(ValidationError, match="direct Agent"):
        validate_topology(request, manifest())


@pytest.mark.parametrize("member", ["@planner", "@verifier"])
def test_hidden_agents_cannot_receive_original_coding_grants(member):
    value = manifest()
    request = submission_request(DynamicWorkflowSpec("finite", {"a": AgentSpec("a", "Task")}), "q")
    hidden = AgentSpec("hidden", "Task", tools=("coding",))
    if member == "@planner":
        value["orchestration"]["planners"]["rule"]["agent"] = asdict(hidden)
    else:
        request["definition"]["completion_policy"] = "policy"
        value["parent_completion_policies"] = {
            "policy": {
                "effective_agent_release": {
                    "definition": submission_request(hidden, "q")["definition"],
                    "agent_bindings": {},
                }
            }
        }
    with pytest.raises(ValidationError, match="Hidden.*Coding"):
        validate_topology(request, value)


@pytest.mark.parametrize(
    "binding,version", [(14, 2), (15, 2), (16, 3), (17, 3), (18, 4), (19, 4), (20, 5), (21, 5)]
)
def test_current_worker_refuses_previous_selected_publication(binding, version):
    value = leaf_manifest()
    value["binding_protocol"] = binding
    value["coding_execution_protocol"]["version"] = version
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)


def test_current_native_publication_accepts_only_22_version6():
    validate_protocol(manifest())


@pytest.mark.parametrize("version", [1, 2, True, 3, 4, 5, 7])
def test_current_native_requires_explicit_integer_version_six(version):
    value = manifest()
    value["coding_execution_protocol"]["version"] = version
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)


@pytest.mark.parametrize("binding", [22, 23])
def test_new_selected_bindings_cannot_drop_native_publication(binding):
    value = manifest()
    value["binding_protocol"] = binding
    value.pop("coding_execution_protocol")
    with pytest.raises(DefinitionMismatch, match="publication is missing"):
        validate_protocol(value)


def test_worker_inventory_pins_selection_and_recorded_managed_planner():
    fields = _worker_sources()["activities"][1]
    assert {"select", "_RecordedCaller.__init__", "_RecordedCaller.call"} <= set(fields)
    assert "_root_kind" in _worker_sources()["control"][1]


@pytest.mark.parametrize("spec", [TeamSpec, DynamicWorkflowSpec])
def test_direct_member_excluded_tool_grants_do_not_reserve_native_resource(spec):
    from ralf_agent.temporal_bindings import normalize_request

    source = spec("finite", {"worker": AgentSpec("a", "Task", tools=("coding", "other"))})
    choice = AgentBindingDescriptor(
        tool_set=BindingSelection.disabled(), runner=BindingSelection.disabled()
    )
    request = normalize_request(
        submission_request(BoundDefinition(source, {f"{source.kind}/members/worker": choice}), "q"),
        manifest(),
    )
    validate_topology(request, manifest())


@pytest.mark.parametrize("spec", [TeamSpec, DynamicWorkflowSpec])
def test_orchestration_policy_bound_applies_before_any_agent_grant(spec):
    request = submission_request(spec("finite", {"a": AgentSpec("a", "Task")}), "q")
    request["definition"]["max_concurrency"] = 33
    with pytest.raises(ValidationError, match="execution policy"):
        validate_topology(request, manifest())


def test_hidden_verifier_uses_effective_grants_from_its_fixed_descriptor():
    value = manifest()
    hidden = AgentSpec("hidden", "Task", tools=("coding", "other"))
    request = submission_request(DynamicWorkflowSpec("finite", {"a": AgentSpec("a", "Task")}), "q")
    request["definition"]["completion_policy"] = "policy"
    value["parent_completion_policies"] = {
        "policy": {
            "effective_agent_release": {
                "definition": submission_request(hidden, "q")["definition"],
                "agent_bindings": {
                    "agent": AgentBindingDescriptor(
                        tool_set=BindingSelection.disabled(), runner=BindingSelection.disabled()
                    ).to_dict()
                },
            }
        }
    }
    validate_topology(request, value)


@pytest.mark.parametrize("member", ["@planner", "@verifier"])
def test_hidden_members_refuse_non_fixed_agent_definitions(member):
    value = manifest()
    request = submission_request(DynamicWorkflowSpec("finite", {"a": AgentSpec("a", "Task")}), "q")
    if member == "@planner":
        value["orchestration"]["planners"]["rule"]["agent"] = {"kind": "sequence"}
    else:
        request["definition"]["completion_policy"] = "policy"
        value["parent_completion_policies"] = {
            "policy": {
                "effective_agent_release": {
                    "definition": {"kind": "sequence", "steps": []},
                    "agent_bindings": {},
                }
            }
        }
    with pytest.raises(ValidationError, match="fixed Agent"):
        validate_topology(request, value)


@pytest.mark.parametrize(
    "helper", ["select", "_RecordedCaller.__init__", "_RecordedCaller.call", "_root_kind"]
)
def test_current_worker_rechecks_actual_managed_selection_helpers(monkeypatch, helper):
    from types import SimpleNamespace

    from ralf_agent import temporal_coding_composition_control, temporal_control_activities
    from ralf_agent.temporal_coding_composition_protocol import check, publish

    runtime = SimpleNamespace(coding_execution=True, coding_composition=True)
    release = publish(manifest(), runtime)
    check(runtime, release)
    target = (
        temporal_coding_composition_control
        if helper == "_root_kind"
        else temporal_control_activities
    )
    if helper.startswith("_RecordedCaller."):
        target, helper = target._RecordedCaller, helper.split(".")[1]

    def substituted(*args, **kwargs):
        return None

    monkeypatch.setattr(target, helper, substituted)
    with pytest.raises(DefinitionMismatch):
        check(runtime, release)


@pytest.mark.parametrize(
    "module,helper",
    [
        ("temporal_coding_composition_protocol", "_direct_agents"),
        ("temporal_coding_composition_protocol", "_validate_hidden_agents"),
        ("temporal_coding_composition_state", "orchestration_enabled"),
        ("temporal_parent_state", "TemporalParentState._project_call_request"),
        ("temporal_parent_state", "TemporalParentState._call_runner_keys"),
        ("temporal_parent_state", "TemporalParentState._adopt_child_result"),
    ],
)
def test_history_rechecks_new_fixed_orchestration_helpers(monkeypatch, module, helper):
    from importlib import import_module

    from ralf_agent.temporal_coding_composition_protocol import validate_protocol
    from tests.test_temporal_coding_composition_configuration import composition_manifest

    value = composition_manifest()
    validate_protocol(value)
    target = import_module("ralf_agent." + module)
    if "." in helper:
        owner, helper = helper.split(".")
        target = getattr(target, owner)

    def substituted(*args, **kwargs):
        return None

    monkeypatch.setattr(target, helper, substituted)
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)


@pytest.mark.parametrize(
    "helper",
    [
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
    ],
)
def test_history_rechecks_all_parent_completion_execution_helpers(monkeypatch, helper):
    from ralf_agent import temporal_parent_completion_state
    from ralf_agent.temporal_coding_composition_protocol import validate_protocol
    from tests.test_temporal_coding_composition_configuration import composition_manifest

    value = composition_manifest()
    validate_protocol(value)

    def substituted(*args, **kwargs):
        return None

    monkeypatch.setattr(temporal_parent_completion_state, helper, substituted)
    with pytest.raises(DefinitionMismatch):
        validate_protocol(value)


def test_parent_completion_history_inventory_never_discovers_worker_io(monkeypatch):
    from importlib import import_module

    from ralf_agent.temporal_coding_composition_protocol import implementation, validate_protocol
    from tests.test_temporal_coding_composition_configuration import composition_manifest

    value = composition_manifest()
    imports = []

    def pure_only(name, *args, **kwargs):
        imports.append(name)
        if name in {
            ".temporal_parent_completion",
            ".temporal_activities",
            ".temporal_parent_workflow",
            ".temporal_coding_composition_control",
        } or name.split(".")[0] in {"temporalio", "psycopg"}:
            raise AssertionError("History attempted Worker I/O discovery")
        return import_module(name, *args, **kwargs)

    monkeypatch.setattr("importlib.import_module", pure_only)
    assert "parent_completion_history" in implementation(history_only=True)
    validate_protocol(value)
    assert ".temporal_parent_completion_state" in imports


@pytest.mark.parametrize("kind", ["graph", "team", "dynamic"])
def test_current_root_guard_records_all_finite_orchestration_kinds(kind):
    reservations = []

    class Registry:
        async def query(self, name, request):
            assert name == "view" and request["scope"] == asdict(engine.scope)
            return {
                "scope": request["scope"],
                "capacity": 4096,
                "accepted_commands": len(reservations),
            }

        async def signal(self, *args, **kwargs):
            raise AssertionError("A positively identified legacy Registry receives no Signal")

        async def execute_update(self, operation, request):
            assert operation == "reserve"
            reservations.append(request)
            return {
                "command_id": request["command_id"],
                "target": request["target"],
                "record_state": "durably_recorded",
                "apply_state": "not_applied",
            }

    engine = object.__new__(TemporalEngine)
    engine._closed, engine._registry, engine.scope = False, Registry(), Scope()
    engine.client = SimpleNamespace(namespace="original")
    engine._release = {
        "kernel": "temporal-3",
        "binding_protocol": 23,
        "coding_composition_protocol": {"version": 7},
    }
    asyncio.run(engine._guard("submit", "original", "run", {"definition": {"kind": kind}}))
    assert reservations[0]["coding_composition"]["version"] == 1
