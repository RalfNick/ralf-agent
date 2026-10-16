"""Bounded manual evidence is tied to original admitted ordinary Tool Actions."""

import copy

import pytest

import ralf_agent as r
from ralf_agent.errors import RalfError
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_state import TOOL_ACTIVITY, TemporalRunState
from ralf_agent.types import digest, submission_request
from tests.test_temporal_deployment_public_registry import NAMESPACE, POLICY, SCOPE, Provider
from tests.test_temporal_recovery_capacity import control, full_registry
from tests.test_temporal_tool_execution import admission


def original_action(*, owned=True):
    from ralf_agent import temporal_deployment_execution_state as deployment
    from ralf_agent import temporal_deployment_release_state as calls
    from ralf_agent.temporal_deployment_admission import root_run_id
    from tests.test_temporal_deployment_execution_state import metadata, response
    from tests.test_temporal_engine import JournalContractFixture

    tools = r.ToolRegistry()
    tools.register(
        r.ToolSpec("write", "write", {"type": "object"}, cost=0, effect="unqueryable_write"),
        lambda arguments, context: pytest.fail("proof must never invoke a Tool"),
    )
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=tools,
        admission_policy=POLICY,
        **({"tool_execution": r.ToolExecutionOwner(version="manual-1")} if owned else {}),
        journal=JournalContractFixture(),
    )
    state = TemporalRunState(
        root_run_id(POLICY.deployment_id, SCOPE, "root-command"),
        SCOPE,
        "root-command",
        submission_request(r.AgentSpec("writer", "write", tools=("write",)), "task", budget=8),
        runtime.manifest,
        execution_epoch="root-epoch",
    )
    # Use the genuine original metadata algorithm with this test's namespace.
    value = metadata(state)
    value["root"].update(namespace=NAMESPACE, scope=SCOPE)
    core = {
        k: v
        for k, v in value["root"].items()
        if k not in {"proof_digest", "state", "execution_epoch"}
    }
    value["root"]["proof_digest"] = digest(core)
    deployment.initialize(
        state,
        value,
        namespace=NAMESPACE["name"],
        epoch=state.epoch,
        original_epoch=state.epoch,
        parent=None,
    )
    deployment.adopt(state, response(state, value))
    calls.initialize(state)
    model, _ = state.next_operation()
    state.accept_model(
        model["id"],
        {
            "ok": True,
            "output": None,
            "tool_calls": [{"name": "write", "arguments": {}, "call_id": "c"}],
            "usage": None,
        },
    )
    action, request = state.next_operation()
    if owned:
        state.admit_tool_dispatch(admission(request))
    identity = {
        "version": 1,
        "scope": SCOPE,
        "run_id": state.run_id,
        "execution_epoch": state.epoch,
        "activity_id": action["attempts"][0]["id"],
        "activity_name": TOOL_ACTIVITY,
        "attempt": 1,
        "invocation_id": "b" * 32,
        "request_digest": digest({"scope": SCOPE, "_deployment_activity_request": request}),
        "manifest_digest": digest(state.manifest),
    }
    calls.begin_activity(state, identity)
    state.operation_unknown(action["id"], "receipt-lost")
    payload = {
        "kind": "reconcile",
        "scope": SCOPE,
        "action_id": action["id"],
        "query": False,
        "result": {"committed": True},
    }
    return state, action, payload


@pytest.mark.parametrize("owned", [False, True])
def test_original_zero_cost_unknown_action_proof_is_pure_and_does_not_imply_stop(owned):
    from ralf_agent.temporal_manual_recovery import action_proof

    state, action, payload = original_action(owned=owned)
    before = copy.deepcopy(vars(state))
    proof = action_proof(state, payload)
    assert proof["action_id"] == action["id"] and proof["execution_epoch"] == state.epoch
    assert proof["proof_digest"] == digest({k: v for k, v in proof.items() if k != "proof_digest"})
    assert vars(state) == before
    if owned:
        assert state.tool_executions[action["id"]]["execution_stopped"] is False
    assert not next(iter(state.deployment_calls.values()))["stopped"]


