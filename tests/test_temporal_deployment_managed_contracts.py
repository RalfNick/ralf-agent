"""Selected dispatch must preserve original managed payload and History contracts."""

import asyncio
import copy
from dataclasses import asdict
from functools import partial
from types import SimpleNamespace

import pytest

from ralf_agent import AgentSpec, Scope, TeamSpec, ToolRegistry
from ralf_agent.errors import DefinitionMismatch
from ralf_agent.governance import DeploymentAdmissionPolicy
from ralf_agent.orchestration_types import ChildCall
from ralf_agent.temporal_activities import TemporalRuntime, registered_activities
from ralf_agent.temporal_deployment_admission import root_run_id
from ralf_agent.temporal_deployment_execution_state import adopt, initialize, view
from ralf_agent.temporal_parent_state import TemporalParentState
from ralf_agent.temporal_state import TemporalCommandRegistryState, TemporalRunState
from ralf_agent.types import digest, submission_request


@pytest.fixture(autouse=True, scope="module")
def _optional_temporal_sdk():
    pytest.importorskip("temporalio")


POLICY = DeploymentAdmissionPolicy("managed-dispatch-regression")
NAMESPACE = {"name": "managed-original", "id": "12345678-1234-5678-1234-567812345678"}


def admitted_state(state, command):
    registry = TemporalCommandRegistryState(admission_policy=POLICY.identity, namespace=NAMESPACE)
    reservation = registry.reserve(
        {
            "scope": state.scope,
            "command_id": command,
            "kind": "submit",
            "target": state.run_id,
            "payload_digest": digest(state.request),
            "admission_policy": POLICY.identity,
            "namespace": NAMESPACE,
            "root_admission": {"version": 1, "manifest_digest": digest(state.manifest)},
        }
    )
    metadata = {"version": 1, "root": reservation["root_admission"], "lineage": []}
    initialize(
        state,
        metadata,
        namespace=NAMESPACE["name"],
        epoch=state.epoch,
        original_epoch=state.epoch,
        parent=None,
    )
    response = {
        "version": 1,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "root": {**metadata["root"], "state": "held-bound", "execution_epoch": state.epoch},
        "metadata_digest": digest(metadata),
    }
    adopt(state, {**response, "proof_digest": digest(response)})
    return state


def selected_setup(monkeypatch, module, **options):
    monkeypatch.setattr(
        module, "TemporalRuntime", partial(TemporalRuntime, _deployment_admission_policy=POLICY)
    )
    runtime, original, *rest = module.setup(**options)
    command = next(key for key, receipt in original.receipts.items() if receipt["kind"] == "submit")
    state = TemporalRunState(
        root_run_id(POLICY.deployment_id, original.scope, command),
        original.scope,
        command,
        original.request,
        runtime.manifest,
        "sdk-original",
    )
    return runtime, admitted_state(state, command), rest


def parent(monkeypatch, *, admitted=True):
    from tests.test_temporal_deployment_dispatch_integration import Provider

    runtime = TemporalRuntime(
        providers={"default": Provider()}, tools=ToolRegistry(), _deployment_admission_policy=POLICY
    )
    scope = asdict(Scope())
    request = submission_request(
        TeamSpec("team", {"a": AgentSpec("a", "Answer")}, child_budget=2), "task", budget=8
    )
    state = TemporalParentState(
        root_run_id(POLICY.deployment_id, scope, "parent"),
        scope,
        "parent",
        request,
        runtime.orchestration_release,
        "sdk-parent",
    )
    if admitted:
        admitted_state(state, "parent")
    return runtime, state


def test_selected_parent_records_original_intent_before_projecting_child(monkeypatch):
    _, state = parent(monkeypatch)
    state.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "child"}], "done": False, "result": None}
    )
    call = state.next_calls()[0]
    assert state.children[0]["deployment_admission"] == call["deployment_admission"]
    assert call["deployment_admission"]["lineage"][0]["child_request_digest"] == digest(
        call["request"]
    )
    assert state.budget["reserved"] == 2
    assert state.next_calls()[0] == call


def test_selected_parent_projection_refusal_leaves_original_intent_and_budget_unchanged(
    monkeypatch,
):
    import ralf_agent.temporal_deployment_execution_state as deployment

    _, state = parent(monkeypatch)
    before = copy.deepcopy((state.children, state.budget, state.revision))

    def reject(*args):
        raise DefinitionMismatch("Original child ancestry refused")

    monkeypatch.setattr(deployment, "project_child", reject)
    with pytest.raises(DefinitionMismatch):
        state.delegate(ChildCall("one", "a", "child"))
    assert (state.children, state.budget, state.revision) == before


