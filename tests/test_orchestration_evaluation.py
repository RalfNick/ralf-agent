import asyncio
import copy
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ralf_agent.errors import ProviderError, ValidationError
from ralf_agent.planning_evaluation import EvaluationLimits
from ralf_agent.storage import SQLiteStore
from ralf_agent.types import ModelResponse, ToolCall


def api():
    assert importlib.util.find_spec("ralf_agent.orchestration_evaluation"), (
        "Missing managed orchestration task evaluation"
    )
    from ralf_agent.orchestration_evaluation import (
        OfflineOrchestrationProvider,
        evaluate_orchestration,
        load_orchestration_cases,
    )

    return evaluate_orchestration, load_orchestration_cases, OfflineOrchestrationProvider


def test_default_is_not_run_and_cases_are_detached_and_varied():
    evaluate, load, _ = api()
    cases = load()
    assert len(cases) >= 4
    assert len({c["dataset"]["id"] for c in cases}) >= 2
    assert {c["expected"]["status"] for c in cases} >= {"completed", "needs_input", "not_found"}
    cases[0]["dataset"]["inventory"][0]["unit_price_cents"] = 999
    assert cases != load()
    report = asyncio.run(evaluate())
    assert report["status"] == "not_run" and report["reason"] == "provider_not_configured"
    assert report["model_quality"] is None and report["calls"] == 0


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_borrowed_provider_method_change_rejects_original_result(kind, tmp_path):
    evaluate, load, fixture = api()

    class Switching(fixture):
        async def complete(self, messages, tools):
            result = await super().complete(messages, tools)

            async def replacement(messages, tools):
                return result

            self.complete = replacement
            return result

    report = asyncio.run(evaluate(Switching(), kind=kind, cases=load()[:1], evidence_dir=tmp_path))
    assert report["calls"] == 1 and report["passed"] == 0


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_known_text_only_provider_is_not_a_model_quality_failure(kind, tmp_path):
    evaluate, load, _ = api()
    from ralf_agent.model_native import GeminiProvider

    provider = GeminiProvider(
        "sample-model",
        api_key="local-placeholder",
        base_url="https://must-not-contact.invalid",
        max_output_tokens=2048,
        timeout=60,
    )
    report = asyncio.run(evaluate(provider, kind=kind, cases=load()[:1], evidence_dir=tmp_path))
    assert report["status"] == "not_run" and report["reason"] == "provider_tools_unsupported"
    assert report["model_quality"] is None and report["calls"] == 0
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_real_managed_members_consume_receipts_and_reconnect(kind, tmp_path):
    evaluate, load, fixture = api()
    provider = fixture()
    cases = load()
    report = asyncio.run(
        evaluate(
            provider,
            kind=kind,
            evidence_dir=tmp_path,
            limits=EvaluationLimits(max_calls=100, repeats=2),
        )
    )
    assert report["status"] == "completed"
    assert report["passed"] == report["total"] == len(cases) * 2
    assert report["model_quality"] is None and report["provider"]["offline_fixture"]
    assert report["summary"]["all_repeats_passed_count"] == len(cases)
    for row in report["cases"]:
        assert all(row["checks"].values()), row
        assert row["replay_same_receipt"] and row["recovered_after_restart"]
        assert row["recovery"]["additional_calls"] == 0
        path = tmp_path / f"{row['case_id']}-{row['repeat']}.sqlite"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        with SQLiteStore(path, readonly=True) as store:
            parent = store.run(row["run_id"])
            children = parent["orchestration"]["children"]
            assert [child["member"] for child in children] == ["researcher", "writer"]
            assert parent["manifest"]["runtime_profile"]["version"] == "2"
            researcher, writer = [store.run(child["run_id"]) for child in children]
            first_writer_request = next(a for a in writer["actions"] if a["kind"] == "model")
            incoming = json.loads(first_writer_request["snapshot"][1]["content"])
            assert (
                incoming["results"]["researcher"] if kind == "team" else incoming
            ) == researcher["result"]
            if parent["result"]["status"] == "completed":
                assert [a["tool"] for a in researcher["actions"] if a["kind"] == "tool"] == [
                    "inventory_lookup"
                ]
                assert [a["tool"] for a in writer["actions"] if a["kind"] == "tool"] == [
                    "calculator"
                ]
    exported = json.dumps(report)
    for case in cases:
        assert case["task"] not in exported
        assert json.dumps(case["expected"]) not in exported


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
@pytest.mark.parametrize("fault", ["wrong-calculator", "no-calculator", "no-lookup"])
def test_correct_final_total_cannot_hide_bogus_or_missing_receipts(kind, fault, tmp_path):
    evaluate, load, fixture = api()
    case = load()[0]
    request = case["request"]
    item = next(i for i in case["dataset"]["inventory"] if i["sku"] == request["target"])

    class Wrong(fixture):
        async def complete(self, messages, tools):
            writer = any(t["function"]["name"] == "calculator" for t in tools)
            if fault == "no-lookup" and not writer:
                return ModelResponse(
                    output={
                        "request": request,
                        "lookup": {
                            "found": True,
                            "dataset_id": request["dataset_id"],
                            "target": request["target"],
                            "item": item,
                        },
                    }
                )
            if writer:
                if fault == "no-calculator" or any(m["role"] == "tool" for m in messages):
                    return ModelResponse(output=case["expected"])
                if fault == "wrong-calculator":
                    return ModelResponse(
                        tool_calls=[
                            ToolCall(
                                "calculator",
                                {
                                    "quantity": request["quantity"] + 1,
                                    "unit_price_cents": item["unit_price_cents"],
                                },
                            )
                        ]
                    )
            return await super().complete(messages, tools)

    report = asyncio.run(evaluate(Wrong(), kind=kind, cases=[case], evidence_dir=tmp_path))
    row = report["cases"][0]
    assert row["state"] == "succeeded" and row["checks"]["total"]
    assert not row["passed"] and report["passed"] == 0
    check = "lookup_receipt" if fault == "no-lookup" else "calculator_receipt"
    assert not row["checks"][check]


