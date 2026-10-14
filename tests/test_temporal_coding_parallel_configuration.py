"""Selected bounded Coding graphs retain exact grants and publication identity."""

import asyncio
import copy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Scope, TemporalExecutionPolicy
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal import TemporalEngine
from ralf_agent.temporal_coding_composition_protocol import (
    publish,
    validate_protocol,
    validate_topology,
)
from ralf_agent.temporal_state import validate_request
from ralf_agent.types import digest, submission_request
from tests.test_temporal_coding_composition_configuration import (
    composition_manifest,
    graph_request,
    manifest,
)
from tests.test_temporal_engine import Provider, registry


def test_existing_boolean_composition_publishes_bounded_version_21():
    original = manifest()
    selected = publish(original, SimpleNamespace(coding_execution=True, coding_composition=True))
    assert selected["binding_protocol"] == 21
    assert selected["coding_composition_protocol"]["version"] == 6
    assert selected["coding_composition_protocol"]["topology"] == "bounded-agent-orchestration"
    assert selected["coding_execution_protocol"] == original["coding_execution_protocol"]
    assert original["binding_protocol"] == 20


@pytest.mark.parametrize(
    "helper", ["child_capacity_released", "coding_runner_keys", "occupied_runner_keys"]
)
@pytest.mark.parametrize("gate", ["history", "worker"])
def test_original_resource_capacity_helper_mutation_is_refused(monkeypatch, helper, gate):
    from ralf_agent import temporal_coding_composition_state
    from ralf_agent.temporal_coding_composition_protocol import check

    runtime = SimpleNamespace(coding_execution=True, coding_composition=True)
    release = publish(manifest(), runtime)
    validate_protocol(release)
    check(runtime, release)

    def foreign_capacity(*args, **kwargs):
        return set()

    monkeypatch.setattr(temporal_coding_composition_state, helper, foreign_capacity)
    with pytest.raises(DefinitionMismatch):
        if gate == "history":
            validate_protocol(release)
        else:
            check(runtime, release)


@pytest.mark.parametrize("gate", ["history", "worker"])
def test_original_blocked_retry_stop_gate_mutation_is_refused(monkeypatch, gate):
    from ralf_agent.temporal_coding_composition_protocol import check
    from ralf_agent.temporal_state import TemporalRunState

    runtime = SimpleNamespace(coding_execution=True, coding_composition=True)
    release = publish(manifest(), runtime)
    validate_protocol(release)
    check(runtime, release)

    def foreign_retry(state):
        state.state = "running"

    monkeypatch.setattr(TemporalRunState, "retry_blocked", foreign_retry)
    with pytest.raises(DefinitionMismatch):
        if gate == "history":
            validate_protocol(release)
        else:
            check(runtime, release)


@pytest.mark.parametrize("concurrency", [1, 2, 32])
def test_bounded_topology_accepts_existing_static_agent_graph(concurrency):
    validate_topology(graph_request(concurrency=concurrency), manifest())


@pytest.mark.parametrize("concurrency", [True, 0, -1, 33, 2.0])
def test_bounded_topology_never_exceeds_registered_default_policy(concurrency):
    request = graph_request()
    request["definition"]["max_concurrency"] = concurrency
    with pytest.raises(ValidationError, match="execution policy"):
        validate_topology(request, manifest())


def test_direct_tool_graph_stays_refused_before_leaf_permission():
    graph = GraphWorkflowSpec("tools", [GraphNode("a", tool="plain")], max_concurrency=2)
    with pytest.raises(ValidationError, match="Agent nodes only"):
        validate_topology(submission_request(graph, "task"), manifest())


def test_parallel_graph_checks_runner_grants_on_every_original_leaf():
    graph = GraphWorkflowSpec(
        "grants",
        [
            GraphNode("a", agent=AgentSpec("a", "answer", tools=("plain",))),
            GraphNode("b", agent=AgentSpec("b", "answer", tools=("coding", "other"))),
        ],
        max_concurrency=2,
    )
    with pytest.raises(ValidationError, match="unique"):
        validate_topology(submission_request(graph, "task"), manifest())


def test_registered_policy_still_limits_bounded_graph_capacity():
    from ralf_agent import TemporalRuntime

    host = TemporalRuntime(
        providers={"default": Provider()},
        tools=registry(),
        execution_policy=TemporalExecutionPolicy(max_concurrency=2),
    )
    release = host.orchestration_release
    release.update(kernel="temporal-3", binding_protocol=21)
    release["coding_composition_protocol"] = composition_manifest()["coding_composition_protocol"]
    graph = GraphWorkflowSpec(
        "bounded",
        [GraphNode("a", agent=AgentSpec("a", "answer"))],
        max_concurrency=2,
    )
    validate_request(submission_request(graph, "task"), release)
    excessive = GraphWorkflowSpec(
        "excessive",
        [GraphNode("a", agent=AgentSpec("a", "answer"))],
        max_concurrency=3,
    )
    with pytest.raises(ValidationError, match="Concurrency exceeds"):
        validate_request(submission_request(excessive, "task"), release)


@pytest.mark.parametrize("mutation", ["old_binding", "old_version", "old_topology", "missing"])
def test_current_publication_refuses_serial_release_reinterpretation(mutation):
    release = composition_manifest()
    release["binding_protocol"] = 21
    release["coding_composition_protocol"].update(version=6, topology="bounded-agent-orchestration")
    if mutation == "old_binding":
        release["binding_protocol"] = 12
    elif mutation == "old_version":
        release["coding_composition_protocol"]["version"] = 1
    elif mutation == "old_topology":
        release["coding_composition_protocol"]["topology"] = "serial-agent-graph"
    else:
        release.pop("coding_composition_protocol")
    with pytest.raises(DefinitionMismatch):
        validate_protocol(release)


def test_current_root_guard_records_exact_bounded_graph_admission():
    accepted = []

    class Registry:
        async def execute_update(self, name, value):
            assert name == "reserve"
            accepted.append(copy.deepcopy(value))

    engine = object.__new__(TemporalEngine)
    engine._closed, engine._registry, engine.scope = False, Registry(), Scope()
    engine._release = {
        "kernel": "temporal-3",
        "binding_protocol": 21,
        "coding_composition_protocol": {"version": 6, "topology": "bounded-agent-orchestration"},
    }
    request = graph_request(concurrency=2)
    asyncio.run(engine._guard("submit", "original", "root", request))
    assert accepted[0]["scope"] == asdict(engine.scope)
    assert accepted[0]["coding_composition"] == {
        "version": 1,
        "manifest_digest": digest(engine.release),
        "request_digest": digest(request),
    }


def test_selected_capability_exposes_finite_orchestration():
    engine = object.__new__(TemporalEngine)
    engine._release = {**composition_manifest(), "orchestration": {"version": "1"}}
    engine._release["binding_protocol"] = 21
    engine._release["coding_composition_protocol"].update(
        version=6, topology="bounded-agent-orchestration"
    )
    assert engine.capabilities["coding_composition"] == "bounded-agent-orchestration"
    assert engine.capabilities["graph"] is True
    assert engine.capabilities["team"] and engine.capabilities["dag"]
    assert engine.capabilities["nesting"] is False
    assert engine.binding_capabilities["supported_definition_kinds"] == [
        "agent",
        "sequence",
        "graph",
        "team",
        "dynamic",
    ]
