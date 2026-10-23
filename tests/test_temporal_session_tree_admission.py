"""Original Coordinator admission of candidate trees is distinct from execution."""

from dataclasses import asdict

import pytest

from relf_agent import AgentBindingDescriptor, AgentSpec, BindingSelection, Scope
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.temporal_session_state import TemporalSessionState
from relf_agent.temporal_session_tree import validate_lineage

from .test_temporal_persistent_session_data import accepted, runtime
from .test_temporal_session_tree_protocol import proposal
from .test_temporal_session_tree_sources import setup


def candidate(host, request):
    return {
        "scope": asdict(Scope()),
        "namespace_id": "actual-namespace-uuid",
        "session_namespace": None,
        "session_id": "tree",
        "command_id": "open",
        "request": request,
        "manifest": proposal(host.orchestration_release),
        "task_queue": "q",
        "activity_timeout": 3,
    }


def turn(state):
    state.command(
        {
            "kind": "submit",
            "scope": state.scope,
            "command_id": "first",
            "session_ref": state.ref.to_dict(),
            "input": "question",
            "budget": 32,
        }
    )
    return state.active["request"]


def test_root_uses_host_dataset_even_with_independent_private_sources():
    host, request, stores = setup()
    state = TemporalSessionState(candidate(host, request))
    assert state.key.namespace == "chat"
    native = TemporalSessionState(accepted(runtime(host.session_store), AgentSpec("a", "Answer")))
    assert state.key.resource_id == native.key.resource_id
    assert state.data_source["physical"] == host.manifest["session_data"]["physical"]
    original = turn(state)
    accepted_lineage = validate_lineage(original, state.binding["manifest"], state.scope)
    assert accepted_lineage["run_id"] == state.active["run_id"]
    assert accepted_lineage["root_ref"] == state.ref.to_dict()
    assert original["session_data_binding"]["resource_id"] == state.key.resource_id
    assert all(store.read(Scope(), state.key.storage_key)[0] == 0 for store in stores)


def test_history_only_root_does_not_infer_a_private_member_dataset():
    host, request, _ = setup(root=False)
    state = TemporalSessionState(candidate(host, request))
    assert state.data_source is None and state.key.namespace is None
    original = turn(state)
    assert "session_data_binding" not in original
    assert original["session_lineage"]["root_turn"] == original["session_turn"]
    assert validate_lineage(original, state.binding["manifest"], state.scope)["path"] == []


def test_disabled_private_members_cannot_disable_the_host_root_source():
    host, request, _ = setup()
    request["agent_bindings"] = {
        path: AgentBindingDescriptor(session=BindingSelection.disabled()).to_dict()
        for path in request["agent_bindings"]
    }
    state = TemporalSessionState(candidate(host, request))
    assert state.data_source["namespace"] == "chat"
    assert turn(state)["session_data_binding"]["resource_id"] == state.key.resource_id


def test_root_dataset_migration_remains_refused_during_idle_rebind():
    host, request, _ = setup()
    state = TemporalSessionState(candidate(host, request))
    other, other_request, _ = setup()
    changed = candidate(other, other_request)
    with pytest.raises(DefinitionMismatch, match="migrate"):
        state.command(
            {
                "kind": "rebind",
                "scope": state.scope,
                "command_id": "move",
                "session_ref": state.ref.to_dict(),
                "expected_binding_revision": 1,
                "binding": {
                    key: changed[key]
                    for key in ("request", "manifest", "task_queue", "activity_timeout")
                },
            }
        )
    assert state.binding_revision == 1


def test_legacy_advanced_source_contract_remains_refused():
    host, request, _ = setup()
    value = candidate(host, request)
    value["manifest"] = host.orchestration_release
    with pytest.raises(ValidationError, match="not implemented"):
        TemporalSessionState(value)


def test_metadata_candidate_is_not_an_implicitly_registered_worker_release():
    host, request, _ = setup()
    state = TemporalSessionState(candidate(host, request))
    with pytest.raises(DefinitionMismatch):
        host.validate_release(state.binding["manifest"])


def test_candidate_parent_does_not_dispatch_children_before_original_root_read():
    from relf_agent.temporal_parent_state import TemporalParentState

    host, request, _ = setup()
    state = TemporalSessionState(candidate(host, request))
    turn(state)
    intent = state.active
    parent = TemporalParentState(
        intent["run_id"],
        state.scope,
        intent["command_id"],
        intent["request"],
        intent["manifest"],
    )
    assert parent.next_calls() == []
    assert parent.result is None and not parent.quiescent
    assert parent.next_session_operation()[0]["kind"] == "session_root_read"


