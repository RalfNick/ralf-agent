"""Compact control carrier preserves the original validator evidence."""

import asyncio
import copy
import importlib
from types import SimpleNamespace

import pytest

from relf_agent.errors import DefinitionMismatch
from relf_agent.types import canonical, digest


def transport():
    name = "relf_agent.temporal_deployment_control_transport"
    assert importlib.util.find_spec(name), "Missing selected3 compact control transport"
    return importlib.import_module(name)


def setup():
    from tests.test_temporal_deployment_control_projection import add_child, original

    state = original(parent=True)
    call = add_child(state)
    manifest, scope, request = state.manifest, state.scope, call["request"]
    namespace = state.composition_namespace
    proof = {
        "version": 1,
        "scope": scope,
        "run_id": call["run_id"],
        "execution_epoch": "child-epoch",
        "original_execution_epoch": "child-epoch",
        "namespace": namespace,
        "request": request,
        "request_digest": digest(request),
        "manifest": manifest,
        "release_digest": "a" * 64,
        "revision": 2,
        "state": "running",
        "physical_stopped": False,
        "action_stops": [],
    }
    proof["proof_digest"] = digest(proof)
    value = {
        "scope": scope,
        "manifest": manifest,
        "release_digest": "a" * 64,
        "snapshot": {
            "run_id": call["run_id"],
            "actions": [
                {
                    "delegated_execution": {
                        "tool_request": {
                            "runtime_manifest": manifest,
                            "arguments": {"manifest": "literal"},
                        }
                    }
                }
            ],
        },
        "budget": {"spent": 0},
        "workflow": {
            "backend": "temporal-parent",
            "planning_revision": 4,
            "quiescent": False,
            "remote_stop_confirmed": False,
            "unknown_remote_execution": True,
            "evidence_ack_pending": False,
            "reconciliation_pending": True,
            "children": [{"old_snapshot": "x" * 100000}],
        },
        "native_history_bundle": [{"retained": "episode"}],
        "input_requests": {"retained": "input"},
        "planning_input_sources": {},
        "coding_composition_proof": proof,
    }
    return state, call, value


def test_request_contains_only_original_identity_and_no_snapshot_or_manifest():
    state, call, _ = setup()
    before = copy.deepcopy(call)
    value = transport().request(state, call, "observe")
    assert set(value) == transport().REQUEST_FIELDS
    assert value["child_execution_epoch"] == "child-epoch"
    assert value["manifest_digest"] == digest(state.manifest)
    assert len(canonical(value)) < 1500 and call == before


def test_observation_expands_exact_physical_proof_and_native_snapshot():
    state, call, original = setup()
    before = copy.deepcopy(original)
    encoded = transport().pack_response(state, call, original)
    assert len(canonical(encoded)) < len(canonical(original)) / 10
    restored = transport().expand_response(state, call, {"ok": True, "result": encoded})
    value = restored["result"]
    assert value["coding_composition_proof"] == original["coding_composition_proof"]
    assert value["snapshot"] == original["snapshot"]
    assert value["manifest"] == state.manifest
    assert value["workflow"]["planning_revision"] == 4
    for field in ("input_requests", "planning_input_sources", "native_history_bundle"):
        assert value[field] == original[field]
    assert "children" not in value["workflow"]
    assert original == before


@pytest.mark.parametrize(
    "fault", ["scope", "epoch", "intent", "manifest", "request", "proof", "path"]
)
def test_changed_binding_reference_or_evidence_refuses_before_adoption(fault):
    state, call, original = setup()
    encoded = transport().pack_response(state, call, original)
    if fault == "scope":
        encoded["binding"]["scope"]["principal"] = "other"
    elif fault == "epoch":
        encoded["binding"]["child_execution_epoch"] = "reset"
    elif fault == "intent":
        encoded["binding"]["child_intent_digest"] = "b" * 64
    elif fault == "manifest":
        encoded["physical_proof"]["manifest_ref"] = "b" * 64
    elif fault == "request":
        encoded["physical_proof"]["request_ref"] = "b" * 64
    elif fault == "proof":
        encoded["physical_proof"]["state"] = "succeeded"
    else:
        encoded["observation"]["snapshot_manifest_refs"][0]["path"] = ["result"]
    with pytest.raises(DefinitionMismatch):
        transport().expand_response(state, call, {"ok": True, "result": encoded})


