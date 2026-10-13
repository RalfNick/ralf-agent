"""Pure parent proposals reject malformed, foreign and deferred evidence."""

import types

import pytest

from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.types import Scope, digest


def child(path=("worker",), *, run_id="worker-run", result=None, input=None, revision=0):
    return {
        "id": "child:" + digest([run_id, "a" * 64]),
        "call_id": "step-0",
        "role": "worker",
        "member_path": list(path),
        "run_id": run_id,
        "release_digest": "a" * 64,
        "state_revision": 3,
        "planning_revision": revision,
        "input": input,
        "input_digest": digest(input),
        "input_consumed": True,
        "result": result,
        "result_digest": digest(result),
        "final_action_id": "final-model",
        "final_snapshot_digest": "b" * 64,
        "final_models": [
            {
                "member_path": list(path),
                "action_id": "final-model",
                "snapshot_digest": "b" * 64,
                "input_digest": digest(input),
                "input_consumed": True,
            }
        ],
    }


def receipt(item, *, tool="lookup", arguments=None, result=None, action_id="tool-1"):
    return {
        "id": "tool:" + digest([item["run_id"], action_id]),
        "run_id": item["run_id"],
        "member_path": item["member_path"],
        "action_id": action_id,
        "tool": tool,
        "arguments": {} if arguments is None else arguments,
        "result": result,
        "receipt": {"state": "completed"},
        "effect_key": "effect-1",
        "consumed_by": ["model:" + digest([item["run_id"], item["final_action_id"]])],
    }


def source(**changes):
    value = {
        "parent_id": "parent-run",
        "parent_kind": "dynamic",
        "scope": {"workspace": "tests", "principal": "owner"},
        "release_digest": "c" * 64,
        "revision": 0,
        "task": {"sku": "wire"},
        "plan": {"steps": [{"id": "step-0", "member": "worker", "input": None}]},
        "candidate": {"total": 20},
        "children": [child()],
        "receipts": [],
        "constraints": {
            "remaining_steps": 4,
            "remaining_revisions": 1,
            "max_concurrency": 1,
            "verifier_budget": 1,
            "parent_budget": {"available": 10, "held": 0, "spent": 0},
        },
    }
    value.update(changes)
    return value


def request(**changes):
    from ralf_agent.parent_completion import ParentCompletionRequest

    return ParentCompletionRequest(**source(**changes))


class AcceptGate:
    identity = {"kind": "test-gate", "version": "1"}

    def verify(self, request):
        from ralf_agent.parent_completion import ParentCompletionVerdict

        return ParentCompletionVerdict("accept")


def test_request_freezes_exact_finite_source_and_restores_it():
    from ralf_agent.parent_completion import ParentCompletionRequest

    original = source(scope=Scope("tests", "owner"))
    value = ParentCompletionRequest(**original)
    original["candidate"]["total"] = 999
    projected = value.to_dict()
    assert projected["candidate"] == {"total": 20}
    assert projected["schema_version"] == 1
    assert set(projected) == {"schema_version", *source()}
    assert ParentCompletionRequest.from_dict(projected).to_dict() == projected
    projected["children"][0]["member_path"].append("forged")
    assert value.children[0]["member_path"] == ["worker"]


@pytest.mark.parametrize(
    "fault",
    ["child-id", "input-digest", "result-digest", "extra", "role", "future", "partial-final"],
)
def test_request_rejects_incomplete_or_inconsistent_child(fault):
    value = source()
    item = value["children"][0]
    if fault == "child-id":
        item["id"] = "child:" + "f" * 64
    elif fault == "input-digest":
        item["input_digest"] = "f" * 64
    elif fault == "result-digest":
        item["result_digest"] = "f" * 64
    elif fault == "extra":
        item["state"] = "succeeded"
    elif fault == "role":
        item["role"] = "verifier"
    elif fault == "future":
        item["planning_revision"] = 1
    else:
        item["final_snapshot_digest"] = None
    from ralf_agent.parent_completion import ParentCompletionRequest

    with pytest.raises(ValidationError):
        ParentCompletionRequest(**value)