def test_private_source_rebind_preserves_history_root_and_forks_member_generation():
    from relf_agent.session_types import SessionRef
    from relf_agent.temporal_session_topology import CompositeSessionTopology
    from relf_agent.types import digest

    host, request, _ = setup(root=False)
    state = TemporalSessionState(candidate(host, request))
    before = state.ref
    other, other_request, _ = setup(root=False)
    changed = candidate(other, other_request)
    receipt = state.command(
        {
            "kind": "rebind",
            "scope": state.scope,
            "command_id": "private-generation",
            "session_ref": before.to_dict(),
            "expected_binding_revision": 1,
            "binding": {
                key: changed[key]
                for key in ("request", "manifest", "task_queue", "activity_timeout")
            },
        }
    )
    after = SessionRef.from_dict(receipt["outcome"]["session_ref"])
    assert receipt["apply_state"] == "applied"
    assert after.key == before.key and after.binding_revision == 2
    layout = CompositeSessionTopology()
    path, declaration = ("team", "members", "writer", "calls", "writer"), digest("writer")
    assert layout.member_address(before, path, declaration) != layout.member_address(
        after, path, declaration
    )
    assert turn(state)["session_lineage"]["root_turn"]["session_ref"] == after.to_dict()


def test_accepted_tree_turn_and_busy_receipt_survive_coordinator_restore():
    import copy

    host, request, _ = setup()
    state = TemporalSessionState(candidate(host, request))
    turn(state)
    restored = copy.deepcopy(state)
    command = {
        "kind": "submit",
        "scope": state.scope,
        "command_id": "busy",
        "session_ref": state.ref.to_dict(),
        "input": "new",
        "budget": 32,
    }
    refusal = restored.command(command)
    assert refusal["apply_state"] == "rejected"
    assert refusal["outcome"]["error"] == "session_busy"
    assert refusal["outcome"]["active_run"] == state.active["turn"]["run"]
    assert copy.deepcopy(restored).command(command) == refusal
    assert restored.active == state.active and restored.snapshot()["busy"]


def test_opted_tree_release_keeps_stateless_composites_with_disabled_data_usable():
    from relf_agent import (
        AgentBindingDescriptor,
        AgentSpec,
        BindingSelection,
        BoundDefinition,
        InMemoryMemory,
        TeamSpec,
        ToolRegistry,
    )
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_bindings import normalize_request
    from relf_agent.temporal_parent_state import TemporalParentState
    from relf_agent.temporal_session_topology import CompositeSessionTopology
    from relf_agent.types import submission_request

    host = TemporalRuntime(
        providers={"default": runtime(InMemoryMemory()).providers["default"]},
        tools=ToolRegistry(),
        enable_sessions=True,
        session_writes=True,
        session_store=InMemoryMemory(),
        session_topology=CompositeSessionTopology(),
    )
    spec = BoundDefinition(
        TeamSpec("t", {"a": AgentSpec("a", "Answer")}),
        {"team/members/a": AgentBindingDescriptor(session=BindingSelection.disabled())},
    )
    request = normalize_request(submission_request(spec, "task"))
    parent = TemporalParentState(
        "stateless", asdict(Scope()), "submit", request, host.orchestration_release
    )
    assert parent.root_context_ready
    assert not parent.root_session_required
    assert parent.next_session_operation() is None


def test_unbound_tree_external_composite_is_rejected_before_run_creation():
    import asyncio

    from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, InMemoryMemory, ToolRegistry
    from relf_agent.errors import NotFound
    from relf_agent.temporal import TemporalEngine
    from relf_agent.temporal_activities import TemporalRuntime
    from relf_agent.temporal_session_topology import CompositeSessionTopology

    class Client:
        async def start_workflow(self, *args, **kwargs):
            raise AssertionError("Unsupported Run must not be created")

    host = TemporalRuntime(
        providers={"default": runtime(InMemoryMemory()).providers["default"]},
        tools=ToolRegistry(),
        enable_sessions=True,
        session_writes=True,
        session_store=InMemoryMemory(),
        session_topology=CompositeSessionTopology(),
    )
    engine = TemporalEngine(Client(), task_queue="q", release=host.orchestration_release)

    async def reserved(*args, **kwargs):
        return None

    async def missing(*args, **kwargs):
        raise NotFound("new")

    engine._guard, engine._view = reserved, missing
    with pytest.raises(ValidationError, match="Session"):
        asyncio.run(
            engine.submit(
                GraphWorkflowSpec("g", [GraphNode("a", agent=AgentSpec("a", "Answer"))]),
                "task",
                command_id="first",
            )
        )
