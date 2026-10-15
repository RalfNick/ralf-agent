"""Original Session Coding closure retains the native fence proof on retirement."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from ralf_agent import temporal_deployment_execution_state as admission
from ralf_agent import temporal_deployment_release as release
from ralf_agent import temporal_deployment_release_state as state_module
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.temporal_state import TOOL_ACTIVITY
from ralf_agent.types import digest
from tests.test_temporal_deployment_coding_validation import Runtime
from tests.test_temporal_session_coding_ancestry import coding_original
from tests.test_temporal_session_deployment_execution import (
    admit,
    coordinator,
    initialize,
    original,
)


def environment(*, composition=False, ordinary=False, fenced=False):
    intent, metadata, state = original() if ordinary else coding_original(composition=composition)
    initialize(state, metadata, coordinator(intent))
    admit(state)
    state.state, state.actions, state.reservations, state.children = "succeeded", [], {}, []
    state.active_action, state.remote_uncertain = None, False
    state.tool_executions = {}
    state.release_digest, state.revision = digest(state.manifest), 1
    if composition:
        state.composition_namespace = copy.deepcopy(intent["namespace"])
        state.composition_original_epoch = state.epoch
        state.composition_admission, state.composition_stop_intent = None, None
    state_module.initialize(state)
    proof = admission.view(state)
    identity = {
        "version": 1,
        "scope": state.scope,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "activity_id": "original-tool",
        "activity_name": TOOL_ACTIVITY,
        "attempt": 1,
        "invocation_id": "a" * 32,
        "request_digest": "b" * 64,
        "manifest_digest": digest(state.manifest),
    }
    state_module.begin_activity(state, identity)
    state_module.end_activity(state, identity)
    call = next(iter(state.deployment_calls.values()))
    candidate = {
        "version": 1,
        "identity": identity,
        "action_id": "original-action",
        "tool_request_digest": "c" * 64,
        "owner": {
            "version": 1,
            "pid": 123,
            "start": "original-birth",
            "deployment": "d" * 64,
            "invocation_id": "original-native",
        },
        "owner_stop_proof": {"original": "durable-proof"},
        "runner": {"original": "runner"},
        "namespace": proof["namespace"],
        "execution_epoch": state.epoch,
    }
    if fenced:
        call["fence_proof"] = {
            **copy.deepcopy(candidate),
            "process_present": False,
            "native_fenced": True,
        }
    runtime = Runtime(state.manifest)
    queries = []

    class Handle:
        async def query(self, name, request):
            assert name == "view" and request["scope"] == state.scope
            queries.append(request["kind"])
            if request["kind"] == "deployment_closure":
                return state_module.view(state)
            assert request == {
                "scope": state.scope,
                "kind": "deployment_coding_call_candidate",
                "identity": identity,
            }
            return copy.deepcopy(candidate)

    async def namespace(request):
        assert request.namespace == proof["namespace"]["name"]
        return SimpleNamespace(namespace_info=SimpleNamespace(id=proof["namespace"]["id"]))

    # Keep the SDK handle's two distinct workflow-id and run-id arguments.
    def get_workflow_handle(workflow_id, **options):
        assert workflow_id == state.run_id and options == {"run_id": state.epoch}
        return Handle()

    client = SimpleNamespace(
        namespace=proof["namespace"]["name"],
        get_workflow_handle=get_workflow_handle,
        workflow_service=SimpleNamespace(describe_namespace=namespace),
    )
    return runtime, client, state, proof, call, candidate, queries


@pytest.mark.parametrize("composition", [False, True])
@pytest.mark.parametrize("fenced", [False, True])
def test_native_and_composition_session_closure_accept_original_call_shape(composition, fenced):
    runtime, client, state, proof, call, _, queries = environment(
        composition=composition, fenced=fenced
    )
    assert "fence_proof" in call
    before = copy.deepcopy(vars(state))
    result = asyncio.run(release._closure(runtime, client, None, proof))
    assert result["ready"] is True and result["reasons"] == [] and result["seal"] is None
    assert result["deployment"]["admission"]["version"] == 2
    assert result["deployment"]["admission"]["session_origin"]["turn_id"]
    assert queries == ["deployment_closure"] + (
        ["deployment_coding_call_candidate"] if fenced else []
    )
    assert vars(state) == before


@pytest.mark.parametrize("fault", ["missing", "identity", "candidate", "present", "unfenced"])
def test_session_coding_closure_rejects_missing_or_forged_fence(fault):
    runtime, client, _, proof, call, candidate, _ = environment(fenced=True)
    if fault == "missing":
        call.pop("fence_proof")
    elif fault == "identity":
        call["fence_proof"]["identity"]["request_digest"] = "e" * 64
    elif fault == "candidate":
        candidate["tool_request_digest"] = "e" * 64
    elif fault == "present":
        call["fence_proof"]["process_present"] = True
    else:
        call["fence_proof"]["native_fenced"] = False
    with pytest.raises((DefinitionMismatch, ValidationError)):
        asyncio.run(release._closure(runtime, client, None, proof))


def test_ordinary_session_closure_excludes_coding_fence_inventory():
    runtime, client, _, proof, call, _, queries = environment(ordinary=True)
    assert "fence_proof" not in call
    assert asyncio.run(release._closure(runtime, client, None, proof))["ready"] is True
    assert queries == ["deployment_closure"]
    call["fence_proof"] = None
    with pytest.raises((DefinitionMismatch, ValidationError)):
        asyncio.run(release._closure(runtime, client, None, proof))
