"""Each original Run control observation executes the complete handler once."""

import asyncio
import copy
from types import SimpleNamespace as NS

import pytest

from ralf_agent.errors import RalfError
from ralf_agent.temporal_workflow import TemporalRunWorkflow
from tests.test_temporal_unowned_tool_end import two_tools


def fixture():
    state, _, scope = two_tools()
    host = object.__new__(TemporalRunWorkflow)
    host.state, host.wake_revision = state, 0
    info = NS(
        workflow_id=state.run_id,
        run_id=state.epoch,
        first_execution_run_id=state.epoch,
        original_execution_run_id=state.epoch,
        namespace="default",
    )
    envelope = {
        "version": 1,
        "run_id": state.run_id,
        "scope": scope,
        "namespace": "default",
        "execution_epoch": None,
        "observation_id": "one",
        "request": {"command_id": "wake", "payload": {"kind": "drive", "scope": scope}},
    }
    return host, info, envelope


def test_observation_is_pure_and_duplicate_drive_executes_complete_handler_each_attempt():
    from ralf_agent.temporal_command_transport import accept, observe

    async def run():
        host, info, e = fixture()
        before = copy.deepcopy(vars(host.state))
        view = observe(host, e, info)
        assert view["result"] is None and vars(host.state) == before
        e["execution_epoch"] = view["execution_epoch"]
        await accept(host, e, info)
        first = observe(host, e, info)["result"]
        assert first["ok"] and host.wake_revision == 1
        await accept(host, e, info)
        assert host.wake_revision == 1
        host._deployment_parent_notification_attempts = 7
        another = {**e, "observation_id": "two"}
        assert observe(host, another, info)["result"] is None
        await accept(host, another, info)
        assert observe(host, another, info)["result"] == first and host.wake_revision == 2
        assert host._deployment_parent_notification_attempts == 0
        assert len(host.state.receipts) == 2 and not host.state.quiescent

    asyncio.run(run())


def test_eviction_drops_only_observation_and_keeps_original_business_receipts():
    from ralf_agent.temporal_command_transport import accept, observe

    async def run():
        host, info, e = fixture()
        e["execution_epoch"] = info.run_id
        for i in range(70):
            await accept(host, {**e, "observation_id": str(i)}, info)
        assert observe(host, {**e, "observation_id": "0"}, info)["result"] is None
        assert len(host._command_observations) == 64 and len(host.state.receipts) == 2
        assert host.wake_revision == 70

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault", ["scope", "namespace", "epoch", "reset", "kind", "version", "payload"]
)
def test_invalid_signal_creates_no_observation_or_business_fact(fault):
    from ralf_agent.temporal_command_transport import accept, observe

    async def run():
        host, info, e = fixture()
        e["execution_epoch"] = info.run_id
        if fault == "scope":
            e["scope"] = {"workspace": "other"}
        elif fault == "namespace":
            e["namespace"] = "other"
        elif fault == "epoch":
            e["execution_epoch"] = "other"
        elif fault == "reset":
            info.first_execution_run_id = "before"
        elif fault == "kind":
            e["request"]["payload"]["kind"] = "approve"
        elif fault == "version":
            e["version"] = True
        else:
            e["request"]["payload"]["query"] = True
            e["request"]["payload"]["kind"] = "reconcile"
        before = copy.deepcopy(vars(host.state))
        await accept(host, e, info)
        assert vars(host.state) == before and not getattr(host, "_command_observations", {})
        with pytest.raises(RalfError):
            observe(host, e, info)

    asyncio.run(run())


@pytest.mark.parametrize("patched", [False, True])
def test_parent_observation_preserves_complete_repeat_wake_and_seal(monkeypatch, patched):
    from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, TemporalRuntime
    from ralf_agent.temporal_command_transport import accept, observe
    from ralf_agent.temporal_parent_state import TemporalParentState
    from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow, workflow
    from ralf_agent.types import submission_request
    from tests.test_temporal_engine import Provider, registry

    async def run():
        _, info, e = fixture()
        runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry())
        definition = GraphWorkflowSpec("g", [GraphNode("a", agent=AgentSpec("a", "answer"))])
        state = TemporalParentState(
            info.workflow_id,
            e["scope"],
            "submit",
            submission_request(definition, "task"),
            runtime.orchestration_release,
        )
        state.epoch = info.run_id
        host = object.__new__(TemporalParentWorkflow)
        host.state, host.wake_revision = state, 0
        forced = []
        host._deployment_force_child_reads = lambda: forced.append(True)
        monkeypatch.setattr(workflow, "patched", lambda _: patched)
        e["execution_epoch"] = info.run_id
        await accept(host, e, info)
        first = observe(host, e, info)["result"]
        recovery = state.memory_recovery_revision
        host._deployment_parent_notification_attempts = 7
        await accept(host, {**e, "observation_id": "again"}, info)
        assert observe(host, {**e, "observation_id": "again"}, info)["result"] == first
        assert state.memory_recovery_revision == recovery + int(
            patched and state.manifest["kernel"] == "temporal-3"
        )
        assert len(forced) == 1 + int(patched) and host.wake_revision == 2
        assert host._deployment_parent_notification_attempts == 0
        state.deployment_seal = {"original": True}
        before = copy.deepcopy(vars(state))
        await accept(host, {**e, "observation_id": "sealed"}, info)
        assert vars(state) == before and len(forced) == 1 + int(patched)
        assert observe(host, {**e, "observation_id": "sealed"}, info)["result"] == first

    asyncio.run(run())


def test_observation_identity_cannot_be_reused_for_a_different_command():
    from ralf_agent.temporal_command_transport import accept, observe

    async def run():
        host, info, e = fixture()
        e["execution_epoch"] = info.run_id
        await accept(host, e, info)
        before = copy.deepcopy(vars(host.state))
        other = {**e, "request": {**e["request"], "command_id": "different"}}
        await accept(host, other, info)
        assert vars(host.state) == before and host.wake_revision == 1
        with pytest.raises(RalfError):
            observe(host, other, info)

    asyncio.run(run())
