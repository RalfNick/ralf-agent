"""Adopt original source revisions without echoing unchanged facts to ancestors."""

import copy
from types import CodeType

import pytest

from ralf_agent import temporal_coding_composition_state as composition
from ralf_agent.temporal_parent_workflow import TemporalParentWorkflow, workflow
from tests.test_temporal_coding_observe_validation import environment


def selected(monkeypatch, *, observation_version=2):
    e = environment(monkeypatch)
    assert e.parent.manifest["deployment_admission_protocol"]["version"] == 4
    for node in e.client.states.values():
        node.deployment_seal = None
        node.deployment_retirement = None
    e.parent.state = "running"
    e.parent.observation_version = observation_version
    e.call.update(settled=False, state="queued", spent=0)
    e.call.pop("physical_stop_proof", None)
    value = object.__new__(TemporalParentWorkflow)
    value.state = e.parent
    value._deployment_notification_revisions = 0
    monkeypatch.setattr(workflow, "patched", lambda name: True)
    child = e.client.states[e.call["run_id"]]
    child.state, child.result = "queued", None

    def observation():
        return {
            **child.diagnostics(),
            "scope": copy.deepcopy(e.parent.scope),
            "coding_composition_proof": composition.physical_stop_view(child),
        }

    assert value._observe_composition(e.call["run_id"], observation())
    return e, value, child, observation


@pytest.mark.parametrize("observation_version", [1, 2])
def test_source_only_revision_is_adopted_without_ancestor_notification(
    monkeypatch, observation_version
):
    e, value, child, observation = selected(monkeypatch, observation_version=observation_version)
    before = value._deployment_notification_token()
    revision = value.state.revision
    old_proof = copy.deepcopy(e.call["physical_stop_proof"])
    child._emit("source_bookkeeping_only")
    assert value._observe_composition(e.call["run_id"], observation())
    # Original evidence and public revisions still advance, never reuse old proof.
    assert value.state.revision > revision
    assert e.call["observed_revision"] == child.revision
    assert e.call["physical_stop_proof"] != old_proof
    assert e.call["physical_stop_proof"] == composition.physical_stop_view(child)
    assert value._deployment_notification_token() == before


def test_source_revision_with_changed_business_state_still_notifies(monkeypatch):
    e, value, child, observation = selected(monkeypatch)
    before = value._deployment_notification_token()
    child.state = "running"
    child._emit("business_progress")
    assert value._observe_composition(e.call["run_id"], observation())
    assert e.call["state"] == "running"
    assert value._deployment_notification_token() != before


def test_legacy_history_keeps_source_revision_notification(monkeypatch):
    e, value, child, observation = selected(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "patched",
        lambda name: name != "ralf-source-revision-notification-v1",
    )
    before = value._deployment_notification_token()
    child._emit("legacy_source_revision")
    assert value._observe_composition(e.call["run_id"], observation())
    assert value._deployment_notification_token() != before


def test_invalid_new_physical_proof_is_refused_without_discount(monkeypatch):
    e, value, child, observation = selected(monkeypatch)
    child._emit("source_revision")
    response = observation()
    response["coding_composition_proof"]["execution_epoch"] = "foreign"
    revision_discount = value._deployment_notification_revisions
    assert value._observe_composition(e.call["run_id"], response) is False
    assert value.state.composition_stop_intent is not None
    assert value._deployment_notification_revisions == revision_discount


@pytest.mark.parametrize("change", ["reserved", "reservations"])
def test_full_child_budget_changes_notify_even_when_parent_budget_does_not(monkeypatch, change):
    e, value, child, observation = selected(monkeypatch)
    before = value._deployment_notification_token()
    budget = copy.deepcopy(value.state.budget)
    discount = value._deployment_notification_revisions
    child._emit("new_child_budget")
    response = observation()
    if change == "reserved":
        response["budget"]["reserved"] += 1
        response["budget"]["remaining"] -= 1
    response["budget"]["reservations"] = [{"id": "original-child-reservation", "amount": 1}]
    assert value._observe_composition(e.call["run_id"], response)
    assert value.state.budget == budget
    assert e.call["spent"] == 0 and e.call["uncertain"] is False
    assert value._deployment_notification_token() != before
    assert value._deployment_notification_revisions == discount


