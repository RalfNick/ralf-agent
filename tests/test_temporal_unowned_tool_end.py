"""Effect adoption never substitutes for the original handler's actual end."""

import copy
from dataclasses import asdict

import pytest

from ralf_agent import AgentSpec, Scope, TemporalRuntime, ToolRegistry, ToolSpec
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request
from tests.test_temporal_engine import Provider


def two_tools(version=1):
    tools = ToolRegistry()
    tools.register(ToolSpec("read", "read", {"type": "object"}, cost=0), lambda a, c: None)
    scope = asdict(Scope())
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=tools)
    state = TemporalRunState(
        "run",
        scope,
        "submit",
        submission_request(AgentSpec("a", "Read", tools=("read",)), {}, budget=8),
        runtime.manifest,
    )
    state.tool_end_evidence_version = version
    model, _ = state.next_operation()
    state.accept_model(
        model["id"],
        {
            "ok": True,
            "output": None,
            "usage": None,
            "tool_calls": [
                {"name": "read", "arguments": {}, "call_id": "slow"},
                {"name": "read", "arguments": {}, "call_id": "fast"},
            ],
        },
    )
    original, _ = state.next_operation()
    state.operation_unknown(original["id"], "original-handler-still-running")
    return state, original, scope


@pytest.mark.parametrize("source", ["operator", "effect-query"])
def test_other_tool_success_never_clears_original_unknown_handler(source):
    state, original, scope = two_tools()
    state.accept_tool(
        original["id"], {"ok": True, "result": "confirmed", "source": source}, reconciled=True
    )
    second, _ = state.next_operation()
    state.accept_tool(second["id"], {"ok": True, "result": "second returned"})
    assert original["status"] == "completed" and state.budget["unknown"] == 0
    assert state.remote_uncertain and not state.quiescent
    assert original["execution_unconfirmed"] is True
    receipt = state.command("stop", {"kind": "cancel", "scope": scope})
    assert receipt["outcome"]["remote_stop_confirmed"] is False


def test_late_actual_original_completion_only_clears_its_own_end_obligation():
    state, original, scope = two_tools()
    manual = {
        "kind": "reconcile",
        "scope": scope,
        "action_id": original["id"],
        "query": False,
        "result": "operator result",
    }
    first = state.command("confirm", manual)
    second, _ = state.next_operation()
    state.operation_unknown(second["id"], "another-handler-unknown")
    state.accept_tool(
        original["id"], {"ok": True, "result": "different actual result", "source": "tool-handler"}
    )
    assert original["result"] == "operator result" and state.command("confirm", manual) == first
    assert state.remote_uncertain and not state.quiescent
    state.accept_tool(second["id"], {"ok": True, "result": "second handler returned"})
    assert not state.remote_uncertain and state.quiescent
    assert state.budget["unknown"] == state.budget["reserved"] == 0
    assert any(
        e["kind"] == "late_effect_evidence" and e["data"]["matches_committed_result"] is False
        for e in state.event_log
    )


def test_restored_action_end_fact_survives_effect_ack_and_other_success():
    state, original, _ = two_tools()
    state.accept_tool(original["id"], {"ok": True, "result": "confirmed"}, reconciled=True)
    restored = copy.deepcopy(state)
    restored.pending_acks.clear()  # Positive effect ACK is independent of handler end.
    second, _ = restored.next_operation()
    restored.accept_tool(second["id"], {"ok": True, "result": "returned"})
    assert not restored.quiescent
    restored.remote_uncertain = False  # Other stages cannot erase the per-Action fact.
    assert not restored.quiescent


def test_legacy_replay_branch_preserves_original_behavior_without_new_facts():
    state, original, _ = two_tools(version=0)
    state.accept_tool(original["id"], {"ok": True, "result": "confirmed"}, reconciled=True)
    second, _ = state.next_operation()
    state.accept_tool(second["id"], {"ok": True, "result": "returned"})
    assert not state.remote_uncertain and state.quiescent
    assert "execution_unconfirmed" not in original
