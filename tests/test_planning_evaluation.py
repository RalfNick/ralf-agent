import asyncio
import copy
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from relf_agent.errors import ProviderError, ValidationError
from relf_agent.types import ModelResponse


def test_quality_suite_has_frozen_distinct_tasks_and_oracles():
    assert importlib.util.find_spec("relf_agent.planning_evaluation"), (
        "Missing planning quality runner"
    )
    from relf_agent.planning_evaluation import load_planning_cases

    cases = load_planning_cases()
    assert len(cases) >= 12
    assert len({case["id"] for case in cases}) == len(cases)
    assert all("oracle" in case and "task" in case for case in cases)


def evaluation_api():
    assert importlib.util.find_spec("relf_agent.planning_evaluation"), (
        "Missing planning quality runner"
    )
    from relf_agent.planning_evaluation import (
        EvaluationLimits,
        evaluate_planning,
        load_planning_cases,
        score_planning_proposal,
    )

    return EvaluationLimits, evaluate_planning, load_planning_cases, score_planning_proposal


def proposal():
    return {
        "status": "plan",
        "nodes": [
            {
                "id": "read",
                "member": "read_ticket",
                "depends_on": [],
                "input": {"kind": "literal", "value": {"ticket": "INC-042"}},
            },
            {
                "id": "fix",
                "member": "repair",
                "depends_on": ["read"],
                "input": {
                    "kind": "object",
                    "fields": {
                        "ticket": {"kind": "literal", "value": "INC-042"},
                        "diagnosis": {"kind": "ref", "source": "read", "path": ["diagnosis"]},
                    },
                },
            },
            {
                "id": "check",
                "member": "verify",
                "depends_on": ["fix"],
                "input": {"kind": "ref", "source": "fix", "path": []},
            },
        ],
        "output": {"kind": "ref", "source": "check", "path": []},
    }


def first_case():
    return evaluation_api()[2]()[0]


def test_oracle_accepts_renamed_ids_and_reordered_nodes():
    *_, score = evaluation_api()
    original = proposal()
    renamed = copy.deepcopy(original)
    names = {"read": "discover", "fix": "remediate", "check": "prove"}
    for node in renamed["nodes"]:
        node["id"] = names[node["id"]]
        node["depends_on"] = [names[name] for name in node["depends_on"]]
        binding = node["input"]
        if binding["kind"] == "ref":
            binding["source"] = names[binding["source"]]
        if binding["kind"] == "object":
            binding["fields"]["diagnosis"]["source"] = "discover"
    renamed["nodes"].reverse()
    renamed["output"]["source"] = "prove"
    assert score(first_case(), original)["passed"]
    assert score(first_case(), renamed)["passed"]


@pytest.mark.parametrize(
    "mutation,dimension",
    [
        ("unknown_member", "members"),
        ("missing_step", "required_steps"),
        ("wrong_argument", "arguments"),
        ("missing_dependency", "dependencies"),
        ("cycle", "dag"),
        ("wrong_output", "output"),
    ],
)
def test_oracle_rejects_semantically_wrong_plans(mutation, dimension):
    *_, score = evaluation_api()
    value = proposal()
    if mutation == "unknown_member":
        value["nodes"][1]["member"] = "delete_database"
    elif mutation == "missing_step":
        value["nodes"].pop()
        value["output"]["source"] = "fix"
    elif mutation == "wrong_argument":
        value["nodes"][0]["input"]["value"]["ticket"] = "INC-OTHER"
    elif mutation == "missing_dependency":
        value["nodes"][1]["depends_on"] = []
    elif mutation == "cycle":
        value["nodes"][0]["depends_on"] = ["check"]
    else:
        value["output"]["source"] = "read"
    result = score(first_case(), value)
    assert not result["passed"]
    assert result["checks"][dimension] is False


def test_suite_is_frozen_and_default_matches_reviewable_json():
    _, _, load, _ = evaluation_api()

    cases = load()
    assert len(cases) >= 18
    assert len({case["category"] for case in cases}) >= 18
    frozen = json.loads((Path(__file__).parents[1] / "evals/planning-cases.json").read_text())
    assert cases == frozen["cases"]
    cases[0]["task"] = "changed"
    assert load()[0]["task"] != "changed"


def test_oracle_rejects_arguments_outside_member_schema():
    *_, score = evaluation_api()
    value = proposal()
    value["nodes"][0]["input"]["value"]["unauthorized_argument"] = True
    assert score(first_case(), value)["checks"]["arguments"] is False