def test_global_call_cap_keeps_unattempted_repeats_in_denominator(tmp_path):
    evaluate, load, fixture = api()
    report = asyncio.run(
        evaluate(
            fixture(),
            cases=load()[:2],
            evidence_dir=tmp_path,
            limits=EvaluationLimits(max_calls=5, repeats=2),
        )
    )
    assert report["calls"] == 5 and report["total"] == 4
    assert report["passed"] == 1 and len(report["cases"]) == 4
    assert [row["calls"] for row in report["cases"]] == [4, 1, 0, 0]
    assert report["summary"]["attempted"] == 2
    assert report["summary"]["dimensions"]["total"]["total"] == 4


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_unknown_provider_failure_observes_recovery_without_retry(kind, tmp_path):
    evaluate, load, fixture = api()

    class Failure(fixture):
        calls = 0
        closed = 0

        def close(self):
            self.closed += 1

        async def complete(self, messages, tools):
            self.calls += 1
            raise ProviderError("privateAdapterException secret-task-answer")

    provider = Failure()
    report = asyncio.run(evaluate(provider, kind=kind, cases=load()[:1], evidence_dir=tmp_path))
    assert provider.calls == report["calls"] == 1 and provider.closed == 0
    assert report["passed"] == 0 and report["usage"] is None
    row = report["cases"][0]
    assert row["state"] == "outcome_unknown"
    assert row["members"][0]["state"] == "waiting_reconciliation"
    assert row["recovery"]["mode"] == "observation_only"
    assert row["recovery"]["additional_calls"] == 0
    assert not row["checks"]["recovery"] and not row["recovered_after_restart"]
    assert "privateAdapterException" not in json.dumps(report)


