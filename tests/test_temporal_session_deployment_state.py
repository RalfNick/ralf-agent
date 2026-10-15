"""Original Session intents survive admission uncertainty and independent ACK debt."""

import copy
import importlib

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.types import digest


def module():
    name = "ralf_agent.temporal_session_deployment_state"
    assert importlib.util.find_spec(name), "Original Session deployment lifecycle is missing"
    return importlib.import_module(name)


def fixture():
    # Reuse the reviewed DTO fixtures; they build a real ordinary published binding.
    from tests.test_temporal_session_deployment_dto import DEPLOYMENT, intent

    return module().TemporalSessionDeploymentState(intent(), deployment_id=DEPLOYMENT)


def registration(state, phase):
    from tests.test_temporal_session_deployment_dto import REGISTRY_EPOCH, start

    return {
        "start": start(state.intent, phase),
        "registry_execution_epoch": REGISTRY_EPOCH,
        "execution_epoch": "original-business-epoch" if phase == "started" else None,
    }


def test_lifecycle_implementation_exists():
    assert module()


def test_reserve_reply_loss_retains_intent_and_requires_same_identity():
    state = fixture()
    frozen = copy.deepcopy(state.intent)
    assert state.view()["phase"] == "intent-accepted"
    state.reserve_issued()
    assert state.view()["phase"] == "reserve-unknown"
    state.adopt_registration(registration(state, "held-unbound"))
    assert state.view()["phase"] == "held-unbound"
    assert state.intent == frozen
    changed = registration(state, "held-unbound")
    changed["start"]["intent"]["submission"]["task_queue"] = "moved"
    with pytest.raises(DefinitionMismatch):
        state.adopt_registration(changed)
    assert state.intent == frozen


def test_capacity_is_positive_only_and_start_is_durable_before_sdk_call():
    state = fixture()
    state.reserve_issued()
    state.record_error("session_control_unavailable")
    assert state.view()["phase"] == "reserve-unknown"
    state.adopt_registration(registration(state, "capacity-deferred"))
    assert state.view()["phase"] == "capacity-deferred"
    assert state.retry() is True
    state.reserve_issued()
    state.adopt_registration(registration(state, "held-unbound"))
    assert state.issue_start() is True
    assert state.lifecycle()["start_issued"] is True
    assert state.view()["phase"] == "start-uncertain"
    assert state.issue_start() is False
    with pytest.raises(DefinitionMismatch):
        state.install_refusal_barrier("definition_mismatch")
    state.record_error("session_control_unavailable")
    assert state.view()["phase"] == "start-uncertain"
    state.adopt_registration(registration(state, "started"))
    assert state.view()["phase"] == "started"
    assert state.view()["execution_epoch"] == "original-business-epoch"


def test_refusal_requires_barrier_before_claim_and_is_stable_after_retry():
    state = fixture()
    result = registration(state, "start-refused")
    with pytest.raises(DefinitionMismatch):
        state.adopt_registration(result)
    barrier = state.install_refusal_barrier("definition_mismatch")
    result["start"]["start_refusal"]["start_barrier_digest"] = barrier["barrier_digest"]
    proof = result["start"]["start_refusal"]
    proof["proof_digest"] = digest({k: v for k, v in proof.items() if k != "proof_digest"})
    state.adopt_registration(result)
    first = state.view()
    assert state.retry() is False
    assert state.view() == first
    assert state.issue_start() is False
    with pytest.raises(DefinitionMismatch):
        state.adopt_registration(registration(state, "held-unbound"))


def test_claimed_intent_cannot_be_downgraded_by_capacity_or_refusal():
    state = fixture()
    state.adopt_registration(registration(state, "held-unbound"))
    for phase in ("capacity-deferred", "reserve-unknown", "start-refused"):
        with pytest.raises(DefinitionMismatch):
            state.adopt_registration(registration(state, phase))
    assert state.view()["phase"] == "held-unbound"