@pytest.mark.parametrize(
    "fault", ["foreign-run", "foreign-path", "tool-id", "foreign-model", "extra"]
)
def test_request_rejects_foreign_or_fabricated_receipt(fault):
    value = source()
    tool = receipt(value["children"][0])
    value["receipts"] = [tool]
    if fault == "foreign-run":
        tool["run_id"] = "unowned-run"
    elif fault == "foreign-path":
        tool["member_path"] = ["unowned"]
    elif fault == "tool-id":
        tool["id"] = "tool:" + "f" * 64
    elif fault == "foreign-model":
        tool["consumed_by"] = ["model:" + "f" * 64]
    else:
        tool["snapshot"] = []
    from ralf_agent.parent_completion import ParentCompletionRequest

    with pytest.raises(ValidationError):
        ParentCompletionRequest(**value)


def test_container_and_retained_revision_sources_have_explicit_shape():
    old = child(revision=0)
    old.update(input_consumed=None, final_action_id=None, final_snapshot_digest=None)
    old["final_models"][0]["member_path"] = ["worker", "leaf"]
    assert request(revision=1, children=[old]).children[0]["planning_revision"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": True},
        {"parent_kind": "agent"},
        {"parent_kind": "team", "revision": 1},
        {"task": float("nan")},
    ],
)
def test_request_rejects_invalid_parent_source(changes):
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.mark.parametrize(
    "status,feedback",
    [
        ("retry", None),
        ("accept", "replacement"),
        ("replan", None),
        ("replan", " "),
        ("reject", "x" * 4097),
    ],
)
def test_verdict_has_bounded_semantics(status, feedback):
    from ralf_agent.parent_completion import ParentCompletionVerdict

    with pytest.raises(ValidationError):
        ParentCompletionVerdict(status, feedback=feedback)


def test_verdict_evidence_ids_must_exist_and_cannot_request_team_replan():
    from ralf_agent.parent_completion import ParentCompletionVerdict
    from ralf_agent.parent_completion_protocol import validate_verdict

    value = request()
    assert (
        validate_verdict(
            value, ParentCompletionVerdict("accept", evidence_ids=[value.children[0]["id"]])
        ).status
        == "accept"
    )
    with pytest.raises(ValidationError):
        validate_verdict(
            value, ParentCompletionVerdict("accept", evidence_ids=["child:" + "f" * 64])
        )
    with pytest.raises(ValidationError):
        ParentCompletionVerdict("accept", evidence_ids=[value.children[0]["id"]] * 2)
    team = source(parent_kind="team", plan=None)
    team["constraints"]["remaining_revisions"] = 0
    with pytest.raises(ValidationError):
        validate_verdict(request(**team), ParentCompletionVerdict("replan", feedback="Try again"))
    assert (
        ParentCompletionVerdict.from_dict(
            {"status": "reject", "feedback": None, "evidence_ids": []}
        ).status
        == "reject"
    )


def test_policy_source_and_evidence_limits_are_enforced_before_gate():
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_completion_protocol import gate_verdict, validate_request_bounds

    with pytest.raises(ValidationError):
        ParentCompletionPolicy(AcceptGate(), max_source_bytes=1_048_577)
    policy = ParentCompletionPolicy(AcceptGate(), max_source_bytes=16)
    with pytest.raises(ValidationError):
        gate_verdict(policy, request())
    policy = ParentCompletionPolicy(AcceptGate(), max_evidence_children=1, max_receipts=1)
    with pytest.raises(ValidationError):
        validate_request_bounds(policy, request(children=[child(), child(run_id="second-run")]))