def test_provider_bounds_cost_and_fixture_classification_preflight(tmp_path):
    evaluate, load, fixture = api()

    class Live(fixture):
        identity = {"kind": "bounded-inventory", "version": "1", "privateAdapter": "secret"}

    for provider, limits, reason in [
        (Live(), EvaluationLimits(), "provider_bounds_unverified"),
        (fixture(), EvaluationLimits(max_cost_usd=0), "cost_cap_not_enforceable"),
    ]:
        report = asyncio.run(
            evaluate(provider, cases=load()[:1], limits=limits, evidence_dir=tmp_path / reason)
        )
        assert report["status"] == "not_run" and report["reason"] == reason
        assert report["calls"] == 0 and not (tmp_path / reason).exists()
        assert "privateAdapter" not in json.dumps(report)


def test_schema_validation_and_fresh_evidence_fail_before_provider_io(tmp_path):
    evaluate, load, fixture = api()
    bad = copy.deepcopy(load()[0])
    bad["id"] = "../escape"
    with pytest.raises(ValidationError):
        asyncio.run(evaluate(fixture(), cases=[bad], evidence_dir=tmp_path / "new"))
    assert not (tmp_path / "new").exists()
    cases = load()[:1]
    path = tmp_path / f"{cases[0]['id']}-0.sqlite"
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(ValidationError, match="fresh"):
        asyncio.run(evaluate(fixture(), cases=cases, evidence_dir=tmp_path))


def test_borrowed_bounded_provider_usage_has_provenance_and_prices(tmp_path):
    evaluate, load, fixture = api()

    class Bounded:
        identity = {
            "kind": "inventory-adapter",
            "version": "1",
            "max_output_tokens": 64,
            "timeout": 0.5,
            "privateAdapter": {"endpoint": "private-token"},
        }
        closed = 0

        async def aclose(self):
            self.closed += 1

        async def complete(self, messages, tools):
            response = await fixture().complete(messages, tools)
            return ModelResponse(
                output=response.output,
                tool_calls=response.tool_calls,
                usage={"input_tokens": 10, "output_tokens": 2, "source": "privateAdapterException"},
            )

    provider = Bounded()
    report = asyncio.run(
        evaluate(
            provider,
            cases=load()[:1],
            evidence_dir=tmp_path,
            limits=EvaluationLimits(max_output_tokens=64, timeout_seconds=0.5),
            prices={"input_per_million_usd": 1, "output_per_million_usd": 2},
        )
    )
    assert report["passed"] == 1 and report["calls"] == 4
    assert provider.closed == 0
    assert report["usage"] == {"input_tokens": 40, "output_tokens": 8}
    assert report["cost_usd"] == pytest.approx(0.000056)
    assert report["usage_provenance"] == {
        "source": "provider-reported",
        "known_usage_calls": 4,
        "unknown_usage_calls": 0,
    }
    assert report["cases"][0]["components_sha256"]
    assert report["model_quality"] == {"task_success_rate": 1}
    assert "privateAdapter" not in json.dumps(report) and "private-token" not in json.dumps(report)


def test_arbitrary_exception_code_is_not_exported(tmp_path):
    evaluate, load, fixture = api()

    class SecretError(ProviderError):
        code = ["privateAdapterException"]

    class Broken(fixture):
        async def complete(self, messages, tools):
            raise SecretError("privateAdapterException")

    report = asyncio.run(evaluate(Broken(), cases=load()[:1], evidence_dir=tmp_path))
    assert report["passed"] == 0 and report["calls"] == 1
    assert report["attempt_statuses"] == {"provider_failure": 1}
    assert "privateAdapterException" not in json.dumps(report)


