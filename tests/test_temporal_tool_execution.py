"""Original History independently adopts actual Tool end and effect evidence."""

import copy
from dataclasses import asdict

import pytest

import relf_agent as r
from relf_agent.errors import RalfError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_state import TemporalRunState, validate_manifest
from relf_agent.types import digest, submission_request

from .test_temporal_engine import Provider, registry


def state_for(*, enabled=True):
    options = {"tool_execution": r.ToolExecutionOwner(version="1")} if enabled else {}
    runtime = TemporalRuntime(providers={"default": Provider()}, tools=registry(), **options)
    state = TemporalRunState(
        "run",
        asdict(r.Scope()),
        "submit",
        submission_request(r.AgentSpec("reader", "Read", tools=("read",)), "task", budget=8),
        runtime.manifest,
        execution_epoch="original-epoch",
    )
    model, _ = state.next_operation()
    state.accept_model(
        model["id"],
        {
            "ok": True,
            "output": None,
            "tool_calls": [{"name": "read", "arguments": {}, "call_id": "c"}],
            "usage": None,
        },
    )
    action, request = state.next_operation()
    if enabled:
        state.admit_tool_dispatch(admission(request))
    return runtime, state, action, request


def proof(request, invocation_id="a" * 32):
    return {
        **{
            name: request[name]
            for name in ("scope", "action_id", "release_digest", "execution_epoch")
        },
        "request_digest": digest(request),
        "invocation_id": invocation_id,
    }


def admission(request, invocation_id="a" * 32):
    return {"run_id": request["run_id"], **proof(request, invocation_id)}


def test_explicit_published_owner_and_original_intent_admission():
    runtime, state, action, request = state_for()
    protocol = runtime.manifest["tool_execution_protocol"]
    assert protocol["version"] == 1 and set(protocol["implementation"]) == {
        "execute",
        "wait",
        "aclose",
    }
    assert state.admit_tool_dispatch(admission(request))["allowed"] is True
    assert state.tool_executions[action["id"]]["execution_stopped"] is False
    assert copy.deepcopy(state).admit_tool_dispatch(admission(request))["allowed"] is True


def test_tool_result_cannot_start_next_business_step_until_actual_end():
    _, state, action, request = state_for()
    state.admit_tool_dispatch(admission(request))
    state.accept_tool(action["id"], {"ok": True, "result": "read", "source": "handler"})
    assert state.next_operation() is None
    assert state.quiescent is False
    assert state.tool_execution_ended(proof(request)) == {
        "action_id": action["id"],
        "recorded": True,
    }
    assert state.next_operation()[0]["kind"] == "model"


@pytest.mark.parametrize("order", ["effect_first", "end_first"])
def test_cancelled_unknown_effect_and_actual_end_are_independent(order):
    _, state, action, request = state_for()
    state.admit_tool_dispatch(admission(request))
    state.command("cancel", {"kind": "cancel", "scope": asdict(r.Scope())})
    state.operation_unknown(action["id"], "lost-receipt")
    assert state.quiescent is False
    response = {"ok": True, "result": "genuine receipt", "source": "query"}
    if order == "effect_first":
        state.accept_tool(action["id"], response, reconciled=True)
        assert state.budget["unknown"] == 0 and state.quiescent is False
        state.tool_execution_ended(proof(request))
    else:
        state.tool_execution_ended(proof(request))
        assert state.budget["unknown"] == 1 and state.quiescent is False
        state.accept_tool(action["id"], response, reconciled=True)
    assert state.quiescent is True and state.state == "cancelled"
    assert state.next_operation() is None


@pytest.mark.parametrize(
    "field", ["scope", "action_id", "release_digest", "request_digest", "execution_epoch"]
)
def test_foreign_end_proof_never_changes_original_history(field):
    _, state, action, request = state_for()
    value = proof(request)
    value[field] = (
        {"workspace": "foreign", "principal": "foreign"} if field == "scope" else "foreign"
    )
    before = copy.deepcopy(state.tool_executions)
    with pytest.raises(RalfError):
        state.tool_execution_ended(value)
    assert (
        state.tool_executions == before
        and state.tool_executions[action["id"]]["execution_stopped"] is False
    )


