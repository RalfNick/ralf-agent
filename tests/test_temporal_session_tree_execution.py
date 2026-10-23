"""Original actors with actual Runtime ports; no separate Worker service proof."""

import asyncio
import copy
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryMemory,
    Scope,
    SessionBindingResource,
    ToolRegistry,
)
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_parent_state import TemporalParentState
from relf_agent.temporal_session_state import TemporalSessionState
from relf_agent.temporal_session_topology import CompositeSessionTopology
from relf_agent.temporal_state import TemporalRunState
from relf_agent.types import submission_request
from tests.test_temporal_memory_bindings import grant
from tests.test_temporal_sessions import Provider


async def ended(state, proof):
    state.session_execution_ended(proof)


async def complete_child(host, child):
    for _ in range(64):
        operation = child.next_operation()
        if operation is None:
            break
        action, request = operation
        if action["kind"] == "context":
            response = await host.prepare_context(request)
            assert response.get("ok"), (response, request)
            child.accept_context(action["id"], response)
        elif action["kind"] == "model":
            child.accept_model(
                action["id"],
                await host.complete_model(request, dispatch_guard=lambda r: grant(child, r)),
            )
        elif action["kind"] == "managed_session":
            child.accept_session(
                action["id"],
                await host.manage_session(
                    request,
                    dispatch_guard=lambda r: grant(child, r),
                    on_end=lambda proof: ended(child, proof),
                ),
            )
        else:
            raise AssertionError(action)
    assert child.state == "succeeded", child.snapshot()
    assert child.quiescent


async def root_operation(host, parent):
    operation = parent.next_session_operation()
    if operation is None:
        return False
    action, request = operation
    if action["kind"] == "session_root_read":
        parent.accept_session_root(
            action["id"],
            await host.prepare_session_root(
                request,
                dispatch_guard=lambda r: grant(parent, r),
                on_end=lambda proof: ended(parent, proof),
            ),
        )
    elif action["kind"] == "managed_session":
        parent.accept_session(
            action["id"],
            await host.manage_session(
                request,
                dispatch_guard=lambda r: grant(parent, r),
                on_end=lambda proof: ended(parent, proof),
            ),
        )
    else:
        raise AssertionError(action)
    assert await host.wait_session_executions(wait_timeout=3)
    return True


async def execute_graph_turn(host, session, command):
    session.command(
        {
            "kind": "submit",
            "scope": session.scope,
            "command_id": command,
            "session_ref": session.ref.to_dict(),
            "input": "question",
            "budget": 32,
        }
    )
    intent = session.active
    parent = TemporalParentState(
        intent["run_id"], session.scope, intent["command_id"], intent["request"], intent["manifest"]
    )
    original_request = copy.deepcopy(parent.request)
    assert parent.next_calls() == [], "No child before original root read adoption"
    assert await root_operation(host, parent)
    assert parent.root_session_snapshot["session_data"]["address"] == session.key.storage_key
    call = parent.next_calls()[0]
    parent.children[0]["dispatch_started"] = True
    parent.mark_started(call["run_id"])
    child = TemporalRunState(
        call["run_id"], session.scope, call["command_id"], call["request"], intent["manifest"]
    )
    await complete_child(host, child)
    child_proof = {"scope": session.scope, "request": child.request, **child.diagnostics()}
    parent.observe(call["run_id"], child_proof)
    parent.next_calls()
    assert parent.state != "succeeded", "Aggregate is gated by original root save"
    assert not parent.quiescent
    for _ in range(12):
        if not await root_operation(host, parent):
            break
    assert parent.state == "succeeded", parent.snapshot()
    assert parent.request == original_request
    assert parent.quiescent
    assert parent.budget["spent"] == 3
    assert parent.budget["reserved"] == parent.budget["unknown"] == 0
    assert session.adopt_observation(
        {
            "scope": session.scope,
            "request": parent.request,
            **parent.diagnostics(),
            "descendants": [child_proof],
        }
    )
    return child.context_snapshot["session_data"]["address"]


class SuffixTopology(CompositeSessionTopology):
    @property
    def identity(self):
        return {"kind": "test-suffix-topology", "version": "1"}

    def member_address(self, session, path, definition_digest, *, namespace=None):
        from relf_agent.temporal_session_data_state import session_storage_key

        logical = super().member_address(session, path, definition_digest)
        return session_storage_key(namespace, logical + ":routing")


@pytest.mark.parametrize("topology", [CompositeSessionTopology(), SuffixTopology()])
def test_original_graph_parent_root_and_private_saves_are_stable_over_two_turns(topology):
    async def run():
        store, provider = InMemoryMemory(), Provider()
        host = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            enable_sessions=True,
            session_writes=True,
            session_store=SessionBindingResource(
                store, namespaces=("chat",), default_namespace="chat"
            ),
            session_topology=topology,
        )
        try:
            graph = GraphWorkflowSpec(
                "g", [GraphNode("writer", agent=AgentSpec("writer", "Write"))]
            )
            session = TemporalSessionState(
                {
                    "scope": asdict(Scope()),
                    "namespace_id": "namespace-uuid",
                    "session_namespace": None,
                    "session_id": "chat",
                    "command_id": "open",
                    "request": submission_request(graph, None),
                    "manifest": host.orchestration_release,
                    "task_queue": "q",
                    "activity_timeout": 3,
                }
            )
            first = await execute_graph_turn(host, session, "first")
            second = await execute_graph_turn(host, session, "second")
            assert first == second != session.key.storage_key
            assert ("routing" in first) == isinstance(topology, SuffixTopology)
            assert store.read(Scope(), first)[0] == 2
            assert store.read(Scope(), session.key.storage_key)[0] == 2
            assert len(provider.calls) == 2
            assert not session.snapshot()["busy"]
        finally:
            await host.close_session_execution()

    asyncio.run(run())