def test_failure_and_non_observe_receipts_keep_original_shape():
    state, call, _ = setup()
    for response in (
        {"ok": False, "code": "unknown"},
        {"ok": True, "result": {"registered": True}},
    ):
        assert transport().expand_response(state, call, response) == response


@pytest.mark.parametrize(
    "actions",
    [
        None,
        [None],
        "bad",
        {"bad": {}},
        [{"delegated_execution": []}],
        [{"delegated_execution": {"tool_request": None}}],
    ],
)
def test_malformed_snapshot_returns_typed_refusal_instead_of_workflow_task_failure(actions):
    state, call, original = setup()
    encoded = transport().pack_response(state, call, original)
    encoded["observation"]["snapshot"]["actions"] = copy.deepcopy(actions)
    encoded["observation"]["snapshot_manifest_refs"] = []
    with pytest.raises(DefinitionMismatch):
        transport().expand_response(state, call, {"ok": True, "result": encoded})
    original["snapshot"]["actions"] = copy.deepcopy(actions)
    with pytest.raises(DefinitionMismatch):
        transport().pack_response(state, call, original)


@pytest.mark.parametrize(
    "fault",
    [None, "target-reset", "parent-reset", "child-pin", "registry-close", "before-target-reset"],
)
def test_control_rechecks_original_ownership_after_await_without_repeating_command(
    monkeypatch, fault
):
    from relf_agent import temporal_deployment_coding_bridge as bridge
    from relf_agent import temporal_deployment_coding_validation as validation
    from relf_agent import temporal_deployment_execution as execution
    from relf_agent import temporal_deployment_execution_state as deployment

    state, call, value = setup()
    mode = "register" if fault == "registry-close" else "observe"
    request = transport().request(state, call, mode)
    steps = []
    closed = False

    class Validator:
        def __init__(self, *args):
            pass

        async def validate(self):
            steps.append("fresh")
            if fault == "parent-reset" and "control" in steps:
                raise DefinitionMismatch("original parent replaced")

        async def permission(self):
            steps.append("permission")
            return not closed

        def _description(self, descriptor, expected):
            steps.append("actual-child")
            if descriptor.run_id != expected["run_id"]:
                raise DefinitionMismatch("original child replaced")

    async def original_proof(*args, **kwargs):
        return deployment.view(state)

    async def control(*args):
        nonlocal closed
        steps.append("control")
        await asyncio.sleep(0)
        if fault == "child-pin":
            call["deployment_execution_epoch"] = "reset-epoch"
        if fault == "registry-close":
            closed = True
        return {"registered": True} if mode == "register" else copy.deepcopy(value)

    async def namespace(*args):
        pass

    class Handle:
        async def describe(self):
            return SimpleNamespace(
                run_id="reset-epoch"
                if fault == "before-target-reset"
                or (fault == "target-reset" and "control" in steps)
                else "child-epoch"
            )

    monkeypatch.setattr(validation, "CodingValidation", Validator)
    monkeypatch.setattr(execution, "validate_activity", original_proof)
    monkeypatch.setattr(execution, "_proof", original_proof)
    monkeypatch.setattr(execution, "_policy", lambda runtime: {})
    monkeypatch.setattr(execution, "_actual", lambda *a, **k: None)
    monkeypatch.setattr(execution, "_namespace", namespace)
    monkeypatch.setattr(bridge, "control", control)
    runtime = SimpleNamespace(validate_release=lambda manifest: None)
    client = SimpleNamespace(get_workflow_handle=lambda *a, **k: Handle())
    info = SimpleNamespace(task_queue=state.deployment_task_queue)

    async def run():
        if fault is not None:
            with pytest.raises(DefinitionMismatch):
                await transport().execute(runtime, client, request, info)
        else:
            result = await transport().execute(runtime, client, request, info)
            restored = transport().expand_response(state, call, {"ok": True, "result": result})
            assert restored["result"]["snapshot"] == value["snapshot"]
            assert steps == ["fresh", "actual-child", "fresh", "control", "actual-child", "fresh"]
        assert steps.count("control") == (0 if fault == "before-target-reset" else 1)

    asyncio.run(run())