def test_separate_session_ledger_requires_original_end_and_no_replacement_owner():
    from tests.test_temporal_session_deployment_dto import call

    state = fixture()
    state.adopt_registration(registration(state, "started"))
    request = state.control_request("observe")
    identity = call(state.intent)
    identity["request_digest"] = digest(request)
    assert state.begin_call(identity)["allowed"] is True
    replacement = copy.deepcopy(identity)
    replacement["invocation_id"] = "replacement"
    with pytest.raises(DefinitionMismatch):
        state.begin_call(replacement)
    result = {
        "ok": True,
        "result": {
            "advance": None,
            "registry_execution_epoch": "original-registry-epoch",
            "execution_epoch": "original-business-epoch",
        },
    }
    end = {
        "body_result": result,
        "identity": identity,
        "body_result_digest": digest(result),
        "body_stopped": True,
    }
    ack = state.end_call(end)
    assert ack["recorded"] is True
    assert state.end_call(end) == ack
    assert state.call_ended(ack, result) is True
    with pytest.raises(DefinitionMismatch):
        state.call_ended(ack, {**result, "advance": {}})
    assert state.view()["phase"] == "started"


def advance(state):
    from ralf_agent.temporal_state import TemporalRunState
    from tests.test_temporal_session_deployment_dto import origin, reservation

    intent = state.intent
    run = TemporalRunState(
        intent["run_id"],
        intent["scope"],
        intent["run_command_id"],
        intent["submission"]["request"],
        intent["submission"]["manifest"],
    )
    action, _ = run.next_operation()
    run.accept_model(action["id"], {"ok": True, "output": "answer", "tool_calls": [], "usage": {}})
    run_proof = {"scope": intent["scope"], "request": run.request, **run.diagnostics()}
    root = reservation(intent)["root_admission"]
    bound = {**root, "state": "held-bound", "execution_epoch": "original-business-epoch"}
    metadata = {"version": 2, "root": root, "lineage": [], "session_origin": origin(intent)}
    deployment = {
        "version": 1,
        "scope": intent["scope"],
        "run_id": intent["run_id"],
        "command_id": intent["run_command_id"],
        "execution_epoch": "original-business-epoch",
        "original_execution_epoch": "original-business-epoch",
        "namespace": intent["namespace"],
        "request": intent["submission"]["request"],
        "request_digest": digest(intent["submission"]["request"]),
        "manifest": intent["submission"]["manifest"],
        "manifest_digest": digest(intent["submission"]["manifest"]),
        "admission": metadata,
        "admission_receipt": {"root": bound},
        "children": [],
    }
    deployment["proof_digest"] = digest(deployment)
    seal = {
        "version": 1,
        **{
            k: deployment[k]
            for k in (
                "scope",
                "run_id",
                "command_id",
                "namespace",
                "execution_epoch",
                "original_execution_epoch",
                "request_digest",
                "manifest_digest",
            )
        },
        "admission_digest": digest(metadata),
        "receipt_digest": digest(deployment["admission_receipt"]),
        "terminal_state": "succeeded",
        "closure_digest": "a" * 64,
        "children": [],
    }
    seal["proof_digest"] = digest(seal)
    return {
        "version": 1,
        "intent_digest": intent["intent_digest"],
        "run_proof": run_proof,
        "descendants": [],
        "closure": {
            "version": 1,
            "deployment": deployment,
            "ready": True,
            "reasons": [],
            "calls": {},
            "seal": seal,
        },
        "retirement": {"root": bound, "certificate": seal, "released": True},
    }


def ended_observation(state, result):
    from tests.test_temporal_session_deployment_dto import call

    identity = call(state.intent)
    identity["request_digest"] = digest(state.control_request("observe"))
    state.begin_call(identity)
    body = {
        "ok": True,
        "result": {
            "advance": result,
            "registry_execution_epoch": "original-registry-epoch",
            "execution_epoch": "original-business-epoch",
        },
    }
    ack = state.end_call(
        {
            "body_result": body,
            "identity": identity,
            "body_result_digest": digest(body),
            "body_stopped": True,
        }
    )
    return body, ack