def test_custom_root_proposal_cannot_rewrite_original_root_before_data_io():
    class WrongRoot(CompositeSessionTopology):
        def root_address(self, session):
            return "foreign"

    class Observed(InMemoryMemory):
        def __init__(self):
            super().__init__()
            self.reads = 0

        def read_page(self, *args, **kwargs):
            self.reads += 1
            return super().read_page(*args, **kwargs)

    async def run():
        store = Observed()
        host = TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            enable_sessions=True,
            session_writes=True,
            session_store=store,
            session_topology=WrongRoot(),
        )
        session = TemporalSessionState(
            {
                "scope": asdict(Scope()),
                "namespace_id": "namespace-uuid",
                "session_namespace": None,
                "session_id": "chat",
                "command_id": "open",
                "request": submission_request(
                    GraphWorkflowSpec("g", [GraphNode("writer", agent=AgentSpec("a", "Answer"))]),
                    None,
                ),
                "manifest": host.orchestration_release,
                "task_queue": "q",
                "activity_timeout": 3,
            }
        )
        session.command(
            {
                "kind": "submit",
                "scope": session.scope,
                "command_id": "first",
                "session_ref": session.ref.to_dict(),
                "input": "task",
                "budget": 32,
            }
        )
        accepted = session.active
        parent = TemporalParentState(
            accepted["run_id"],
            session.scope,
            accepted["command_id"],
            accepted["request"],
            accepted["manifest"],
        )
        _, request = parent.next_session_operation()
        try:
            response = await host.prepare_session_root(
                request, dispatch_guard=lambda r: grant(parent, r)
            )
            assert not response["ok"]
            assert store.reads == 0
        finally:
            await host.close_session_execution()

    asyncio.run(run())


@pytest.mark.parametrize("enabled,writes", [(False, True), (True, False)])
def test_topology_requires_original_session_admission_and_write_protocol(enabled, writes):
    from relf_agent.errors import ValidationError

    with pytest.raises(ValidationError):
        TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            session_store=InMemoryMemory(),
            enable_sessions=enabled,
            session_writes=writes,
            session_topology=CompositeSessionTopology(),
        )


def test_runtime_topology_replacement_refuses_before_publishing_or_io():
    from relf_agent.errors import DefinitionMismatch

    host = TemporalRuntime(
        providers={"default": Provider()},
        tools=ToolRegistry(),
        session_store=InMemoryMemory(),
        enable_sessions=True,
        session_writes=True,
        session_topology=CompositeSessionTopology(),
    )
    host.session_topology = SuffixTopology()
    with pytest.raises(DefinitionMismatch):
        host.validate_release()
    asyncio.run(host.close_session_execution())


def test_duplicate_admitted_root_read_cannot_disown_original_reader():
    async def run():
        from relf_agent.temporal_bindings import normalize_request

        started, finish = asyncio.Event(), asyncio.Event()

        class SlowMemory(InMemoryMemory):
            async def read_page(self, scope, address, query):
                started.set()
                await finish.wait()
                return super().read_page(scope, address, query)

        backend = SlowMemory()
        host = TemporalRuntime(
            providers={"default": Provider()},
            tools=ToolRegistry(),
            session_store=backend,
            enable_sessions=True,
            session_writes=True,
            session_topology=CompositeSessionTopology(),
        )
        definition = GraphWorkflowSpec(
            "g", [GraphNode("writer", agent=AgentSpec("writer", "Answer"))]
        )
        request = normalize_request(submission_request(definition, "task"))
        session = TemporalSessionState(
            {
                "scope": asdict(Scope()),
                "namespace_id": "actual-namespace",
                "session_namespace": None,
                "session_id": "chat",
                "command_id": "open",
                "request": request,
                "manifest": host.orchestration_release,
                "task_queue": "q",
                "activity_timeout": 3,
            }
        )
        from .test_temporal_session_tree_admission import turn

        turn(session)
        intent = session.active
        state = TemporalParentState(
            intent["run_id"],
            session.scope,
            intent["command_id"],
            intent["request"],
            intent["manifest"],
        )
        action, read = state.next_session_operation()
        pending = asyncio.create_task(
            host.prepare_session_root(
                read,
                dispatch_guard=lambda r: grant(state, r),
                on_end=lambda proof: ended(state, proof),
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 3)
            duplicate = await host.prepare_session_root(
                read,
                dispatch_guard=lambda r: grant(state, r),
                on_end=lambda proof: ended(state, proof),
            )
            assert not duplicate["ok"]
            state.accept_session_root(action["id"], duplicate)
            assert not state.quiescent
            assert not host.session_execution.active_count == 0
            assert not session.adopt_observation(
                {"scope": state.scope, "request": state.request, **state.diagnostics()}
            )
        finally:
            finish.set()
            await pending
            assert await host.wait_session_executions(wait_timeout=3)
            await host.close_session_execution(wait_timeout=3)
        assert state.quiescent and state.state == "failed"

    asyncio.run(run())
