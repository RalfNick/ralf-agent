import asyncio

import pytest

from relf_agent.business_evaluation import evaluate_business, load_business_cases
from relf_agent.errors import ProviderError
from relf_agent.planning_evaluation import EvaluationLimits
from relf_agent.types import ModelResponse


class BoundedProvider:
    def __init__(self, bounds):
        self.identity = {"kind": "bounded-business-provider", "version": "1", **bounds}
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        assert tools and "bypass" in messages[1]["content"].lower()
        return ModelResponse(
            output={"status": "refused", "ticket_id": None, "cause": None, "fix": None},
            usage={"input_tokens": 10, "output_tokens": 5},
        )


@pytest.mark.parametrize(
    "bounds",
    [
        {},
        {"max_output_tokens": 32},
        {"timeout": 0.5},
        {"max_output_tokens": 64, "timeout": 0.5},
        {"max_output_tokens": 32, "timeout": 1},
    ],
)
def test_live_bounds_must_match_before_evidence_or_dispatch(tmp_path, bounds):
    provider = BoundedProvider(bounds)
    directory = tmp_path / "not-created"
    report = asyncio.run(
        evaluate_business(
            provider,
            cases=load_business_cases()[-1:],
            limits=EvaluationLimits(max_cases=1, max_output_tokens=32, timeout_seconds=0.5),
            evidence_dir=directory,
        )
    )
    assert report["status"] == "not_run"
    assert report["reason"] == "provider_bounds_unverified"
    assert report["model_quality"] is None and report["calls"] == 0
    assert provider.calls == 0 and not directory.exists()


def test_matching_live_bounds_allow_managed_business_run(tmp_path):
    provider = BoundedProvider({"max_output_tokens": 32, "timeout": 0.5})
    report = asyncio.run(
        evaluate_business(
            provider,
            cases=load_business_cases()[-1:],
            limits=EvaluationLimits(max_cases=1, max_output_tokens=32, timeout_seconds=0.5),
            evidence_dir=tmp_path / "evidence",
        )
    )
    assert report["status"] == "completed" and report["passed"] == report["total"] == 1
    assert report["calls"] == 1 and provider.calls == 1
    assert report["usage"] == {"input_tokens": 10, "output_tokens": 5}


def test_bounded_failed_request_remains_in_business_denominator(tmp_path):
    class FailingProvider(BoundedProvider):
        async def complete(self, messages, tools):
            self.calls += 1
            raise ProviderError("Controlled offline provider failure")

    provider = FailingProvider({"max_output_tokens": 32, "timeout": 0.5})
    report = asyncio.run(
        evaluate_business(
            provider,
            cases=load_business_cases()[-1:],
            limits=EvaluationLimits(max_cases=1, max_output_tokens=32, timeout_seconds=0.5),
            evidence_dir=tmp_path / "evidence",
        )
    )
    assert report["status"] == "completed" and report["passed"] == 0 and report["total"] == 1
    assert report["calls"] == 1 and provider.calls == 1
    assert report["usage"] is None and report["model_quality"] == {"task_success_rate": 0}
    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["state"] == "waiting_reconciliation"
    assert report["cases"][0]["metrics"]["recovery"] is False