def test_conditional_oracle_requires_exact_branch_and_optional_output():
    _, _, load, score = evaluation_api()
    case = next(case for case in load() if case["id"] == "conditional-repair")
    value = {
        "status": "plan",
        "nodes": [
            {
                "id": "c",
                "member": "check",
                "depends_on": [],
                "input": {"kind": "literal", "value": {"service": "search"}},
            },
            {
                "id": "r",
                "member": "repair",
                "depends_on": ["c"],
                "input": {"kind": "ref", "source": "c", "path": []},
                "when": {
                    "value": {"kind": "ref", "source": "c", "path": ["healthy"]},
                    "equals": False,
                },
            },
        ],
        "output": {"kind": "ref", "source": "r", "path": [], "required": False, "default": None},
    }
    assert score(case, value)["passed"]
    value["nodes"][1]["when"]["equals"] = True
    assert score(case, value)["checks"]["conditions"] is False
    value["nodes"][1]["when"]["equals"] = False
    value["output"]["required"] = True
    assert score(case, value)["checks"]["output"] is False


def test_stop_decisions_score_expected_conclusion_and_nonempty_reason():
    _, _, load, score = evaluation_api()
    case = next(case for case in load() if case["id"] == "missing-environment")
    assert score(case, {"status": "needs_input", "reason": "Which environment?"})["passed"]
    assert not score(case, {"status": "refused", "reason": "Cannot deploy."})["passed"]
    assert not score(case, {"status": "needs_input", "reason": "  "})["passed"]


def test_parallel_evidence_oracle_rejects_unnecessary_serialization():
    _, _, load, score = evaluation_api()
    case = next(case for case in load() if case["id"] == "parallel-evidence")
    value = {
        "status": "plan",
        "nodes": [
            {
                "id": "a",
                "member": "logs",
                "depends_on": [],
                "input": {"kind": "literal", "value": {"service": "checkout"}},
            },
            {
                "id": "b",
                "member": "metrics",
                "depends_on": ["a"],
                "input": {"kind": "literal", "value": {"service": "checkout"}},
            },
            {
                "id": "c",
                "member": "summarize",
                "depends_on": ["a", "b"],
                "input": {
                    "kind": "object",
                    "fields": {
                        "logs": {"kind": "ref", "source": "a", "path": []},
                        "metrics": {"kind": "ref", "source": "b", "path": []},
                    },
                },
            },
        ],
        "output": {"kind": "ref", "source": "c", "path": []},
    }
    assert score(case, value)["checks"]["dag"]
    assert score(case, value)["checks"]["dependencies"] is False


def test_case_loader_rejects_broken_oracle_and_duplicate_case_id(tmp_path):
    _, _, load, _ = evaluation_api()
    value = {"version": "1", "cases": [first_case(), first_case()]}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValidationError):
        load(path)
    value["cases"] = [first_case()]
    value["cases"][0]["oracle"]["required_members"].append("not_registered")
    path.write_text(json.dumps(value))
    with pytest.raises(ValidationError):
        load(path)


class OfflinePlanningProvider:
    identity = {"kind": "scripted-test", "version": "1", "model": "fixture"}

    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        assert tools == []
        value = next(self.results)
        if isinstance(value, Exception):
            raise value
        return value


def test_runner_records_managed_child_usage_and_failure_denominator(tmp_path):
    Limits, evaluate, _, _ = evaluation_api()
    provider = OfflinePlanningProvider(
        [
            ModelResponse(output=proposal(), usage={"input_tokens": 200, "output_tokens": 80}),
            ProviderError("do not print credential abc-SECRET"),
            ModelResponse(output={"status": "plan", "nodes": "bad-SENSITIVE"}),
        ]
    )
    report = asyncio.run(
        evaluate(
            provider,
            cases=[first_case()],
            limits=Limits(max_cases=1, repeats=3, max_calls=3),
            evidence_dir=tmp_path,
            offline=True,
            prices={"input_per_million_usd": 1, "output_per_million_usd": 2},
        )
    )
    assert report["scope"] == "offline-planning-fixture"
    assert report["total"] == 3 and report["passed"] == 1
    assert report["pass_rate"] == pytest.approx(1 / 3)
    assert report["model_quality"] is None
    assert report["calls"] == 3
    assert report["usage"] is None and report["cost_usd"] is None
    assert report["cases"][0]["usage"] == {"input_tokens": 200, "output_tokens": 80}
    assert report["cases"][0]["usage_source"] == "provider"
    assert report["cases"][0]["cost_usd"] == pytest.approx(0.00036)
    assert all(case["latency_ms"] >= 0 for case in report["cases"])
    assert all(case["run_id"] for case in report["cases"])
    assert all(case["evidence"]["sha256"] for case in report["cases"] if case["evidence"])
    assert "SECRET" not in json.dumps(report)
    assert "SENSITIVE" not in json.dumps(report)
    assert list(tmp_path.glob("*.sqlite"))
    with sqlite3.connect(tmp_path / "incident-sequence-2.sqlite") as conn:
        retained = conn.execute("SELECT data FROM runs").fetchone()[0]
    assert "bad-SENSITIVE" in retained
    assert (tmp_path / "incident-sequence-2.sqlite").stat().st_mode & 0o777 == 0o600


