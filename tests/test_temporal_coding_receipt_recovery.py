"""An already adopted native tombstone remains readable after stop work drains."""

import copy

import pytest

from relf_agent.errors import RalfError
from relf_agent.types import canonical
from tests.test_temporal_coding_state import OWNER, bind, no_prepare_recovery
from tests.test_temporal_tool_execution import admission, proof


def stopped_recovery(*, publication=4):
    state, action, request = no_prepare_recovery()
    if publication is not None:
        # The concrete joint publication is covered by the deployment suite;
        # this pure History fixture selects the experimental receipt behavior.
        state.manifest["deployment_admission_protocol"] = {"version": publication}
    operation, _ = state.next_operation()
    assert operation["kind"] == "coding_stop"
    original = {
        **admission(request, "c" * 32),
        "kind": "unprepared",
        "evidence": {"namespace_binding": bind(request), "prepare_granted": False},
    }
    state.coding_receipt({**admission(request, "c" * 32), "kind": "owner", "evidence": OWNER})
    first = state.coding_receipt(original)
    state.tool_execution_ended(proof(request))
    state.accept_coding_stop(
        action["id"], {"ok": True, "code": "effect_outcome_unknown", "dispatched": True}
    )
    assert state.next_operation() is None

    # A new, admitted recovery invocation observes an already stopped owner.
    # Workflow progress can clear stop_needed while its journal I/O is in flight.
    recovery = admission(request, "d" * 32)
    state.admit_coding_stop(recovery)
    assert state.next_operation() is None
    native = action["delegated_execution"]
    assert native["stop_needed"] is False
    return state, action, original, recovery, first


@pytest.mark.parametrize("restored", [False, True])
def test_same_unprepared_receipt_survives_concurrent_stop_work_drain(restored):
    state, action, original, recovery, first = stopped_recovery()
    if restored:
        state = copy.deepcopy(state)
        action = next(a for a in state.actions if a["id"] == action["id"])
    native = action["delegated_execution"]
    before = copy.deepcopy(native)
    budget = copy.deepcopy(state.budget)
    events = copy.deepcopy(state.event_log)
    assert state.coding_receipt({**original, **recovery}) == first
    assert native == before
    assert state.event_log == events
    assert state.budget == budget and state.budget["unknown"] == 1
    assert action["status"] == "outcome_unknown"
    assert native["grants"] == {} and len(action["attempts"]) == 1


@pytest.mark.parametrize("publication", [None, 3])
def test_legacy_receipt_path_preserves_original_refusal(publication):
    state, action, original, recovery, _ = stopped_recovery(publication=publication)
    before = canonical(state.__dict__)
    with pytest.raises(RalfError):
        state.coding_receipt({**original, **recovery})
    assert canonical(state.__dict__) == before


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "run_id",
        "action_id",
        "execution_epoch",
        "release_digest",
        "request_digest",
        "unadmitted_stop",
        "business_claim",
        "namespace",
        "runner",
        "prepare_granted",
        "boolean_as_number",
    ],
)
def test_duplicate_native_receipt_cannot_replace_original_proof_or_evidence(fault):
    state, _, original, recovery, _ = stopped_recovery()
    payload = copy.deepcopy({**original, **recovery})
    if fault == "scope":
        payload["scope"]["workspace"] = "foreign"
    elif fault in {"unadmitted_stop", "business_claim"}:
        payload["invocation_id"] = ("e" if fault == "unadmitted_stop" else "a") * 32
    elif fault == "prepare_granted":
        payload["evidence"]["prepare_granted"] = True
    elif fault == "boolean_as_number":
        payload["evidence"]["prepare_granted"] = 0
    elif fault in {"namespace", "runner"}:
        binding = payload["evidence"]["namespace_binding"]
        if fault == "namespace":
            binding["environment"]["expected_generation"] = "0" * 32
        else:
            binding["runner"] = {"kind": "replacement"}
    else:
        payload[fault] = "foreign"
    before = canonical(state.__dict__)
    with pytest.raises(RalfError):
        state.coding_receipt(payload)
    assert canonical(state.__dict__) == before


@pytest.mark.parametrize("fault", ["first_receipt", "grants", "prepared", "stop", "thread", "turn"])
def test_adopted_receipt_cannot_hide_new_or_contradictory_native_state(fault):
    state, action, original, recovery, _ = stopped_recovery()
    native = action["delegated_execution"]
    if fault == "first_receipt":
        del native["unprepared"]
    elif fault == "grants":
        native["grants"]["prepare"] = {"unexpected": True}
    else:
        native[fault] = {"unexpected": True}
    before = canonical(state.__dict__)
    with pytest.raises(RalfError):
        state.coding_receipt({**original, **recovery})
    assert canonical(state.__dict__) == before