def test_end_is_idempotent_and_prior_model_uncertainty_is_preserved():
    _, state, action, request = state_for()
    state.tool_executions[action["id"]]["prior_remote_uncertain"] = True
    first = state.tool_execution_ended(proof(request))
    count = len(state.event_log)
    assert state.tool_execution_ended(proof(request)) == first
    assert len(state.event_log) == count and state.remote_uncertain is True


def test_cancellation_before_admission_refuses_new_handler_and_accepts_true_end():
    _, state, action, request = state_for()
    state.command("cancel", {"kind": "cancel", "scope": asdict(r.Scope())})
    assert state.admit_tool_dispatch(admission(request))["allowed"] is True  # grant preceded cancel
    state.tool_execution_ended(proof(request))
    assert state.tool_executions[action["id"]]["execution_stopped"] is True


@pytest.mark.parametrize("version", [True, 0, 2, "1"])
def test_unsupported_protocol_refuses_before_execution(version):
    runtime, *_ = state_for()
    manifest = runtime.manifest
    manifest["tool_execution_protocol"]["version"] = version
    with pytest.raises(RalfError):
        validate_manifest(manifest)


def test_legacy_manifest_envelope_and_uncertainty_are_unchanged():
    runtime, state, action, request = state_for(enabled=False)
    assert "tool_execution_protocol" not in runtime.manifest and "release_digest" not in request
    assert not hasattr(state, "tool_executions") or state.tool_executions == {}
    state.operation_unknown(action["id"], "timeout")
    state.accept_tool(action["id"], {"ok": True, "result": "receipt"}, reconciled=True)
    assert state.remote_uncertain is True and state.quiescent is False


def test_new_binding_requires_tool_protocol_and_cannot_downgrade_marker():
    runtime, *_ = state_for(enabled=False)
    manifest = runtime.manifest
    manifest.update(kernel="temporal-3", binding_protocol=3, dispatch_admission="history-1")
    with pytest.raises(RalfError):
        validate_manifest(manifest)
    enabled_runtime, *_ = state_for()
    manifest = enabled_runtime.manifest
    manifest["binding_protocol"] = 1
    with pytest.raises(RalfError):
        validate_manifest(manifest)


def test_true_end_then_lost_response_preserves_effect_unknown_without_stop_unknown():
    _, state, action, request = state_for()
    state.admit_tool_dispatch(admission(request))
    state.tool_execution_ended(proof(request))
    state.command("cancel", {"kind": "cancel", "scope": asdict(r.Scope())})
    state.operation_unknown(action["id"], "receipt-lost-after-end")
    assert state.remote_uncertain is False and state.budget["unknown"] == 1
    state.accept_tool(action["id"], {"ok": True, "result": "receipt"}, reconciled=True)
    assert state.quiescent is True
    assert state.pending_acks[0]["release_digest"] == request["release_digest"]


def test_foreign_stage_uncertainty_after_tool_intent_cannot_be_cleared_by_tool_end():
    _, state, action, request = state_for()
    state.remote_uncertain = True
    state.tool_execution_ended(proof(request))
    assert state.remote_uncertain is True


def test_later_model_unknown_survives_repeated_end_of_previous_unknown_tool():
    _, state, action, request = state_for()
    state.operation_unknown(action["id"], "lost")
    state.tool_execution_ended(proof(request))
    state.accept_tool(action["id"], {"ok": True, "result": "receipt"}, reconciled=True)
    model, _ = state.next_operation()
    state.operation_unknown(model["id"], "model-lost")
    state.tool_execution_ended(proof(request))
    assert state.remote_uncertain is True


def test_missing_callbacks_refuse_before_any_actual_tool():
    import asyncio

    runtime, _, _, request = state_for()

    async def run():
        response = await runtime.execute_tool(request)
        assert response["ok"] is False and response["dispatched"] is False
        await runtime.close_context_execution()

    asyncio.run(run())