def test_call_bound_keeps_unattempted_cases_in_denominator(tmp_path):
    Limits, evaluate, _, _ = evaluation_api()
    provider = OfflinePlanningProvider([ModelResponse(output=proposal())])
    report = asyncio.run(
        evaluate(
            provider,
            cases=[first_case()],
            limits=Limits(max_cases=1, repeats=3, max_calls=1),
            evidence_dir=tmp_path,
            offline=True,
        )
    )
    assert report["total"] == 3 and report["passed"] == 1
    assert report["calls"] == provider.calls == 1
    assert [case["status"] for case in report["cases"]] == [
        "passed",
        "budget_exhausted",
        "budget_exhausted",
    ]


def test_money_cap_fails_closed_without_token_cost_guarantee(tmp_path):
    Limits, evaluate, _, _ = evaluation_api()
    provider = OfflinePlanningProvider([ModelResponse(output=proposal())])
    report = asyncio.run(
        evaluate(
            provider,
            cases=[first_case()],
            limits=Limits(max_cost_usd=0.01),
            evidence_dir=tmp_path,
        )
    )
    assert report["status"] == "not_run"
    assert report["reason"] == "cost_cap_not_enforceable"
    assert report["calls"] == provider.calls == 0
    assert report["pass_rate"] is None


def test_missing_provider_reports_not_run():
    Limits, evaluate, _, _ = evaluation_api()
    report = asyncio.run(evaluate(None, limits=Limits(max_cases=2)))
    assert report["status"] == "not_run"
    assert report["total"] == 2 and report["passed"] == 0
    assert report["model_quality"] is None
    assert report["reason"] == "provider_not_configured"


def test_timeout_is_a_failure_and_keeps_call_and_unknown_usage(tmp_path):
    Limits, evaluate, _, _ = evaluation_api()

    class DelayedProvider:
        identity = {"kind": "scripted-test", "version": "1"}

        async def complete(self, messages, tools):
            await asyncio.sleep(10)

    report = asyncio.run(
        evaluate(
            DelayedProvider(),
            cases=[first_case()],
            limits=Limits(max_cases=1, timeout_seconds=0.01),
            evidence_dir=tmp_path,
            offline=True,
        )
    )
    assert report["total"] == report["calls"] == 1
    assert report["cases"][0]["status"] == "timeout"
    assert report["usage"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_cases": 0},
        {"max_calls": -1},
        {"repeats": True},
        {"timeout_seconds": float("inf")},
        {"max_cost_usd": -1},
    ],
)
def test_limits_reject_unbounded_or_invalid_configuration(kwargs):
    Limits, *_ = evaluation_api()
    with pytest.raises(ValidationError):
        Limits(**kwargs)


def test_cli_default_reports_not_run_without_a_model():
    from .test_cli import ROOT, subprocess_env

    script = ROOT / "examples/evaluate_planning.py"
    assert script.exists(), "Missing planning evaluation command"
    completed = subprocess.run(
        [sys.executable, str(script), "--max-cases", "2"],
        env=subprocess_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "not_run"
    assert report["reason"] == "provider_not_configured"
    assert report["total"] == 2 and report["calls"] == 0


def test_cli_explicit_offline_fixtures_are_not_model_quality(tmp_path):
    from .test_cli import ROOT, subprocess_env

    script = ROOT / "examples/evaluate_planning.py"
    assert script.exists(), "Missing planning evaluation command"
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "version": "1",
                "responses": [
                    {
                        "case_id": "incident-sequence",
                        "output": proposal(),
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                    }
                ],
            }
        )
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--fixture",
            str(fixture),
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ],
        env=subprocess_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["scope"] == "offline-planning-fixture"
    assert report["total"] == report["passed"] == 1
    assert report["model_quality"] is None
    assert list((tmp_path / "evidence").glob("*.sqlite"))