def test_positive_retirement_and_original_observer_end_are_both_required():
    state = fixture()
    state.adopt_registration(registration(state, "started"))
    proof = advance(state)
    body, ack = ended_observation(state, proof)
    assert state.validate_observation(body, ack) == {**proof["run_proof"], "descendants": []}
    for mutation in (
        "quiet-not-retired",
        "wrong-seal",
        "unended-business",
        "wrong-intent",
        "wrong-root-epoch",
        "wrong-children",
    ):
        damaged = copy.deepcopy(proof)
        if mutation == "quiet-not-retired":
            damaged["retirement"] = None
        elif mutation == "wrong-seal":
            damaged["retirement"]["certificate"]["proof_digest"] = "b" * 64
        elif mutation == "unended-business":
            damaged["closure"]["calls"]["active"] = {
                "identity": {},
                "allowed": True,
                "stopped": False,
                "end_proof": None,
            }
        elif mutation == "wrong-children":
            seal = damaged["closure"]["seal"]
            seal["children"] = [{"foreign": "child"}]
            seal["proof_digest"] = digest({k: v for k, v in seal.items() if k != "proof_digest"})
        elif mutation == "wrong-intent":
            damaged["intent_digest"] = "c" * 64
        else:
            damaged["retirement"]["root"]["execution_epoch"] = "replacement"
        # A new real original ACK is needed for each different body, not a fabricated return ACK.
        other = fixture()
        other.adopt_registration(registration(other, "started"))
        with pytest.raises((DefinitionMismatch, ValidationError)):
            changed_body, changed_ack = ended_observation(other, damaged)
            other.validate_observation(changed_body, changed_ack)
    lost = fixture()
    lost.adopt_registration(registration(lost, "started"))
    with pytest.raises(DefinitionMismatch):
        lost.validate_observation(body, ack)
    assert lost.view()["phase"] == "started"


def test_build_intent_preserves_first_envelope_and_deployment_run_identity():
    from tests.test_temporal_session_deployment_dto import DEPLOYMENT, intent

    value = intent()
    active = {
        "turn": {
            "turn_id": value["turn_id"],
            "turn_seq": 1,
            "session": value["session_ref"],
            "command_id": value["session_command_id"],
        },
        "run_id": value["run_id"],
        "command_id": value["run_command_id"],
        **{
            k: copy.deepcopy(value["submission"][k])
            for k in ("request", "manifest", "task_queue", "activity_timeout")
        },
    }
    built = module().build_intent(
        active,
        value["binding"],
        deployment_id=DEPLOYMENT,
        namespace=value["namespace"],
        coordinator_execution_epoch=value["coordinator_execution_epoch"],
    )
    assert built == value
    active["task_queue"] = "moved"
    assert built["submission"]["task_queue"] == "original-queue"


def session_state():
    from ralf_agent import temporal_deployment_protocol
    from ralf_agent.temporal_session_state import TemporalSessionState
    from tests.test_temporal_deployment_protocol import POLICY
    from tests.test_temporal_session_deployment_dto import NAMESPACE, intent

    value = intent()
    binding = copy.deepcopy(value["binding"])
    binding["manifest"] = temporal_deployment_protocol.publish(
        binding["manifest"],
        {**POLICY, "deployment_id": "original-deployment"},
        public=True,
        session_deployment=True,
    )
    accepted = {
        "scope": value["scope"],
        "namespace_id": NAMESPACE["id"],
        "session_namespace": None,
        "session_id": "chat",
        "command_id": "open",
        **binding,
    }
    return TemporalSessionState(
        accepted,
        deployment_context={
            "namespace": NAMESPACE,
            "coordinator_execution_epoch": value["coordinator_execution_epoch"],
        },
    )


def submit_session(state, command="session-submit-1"):
    return state.command(
        {
            "kind": "submit",
            "scope": state.scope,
            "command_id": command,
            "session_ref": state.ref.to_dict(),
            "input": {"task": [1, 2]},
            "budget": 7,
        }
    )


def selector(entry):
    return {name: entry.intent[name] for name in module().START_SELECTOR_FIELDS}


def test_existing_session_accepts_deployment_intent_before_any_reservation_and_keeps_legacy_ids():
    from ralf_agent.temporal_deployment_admission import root_run_id
    from tests.test_temporal_sessions import session, submit

    state = session_state()
    receipt = submit_session(state)
    entry = state.deployment_turn()
    assert entry.view()["phase"] == "intent-accepted"
    assert entry.intent["run_id"] == root_run_id(
        "original-deployment", state.scope, state.active["command_id"]
    )
    assert state.deployment_view(selector(entry)) == entry.view()
    assert state.deployment_command(selector(entry))["receipt"] == receipt
    assert state.active["started"] is False
    legacy, _ = session()
    submit(legacy)
    assert legacy.active["run_id"] == "ralf-temporal-" + digest(
        [legacy.scope, legacy.active["command_id"]]
    )
    with pytest.raises(DefinitionMismatch):
        state.mark_started()