def test_timeout_and_missing_usage_do_not_become_known_cost(tmp_path):
    evaluate, load, fixture = api()

    class Slow(fixture):
        calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            await asyncio.sleep(0.1)
            return await super().complete(messages, tools)

    provider = Slow()
    report = asyncio.run(
        evaluate(
            provider,
            cases=load()[:1],
            evidence_dir=tmp_path,
            limits=EvaluationLimits(timeout_seconds=0.005),
            prices={"input_per_million_usd": 1, "output_per_million_usd": 1},
        )
    )
    assert provider.calls == report["calls"] == 1
    assert report["attempt_statuses"] == {"timeout": 1}
    assert report["usage"] is None and report["cost_usd"] is None
    assert report["usage_provenance"]["unknown_usage_calls"] == 1
    assert report["cases"][0]["recovery"]["additional_calls"] == 0


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_missing_quantity_and_stock_stop_without_calculator(kind):
    evaluate, load, fixture = api()
    cases = [copy.deepcopy(load()[0]), copy.deepcopy(load()[1])]
    cases[0]["request"]["quantity"] = None
    cases[1]["request"]["quantity"] = 99
    for case in cases:
        case["expected"] = {"status": "needs_input", "total": None}
    report = asyncio.run(evaluate(fixture(), kind=kind, cases=cases))
    assert report["passed"] == 2 and report["calls"] == 5
    assert [row["members"][1]["tool_actions"] for row in report["cases"]] == [0, 0]


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_process_exit_with_executing_child_reattaches_observation_only(kind, tmp_path):
    _, load, fixture = api()
    from ralf_agent.orchestration_evaluation import _assembly, _OrchestrationProvider

    # Exit after the original engine's durable model_dispatched event, while
    # Provider.complete is executing. Reattachment must not resume that request.
    script = """
import asyncio
import os
import sys
from pathlib import Path
from ralf_agent.orchestration_evaluation import (
    OfflineOrchestrationProvider, _OrchestrationProvider, _assembly,
    load_orchestration_cases,
)
from ralf_agent.planning_evaluation import EvaluationLimits, _new_evidence_path

class Exit(OfflineOrchestrationProvider):
    async def complete(self, messages, tools):
        os._exit(73)

async def main():
    directory, kind = Path(sys.argv[1]), sys.argv[2]
    case = load_orchestration_cases()[0]
    path = _new_evidence_path(directory, case['id'], 0)
    audited = _OrchestrationProvider(Exit(), EvaluationLimits())
    builder, profile, harness = _assembly(case, audited, kind, directory)
    async with await builder.abuild(profile, path) as runtime:
        handle = runtime.submit(harness.definition,
            {'task': case['task'], 'request': case['request']},
            command_id='evaluate:first', budget=32)
        await runtime.drive(handle.run_id)

asyncio.run(main())
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), kind],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode == 73, child.stderr
    case = load()[0]
    path = tmp_path / f"{case['id']}-0.sqlite"
    with SQLiteStore(path, readonly=True) as store:
        before = [
            json.loads(row[0]) for row in store.conn.execute("SELECT data FROM runs ORDER BY id")
        ]
        receipt = json.loads(
            store.conn.execute("SELECT receipt FROM commands WHERE id='evaluate:first'").fetchone()[
                0
            ]
        )
        assert any(
            a["kind"] == "model" and a["status"] == "executing"
            for r in before
            for a in r["actions"]
        )

    async def observe():
        audited = _OrchestrationProvider(fixture(), EvaluationLimits())
        builder, profile, harness = _assembly(case, audited, kind, tmp_path)
        async with await builder.abuild(profile, path) as runtime:
            handle = runtime.submit(
                harness.definition,
                {"task": case["task"], "request": case["request"]},
                command_id="evaluate:first",
                budget=32,
            )
            assert handle.run_id == receipt["run_id"]
            assert handle.receipt.command_id == receipt["command_id"]
            assert runtime.status(handle.run_id).state not in {"succeeded", "failed", "cancelled"}
            assert audited.attempts == []

    asyncio.run(observe())
    with SQLiteStore(path, readonly=True) as store:
        after = [
            json.loads(row[0]) for row in store.conn.execute("SELECT data FROM runs ORDER BY id")
        ]
    assert after == before
