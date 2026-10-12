import asyncio
import copy
import json
from pathlib import Path

import pytest

from ralf_agent import ModelResponse
from ralf_agent.planning_evaluation import (
    evaluate_planning,
    load_planning_cases,
    score_planning_proposal,
)


def incident_proposal():
    document = json.loads((Path(__file__).parents[1] / "evals/planning-fixtures.json").read_text())
    return copy.deepcopy(document["responses"][0]["output"])


@pytest.mark.parametrize("change", [{"required": False}, {"default": "fabricated"}])
def test_required_evidence_reference_cannot_be_weakened_to_optional_or_fabricated(change):
    proposal = incident_proposal()
    repair = next(node for node in proposal["nodes"] if node["member"] == "repair")
    repair["input"]["fields"]["diagnosis"].update(change)
    scored = score_planning_proposal(load_planning_cases()[0], proposal)
    assert scored["checks"]["arguments"] is False
    assert scored["passed"] is False


@pytest.mark.parametrize(
    "schema",
    [
        {"minProperties": 2},
        {"not": {"required": ["ticket"]}},
        {"propertyNames": {"pattern": "^other$"}},
        {"dependentRequired": {"ticket": ["approval"]}},
    ],
)
def test_static_object_binding_is_checked_against_the_complete_member_schema(schema):
    case = load_planning_cases()[0]
    case["members"][0]["input_schema"].update(schema)
    proposal = incident_proposal()
    reader = next(node for node in proposal["nodes"] if node["member"] == "read_ticket")
    reader["input"] = {
        "kind": "object",
        "fields": {"ticket": {"kind": "literal", "value": "INC-042"}},
    }
    scored = score_planning_proposal(case, proposal)
    assert scored["checks"]["arguments"] is False
    assert scored["passed"] is False


def test_nested_static_object_binding_does_not_skip_joint_schema_constraints():
    from ralf_agent.planning_evaluation import _argument_schema

    binding = {
        "kind": "object",
        "fields": {
            "request": {
                "kind": "object",
                "fields": {"ticket": {"kind": "literal", "value": "INC-042"}},
            },
        },
    }
    schema = {
        "type": "object",
        "properties": {
            "request": {"type": "object", "minProperties": 2},
        },
    }
    assert _argument_schema(binding, schema) is False


def test_offline_provider_identity_never_becomes_real_planning_quality():
    class Provider:
        identity = {"kind": "offline", "version": "1", "max_output_tokens": 2048, "timeout": 60}

        async def complete(self, messages, tools):
            return ModelResponse(output=incident_proposal())

    report = asyncio.run(evaluate_planning(Provider(), cases=load_planning_cases()[:1]))
    assert report["passed"] == 1
    assert report["scope"] == "offline-planning-fixture"
    assert report["model_quality"] is None


@pytest.mark.parametrize("mode", ["async", "lazy"])
def test_invalid_provider_preflight_cannot_dispatch_a_planning_request(mode):
    from contextlib import contextmanager

    class Provider:
        identity = {"kind": "offline", "version": "1"}
        calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            return ModelResponse(output=incident_proposal())

    async def async_validate(messages, tools):
        raise ValidationError("Request must be rejected before model I/O")

    @contextmanager
    def lazy_validate(messages, tools):
        raise ValidationError("Request must be rejected before model I/O")
        yield

    from ralf_agent.errors import ValidationError

    provider = Provider()
    provider.validate_request = async_validate if mode == "async" else lazy_validate
    report = asyncio.run(evaluate_planning(provider, cases=load_planning_cases()[:1]))
    assert report["passed"] == 0 and report["total"] == 1
    assert report["calls"] == 0 and provider.calls == 0
    assert report["model_quality"] is None


def test_public_provider_report_excludes_arbitrary_adapter_metadata():
    from ralf_agent.planning_evaluation import _safe_identity

    class Provider:
        identity = {
            "kind": "bounded-provider",
            "version": "1",
            "model": "selected-model",
            "timeout": 60,
            "max_output_tokens": 2048,
            "generation": {"temperature": 0, "adapter_private_field": "PRIVATE_MARKER"},
            "token_parameter": {"private": "PRIVATE_MARKER"},
        }

    result = _safe_identity(Provider())
    assert "PRIVATE_MARKER" not in json.dumps(result)
    assert result["generation"] == {"temperature": 0}
    assert "token_parameter" not in result
    assert result["max_output_tokens"] == 2048 and result["timeout"] == 60
    assert len(result["configuration_sha256"]) == 64


def test_long_offline_identity_remains_offline_after_report_sanitization():
    from ralf_agent.business_evaluation import evaluate_business, load_business_cases

    class Provider:
        identity = {
            "kind": "offline-" + "x" * 129,
            "version": "1",
            "max_output_tokens": 2048,
            "timeout": 60,
        }

        async def complete(self, messages, tools):
            if tools:
                return ModelResponse(
                    output={"status": "refused", "ticket_id": None, "cause": None, "fix": None}
                )
            return ModelResponse(output={"status": "refused", "reason": "Unsafe task"})

    planning = asyncio.run(evaluate_planning(Provider(), cases=load_planning_cases()[9:10]))
    business = asyncio.run(evaluate_business(Provider(), cases=load_business_cases()[-1:]))
    assert planning["passed"] == business["passed"] == 1
    assert planning["scope"] == "offline-planning-fixture" and business["offline"] is True
    assert planning["model_quality"] is None and business["model_quality"] is None
    assert "kind" not in planning["provider"] and "kind" not in business["provider"]


@pytest.mark.parametrize("sanitizer", ["planning", "compatibility"])
def test_valid_large_json_integer_metadata_does_not_overflow_report(sanitizer):
    from ralf_agent.model_compatibility import _public_identity
    from ralf_agent.planning_evaluation import _safe_identity

    class Provider:
        identity = {"kind": "offline", "version": "1", "generation": {"seed": 10**400}}

    result = (_safe_identity if sanitizer == "planning" else _public_identity)(Provider())
    assert result["generation"]["seed"] == 10**400