def test_original_refusal_readback_survives_active_clear_rebind_and_next_turn():
    state = session_state()
    receipt = submit_session(state)
    entry = state.deployment_turn()
    selected = selector(entry)
    barrier = entry.install_refusal_barrier("definition_mismatch")
    result = registration(entry, "start-refused")
    refusal = result["start"]["start_refusal"]
    refusal["start_barrier_digest"] = barrier["barrier_digest"]
    refusal["proof_digest"] = digest({k: v for k, v in refusal.items() if k != "proof_digest"})
    from tests.test_temporal_session_deployment_dto import call

    identity = call(entry.intent)
    identity["mode"] = "register"
    identity["request_digest"] = digest(entry.control_request("register"))
    entry.begin_call(identity)
    ack = entry.end_call(
        {
            "body_result": {"ok": True, "result": result},
            "identity": identity,
            "body_result_digest": digest({"ok": True, "result": result}),
            "body_stopped": True,
        }
    )
    state.adopt_deployment_registration(result, ack)
    original = state.deployment_view(selected)
    assert state.active is None and state.history == []
    rebound = state.command(
        {
            "kind": "rebind",
            "scope": state.scope,
            "command_id": "rebind",
            "session_ref": state.ref.to_dict(),
            "binding": state.binding,
            "expected_binding_revision": 1,
        }
    )
    assert rebound["apply_state"] == "applied"
    submit_session(state, "second")
    assert state.deployment_view(selected) == original
    assert state.deployment_command(selected)["receipt"] == receipt
    assert state.deployment_retry(selected) == {
        "intent_digest": entry.intent["intent_digest"],
        "wake_recorded": False,
    }


def test_receipts_keep_original_binding_after_idle_rebind():
    state = session_state()
    original = state.ref.to_dict()
    state.command(
        {
            "kind": "rebind",
            "scope": state.scope,
            "command_id": "rebind",
            "session_ref": original,
            "binding": state.binding,
            "expected_binding_revision": 1,
        }
    )
    selected = {"scope": state.scope, **state.deployment_context, "command_id": "open"}
    assert state.deployment_receipt(selected) == {
        "receipt": state.receipts["open"],
        "session_ref": original,
    }
    assert state.ref.binding_revision == 2


def test_selected_workflow_issues_original_start_once_and_requires_positive_registry_epoch(
    monkeypatch,
):
    import asyncio

    from ralf_agent import temporal_session_workflow as product

    state = session_state()
    submit_session(state)
    instance = product.TemporalSessionWorkflow.__new__(product.TemporalSessionWorkflow)
    instance.state, instance.wake_revision = state, 0
    starts = []
    calls = []

    async def control(mode, entry):
        from tests.test_temporal_session_deployment_dto import call

        calls.append(mode)
        identity = call(entry.intent)
        identity.update(
            mode=mode,
            activity_id="call-" + str(len(calls)),
            request_digest=digest(entry.control_request(mode)),
        )
        entry.begin_call(identity)
        if mode == "register":
            # A start exception is uncertainty; a later original SDK read is the only success.
            phase = "held-unbound" if not entry.start_issued else "start-uncertain"
            result = registration(entry, phase)
        else:
            result = {
                "advance": None,
                "registry_execution_epoch": "original-registry-epoch",
                "execution_epoch": "original-business-epoch",
            }
        body = {"ok": True, "result": result}
        return {
            **body,
            "call_end": entry.end_call(
                {
                    "body_result": body,
                    "identity": identity,
                    "body_result_digest": digest(body),
                    "body_stopped": True,
                }
            ),
        }

    async def start_child(*args, **kwargs):
        starts.append((args, kwargs, state.deployment_turn().lifecycle()))
        raise product.WorkflowAlreadyStartedError(state.active["run_id"], "business")

    monkeypatch.setattr(instance, "_deployment_control", control, raising=False)
    monkeypatch.setattr(product.workflow, "start_child_workflow", start_child)
    asyncio.run(instance._deployment_step())
    assert len(starts) == 1
    assert starts[0][2]["start_issued"] is True
    assert starts[0][2]["start"]["phase"] == "start-uncertain"
    assert starts[0][1]["id_reuse_policy"] is product.WorkflowIDReusePolicy.REJECT_DUPLICATE
    assert starts[0][1]["parent_close_policy"] is product.workflow.ParentClosePolicy.ABANDON
    assert starts[0][1]["retry_policy"] is None
    assert (
        starts[0][0][1]["deployment_admission"]["session_origin"]["intent_digest"]
        == state.deployment_turn().intent["intent_digest"]
    )
    assert state.active["started"] is False and state.snapshot()["busy"] is True
    asyncio.run(instance._deployment_step())
    assert len(starts) == 1 and "observe" not in calls