@pytest.mark.parametrize(
    "fault",
    [
        "grant",
        "tool-request",
        "call",
        "call-request",
        "invocation",
        "seal",
        "native",
        "known",
        "payload",
    ],
)
def test_manual_proof_rejects_unproven_or_settled_action_without_mutation(fault):
    from ralf_agent.temporal_manual_recovery import action_proof

    state, action, payload = original_action()
    owner = state.tool_executions[action["id"]]
    call = next(iter(state.deployment_calls.values()))
    if fault == "grant":
        owner["grant_allowed"] = False
    elif fault == "tool-request":
        owner["request_digest"] = "a" * 64
    elif fault == "call":
        state.deployment_calls.clear()
    elif fault == "call-request":
        call["identity"]["request_digest"] = "a" * 64
    elif fault == "invocation":
        owner["invocation_id"] = "not-an-invocation"
    elif fault == "seal":
        state.deployment_seal = {"sealed": True}
    elif fault == "native":
        action["delegated_execution"] = {}
    elif fault == "known":
        state.accept_tool(action["id"], {"ok": True, "result": "old"}, reconciled=True)
    elif fault == "payload":
        payload["query"] = True
    before = copy.deepcopy(vars(state))
    with pytest.raises(RalfError):
        action_proof(state, payload)
    assert vars(state) == before


def manual_request(original, *, target=None, action_id="original-action", command_id="manual"):
    payload = {
        "kind": "reconcile",
        "scope": SCOPE,
        "action_id": action_id,
        "query": False,
        "result": {"committed": True},
    }
    return {
        **control(original, "reconcile", command_id),
        "target": target or original["target"],
        "payload_digest": digest(payload),
        "recovery": {
            "root_command_id": original["command_id"],
            "execution_epoch": "original-root-epoch" if target is None else "child-epoch",
            "payload": payload,
        },
    }


def verified(prepared):
    root, request = prepared["root"], prepared["request"]
    proof = {
        "version": 1,
        "scope": SCOPE,
        "run_id": request["target"],
        "execution_epoch": prepared["target_execution_epoch"],
        "manifest_digest": root["manifest_digest"],
        "action_id": prepared["manual_payload"]["action_id"],
        "action_digest": "a" * 64,
        "tool_request_digest": "b" * 64,
        "call_digest": "c" * 64,
    }
    return {
        "binding": {
            "version": 2 if request["target"] == root["run_id"] else 1,
            "scope": SCOPE,
            "namespace": NAMESPACE,
            "target": request["target"],
            "target_execution_epoch": prepared["target_execution_epoch"],
            "root_run_id": root["run_id"],
            "root_execution_epoch": root["execution_epoch"],
        },
        "action": {**proof, "proof_digest": digest(proof)},
    }


@pytest.mark.parametrize("version", [2, 3, 4])
@pytest.mark.parametrize("target", [None, "original-child"])
def test_full_registry_preserves_one_verified_slot_per_original_action(version, target):
    state, original = full_registry(version)
    request = manual_request(original, target=target)
    with pytest.raises(RalfError):
        state.reserve(request)  # no synchronous proof bypass
    prepared = state.prepare_deployment_control(request)
    first = state.commit_deployment_control(request, verified(prepared))
    assert len(state.deployment.commands) == 2
    assert state.prepare_deployment_control(request) == {"receipt": first}
    assert state.reserve(request) == first
    fresh = copy.deepcopy(request)
    fresh["command_id"] = "another-id"
    with pytest.raises(RalfError):
        state.prepare_deployment_control(fresh)
    changed = copy.deepcopy(request)
    changed["recovery"]["payload"]["result"] = "different"
    changed["payload_digest"] = digest(changed["recovery"]["payload"])
    with pytest.raises(RalfError):
        state.prepare_deployment_control(changed)
    assert len(state.deployment.commands) == 2


def test_registry_rechecks_held_root_after_verification_await():
    state, original = full_registry()
    request = manual_request(original)
    proof = verified(state.prepare_deployment_control(request))
    state.deployment.roots.clear()
    with pytest.raises(RalfError):
        state.commit_deployment_control(request, proof)
    assert len(state.deployment.commands) == 1


@pytest.mark.parametrize("reset", [False, True])
def test_public_two_manual_query_checks_original_sdk_epoch(monkeypatch, reset):
    from types import SimpleNamespace

    from ralf_agent.temporal_manual_recovery import action_proof
    from ralf_agent.temporal_workflow import TemporalRunWorkflow, workflow

    state, _, payload = original_action()
    node = TemporalRunWorkflow.__new__(TemporalRunWorkflow)
    node.state = state
    monkeypatch.setattr(
        workflow,
        "info",
        lambda: SimpleNamespace(
            workflow_id=state.run_id,
            namespace=NAMESPACE["name"],
            run_id=state.epoch,
            first_execution_run_id="pre-reset" if reset else state.epoch,
            original_execution_run_id=state.epoch,
        ),
    )
    result = node.view({"kind": "deployment_manual_recovery", "scope": SCOPE, "payload": payload})
    assert result == ({"error": "definition_mismatch"} if reset else action_proof(state, payload))