def test_cli_refuses_missing_env_without_echoing_values(tmp_path):
    from .test_cli import ROOT, subprocess_env

    script = ROOT / "examples/evaluate_planning.py"
    assert script.exists(), "Missing planning evaluation command"
    env = subprocess_env()
    env["EVAL_PRIVATE_KEY"] = "SENSITIVE-DO-NOT-PRINT"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--provider",
            "anthropic",
            "--model-env",
            "EVAL_MODEL_UNSET",
            "--key-env",
            "EVAL_PRIVATE_KEY",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 2
    report = json.loads(completed.stdout)
    assert report["status"] == "not_run"
    assert report["reason"] == "model_not_configured"
    assert "SENSITIVE" not in completed.stdout + completed.stderr


def test_cli_applies_case_bound_to_larger_offline_fixture():
    from .test_cli import ROOT, subprocess_env

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples/evaluate_planning.py"),
            "--fixture",
            str(ROOT / "evals/planning-fixtures.json"),
            "--max-cases",
            "1",
        ],
        env=subprocess_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["total"] == report["passed"] == report["calls"] == 1


def test_native_http_transport_fixture_keeps_json_text_usage_and_model_identity(tmp_path):
    from relf_agent.providers import OpenAIChatProvider

    Limits, evaluate, _, _ = evaluation_api()
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(proposal())}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 500, "completion_tokens": 120},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIChatProvider(
                "transport-fixture-model",
                api_key="local-fixture-key",
                client=client,
                max_output_tokens=512,
                timeout=3,
            )
            return await evaluate(
                provider,
                cases=[first_case()],
                limits=Limits(max_cases=1, max_calls=1, max_output_tokens=512, timeout_seconds=3),
                evidence_dir=tmp_path,
                offline=True,
            )

    report = asyncio.run(run())
    assert report["passed"] == report["total"] == report["calls"] == 1
    assert report["provider"]["model"] == "transport-fixture-model"
    assert report["usage"] == {"input_tokens": 500, "output_tokens": 120}
    assert report["scope"] == "offline-planning-fixture" and report["model_quality"] is None
    assert requests[0]["max_completion_tokens"] == 512
    assert requests[0].get("tools", []) == []
    assert "oracle" not in requests[0]["messages"][-1]["content"]


def test_real_http_provider_bounds_are_verified_before_any_call():
    from relf_agent.providers import OpenAIChatProvider

    Limits, evaluate, _, _ = evaluation_api()
    provider = OpenAIChatProvider(
        "configured-model", api_key="local-fixture-key", max_output_tokens=100, timeout=1
    )
    report = asyncio.run(
        evaluate(
            provider,
            cases=[first_case()],
            limits=Limits(max_cases=1, max_output_tokens=512, timeout_seconds=3),
        )
    )
    assert report["status"] == "not_run"
    assert report["reason"] == "provider_bounds_unverified"
    assert report["calls"] == 0


def test_cli_existing_report_is_rejected_before_creating_runs(tmp_path):
    from .test_cli import ROOT, subprocess_env

    report = tmp_path / "previous.json"
    report.write_text("previous evidence")
    evidence = tmp_path / "new-evidence"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples/evaluate_planning.py"),
            "--fixture",
            str(ROOT / "evals/planning-fixtures.json"),
            "--report",
            str(report),
            "--evidence-dir",
            str(evidence),
        ],
        env=subprocess_env(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 2
    assert report.read_text() == "previous evidence"
    assert not evidence.exists()


def test_non_json_provider_output_remains_a_counted_failure(tmp_path):
    Limits, evaluate, _, _ = evaluation_api()
    provider = OfflinePlanningProvider(
        [ModelResponse(output={"status": "plan", "invalid": float("nan")})]
    )
    report = asyncio.run(
        evaluate(
            provider,
            cases=[first_case()],
            limits=Limits(max_cases=1),
            evidence_dir=tmp_path,
            offline=True,
        )
    )
    assert report["total"] == report["calls"] == 1
    assert report["passed"] == 0
    assert report["cases"][0]["evidence"]["invalid_json"] is True
    assert report["cases"][0]["evidence"]["sha256"]