def boundary(monkeypatch, runtime, state):
    from temporalio import activity, workflow

    import ralf_agent.temporal_deployment_execution as transport
    from ralf_agent.temporal_control_activities import registered_parent_activities
    from ralf_agent.temporal_workflow import TemporalRunWorkflow

    class Handle:
        async def execute_update(self, name, payload, **options):
            if name == "admit_context_dispatch":
                return state.admit_context_dispatch(payload)
            if name == "session_execution_ended":
                return state.session_execution_ended(payload)
            raise AssertionError(name)

    client = SimpleNamespace(
        namespace=NAMESPACE["name"], get_workflow_handle=lambda *args, **kwargs: Handle()
    )

    async def validated(*args):
        # SDK/Registry ancestry has its own tests. This boundary test retains
        # the real selected wrapper and every original business handler.
        return view(state)

    async def namespace(client, expected):
        return expected

    monkeypatch.setattr(transport, "validate_activity", validated)
    monkeypatch.setattr(transport, "_namespace", namespace)
    monkeypatch.setattr(
        activity,
        "info",
        lambda: SimpleNamespace(
            workflow_id=state.run_id,
            workflow_run_id=state.epoch,
            workflow_namespace=NAMESPACE["name"],
        ),
    )
    functions = transport.wrap_activities(
        runtime,
        client,
        registered_activities(runtime, client) + registered_parent_activities(runtime, client),
    )
    registered = {
        activity._Definition.must_from_callable(function).name: function for function in functions
    }

    async def execute(name, value, **options):
        return await registered[name](value)

    monkeypatch.setattr(workflow, "execute_activity", execute)
    runner = TemporalRunWorkflow.__new__(TemporalRunWorkflow)
    runner.state = state
    return runner


async def step(runner, state):
    from ralf_agent.temporal_completion_state import ACTIVITY as COMPLETION
    from ralf_agent.temporal_limits_state import ACTIVITY as LIMITS
    from ralf_agent.temporal_managed_context import ACTIVITY as CONTEXT
    from ralf_agent.temporal_session_save_state import ACTIVITY as SESSION
    from ralf_agent.temporal_state import CONTEXT_ACTIVITY, MODEL_ACTIVITY, TOOL_ACTIVITY

    action, request = state.next_operation()
    name, accept = {
        "agent_limits": (LIMITS, state.accept_limits),
        "agent_completion": (COMPLETION, state.accept_completion),
        "managed_context": (CONTEXT, state.accept_managed_context),
        "managed_session": (SESSION, state.accept_session),
        "model": (MODEL_ACTIVITY, state.accept_model),
        "context": (CONTEXT_ACTIVITY, state.accept_context),
        "tool": (TOOL_ACTIVITY, state.accept_tool),
    }[action["kind"]]
    response = await runner._execute_activity(name, request)
    assert response["ok"], response
    accept(action["id"], response)
    assert state.state != "failed", state.error
    return action


def test_selected_limits_adopts_successful_original_request_digest(monkeypatch):
    from tests import test_temporal_limits as fixture

    async def run():
        runtime, state, rest = selected_setup(monkeypatch, fixture)
        runner = boundary(monkeypatch, runtime, state)
        action = await step(runner, state)
        assert action["kind"] == "agent_limits"
        assert state.step["max_decisions"] == 2
        assert rest[0].calls == ["limited"]

    asyncio.run(run())


def test_selected_completion_adopts_successful_original_request_digest(monkeypatch):
    from tests import test_temporal_completion as fixture

    async def run():
        runtime, state, rest = selected_setup(monkeypatch, fixture)
        runner = boundary(monkeypatch, runtime, state)
        for _ in range(5):
            action = await step(runner, state)
            if action["kind"] == "agent_completion":
                break
        assert action["kind"] == "agent_completion"
        assert state.state == "succeeded"
        assert len(rest[1].calls) == 1

    asyncio.run(run())


def test_selected_managed_context_grants_original_dispatch_digest(monkeypatch):
    from tests import test_temporal_managed_context as fixture

    async def run():
        runtime, state, rest = selected_setup(monkeypatch, fixture)
        runner = boundary(monkeypatch, runtime, state)
        for _ in range(30):
            action = await step(runner, state)
            if action.get("phase") == "write":
                break
        assert action["kind"] == "managed_context"
        assert action["phase"] == "write"
        assert action["dispatch_grant"]["allowed"] is True
        assert state.active_action is None
        assert len(rest[1]) == 1

    asyncio.run(run())


def test_selected_session_write_grants_original_dispatch_digest_and_saves_once(monkeypatch):
    from tests import test_temporal_session_writes as fixture

    async def run():
        runtime, state, rest = selected_setup(monkeypatch, fixture)
        runner = boundary(monkeypatch, runtime, state)
        actions = []
        for _ in range(15):
            if state.state == "succeeded":
                break
            actions.append(await step(runner, state))
        assert state.state == "succeeded", state.error
        writes = [action for action in actions if action.get("phase") == "session-write"]
        assert len(writes) == 1
        assert writes[0]["dispatch_grant"]["allowed"] is True
        assert state.budget["unknown"] == 0
        await runtime.close_session_execution()

    asyncio.run(run())


def test_selected_parent_activity_carrier_preserves_original_selection_payload(monkeypatch):
    from datetime import timedelta

    from ralf_agent.temporal_parent_state import SELECTION_ACTIVITY
    from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow

    async def run():
        runtime, state = parent(monkeypatch)
        boundary(monkeypatch, runtime, state)
        runner = TemporalParentWorkflow.__new__(TemporalParentWorkflow)
        runner.state = state
        payload = {
            "runtime_manifest": state.manifest,
            "kind": "team",
            "definition": state.definition,
            "input": state.request["input"],
            "results": state.results,
        }
        response = await runner._activity(SELECTION_ACTIVITY, payload, timedelta(seconds=1))
        assert response["ok"], response
        state.accept_selection(response["result"])
        call = state.next_calls()[0]
        assert call["member"] == "a"
        assert call["request"]["input"] == {"results": {}, "task": "task"}

    asyncio.run(run())