def test_matching_retirement_hint_during_observe_keeps_new_dirty_generation(monkeypatch):
    import asyncio

    from ralf_agent import temporal_session_workflow as product
    from tests.test_temporal_session_deployment_dto import call

    state = session_state()
    submit_session(state)
    entry = state.deployment_turn()
    entry.adopt_registration(registration(entry, "started"))
    state.active["started"] = True
    instance = product.TemporalSessionWorkflow.__new__(product.TemporalSessionWorkflow)
    instance.state, instance.wake_revision = state, 4
    hint = {
        **selector(entry),
        "run_id": entry.intent["run_id"],
        "execution_epoch": "original-business-epoch",
        "change_token": "a" * 64,
    }

    async def observe(mode, actual):
        assert mode == "observe"
        instance.wake(hint)
        identity = call(entry.intent)
        identity["request_digest"] = digest(entry.control_request("observe"))
        entry.begin_call(identity)
        body = {
            "ok": True,
            "result": {
                "advance": None,
                "registry_execution_epoch": "original-registry-epoch",
                "execution_epoch": "original-business-epoch",
            },
        }
        return {
            **body,
            "call_end": entry.end_call(
                {
                    "body_result": body,
                    "identity": identity,
                    "body_result_digest": digest(body),
                    "body_stopped": True,
                }
            ),
        }

    monkeypatch.setattr(instance, "_deployment_control", observe, raising=False)
    observed_generation = asyncio.run(instance._deployment_step())
    assert observed_generation == 4 and instance.wake_revision == 5
    assert state.snapshot()["busy"] is True
    instance.wake({**hint, "run_id": "replacement"})
    assert instance.wake_revision == 5


def register_session(state, phase):
    from tests.test_temporal_session_deployment_dto import call

    entry = state.deployment_turn()
    identity = call(entry.intent)
    identity.update(
        mode="register",
        activity_id="register",
        request_digest=digest(entry.control_request("register")),
    )
    entry.begin_call(identity)
    result = registration(entry, phase)
    ack = entry.end_call(
        {
            "body_result": {"ok": True, "result": result},
            "identity": identity,
            "body_result_digest": digest({"ok": True, "result": result}),
            "body_stopped": True,
        }
    )
    state.adopt_deployment_registration(result, ack)


def test_two_consecutive_turns_publish_once_only_after_retirement_and_own_ack():
    state = session_state()
    first = submit_session(state)
    entry = state.deployment_turn()
    first_selector = selector(entry)
    register_session(state, "started")
    proof = advance(entry)
    body, ack = ended_observation(entry, proof)
    # A returned ACK which has not been recorded in original Session History cannot clear active.
    stored = copy.deepcopy(entry.calls)
    entry.calls = {}
    with pytest.raises(DefinitionMismatch):
        state.adopt_deployment_observation(body, ack)
    assert state.snapshot()["busy"] is True
    assert proof["retirement"]["released"] is True
    entry.calls = stored
    assert state.adopt_deployment_observation(body, ack) is True
    assert state.snapshot()["busy"] is False
    assert state.history == [
        {"role": "user", "content": '{"task":[1,2]}'},
        {"role": "assistant", "content": "answer"},
    ]
    assert state.deployment_command(first_selector)["receipt"] == first
    second = submit_session(state, "second")
    assert second["outcome"]["turn"]["turn_seq"] == 2
    second_entry = state.deployment_turn()
    assert second_entry.intent["submission"]["request"]["session_history"] == state.history
    # Old observation cannot publish into the second original Turn.
    with pytest.raises(DefinitionMismatch):
        state.adopt_deployment_observation(body, ack)
    register_session(state, "started")
    second_body, second_ack = ended_observation(second_entry, advance(second_entry))
    assert state.adopt_deployment_observation(second_body, second_ack) is True
    assert len(state.history) == 4
    assert entry.published is True and second_entry.published is True
    assert state.deployment_view(first_selector)["phase"] == "started"


