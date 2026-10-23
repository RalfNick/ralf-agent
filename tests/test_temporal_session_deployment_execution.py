"""Session SDK parent is distinct from the original business root ancestry."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent import temporal_deployment_execution as sdk
from relf_agent import temporal_deployment_execution_state as pure
from relf_agent.errors import DefinitionMismatch, ValidationError
from relf_agent.types import digest
from tests.test_temporal_session_deployment_dto import origin, reservation
from tests.test_temporal_session_deployment_state import session_state, submit_session


def original():
    session = session_state()
    submit_session(session)
    intent = session.deployment_turn().intent
    metadata = {
        "version": 2,
        "root": reservation(intent)["root_admission"],
        "lineage": [],
        "session_origin": origin(intent),
    }
    state = SimpleNamespace(
        scope=intent["scope"],
        run_id=intent["run_id"],
        epoch="business-epoch",
        request=intent["submission"]["request"],
        manifest=intent["submission"]["manifest"],
        receipts={intent["run_command_id"]: {"kind": "submit"}},
    )
    return intent, metadata, state


def initialize(state, metadata, parent=None):
    pure.initialize(
        state,
        metadata,
        namespace=metadata["root"]["namespace"]["name"],
        epoch=state.epoch,
        original_epoch=state.epoch,
        parent=parent,
    )


def coordinator(intent):
    return {
        "namespace": intent["namespace"]["name"],
        "workflow_id": intent["coordinator_id"],
        "run_id": intent["coordinator_execution_epoch"],
    }


def admit(state):
    metadata = state.deployment_admission
    root = {**metadata["root"], "state": "held-bound", "execution_epoch": "business-epoch"}
    result = {
        "version": 1,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "root": root,
        "metadata_digest": digest(metadata),
    }
    pure.adopt(state, {**result, "proof_digest": digest(result)})


def test_session_root_uses_original_sdk_coordinator_without_business_parent_edge():
    intent, metadata, state = original()
    initialize(state, metadata, coordinator(intent))
    admit(state)
    proof = pure.view(state)
    assert proof["admission"]["lineage"] == []
    assert proof["admission"]["session_origin"] == origin(intent)
    sdk._metadata(
        metadata,
        state.manifest["deployment_admission_protocol"]["policy"],
        scope=state.scope,
        run_id=state.run_id,
        command_id=intent["run_command_id"],
        request_digest=digest(state.request),
        manifest_digest=digest(state.manifest),
        manifest=state.manifest,
    )


@pytest.mark.parametrize(
    "damage",
    ["missing-parent", "reset-coordinator", "wrong-turn", "wrong-origin-epoch", "legacy-metadata"],
)
def test_session_root_rejects_unrelated_sdk_parent_or_origin(damage):
    intent, metadata, state = original()
    parent = coordinator(intent)
    if damage == "missing-parent":
        parent = None
    elif damage == "reset-coordinator":
        parent["run_id"] = "reset"
    elif damage == "wrong-turn":
        state.request["session_turn"]["turn_id"] = "other"
    elif damage == "wrong-origin-epoch":
        metadata["session_origin"]["coordinator_first_execution_epoch"] = "reset"
    else:
        metadata = {"version": 1, "root": metadata["root"], "lineage": []}
    with pytest.raises((DefinitionMismatch, ValidationError)):
        initialize(state, metadata, parent)
    assert not hasattr(state, "deployment_admission")


def test_business_child_inherits_origin_and_keeps_actual_business_parent():
    intent, metadata, parent = original()
    parent.request["definition"]["kind"] = "graph"
    metadata["root"]["request_digest"] = digest(parent.request)
    root = metadata["root"]
    root["proof_digest"] = digest(
        {k: v for k, v in root.items() if k not in {"proof_digest", "state", "execution_epoch"}}
    )
    initialize(parent, metadata, coordinator(intent))
    admit(parent)
    child_request = {
        "definition": {"kind": "agent"},
        "input": "child",
        "session_history": [],
        "session_observer": {"coordinator_id": intent["coordinator_id"]},
    }
    call = {
        "id": "original-call",
        "run_id": "original-child",
        "command_id": "child-command",
        "request": child_request,
    }
    parent.children = [call]
    projected = pure.project_child(parent, call)
    assert projected["version"] == 2 and projected["session_origin"] == origin(intent)
    assert len(projected["lineage"]) == 1
    child = SimpleNamespace(
        scope=parent.scope,
        run_id=call["run_id"],
        epoch="child-epoch",
        request=child_request,
        manifest=parent.manifest,
        receipts={call["command_id"]: {"kind": "submit"}},
    )
    initialize(
        child,
        projected,
        {
            "namespace": intent["namespace"]["name"],
            "workflow_id": parent.run_id,
            "run_id": parent.epoch,
        },
    )
    assert child.deployment_sdk_parent["workflow_id"] == parent.run_id
    with pytest.raises(DefinitionMismatch):
        initialize(child, projected, coordinator(intent))


def test_sdk_start_binding_reads_exact_original_session_root_and_rechecks_origin(monkeypatch):
    from relf_agent import temporal_session_deployment_verification as verification

    intent, metadata, state = original()
    initialize(state, metadata, coordinator(intent))
    proof = pure.view(state)
    saved = {
        "reservation": reservation(intent),
        "submission": intent["submission"],
        "run_receipt": None,
        "execution_epoch": None,
        "intent": intent,
        "session_origin": origin(intent),
    }
    verified = []

    async def check(runtime, client, value, session_origin):
        assert value == intent and session_origin == origin(intent)
        verified.append(True)
        return {"intent": copy.deepcopy(value), "session_origin": copy.deepcopy(session_origin)}

    monkeypatch.setattr(verification, "validate_session_origin", check)

    class Handle:
        async def query(self, name, request):
            if request["kind"] == "deployment_session_root":
                return copy.deepcopy(saved)
            assert request["kind"] == "deployment_start"
            return {
                "scope": proof["scope"],
                "run_id": proof["run_id"],
                "execution_epoch": proof["execution_epoch"],
                "activity_timeout": intent["submission"]["activity_timeout"],
                "task_queue": intent["submission"]["task_queue"],
                "request_digest": proof["request_digest"],
                "manifest_digest": proof["manifest_digest"],
            }

    async def namespace(client, expected):
        assert expected == intent["namespace"]

    monkeypatch.setattr(sdk, "_namespace", namespace)
    client = SimpleNamespace(get_workflow_handle=lambda *args, **kwargs: Handle())
    runtime = SimpleNamespace(validate_release=lambda value: None)
    description = SimpleNamespace(task_queue=intent["submission"]["task_queue"])
    asyncio.run(
        sdk._public_start_binding(
            client,
            state.manifest["deployment_admission_protocol"]["policy"],
            proof,
            description,
            runtime=runtime,
        )
    )
    assert len(verified) >= 2
    saved["session_origin"]["coordinator_execution_epoch"] = "reset"
    with pytest.raises(DefinitionMismatch):
        asyncio.run(
            sdk._public_start_binding(
                client,
                state.manifest["deployment_admission_protocol"]["policy"],
                proof,
                description,
                runtime=runtime,
            )
        )
