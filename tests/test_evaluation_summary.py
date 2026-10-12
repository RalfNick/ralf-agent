import asyncio

import pytest

from ralf_agent.errors import ValidationError


def summarize(rows):
    from ralf_agent.evaluation_summary import summarize_evaluation

    return summarize_evaluation(rows)


def test_repeated_quality_keeps_failure_and_unattempted_rows_in_denominator():
    rows = [
        {"case_id": "repair", "repeat": 0, "passed": True, "calls": 3, "metrics": {"stop": True}},
        {"case_id": "repair", "repeat": 1, "passed": False, "calls": 1, "metrics": {"stop": False}},
        {"case_id": "repair", "repeat": 2, "passed": False, "calls": 0},
        {"case_id": "refuse", "repeat": 0, "passed": True, "calls": 1, "metrics": {"stop": True}},
        {"case_id": "refuse", "repeat": 1, "passed": True, "calls": 1, "metrics": {"stop": True}},
        {"case_id": "refuse", "repeat": 2, "passed": True, "calls": 1, "metrics": {"stop": True}},
    ]
    result = summarize(rows)
    assert result["total"] == 6 and result["passed"] == 4
    assert result["attempted"] == 5 and result["calls"] == 7
    assert result["pass_rate"] == pytest.approx(2 / 3)
    assert result["repeated_case_count"] == 2
    assert result["all_repeats_passed_count"] == 1
    assert result["mixed_outcome_case_count"] == 1
    assert result["per_case"]["repair"] == {
        "total": 3,
        "passed": 1,
        "attempted": 2,
        "calls": 4,
        "pass_rate": 1 / 3,
        "all_repeats_passed": False,
        "mixed_outcomes": True,
    }
    assert result["dimensions"]["stop"] == {"passed": 4, "total": 6, "rate": 2 / 3}
    assert "model_quality" not in result


def test_checks_and_metrics_are_separate_measurements_and_detached():
    rows = [
        {
            "case_id": "plan",
            "repeat": 0,
            "passed": False,
            "calls": 1,
            "checks": {"arguments": False, "stop": True},
        },
        {
            "case_id": "plan",
            "repeat": 1,
            "passed": True,
            "calls": 1,
            "checks": {"arguments": True, "stop": True},
        },
    ]
    result = summarize(rows)
    assert result["dimensions"]["arguments"] == {"passed": 1, "total": 2, "rate": 0.5}
    assert result["dimensions"]["stop"]["rate"] == 1
    result["per_case"]["plan"]["total"] = 99
    assert summarize(rows)["per_case"]["plan"]["total"] == 2


@pytest.mark.parametrize(
    "rows",
    [
        [{"case_id": "x", "repeat": 0, "passed": True, "calls": True}],
        [{"case_id": "x", "repeat": 0, "passed": 1, "calls": 1}],
        [{"case_id": "x", "repeat": 0, "passed": True, "calls": -1}],
        [{"case_id": "x", "repeat": 0, "passed": True, "calls": 1}] * 2,
        [{"case_id": "x", "repeat": True, "passed": True, "calls": 1}],
        [{"case_id": "x", "repeat": 0, "passed": True, "calls": 1, "checks": {"stop": 1}}],
    ],
)
def test_summary_rejects_counts_that_could_fabricate_quality(rows):
    with pytest.raises(ValidationError):
        summarize(rows)


def test_empty_summary_has_no_quality_rate():
    result = summarize([])
    assert result["total"] == 0 and result["pass_rate"] is None and result["per_case"] == {}


def test_business_evaluator_exports_repeats_without_claiming_offline_quality():
    from ralf_agent.business_evaluation import evaluate_business, load_business_cases
    from ralf_agent.business_evaluation_cli import _OfflineBusinessProvider
    from ralf_agent.planning_evaluation import EvaluationLimits

    report = asyncio.run(
        evaluate_business(
            _OfflineBusinessProvider(),
            cases=load_business_cases()[-1:],
            limits=EvaluationLimits(repeats=3, max_calls=1),
            offline=True,
        )
    )
    assert report["total"] == 3 and report["passed"] == 1
    assert report["summary"]["attempted"] == 1
    assert report["summary"]["per_case"]["bypass-approval"]["passed"] == 1
    assert report["summary"]["all_repeats_passed_count"] == 0
    assert report["model_quality"] is None


def test_planning_evaluator_exports_unattempted_repeats_and_real_oracle_failures():
    from ralf_agent import ModelResponse
    from ralf_agent.planning_evaluation import (
        EvaluationLimits,
        evaluate_planning,
        load_planning_cases,
    )

    class Provider:
        identity = {"kind": "offline-summary-fixture", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(output={"status": "refused", "reason": "Cannot repair"})

    report = asyncio.run(
        evaluate_planning(
            Provider(),
            cases=load_planning_cases()[:1],
            offline=True,
            limits=EvaluationLimits(repeats=2, max_calls=1),
        )
    )
    assert report["passed"] == 0 and report["total"] == 2
    assert report["summary"]["attempted"] == 1
    assert report["summary"]["dimensions"]["decision"]["rate"] == 0
    assert report["model_quality"] is None
