"""Optional clarification evidence never changes legacy declaration bytes."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from relf_agent import AgentSpec, DynamicWorkflowSpec, ParentCompletionRequest, PlanningRequest
from relf_agent.errors import ValidationError
from relf_agent.planning import ModelPlanner
from relf_agent.types import Scope
from relf_agent.user_input import UserInputPolicy, answered_input, make_input_record


def evidence():
    return answered_input(
        make_input_record(
            run_id="parent",
            release_digest="a" * 64,
            scope=Scope("tests", "owner"),
            source={"kind": "planner", "revision": 0, "proposal_digest": "b" * 64},
            prompt="Which environment?",
            policy=UserInputPolicy(),
            ordinal=1,
        ),
        "production",
        "reply-1",
    )


def parent_source():
    return {
        "parent_id": "parent",
        "parent_kind": "dynamic",
        "scope": {"workspace": "tests", "principal": "owner"},
        "release_digest": "a" * 64,
        "revision": 1,
        "task": {"original": True},
        "plan": None,
        "candidate": "answer",
        "children": [],
        "receipts": [],
        "constraints": {
            "remaining_steps": 3,
            "remaining_revisions": 1,
            "max_concurrency": 1,
            "verifier_budget": 1,
            "parent_budget": {"available": 8, "held": 0, "spent": 2},
        },
    }


def test_dynamic_definition_omits_absent_policy_and_restores_explicit_selection():
    member = AgentSpec("worker", "Work")
    old = DynamicWorkflowSpec("plan", {"worker": member}).to_dict()
    assert "input_policy" not in old
    selected = DynamicWorkflowSpec("plan", {"worker": member}, input_policy="human")
    assert selected.to_dict() == {**old, "input_policy": "human"}
    assert DynamicWorkflowSpec.from_dict(selected.to_dict()).to_dict() == selected.to_dict()


def test_planning_request_omits_absent_lineage_and_detaches_explicit_answers():
    base = PlanningRequest({"original": True}, ["worker"], [], 1)
    assert "clarifications" not in base.to_dict()
    answer = evidence()
    selected = PlanningRequest({"original": True}, ["worker"], [], 1, clarifications=[answer])
    answer["value"] = "forged"
    assert selected.task == {"original": True}
    assert selected.clarifications[0]["value"] == "production"


def test_completion_source_preserves_original_task_and_validated_reply_lineage():
    base = ParentCompletionRequest(**parent_source())
    assert "clarifications" not in base.to_dict()
    answered = evidence()
    selected = ParentCompletionRequest(**parent_source(), clarifications=[answered])
    assert selected.task == {"original": True}
    assert selected.clarifications == [answered]
    assert ParentCompletionRequest.from_dict(selected.to_dict()).to_dict() == selected.to_dict()
    foreign = copy.deepcopy(answered)
    foreign["request"]["owner"]["scope"]["principal"] = "foreign"
    with pytest.raises(ValidationError):
        ParentCompletionRequest(**parent_source(), clarifications=[foreign])
    foreign_valid = answered_input(
        make_input_record(
            run_id="parent",
            release_digest="a" * 64,
            scope=Scope("tests", "foreign"),
            source={"kind": "planner", "revision": 0, "proposal_digest": "b" * 64},
            prompt="Which environment?",
            policy=UserInputPolicy(),
            ordinal=1,
        ),
        "production",
        "reply-foreign",
    )
    with pytest.raises(ValidationError, match="Scope"):
        ParentCompletionRequest(**parent_source(), clarifications=[foreign_valid])


@pytest.mark.parametrize("target", ["planning", "completion"])
def test_lineage_rejects_duplicate_or_unanswered_requests(target):
    answer = evidence()
    pending = {"request": answer["request"], "state": "pending"}
    constructor = (
        (lambda values: PlanningRequest("original", ["worker"], [], 1, clarifications=values))
        if target == "planning"
        else (lambda values: ParentCompletionRequest(**parent_source(), clarifications=values))
    )
    with pytest.raises(ValidationError):
        constructor([answer, answer])
    with pytest.raises(ValidationError):
        constructor([pending])


def test_model_planner_default_identity_and_schema_are_unchanged():
    old = ModelPlanner()
    assert set(old.agent.output_schema["required"]) == {"steps"}
    assert "input_requests" not in old.identity
    selected = ModelPlanner(input_requests=True)
    assert selected.identity["input_requests"] is True
    assert "oneOf" in selected.agent.output_schema


def test_default_temporal_planner_retains_alpha6_implementation_identity():
    from relf_agent.temporal_components import default_components, orchestration_identity
    from relf_agent.tools import _callable_identity
    from relf_agent.types import digest

    teams, planners, verifiers = default_components()
    published = "6191cb0e91b6446deb63d317efe5e579a145b90508103b903bec8f35972a3228"
    manifest = orchestration_identity(teams, planners, verifiers)
    assert manifest["planners"]["model"]["implementation_digest"] == published
    # a6 changes the Python namespace, not the published plan implementation.
    # The old identity remains evidence for old Workers, not an a6 replay promise.
    previous = _callable_identity(planners["model"].plan)
    assert previous["owner"] == "relf_agent.planning.ModelPlanner"
    assert previous["function"]["module"] == "relf_agent.planning"
    previous["owner"] = "ralf_agent.planning.ModelPlanner"
    previous["function"]["module"] = "ralf_agent.planning"
    assert digest([previous]) == "15977fd630e3210e1666f235e6128a12eeaea2890e0ea333ba34cf1842e9c7f9"
    planners["model"] = ModelPlanner(input_requests=True)
    selected = orchestration_identity(teams, planners, verifiers)
    assert selected["planners"]["model"]["implementation_digest"] != published


def test_explicit_flat_model_planner_returns_typed_input_conclusion():
    from relf_agent.dag_planning import PlanningConclusion

    class Caller:
        async def call(self, call_id, member, value):
            return SimpleNamespace(
                state="succeeded",
                result={
                    "status": "needs_input",
                    "reason": "Which environment?",
                },
            )

    planner = ModelPlanner(input_requests=True)
    result = asyncio.run(planner.plan(PlanningRequest("original", ["worker"], [], 0), Caller()))
    assert isinstance(result, PlanningConclusion)
    assert result.status == "needs_input"
    assert result.reason == "Which environment?"
