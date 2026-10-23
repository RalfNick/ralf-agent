"""Additive parent policy declarations and actual planner feedback inputs."""

import pytest

from relf_agent.errors import ValidationError
from relf_agent.orchestration_types import ChildCall, DynamicWorkflowSpec, TeamSpec
from relf_agent.planning import PlanningRequest
from relf_agent.spec_codec import decode_spec, encode_spec
from relf_agent.types import AgentSpec, digest


def members():
    return {"worker": AgentSpec("worker", "Use the declared evidence.")}


@pytest.mark.parametrize("cls", [DynamicWorkflowSpec, TeamSpec])
def test_parent_completion_selection_roundtrips_without_default_migration(cls):
    old = encode_spec(cls("parent", members()))
    assert "completion_policy" not in old
    new = encode_spec(cls("parent", members(), completion_policy="business"))
    assert new["completion_policy"] == "business"
    assert encode_spec(decode_spec(new)) == new
    assert {k: v for k, v in new.items() if k != "completion_policy"} == old


@pytest.mark.parametrize("cls", [DynamicWorkflowSpec, TeamSpec])
@pytest.mark.parametrize("name", ["", " ", 0, False, {}, []])
def test_parent_completion_names_require_explicit_nonempty_registration(cls, name):
    with pytest.raises(ValidationError):
        cls("parent", members(), completion_policy=name)


def feedback():
    return {
        "revision": 0,
        "feedback": "Use the calculator receipt for the requested quantity.",
        "evidence_ids": ["tool:" + digest(["run", "action"])],
        "source_digest": digest({"candidate": {"total": 1}}),
    }


def test_parent_verification_feedback_is_actual_planner_input_and_detached():
    prior = feedback()
    request = PlanningRequest("task", ["worker"], [], 1, verification_feedback=prior)
    assert request.to_dict()["verification_feedback"] == prior
    assert PlanningRequest(**request.to_dict()).to_dict() == request.to_dict()
    prior["evidence_ids"].clear()
    assert request.verification_feedback["evidence_ids"]
    assert "verification_feedback" not in PlanningRequest("task", ["worker"], [], 0).to_dict()


@pytest.mark.parametrize(
    "change",
    [
        {"revision": True},
        {"revision": -1},
        {"revision": 1},
        {"feedback": ""},
        {"feedback": "x" * 4097},
        {"evidence_ids": ["tool:a", "tool:a"]},
        {"evidence_ids": "tool:a"},
        {"source_digest": "foreign"},
        {"unknown": True},
    ],
)
def test_planner_feedback_rejects_invalid_or_ambiguous_source(change):
    value = feedback()
    value.update(change)
    with pytest.raises(ValidationError):
        PlanningRequest("task", ["worker"], [], 1, verification_feedback=value)


def test_declared_verifier_call_is_available_for_authority_dispatch():
    call = ChildCall("verdict", "@verifier", {"candidate": {"total": 1}})
    assert call.to_dict()["member"] == "@verifier"


@pytest.mark.parametrize("member", [{}, []])
def test_invalid_child_member_returns_declared_validation_error(member):
    with pytest.raises(ValidationError):
        ChildCall("verdict", member, {})