@pytest.mark.parametrize("kind", ["future_fact", "recovery", "physical_owner"])
def test_parent_fact_or_resource_change_during_adoption_cannot_be_discounted(monkeypatch, kind):
    e, value, child, observation = selected(monkeypatch)
    original = value.state._adopt_child_result

    def adopt(call):
        original(call)
        if kind == "future_fact":
            value.state.extension_fact = {"revision": 1, "proof_digest": "business-value"}
        elif kind == "recovery":
            value.state.memory_recovery_revision += 1
        else:
            value.state.deployment_calls["new-owner"] = {
                "identity": {"activity_name": "business-handler"},
                "stopped": False,
                "fence_proof": None,
            }

    # Install on the class: a bound port is not part of persisted Workflow facts.
    monkeypatch.setattr(type(value.state), "_adopt_child_result", lambda self, call: adopt(call))
    discount = value._deployment_notification_revisions
    child._emit("source_bookkeeping_only")
    assert value._observe_composition(e.call["run_id"], observation())
    assert value._deployment_notification_revisions == discount


@pytest.mark.parametrize("state", ["cancelling", "cancelled", "failed", "succeeded"])
def test_termination_keeps_all_source_revision_notifications(monkeypatch, state):
    e, value, child, observation = selected(monkeypatch)
    value.state.state = state
    before = value._deployment_notification_token()
    discount = value._deployment_notification_revisions
    child._emit("source_bookkeeping_only")
    assert value._observe_composition(e.call["run_id"], observation())
    assert value._deployment_notification_token() != before
    assert value._deployment_notification_revisions == discount


def test_same_revision_conflicting_evidence_is_not_hidden(monkeypatch):
    e, value, child, observation = selected(monkeypatch)
    response = observation()
    response["budget"]["reserved"] += 1
    response["budget"]["remaining"] -= 1
    discount = value._deployment_notification_revisions
    assert value._observe_composition(e.call["run_id"], response) is False
    assert value.state.composition_stop_intent is not None
    assert value._deployment_notification_revisions == discount


def test_repeated_source_adoption_does_not_consume_ack_or_dirty_work(monkeypatch):
    e, value, child, observation = selected(monkeypatch)
    value._deployment_parent_notified = "a" * 64
    value._deployment_parent_pending = {"token": "b" * 64}
    value._deployment_dirty = {e.call["run_id"]: 7}
    before = value._deployment_notification_token()
    for _ in range(3):
        child._emit("source_bookkeeping_only")
        assert value._observe_composition(e.call["run_id"], observation())
        assert e.call["observed_revision"] == child.revision
        assert value._deployment_notification_token() == before
    assert value._deployment_parent_notified == "a" * 64
    assert value._deployment_parent_pending == {"token": "b" * 64}
    assert value._deployment_dirty == {e.call["run_id"]: 7}
    child.state = "running"
    child._emit("real_business_progress")
    assert value._observe_composition(e.call["run_id"], observation())
    assert value._deployment_notification_token() != before


@pytest.mark.parametrize("field", ["revision", "state_revision", "proof_digest"])
def test_nested_business_fields_with_bookkeeping_names_still_notify(monkeypatch, field):
    e, value, child, observation = selected(monkeypatch)
    before = value._deployment_notification_token()
    child.result = {field: "new-business-fact"}
    child._emit("business_data")
    assert value._observe_composition(e.call["run_id"], observation())
    assert value._deployment_notification_token() != before


def test_inlined_comparison_body_is_covered_by_registered_worker_inventory(monkeypatch):
    from ralf_agent.temporal_coding_composition_protocol import implementation

    function = TemporalParentWorkflow._observe_composition
    before = implementation()["parent_workflow"]["TemporalParentWorkflow._observe_composition"]
    inner = next(
        item
        for item in function.__code__.co_consts
        if type(item) is CodeType and item.co_name == "notification_facts"
    )
    changed = inner.replace(
        co_consts=tuple(
            "changed-source-pin" if item == "observed_revision" else item
            for item in inner.co_consts
        )
    )
    assert changed != inner
    monkeypatch.setattr(
        function,
        "__code__",
        function.__code__.replace(
            co_consts=tuple(
                changed if item is inner else item for item in function.__code__.co_consts
            )
        ),
    )
    assert (
        implementation()["parent_workflow"]["TemporalParentWorkflow._observe_composition"] != before
    )
