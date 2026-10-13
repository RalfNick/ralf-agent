"""Bounded plan proposals, managed model planning and pure verification."""

import re
from typing import Protocol

from .dag_planning import DAGProposal, PlanningConclusion
from .errors import ValidationError
from .orchestration_types import ChildCall, _JsonValue
from .types import AgentSpec, canonical

PlanStep = ChildCall


class PlanningRequest(_JsonValue):
    def __init__(
        self,
        task,
        members,
        results,
        revision,
        capabilities=None,
        constraints=None,
        verification_feedback=None,
    ):
        if (
            capabilities is not None
            and not isinstance(capabilities, dict)
            or constraints is not None
            and not isinstance(constraints, dict)
        ):
            raise ValidationError("Planning capabilities/constraints require JSON objects")
        if verification_feedback is not None:
            value = verification_feedback
            if (
                type(value) is not dict
                or set(value) != {"revision", "feedback", "evidence_ids", "source_digest"}
                or type(value["revision"]) is not int
                or value["revision"] < 0
                or type(revision) is not int
                or value["revision"] != revision - 1
                or not isinstance(value["feedback"], str)
                or not value["feedback"].strip()
                or len(value["feedback"]) > 4096
                or type(value["evidence_ids"]) is not list
                or len(value["evidence_ids"]) > 256
                or any(not isinstance(item, str) or not item for item in value["evidence_ids"])
                or len(set(value["evidence_ids"])) != len(value["evidence_ids"])
                or not isinstance(value["source_digest"], str)
                or re.fullmatch(r"[a-f0-9]{64}", value["source_digest"]) is None
            ):
                raise ValidationError(
                    "Planner feedback requires a bounded original verification source"
                )
        self._data_json = canonical(
            {
                "task": task,
                "members": list(members),
                "results": results,
                "revision": revision,
                **({"capabilities": capabilities} if capabilities is not None else {}),
                **({"constraints": constraints} if constraints is not None else {}),
                **(
                    {"verification_feedback": verification_feedback}
                    if verification_feedback is not None
                    else {}
                ),
            }
        )


class PlanProposal(_JsonValue):
    def __init__(self, steps):
        if (
            not isinstance(steps, (tuple, list))
            or not 1 <= len(steps) <= 256
            or any(not isinstance(step, ChildCall) for step in steps)
        ):
            raise ValidationError("Plan proposals require 1 to 256 registered steps")
        self._data_json = canonical({"steps": [step.to_dict() for step in steps]})


class Verification(_JsonValue):
    def __init__(self, status, result=None):
        if status not in {"succeeded", "failed", "replan"}:
            raise ValidationError("Verifier must succeed, fail or request bounded replanning")
        self._data_json = canonical({"status": status, "result": result})


class Planner(Protocol):
    identity: dict

    async def plan(
        self, request: PlanningRequest, caller
    ) -> PlanProposal | DAGProposal | PlanningConclusion | None: ...


class PlanVerifier(Protocol):
    identity: dict

    def verify(self, request: PlanningRequest) -> Verification: ...


class RulePlanner:
    def __init__(self, members=None):
        self._members = None if members is None else tuple(members)
        if self._members is not None and (
            not self._members or any(not isinstance(name, str) for name in self._members)
        ):
            raise ValidationError("RulePlanner members must be a non-empty sequence")

    @property
    def identity(self):
        return {"kind": "rule-planner", "version": "1", "members": self._members}

    async def plan(self, request, caller):
        return PlanProposal(
            [
                PlanStep(f"step-{index}", name, {"task": request.task, "prior": request.results})
                for index, name in enumerate(self._members or request.members)
            ]
        )


class CompleteVerifier:
    identity = {"kind": "complete-plan-verifier", "version": "1"}

    def verify(self, request):
        return Verification("succeeded", request.results[-1]["result"])


class ModelPlanner:
    """Uses an allowlisted, tool-free child Agent; no hidden Provider loop."""

    def __init__(self, *, provider="default", instructions=None, version="1"):
        self.agent = AgentSpec(
            "planner",
            instructions
            or (
                "Return a JSON object with steps: [{id,member,input}]. "
                "Use only the supplied member names; do not execute tools."
            ),
            provider=provider,
            version=version,
            max_decisions=1,
            output_schema={
                "type": "object",
                "required": ["steps"],
                "additionalProperties": False,
                "properties": {
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 256,
                        "items": {
                            "type": "object",
                            "required": ["id", "member", "input"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "member": {"type": "string"},
                                "input": {},
                            },
                        },
                    }
                },
            },
        )

    @property
    def identity(self):
        from dataclasses import asdict

        return {"kind": "model-planner", "version": "1", "agent": asdict(self.agent)}

    async def plan(self, request, caller):
        result = await caller.call("planner", "@planner", request.to_dict())
        if result.state not in {"succeeded", "failed", "cancelled"}:
            return None
        if result.state != "succeeded":
            raise ValidationError("The managed planner Agent did not succeed")
        output = result.result
        if not isinstance(output, dict) or set(output) != {"steps"}:
            raise ValidationError("Model planner must return an explicit steps object")
        try:
            return PlanProposal([PlanStep(**step) for step in output["steps"]])
        except (TypeError, KeyError) as exc:
            raise ValidationError("Model planner returned invalid steps") from exc
