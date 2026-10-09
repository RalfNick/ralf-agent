"""Independent dev17 review: intended assertions fail on the reviewed code.

No services or paid providers are used. Run with PYTHONDONTWRITEBYTECODE=1,
pytest -p no:cacheprovider and --basetemp inside this review directory.
"""

import asyncio

import pytest

from ralf_agent import AgentSpec, DAGNode, DAGProposal, DynamicWorkflowSpec, ModelResponse, ToolCall
from ralf_agent.business_evaluation import evaluate_business, load_business_cases
from ralf_agent.errors import ValidationError
from tests.test_temporal_composites import observation, state


@pytest.mark.parametrize("location", ["node", "output", "patch"])
def test_dynamic_proposal_rejects_remote_schema_before_adoption(location):
    parent = state(DynamicWorkflowSpec("dag", {"a": AgentSpec("a", "Answer")}, plan_mode="dag"))
    remote = {"$ref": "https://review.invalid/schema"}
    if location == "patch":
        parent.accept_selection(DAGProposal([DAGNode("one", "a")]).to_dict())
        proposal = DAGProposal([DAGNode("one", "a", output_schema=remote)])
        with pytest.raises(ValidationError):
            parent.patch(proposal.to_dict(), 0)
    else:
        proposal = (
            DAGProposal([DAGNode("one", "a", output_schema=remote)])
            if location == "node"
            else DAGProposal([DAGNode("one", "a")], output_schema=remote)
        )
        with pytest.raises(ValidationError):
            parent.accept_selection(proposal.to_dict())
    assert parent.children == []


@pytest.mark.parametrize("held", ["unknown", "reserved"])
def test_contradictory_quiescent_observation_cannot_release_child_escrow(held):
    parent = state()
    parent.accept_selection(
        {"calls": [{"id": "one", "member": "a", "input": "x"}], "done": False, "result": None}
    )
    call = parent.next_calls()[0]
    evidence = observation(parent, call, state="failed", spent=0)
    evidence["budget"].update({held: 1, "remaining": call["cap"] - 1})
    with pytest.raises(ValidationError):
        parent.observe(call["run_id"], evidence)
    assert not parent.children[0]["settled"]
    assert parent.budget["reserved"] + parent.budget["unknown"] == call["cap"]


def test_business_scorer_rejects_repair_before_inspection(tmp_path):
    case = load_business_cases()[0]

    class Provider:
        identity = {"kind": "review-offline-fixture", "version": "1"}

        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "apply_fix",
                            {
                                "ticket_id": case["expected"]["ticket_id"],
                                "fix": case["expected"]["fix"],
                            },
                        )
                    ]
                )
            if self.calls == 2:
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "inspect_ticket",
                            {
                                "ticket_id": case["expected"]["ticket_id"],
                            },
                        )
                    ]
                )
            return ModelResponse(output=case["expected"])

    report = asyncio.run(
        evaluate_business(
            Provider(), cases=[case], offline=True, evidence_dir=tmp_path / "business-evidence"
        )
    )
    assert report["passed"] == 0, report["cases"][0]
