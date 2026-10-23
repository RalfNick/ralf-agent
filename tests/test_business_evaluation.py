import asyncio
import importlib.util

from relf_agent import ModelResponse, ToolCall
from relf_agent.planning_evaluation import EvaluationLimits


def evaluator():
    assert importlib.util.find_spec("relf_agent.business_evaluation"), (
        "Missing end-to-end business evaluation"
    )
    from relf_agent.business_evaluation import evaluate_business, load_business_cases

    return evaluate_business, load_business_cases


def test_default_report_does_not_invent_real_model_quality():
    evaluate, load = evaluator()
    cases = load()
    assert (
        len({case["expected"]["fix"] for case in cases if case["expected"]["status"] == "resolved"})
        >= 3
    )
    report = asyncio.run(evaluate(None))
    assert (
        report["status"] == "not_run" and report["model_quality"] is None and report["calls"] == 0
    )


def test_offline_business_runs_score_tool_arguments_stop_approval_and_real_effects():
    evaluate, load = evaluator()
    cases = load()[:3]

    class Provider:
        identity = {"kind": "business-fixture", "version": "1"}
        responses = []

        async def complete(self, messages, tools):
            return self.responses.pop(0)

    provider = Provider()
    for case in cases:
        expected = case["expected"]
        ticket = case["ticket"]["id"]
        provider.responses.extend(
            [
                ModelResponse(tool_calls=[ToolCall("inspect_ticket", {"ticket_id": ticket})]),
                ModelResponse(
                    tool_calls=[
                        ToolCall("apply_fix", {"ticket_id": ticket, "fix": expected["fix"]})
                    ]
                ),
                ModelResponse(output=expected),
            ]
        )
    report = asyncio.run(
        evaluate(
            provider, cases=cases, offline=True, limits=EvaluationLimits(max_cases=3, max_calls=12)
        )
    )
    assert report["passed"] == 3 and report["model_quality"] is None and report["calls"] == 9
    for row in report["cases"]:
        assert (
            row["metrics"]["tool_arguments"]
            and row["metrics"]["approval"]
            and row["metrics"]["stop"]
        )
        assert row["business_writes"] == 1 and row["replay_same_receipt"]


def test_wrong_tool_parameters_are_denied_and_scored_as_failure():
    evaluate, load = evaluator()

    class Provider:
        identity = {"kind": "wrong-parameters", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(
                tool_calls=[ToolCall("apply_fix", {"ticket_id": "other", "fix": "delete_all"})]
            )

    report = asyncio.run(evaluate(Provider(), cases=load()[:1], offline=True))
    assert report["passed"] == 0 and report["cases"][0]["business_writes"] == 0
    assert not report["cases"][0]["metrics"]["tool_arguments"]


def test_injected_case_paths_are_validated_before_creating_private_evidence(tmp_path):
    import copy

    import pytest

    from relf_agent.errors import ValidationError

    evaluate, load = evaluator()
    case = copy.deepcopy(load()[0])
    case["id"] = "../escape"

    class Provider:
        identity = {"kind": "never-called", "version": "1"}
        calls = 0

        async def complete(self, *args):
            self.calls += 1
            raise AssertionError("Must reject preflight")

    provider = Provider()
    with pytest.raises(ValidationError):
        asyncio.run(evaluate(provider, cases=[case], evidence_dir=tmp_path / "private"))
    assert not (tmp_path / "escape-0.sqlite").exists() and provider.calls == 0


def test_usage_is_aggregated_and_fixture_identity_cannot_claim_quality():
    evaluate, load = evaluator()

    class Provider:
        identity = {"kind": "fixture", "version": "1"}

        async def complete(self, messages, tools):
            return ModelResponse(
                output=load()[-1]["expected"], usage={"input_tokens": 100, "output_tokens": 10}
            )

    report = asyncio.run(
        evaluate(
            Provider(),
            cases=load()[-1:],
            prices={"input_per_million_usd": 1, "output_per_million_usd": 2},
        )
    )
    assert report["model_quality"] is None
    assert report["usage"] == {"input_tokens": 100, "output_tokens": 10}
    assert report["cost_usd"] == 0.00012
    assert report["cases"][0]["recovered_after_restart"]


def test_invalid_injected_id_has_typed_preflight_error():
    import copy

    import pytest

    from relf_agent.errors import ValidationError

    evaluate, load = evaluator()
    case = copy.deepcopy(load()[0])
    case["id"] = []
    with pytest.raises(ValidationError):
        asyncio.run(evaluate(cases=[case]))


def test_offline_cli_runs_distinct_fixtures_with_bounded_calls(capsys):
    import json

    from relf_agent.business_evaluation_cli import main

    assert main(["--offline", "--max-calls", "16"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] == 8 and report["calls"] == 15 and report["model_quality"] is None


def test_evaluation_discloses_strict_output_contract_to_real_provider():
    from relf_agent.business_evaluation_cli import _OfflineBusinessProvider

    class ContractProvider(_OfflineBusinessProvider):
        async def complete(self, messages, tools):
            assert '"additionalProperties":false' in messages[0]["content"]
            assert "no Markdown" in messages[0]["content"]
            assert "connection_pool_exhausted" in messages[0]["content"]
            return await super().complete(messages, tools)

    evaluate, load = evaluator()
    report = asyncio.run(evaluate(ContractProvider(), cases=load()[:1], offline=True))
    assert report["passed"] == 1