def test_full_selected_query_and_callback_abi_preserves_original_start_views():
    import asyncio

    from ralf_agent import temporal_session_workflow as product
    from tests.test_temporal_session_deployment_dto import call

    state = session_state()
    receipt = submit_session(state)
    entry = state.deployment_turn()
    instance = product.TemporalSessionWorkflow.__new__(product.TemporalSessionWorkflow)
    instance.state, instance.wake_revision = state, 0
    selected = selector(entry)
    assert instance.view({"kind": "deployment_session_lifecycle", **selected}) == entry.lifecycle()
    assert (
        instance.view(
            {
                "kind": "deployment_session_intent",
                **{k: v for k, v in selected.items() if k != "intent_digest"},
            }
        )
        == entry.intent
    )
    assert instance.view({"kind": "deployment_session_command", **selected})["receipt"] == receipt
    identity = call(entry.intent)
    identity["request_digest"] = digest(entry.control_request("observe"))
    assert (
        asyncio.run(instance.session_deployment_call_start({"identity": identity}))["allowed"]
        is True
    )
    body = {"ok": False, "code": "session_control_unavailable"}
    payload = {
        "body_result": body,
        "identity": identity,
        "body_result_digest": digest(body),
        "body_stopped": True,
    }
    ack = asyncio.run(instance.session_deployment_call_end(payload))
    assert entry.call_ended(ack, body) is True
    assert asyncio.run(instance.retry_deployment_turn(selected)) == {
        "intent_digest": entry.intent["intent_digest"],
        "wake_recorded": True,
    }
    assert instance.wake_revision == 1


def test_selected_binding_query_returns_original_revision_for_stale_ref_rejection():
    from ralf_agent import temporal_session_workflow as product

    state = session_state()
    original = state.ref.to_dict()
    first_binding = copy.deepcopy(state.binding)
    changed = copy.deepcopy(state.binding)
    changed["task_queue"] = "later-queue"
    state.command(
        {
            "kind": "rebind",
            "scope": state.scope,
            "command_id": "rebind",
            "session_ref": original,
            "binding": changed,
            "expected_binding_revision": 1,
        }
    )
    instance = product.TemporalSessionWorkflow.__new__(product.TemporalSessionWorkflow)
    instance.state, instance.wake_revision = state, 0
    query = {
        "kind": "deployment_session_binding",
        "scope": state.scope,
        **state.deployment_context,
        "session_ref": original,
    }
    assert instance.view(query) == first_binding
    current = instance.view({**query, "session_ref": state.ref.to_dict()})
    assert current["task_queue"] == "later-queue"
    first_binding["task_queue"] = "mutated"
    assert instance.view(query)["task_queue"] == "original-queue"
    forged = {**original, "definition_digest": "b" * 64}
    assert instance.view({**query, "session_ref": forged}) == {"error": "definition_mismatch"}
    receipt = state.command(
        {
            "kind": "submit",
            "scope": state.scope,
            "command_id": "stale",
            "session_ref": original,
            "input": "question",
            "budget": 1,
        }
    )
    assert receipt["apply_state"] == "rejected"
    assert receipt["outcome"]["error"] == "session_binding_mismatch"


def test_failed_intent_validation_does_not_leave_unaccepted_active_turn():
    state = session_state()
    binding = copy.deepcopy(state.binding)
    binding["request"]["definition"]["steps"][0]["instructions"] = "x" * (1024 * 1024)
    state.command(
        {
            "kind": "rebind",
            "scope": state.scope,
            "command_id": "oversized-binding",
            "session_ref": state.ref.to_dict(),
            "binding": binding,
            "expected_binding_revision": 1,
        }
    )
    with pytest.raises(ValidationError):
        submit_session(state)
    assert state.active is None
    assert state.records == []
    assert state.deployment_turns == {}
    assert "session-submit-1" not in state.receipts


