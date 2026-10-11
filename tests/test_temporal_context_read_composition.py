"""Actual Runtime ports with original portable actors; no Service claim."""

import asyncio
import copy

import pytest

from ralf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryMemory,
    ManagedContextPipeline,
    Scope,
    TeamSpec,
    WorkflowSpec,
)
from ralf_agent.temporal_control_activities import select
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.temporal_session_state import TemporalSessionState
from ralf_agent.temporal_session_topology import CompositeSessionTopology
from ralf_agent.temporal_state import TemporalRunState

from .test_temporal_context_read_runtime import call
from .test_temporal_memory_bindings import grant
from .test_temporal_persistent_session_data import accepted, runtime
from .test_temporal_session_tree_execution import ended, root_operation


def definition(kind):
    agent = AgentSpec("writer", "Answer")
    graph = GraphWorkflowSpec("graph", [GraphNode("writer", agent=agent)])
    return {
        "native": agent,
        "sequence": WorkflowSpec("sequence", [agent, agent]),
        "graph": graph,
        "team": TeamSpec("team", {"writer": agent}),
        "plan": DynamicWorkflowSpec("plan", {"writer": agent}),
        "dag": DynamicWorkflowSpec("dag", {"writer": agent}, planner="dag-rule", plan_mode="dag"),
        "nested": TeamSpec("outer", {"inner": graph}, child_budget=16),
    }[kind]


async def execute(host, state, records):
    records.append(state)
    if isinstance(state, TemporalParentState):
        for _ in range(32):
            while await root_operation(host, state):
                pass
            if state.state == "succeeded":
                return
            if state.stage in {"select", "plan", "verify"} and state.children_quiescent:
                kind = "team" if state.stage == "select" else state.stage
                result = await select(
                    host,
                    {
                        "runtime_manifest": state.manifest,
                        "definition": state.definition,
                        "kind": kind,
                        "input": state.request["input"],
                        "results": state.results,
                        "planning_request": state.planning_request()
                        if state.kind == "dynamic"
                        else None,
                        "planner_snapshot": None,
                    },
                )
                if kind == "verify":
                    state.accept_verification(result)
                else:
                    state.accept_selection(result)
            for intent in state.next_calls():
                cls = (
                    TemporalParentState
                    if intent["request"]["definition"]["kind"] in {"graph", "team", "dynamic"}
                    else TemporalRunState
                )
                child = cls(
                    intent["run_id"],
                    state.scope,
                    intent["command_id"],
                    intent["request"],
                    state.manifest,
                )
                state.mark_started(child.run_id)
                next(c for c in state.children if c["run_id"] == child.run_id)[
                    "dispatch_started"
                ] = True
                await execute(host, child, records)
                state.observe(
                    child.run_id,
                    {"scope": child.scope, "request": child.request, **child.diagnostics()},
                )
        raise AssertionError(state.diagnostics())
    for _ in range(64):
        operation = state.next_operation()
        if operation is None:
            break
        action, request = operation
        if action["kind"] in {"context", "managed_context"}:
            response = await call(host, state, action, request)
            method = (
                state.accept_context
                if action["kind"] == "context"
                else state.accept_managed_context
            )
            method(action["id"], response)
            assert await host.wait_context_executions(wait_timeout=3)
        elif action["kind"] == "model":
            response = await host.complete_model(request, dispatch_guard=lambda r: grant(state, r))
            state.accept_model(action["id"], response)
        elif action["kind"] == "managed_session":
            response = await host.manage_session(
                request, dispatch_guard=lambda r: grant(state, r), on_end=lambda p: ended(state, p)
            )
            state.accept_session(action["id"], response)
            assert await host.wait_session_executions(wait_timeout=3)
        else:
            raise AssertionError(action)
    assert state.state == "succeeded" and state.quiescent, state.diagnostics()
    assert all(s["status"] == "completed" for s in state.context_read_stages.values())


@pytest.mark.parametrize("kind", ["native", "sequence", "graph", "team", "plan", "dag", "nested"])
@pytest.mark.parametrize("managed", [False, True])
def test_original_composition_reads_and_saves_are_stable_over_two_turns(kind, managed):
    async def run():
        backend = InMemoryMemory()
        host = runtime(
            backend,
            context_reads=True,
            session_topology=CompositeSessionTopology(),
            context_builder=ManagedContextPipeline() if managed else None,
        )
        declared = definition(kind)
        value = accepted(host, declared)
        value["manifest"] = host.orchestration_release
        session = TemporalSessionState(value)
        try:
            for number in (1, 2):
                session.command(
                    {
                        "kind": "submit",
                        "scope": session.scope,
                        "command_id": f"turn-{number}",
                        "session_ref": session.ref.to_dict(),
                        "input": "question",
                        "budget": 64,
                    }
                )
                intent = session.active
                cls = (
                    TemporalParentState if kind not in {"native", "sequence"} else TemporalRunState
                )
                state = cls(
                    intent["run_id"],
                    session.scope,
                    intent["command_id"],
                    intent["request"],
                    intent["manifest"],
                )
                before = copy.deepcopy(state.request)
                records = []
                await execute(host, state, records)
                assert state.request == before
                assert session.adopt_observation(
                    {
                        "scope": state.scope,
                        "request": state.request,
                        **state.diagnostics(),
                        "descendants": [
                            {"scope": item.scope, "request": item.request, **item.diagnostics()}
                            for item in records[1:]
                        ],
                    }
                )
                assert not session.snapshot()["busy"]
                assert backend.read(Scope(), session.key.storage_key)[0] == number * (
                    2 if kind == "sequence" else 1
                )
                assert any(
                    not isinstance(item, TemporalParentState) and item.context_read_stages
                    for item in records
                )
        finally:
            await host.close_context_execution()
            await host.close_session_execution()

    asyncio.run(run())