@pytest.mark.parametrize("target_root", [False, True])
def test_sdk_manual_fallback_preserves_normal_admission_and_duplicate_before_target(target_root):
    import asyncio
    from dataclasses import asdict

    from ralf_agent import temporal_deployment_submissions as transport
    from tests.test_temporal_deployment_control_transport import Handle, environment

    async def run():
        engine, child, root = await environment()
        client = engine.client
        target = root.run_id if target_root else child
        scope = asdict(engine.scope)
        payload = {
            "kind": "reconcile",
            "scope": scope,
            "action_id": "original-action",
            "query": False,
            "result": "genuine",
        }
        # Normal capacity remains the existing path, including default releases
        # without ToolExecutionOwner and original completed/late evidence.
        assert "tool_execution_protocol" not in engine.release
        await transport.guard(engine, "reconcile", "normal", target, payload)
        assert not any("recovery" in call[-1] for call in client.calls if call[0] == "update")
        client.registry.state.capacity = len(client.registry.state.commands)

        class RecoveryHandle(Handle):
            async def execute_update(self, name, value, **options):
                if name == "reserve" and "recovery" in value:
                    prepared = client.registry.state.prepare_deployment_control(value)
                    binding = {
                        "version": 2 if target_root else 1,
                        "scope": scope,
                        "namespace": prepared["root"]["namespace"],
                        "target": target,
                        "target_execution_epoch": prepared["target_execution_epoch"],
                        "root_run_id": root.run_id,
                        "root_execution_epoch": prepared["root"]["execution_epoch"],
                    }
                    proof = {
                        "version": 1,
                        "scope": scope,
                        "run_id": target,
                        "execution_epoch": binding["target_execution_epoch"],
                        "manifest_digest": prepared["root"]["manifest_digest"],
                        "action_id": payload["action_id"],
                        "action_digest": "a" * 64,
                        "tool_request_digest": "b" * 64,
                        "call_digest": "c" * 64,
                    }
                    return client.registry.state.commit_deployment_control(
                        value,
                        {"binding": binding, "action": {**proof, "proof_digest": digest(proof)}},
                    )
                return await super().execute_update(name, value, **options)

        client.get_workflow_handle = lambda identity, **options: RecoveryHandle(
            client, identity, options.get("run_id")
        )
        binding = await transport.guard(engine, "reconcile", "protected", target, payload)
        assert binding["version"] == (2 if target_root else 1)
        del client.runs[target]
        assert await transport.guard(engine, "reconcile", "protected", target, payload) == binding
        assert len(client.registry.state.manual_recoveries) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    ["timeout", "cancelled", "authorization_denied", "definition_mismatch", "idempotency_conflict"],
)
def test_sdk_uncertain_or_identity_refusal_never_retries_with_manual_allowance(monkeypatch, fault):
    import asyncio
    from dataclasses import asdict

    from ralf_agent import temporal_deployment_submissions as transport
    from ralf_agent.errors import AuthorizationDenied, DefinitionMismatch, IdempotencyConflict
    from tests.test_temporal_deployment_control_transport import environment

    async def run():
        engine, _, root = await environment()
        errors = {
            "timeout": TimeoutError,
            "cancelled": asyncio.CancelledError,
            "authorization_denied": AuthorizationDenied,
            "definition_mismatch": DefinitionMismatch,
            "idempotency_conflict": IdempotencyConflict,
        }
        calls = []

        async def refused(handle, name, request):
            calls.append(request)
            raise errors[fault]("original refusal")

        monkeypatch.setattr(transport, "_update", refused)
        with pytest.raises(errors[fault]):
            await transport.guard(
                engine,
                "reconcile",
                "manual",
                root.run_id,
                {
                    "kind": "reconcile",
                    "scope": asdict(engine.scope),
                    "action_id": "original",
                    "query": False,
                    "result": "genuine",
                },
            )
        assert len(calls) == 1 and "recovery" not in calls[0]

    asyncio.run(run())


def test_real_receipt_between_proof_and_manual_adoption_is_not_overwritten():
    from ralf_agent.temporal_manual_recovery import action_proof

    state, action, payload = original_action()
    action_proof(state, payload)
    state.accept_tool(action["id"], {"ok": True, "result": "real receipt"}, reconciled=True)
    original = copy.deepcopy(action["result"])
    state.command("operator-late", payload)
    assert action["result"] == original
    assert any(event["kind"] == "late_effect_evidence" for event in state.event_log)


def test_only_first_verified_manual_command_wins_racing_action_slot():
    state, original = full_registry()
    first = manual_request(original, command_id="first")
    second = manual_request(original, command_id="second")
    proof = verified(state.prepare_deployment_control(first))
    state.commit_deployment_control(second, verified(state.prepare_deployment_control(second)))
    with pytest.raises(RalfError):
        state.commit_deployment_control(first, proof)
    assert len(state.deployment.commands) == 2 and len(state.deployment.manual_recoveries) == 1
