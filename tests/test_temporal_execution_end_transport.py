"""Original end observations invoke whole handlers without adopting business effects."""

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("temporalio")

from ralf_agent.errors import RalfError
from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow
from ralf_agent.types import digest

OPERATIONS = (
    "tool_execution_ended",
    "context_execution_ended",
    "session_execution_ended",
    "deployment_call_ended",
)


def fixture(monkeypatch, operation):
    node_type = TemporalRunWorkflow
    if operation == "tool_execution_ended":
        from tests.test_temporal_tool_execution import proof, state_for

        _, state, _, request = state_for()
        value = proof(request)
    elif operation == "context_execution_ended":
        from tests.test_temporal_context_read_state import admission, proof, state_for

        state, _, request = state_for()
        state.admit_context_dispatch(admission(request))
        value = proof(request)
    elif operation == "session_execution_ended":
        from tests.test_temporal_parent_session import parent

        state, _, _ = parent()
        assert state.next_calls() == []
        action, request = state.next_session_operation()
        state.admit_context_dispatch(
            {
                "scope": state.scope,
                "release_digest": state.release_digest,
                "action_id": action["id"],
                "phase": action["phase"],
                "request_digest": digest(request),
            }
        )
        value = {k: request[k] for k in ("scope", "action_id", "release_digest")} | {
            "request_digest": digest(request)
        }
        node_type = TemporalParentWorkflow
    else:
        from tests.test_temporal_deployment_release_state import identity, module, original

        state = original(monkeypatch, parent=True)
        state.authorize = lambda scope: TemporalRunState.authorize(state, scope)
        value = identity(state)
        module().begin_activity(state, value)
        node_type = TemporalParentWorkflow
    node = object.__new__(node_type)
    node.state, node.wake_revision = state, 0
    if operation == "deployment_call_ended":
        node._deployment_retirement_wait_ready = lambda: True
    info = NS(
        workflow_id=state.run_id,
        run_id=state.epoch,
        first_execution_run_id=state.epoch,
        original_execution_run_id=state.epoch,
        namespace="default",
    )
    monkeypatch.setattr(workflow, "info", lambda: info)
    e = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "namespace": info.namespace,
        "execution_epoch": info.run_id,
        "observation_id": "original",
        "operation": operation,
        "proof": value,
    }
    return node, info, e


@pytest.mark.parametrize("operation", OPERATIONS)
def test_whole_original_handler_and_typed_ack_are_separate_from_business(monkeypatch, operation):
    from ralf_agent.temporal_execution_end_transport import accept, observe

    async def run():
        node, info, e = fixture(monkeypatch, operation)
        before = copy.deepcopy(vars(node.state))
        assert observe(node, e, info)["result"] is None
        assert vars(node.state) == before
        await accept(node, e, info)
        first = observe(node, e, info)["result"]
        assert first["ok"] and node.wake_revision == 1
        await accept(node, e, info)
        assert node.wake_revision == 1
        await accept(node, {**e, "observation_id": "again"}, info)
        assert observe(node, {**e, "observation_id": "again"}, info)["result"] == first
        assert node.wake_revision == (1 if operation == "deployment_call_ended" else 2)
        assert node.state.state == before["state"]
        if operation == "tool_execution_ended":
            assert node.state.tool_executions[e["proof"]["action_id"]]["execution_stopped"]
        if operation == "session_execution_ended":
            assert "execution_end_proof" in node.state.actions[-1]

    asyncio.run(run())


@pytest.mark.parametrize("operation", OPERATIONS)
def test_wrong_original_proof_cannot_end_another_execution(monkeypatch, operation):
    from ralf_agent.temporal_execution_end_transport import accept, observe

    async def run():
        node, info, e = fixture(monkeypatch, operation)
        e = copy.deepcopy(e)
        e["proof"]["request_digest"] = "f" * 64
        before = copy.deepcopy(vars(node.state))
        await accept(node, e, info)
        assert observe(node, e, info)["result"]["ok"] is False
        assert vars(node.state) == before and node.wake_revision == 0

    asyncio.run(run())


@pytest.mark.parametrize("operation", OPERATIONS)
def test_original_workflow_signal_and_status_probe_share_end_observation(monkeypatch, operation):
    async def run():
        node, _, envelope = fixture(monkeypatch, operation)
        request = {
            "kind": "status",
            "scope": node.state.scope,
            "execution_end_observation": envelope,
        }
        assert node.view(request)["execution_end_observation"]["result"] is None
        await node.execution_ended(envelope)
        assert node.view(request)["execution_end_observation"]["result"]["ok"] is True
        assert node.wake_revision == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["scope", "namespace", "epoch", "reset", "version", "operation", "nonce"]
)
def test_invalid_end_envelope_never_invokes_original_handler(monkeypatch, fault):
    from ralf_agent.temporal_execution_end_transport import accept, observe

    async def run():
        node, info, e = fixture(monkeypatch, "tool_execution_ended")
        e = copy.deepcopy(e)
        if fault == "scope":
            e["scope"] = {"workspace": "other"}
        elif fault == "namespace":
            e["namespace"] = "other"
        elif fault == "epoch":
            e["execution_epoch"] = "other"
        elif fault == "reset":
            info.first_execution_run_id = "before"
        elif fault == "version":
            e["version"] = True
        elif fault == "operation":
            e["operation"] = "admit_tool_dispatch"
        else:
            e["observation_id"] = "x" * 129
        before = copy.deepcopy(vars(node.state))
        await accept(node, e, info)
        assert vars(node.state) == before and node.wake_revision == 0
        with pytest.raises(RalfError):
            observe(node, e, info)

    asyncio.run(run())


def test_cache_eviction_does_not_remove_original_end_proof(monkeypatch):
    from ralf_agent.temporal_execution_end_transport import accept, observe

    async def run():
        node, info, e = fixture(monkeypatch, "tool_execution_ended")
        for i in range(70):
            await accept(node, {**e, "observation_id": str(i)}, info)
        assert len(node._execution_end_observations) == 64
        assert observe(node, {**e, "observation_id": "0"}, info)["result"] is None
        assert node.state.tool_executions[e["proof"]["action_id"]]["end_proof"] == e["proof"]
        assert node.wake_revision == 70

    asyncio.run(run())