def test_registration_is_detached_and_pins_identity_and_original_method():
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_completion_protocol import (
        gate_verdict,
        policy_registration,
        validate_policy,
    )

    gate = AcceptGate()
    policy = ParentCompletionPolicy(gate)
    registered = policy_registration(policy)
    assert set(registered) == {
        "identity",
        "implementation_digest",
        "gate_registration",
        "stage_registration",
    }
    registered["identity"]["version"] = "tampered"
    assert validate_policy(policy)["identity"]["version"] == "1"
    gate.verify = types.MethodType(lambda self, request: self.__class__.verify(self, request), gate)
    with pytest.raises(DefinitionMismatch):
        gate_verdict(policy, request())


def test_gate_drift_during_execution_is_rejected():
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_completion_protocol import gate_verdict

    class DriftGate:
        identity = {"kind": "drifting-gate", "version": "1"}

        def verify(self, request):
            from ralf_agent.parent_completion import ParentCompletionVerdict

            self.identity = {"kind": "drifting-gate", "version": "2"}
            return ParentCompletionVerdict("accept")

    with pytest.raises(DefinitionMismatch):
        gate_verdict(ParentCompletionPolicy(DriftGate()), request())


def test_lazy_gate_return_and_async_implementation_are_rejected():
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_completion_protocol import gate_verdict

    class LazyGate(AcceptGate):
        def verify(self, request):
            return iter(["accept"])

    class AsyncGate(AcceptGate):
        async def verify(self, request):
            return "accept"

    with pytest.raises(ValidationError):
        gate_verdict(ParentCompletionPolicy(LazyGate()), request())
    with pytest.raises(ValidationError):
        ParentCompletionPolicy(AsyncGate())


def test_container_receipts_use_real_run_and_corresponding_leaf_final_model():
    from ralf_agent.parent_completion import ParentCompletionRequest

    owner = child(("group",))
    owner.update(input_consumed=None, final_action_id=None, final_snapshot_digest=None)
    owner["final_models"][0]["member_path"] = ["group", "leaf"]
    tool = receipt(owner)
    tool["member_path"] = ["group", "leaf"]
    tool["consumed_by"] = ["model:" + digest([owner["run_id"], "final-model"])]
    assert request(children=[owner], receipts=[tool]).receipts[0]["run_id"] == "worker-run"
    wrong = source(children=[owner], receipts=[tool])
    wrong["receipts"][0]["member_path"] = ["group", "other-leaf"]
    with pytest.raises(ValidationError):
        ParentCompletionRequest(**wrong)


def test_container_model_slot_must_be_a_step_or_node_descendant():
    owner = child(("group",))
    owner.update(input_consumed=None, final_action_id=None, final_snapshot_digest=None)
    with pytest.raises(ValidationError):
        request(children=[owner])


def test_policy_changed_to_invalid_gate_fails_as_definition_mismatch():
    from ralf_agent.parent_completion import ParentCompletionPolicy
    from ralf_agent.parent_completion_protocol import gate_verdict

    policy = ParentCompletionPolicy(AcceptGate())
    policy.gate = None
    with pytest.raises(DefinitionMismatch):
        gate_verdict(policy, request())


def test_request_restore_rejects_unknown_fields_and_version():
    from ralf_agent.parent_completion import ParentCompletionRequest

    for changes in ({"source_digest": "a" * 64}, {"schema_version": True}, {"schema_version": 2}):
        with pytest.raises(ValidationError):
            ParentCompletionRequest.from_dict({**request().to_dict(), **changes})


def test_container_direct_tool_has_real_run_and_explicitly_empty_consumption():
    owner = child(("group",))
    owner.update(
        input_consumed=None, final_action_id=None, final_snapshot_digest=None, final_models=[]
    )
    tool = receipt(owner)
    tool["member_path"] = ["group", "measure"]
    tool["consumed_by"] = []
    assert request(children=[owner], receipts=[tool]).receipts[0]["consumed_by"] == []
    tool["consumed_by"] = ["model:" + digest([owner["run_id"], "invented-final"])]
    with pytest.raises(ValidationError):
        request(children=[owner], receipts=[tool])