@pytest.mark.parametrize("change", ["id", "queue", "first", "original", "parent"])
def test_selected_coordinator_initialization_rejects_changed_actual_sdk_identity(
    monkeypatch, change
):
    from types import SimpleNamespace

    from ralf_agent import temporal_session_workflow as product
    from ralf_agent.temporal_session_state import workflow_id

    state = session_state()
    accepted = {
        "scope": state.scope,
        "namespace_id": state.namespace_id,
        "session_namespace": None,
        "session_id": "chat",
        "command_id": "open",
        **state.binding,
    }
    epoch = state.deployment_context["coordinator_execution_epoch"]
    info = SimpleNamespace(
        workflow_id=workflow_id(state.key),
        task_queue=state.binding["task_queue"],
        namespace=state.deployment_context["namespace"]["name"],
        run_id=epoch,
        first_execution_run_id=epoch,
        original_execution_run_id=epoch,
        parent=None,
    )
    setattr(
        info,
        {
            "id": "workflow_id",
            "queue": "task_queue",
            "first": "first_execution_run_id",
            "original": "original_execution_run_id",
            "parent": "parent",
        }[change],
        "replacement",
    )
    monkeypatch.setattr(product.workflow, "info", lambda: info)
    with pytest.raises(product.ApplicationError):
        product.TemporalSessionWorkflow(accepted)


def test_selected_status_inventories_original_session_call_debt_after_root_retirement():
    from tests.test_temporal_session_deployment_dto import call
    from tests.test_temporal_sessions import session

    state = session_state()
    submit_session(state)
    entry = state.deployment_turn()
    entry.adopt_registration(registration(entry, "started"))
    identity = call(entry.intent)
    identity["request_digest"] = digest(entry.control_request("observe"))
    entry.begin_call(identity)
    assert state.snapshot()["deployment_close"] == {"pending_calls": 1, "unpublished_turns": 1}
    # Positive root retirement is outside this independent Session call ledger.
    root_retirement = {"released": True}
    entry.end_call(
        {
            "body_result": {"ok": False, "code": "session_control_unavailable"},
            "identity": identity,
            "body_result_digest": digest({"ok": False, "code": "session_control_unavailable"}),
            "body_stopped": True,
        }
    )
    assert state.snapshot()["deployment_close"] == {"pending_calls": 0, "unpublished_turns": 1}
    entry.published = True
    assert state.snapshot()["deployment_close"] == {"pending_calls": 0, "unpublished_turns": 0}
    assert root_retirement == {"released": True}
    legacy, _ = session()
    assert "deployment_close" not in legacy.snapshot()


def test_late_original_observer_end_body_recovers_after_sdk_timeout_once(monkeypatch):
    import asyncio

    from ralf_agent import temporal_session_workflow as product
    from tests.test_temporal_session_deployment_dto import call

    state = session_state()
    submit_session(state)
    register_session(state, "started")
    entry = state.deployment_turn()
    instance = product.TemporalSessionWorkflow.__new__(product.TemporalSessionWorkflow)
    instance.state, instance.wake_revision = state, 0
    identity = call(entry.intent)
    identity["request_digest"] = digest(entry.control_request("observe"))
    controls = []

    async def timed_out(mode, original):
        controls.append(mode)
        original.begin_call(identity)
        return {"ok": False, "code": "session_control_unavailable"}

    monkeypatch.setattr(instance, "_deployment_control", timed_out)
    observed = asyncio.run(instance._deployment_step())
    assert state.snapshot()["busy"] is True
    asyncio.run(instance._deployment_step())
    assert controls == ["observe"]
    body = {
        "ok": True,
        "result": {
            "advance": advance(entry),
            "registry_execution_epoch": "original-registry-epoch",
            "execution_epoch": "original-business-epoch",
        },
    }
    payload = {
        "identity": identity,
        "body_result_digest": digest(body),
        "body_result": body,
        "body_stopped": True,
    }
    ack = asyncio.run(instance.session_deployment_call_end(payload))
    assert set(ack) == {"identity", "body_result_digest", "body_stopped", "recorded"}
    assert instance.wake_revision != observed
    asyncio.run(instance._deployment_step())
    assert state.snapshot()["busy"] is False and len(state.history) == 2
    assert controls == ["observe"]
    asyncio.run(instance.session_deployment_call_end(payload))
    asyncio.run(instance._deployment_step())
    assert len(state.history) == 2 and controls == ["observe"]


def test_end_rejects_forged_full_result_before_mutating_original_call():
    from tests.test_temporal_session_deployment_dto import call

    state = fixture()
    identity = call(state.intent)
    identity["request_digest"] = digest(state.control_request("observe"))
    state.begin_call(identity)
    before = copy.deepcopy(state.calls)
    body = {"ok": False, "code": "session_control_unavailable"}
    with pytest.raises(DefinitionMismatch):
        state.end_call(
            {
                "identity": identity,
                "body_result_digest": "a" * 64,
                "body_result": body,
                "body_stopped": True,
            }
        )
    assert state.calls == before


@pytest.mark.parametrize("positive", [False, True])
def test_nonpositive_late_body_closes_debt_without_automatic_observer_wake(positive):
    import asyncio

    from ralf_agent import temporal_session_workflow as product
    from tests.test_temporal_session_deployment_dto import call

    state = session_state()
    submit_session(state)
    register_session(state, "started")
    entry = state.deployment_turn()
    instance = product.TemporalSessionWorkflow.__new__(product.TemporalSessionWorkflow)
    instance.state, instance.wake_revision = state, 0
    identity = call(entry.intent)
    identity["request_digest"] = digest(entry.control_request("observe"))
    entry.begin_call(identity)
    body = {"ok": False, "code": "session_control_unavailable"}
    if positive:
        body = {
            "ok": True,
            "result": {
                "advance": None,
                "registry_execution_epoch": "original-registry-epoch",
                "execution_epoch": "original-business-epoch",
            },
        }
    payload = {
        "identity": identity,
        "body_result_digest": digest(body),
        "body_result": body,
        "body_stopped": True,
    }
    asyncio.run(instance.session_deployment_call_end(payload))
    assert instance.wake_revision == 0
    assert entry.recovered_result() is None
    assert state.snapshot()["busy"] is True and state.history == []


def test_late_positive_result_waits_for_every_original_call_end():
    from tests.test_temporal_session_deployment_dto import call

    state = session_state()
    submit_session(state)
    register_session(state, "started")
    entry = state.deployment_turn()
    observer = call(entry.intent)
    observer["request_digest"] = digest(entry.control_request("observe"))
    other = call(entry.intent)
    other["mode"] = "register"
    other["activity_id"] = "original-late-register"
    other["request_digest"] = digest(entry.control_request("register"))
    entry.begin_call(observer)
    entry.begin_call(other)
    body = {
        "ok": True,
        "result": {
            "advance": advance(entry),
            "registry_execution_epoch": "original-registry-epoch",
            "execution_epoch": "original-business-epoch",
        },
    }
    entry.end_call(
        {
            "identity": observer,
            "body_result_digest": digest(body),
            "body_result": body,
            "body_stopped": True,
        }
    )
    assert state.recover_deployment_result() is False
    assert state.snapshot()["busy"] is True
    failed = {"ok": False, "code": "session_control_unavailable"}
    entry.end_call(
        {
            "identity": other,
            "body_result_digest": digest(failed),
            "body_result": failed,
            "body_stopped": True,
        }
    )
    assert state.recover_deployment_result() is True
    assert state.snapshot()["busy"] is False and len(state.history) == 2


def test_late_registration_body_recovers_same_original_start_once():
    from tests.test_temporal_session_deployment_dto import call

    state = session_state()
    submit_session(state)
    entry = state.deployment_turn()
    identity = call(entry.intent)
    identity["mode"] = "register"
    identity["request_digest"] = digest(entry.control_request("register"))
    entry.begin_call(identity)
    assert state.recover_deployment_result() is False
    body = {"ok": True, "result": registration(entry, "started")}
    entry.end_call(
        {
            "identity": identity,
            "body_result_digest": digest(body),
            "body_result": body,
            "body_stopped": True,
        }
    )
    assert state.recover_deployment_result() is True
    assert state.active["started"] is True
    assert entry.view()["execution_epoch"] == "original-business-epoch"
    assert state.recover_deployment_result() is False
