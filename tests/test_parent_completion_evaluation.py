"""Independent scoring of original parent completion records and managed Runs."""

import asyncio
import copy
import importlib.util
import inspect
import json

import pytest

from ralf_agent.errors import ValidationError
from ralf_agent.orchestration_evaluation import (
    OfflineOrchestrationProvider,
    evaluate_orchestration,
    load_orchestration_cases,
)
from ralf_agent.storage import SQLiteStore
from ralf_agent.types import ModelResponse, ToolCall, digest


def evaluate(provider, **options):
    assert "completion_gate" in inspect.signature(evaluate_orchestration).parameters, (
        "Completion gate must be an explicit opt-in evaluator argument"
    )
    return asyncio.run(evaluate_orchestration(provider, completion_gate=True, **options))


def score(case, parent, children, kind):
    assert importlib.util.find_spec("ralf_agent.parent_completion_evaluation"), (
        "Missing independent parent completion evidence oracle"
    )
    from ralf_agent.parent_completion_evaluation import score_parent_completion

    return score_parent_completion(case, parent, children, kind)


def records(directory, row):
    with SQLiteStore(
        directory / f"{row['case_id']}-{row['repeat']}.sqlite", readonly=True
    ) as store:
        parent = store.run(row["run_id"])
        children = [store.run(c["run_id"]) for c in parent["orchestration"]["children"]]
        budgets = {c["id"]: store.budget(c["id"]) for c in children}
        events = store.events(parent["id"])
    return parent, children, budgets, events


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_opted_inventory_gate_accepts_five_real_current_chains(kind, tmp_path):
    cases = load_orchestration_cases()
    report = evaluate(OfflineOrchestrationProvider(), kind=kind, evidence_dir=tmp_path)
    assert report["passed"] == report["total"] == 5
    assert report["calls"] == 17 and report["model_quality"] is None
    assert report["completion_gate"] is True and report["version"] == "1"
    for case, row in zip(cases, report["cases"], strict=True):
        assert all(row["checks"].values()), row
        parent, children, budgets, _ = records(tmp_path, row)
        assert parent["definition"]["completion_policy"] == "inventory"
        assert parent["manifest"]["runtime_profile"]["version"] == "2"
        journal = parent["parent_completion_stages"]["r0"]
        assert journal["status"] == "adopted" and journal["adopted_verdict"]["status"] == "accept"
        assert journal["source"]["candidate"] == case["expected"]
        assert journal["source_digest"] == digest(journal["source"])
        assert all(b["held"] == 0 for b in budgets.values())
        assert {c["role"] for c in parent["orchestration"]["children"]} == {"worker"}
        checks = score(case, parent, children, kind)
        assert checks["current_lineage"] and checks["parent_completion"]
        assert all(value for name, value in checks.items() if name != "recovery")
        assert row["completion"]["source_sha256"] == journal["source_digest"]
    exported = json.dumps(report)
    for case in cases:
        assert case["task"] not in exported
        assert json.dumps(case["expected"]) not in exported
    assert "Inventory completion lacks" not in exported


class BogusWriter(OfflineOrchestrationProvider):
    def __init__(self, fault, *, once=False):
        self.fault, self.once, self.writer_finals = fault, once, 0

    async def complete(self, messages, tools):
        writer = any(t["function"]["name"] == "calculator" for t in tools)
        if writer and (not self.once or self.writer_finals == 0):
            incoming = json.loads(messages[1]["content"])
            evidence = incoming["results"]["researcher"] if "results" in incoming else incoming
            request, lookup = evidence["request"], evidence["lookup"]
            total = request["quantity"] * lookup["item"]["unit_price_cents"]
            if self.fault == "wrong-parameters" and not any(m["role"] == "tool" for m in messages):
                return ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "calculator",
                            {
                                "quantity": request["quantity"] + 1,
                                "unit_price_cents": lookup["item"]["unit_price_cents"],
                            },
                        )
                    ]
                )
            if self.fault in {"fake-total", "wrong-parameters"}:
                self.writer_finals += 1
                return ModelResponse(output={"status": "completed", "total": total})
        return await super().complete(messages, tools)


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
@pytest.mark.parametrize("fault", ["fake-total", "wrong-parameters"])
def test_schema_valid_answer_cannot_publish_success_without_exact_receipts(kind, fault, tmp_path):
    case = load_orchestration_cases()[0]
    report = evaluate(BogusWriter(fault), kind=kind, cases=[case], evidence_dir=tmp_path)
    row = report["cases"][0]
    assert row["state"] == "failed" and not row["passed"] and report["passed"] == 0
    parent, children, budgets, _ = records(tmp_path, row)
    assert parent["result"] is None and all(c["state"] == "succeeded" for c in children)
    assert all(b["held"] == 0 for b in budgets.values())
    assert not score(case, parent, children, kind)["parent_completion"]


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_legitimate_missing_quantity_and_insufficient_stock_stop_without_calculator(kind, tmp_path):
    cases = copy.deepcopy(load_orchestration_cases()[:2])
    cases[0]["request"]["quantity"] = None
    cases[1]["request"]["quantity"] = 99
    for case in cases:
        case["expected"] = {"status": "needs_input", "total": None}
    report = evaluate(OfflineOrchestrationProvider(), kind=kind, cases=cases, evidence_dir=tmp_path)
    assert report["passed"] == 2 and report["calls"] == 5
    assert [r["members"][1]["tool_actions"] for r in report["cases"]] == [0, 0]


def test_bounded_plan_replan_scores_current_pair_and_keeps_old_bad_attempt(tmp_path):
    case = load_orchestration_cases()[0]
    report = evaluate(BogusWriter("fake-total", once=True), cases=[case], evidence_dir=tmp_path)
    row = report["cases"][0]
    assert row["passed"] and report["calls"] == 7
    parent, children, _, events = records(tmp_path, row)
    assert parent["orchestration"]["revision"] == 1
    assert len(children) == 4 and [c["call_id"] for c in children] == [
        "r0.step.step-0",
        "r0.step.step-1",
        "r1.step.step-0",
        "r1.step.step-1",
    ]
    old, current = (parent["parent_completion_stages"][key] for key in ("r0", "r1"))
    assert old["adopted_verdict"]["status"] == "replan"
    assert current["adopted_verdict"]["status"] == "accept"
    assert parent["orchestration"]["verification_feedback"]["source_digest"] == old["source_digest"]
    assert parent["orchestration"]["revisions"][1]["proposal"]
    assert any(e.kind == "plan_replanning" for e in events)
    assert len(children[1]["actions"]) == 1 and len(children[3]["actions"]) == 3
    checks = score(case, parent, children, "plan-and-execute")
    assert all(value for key, value in checks.items() if key != "recovery")


@pytest.mark.parametrize(
    "corruption",
    [
        "digest",
        "candidate",
        "foreign-scope",
        "child-owner",
        "call-id",
        "release",
        "source-input",
        "source-revision",
        "final-snapshot",
        "receipt-result",
        "receipt-consumption",
        "unsettled-history",
        "unknown-history",
        "missing-child",
        "duplicate-child",
        "tool-digest",
        "tool-proposal",
    ],
)
def test_independent_oracle_rejects_forged_source_and_original_records(corruption, tmp_path):
    case = load_orchestration_cases()[0]
    report = evaluate(OfflineOrchestrationProvider(), cases=[case], evidence_dir=tmp_path)
    parent, children, _, _ = records(tmp_path, report["cases"][0])
    journal = parent["parent_completion_stages"]["r0"]
    source = journal["source"]
    if corruption == "digest":
        journal["source_digest"] = "a" * 64
    elif corruption == "candidate":
        source["candidate"]["total"] += 1
    elif corruption == "foreign-scope":
        children[0]["scope"]["principal"] = "foreign"
    elif corruption == "child-owner":
        children[0]["parent_id"] = "foreign"
    elif corruption == "call-id":
        source["children"][0]["call_id"] = "r0.step.foreign"
    elif corruption == "release":
        children[0]["release_digest"] = "b" * 64
    elif corruption == "source-input":
        source["children"][0]["input"]["request"]["quantity"] += 1
        source["children"][0]["input_digest"] = digest(source["children"][0]["input"])
    elif corruption == "source-revision":
        source["children"][0]["state_revision"] = children[0]["revision"] + 1
    elif corruption == "final-snapshot":
        source["children"][0]["final_snapshot_digest"] = "c" * 64
        source["children"][0]["final_models"][0]["snapshot_digest"] = "c" * 64
    elif corruption == "receipt-result":
        source["receipts"][-1]["result"]["total"] += 1
    elif corruption == "receipt-consumption":
        source["receipts"][-1]["consumed_by"] = []
    elif corruption == "unsettled-history":
        parent["orchestration"]["children"][0]["settled"] = False
    elif corruption == "unknown-history":
        children[0]["state"] = "waiting_reconciliation"
        children[0]["actions"][0]["status"] = "unknown"
    elif corruption == "missing-child":
        children.pop()
    elif corruption == "duplicate-child":
        children.append(copy.deepcopy(children[0]))
    elif corruption == "tool-digest":
        children[0]["actions"][1]["digest"] = "d" * 64
    elif corruption == "tool-proposal":
        children[0]["actions"][0]["response"]["tool_calls"][0]["arguments"]["target"] = "foreign"
    if corruption != "digest":
        journal["source_digest"] = digest(source)
    checks = score(case, parent, children, "plan-and-execute")
    assert not checks["parent_completion"], corruption


def test_previous_good_receipt_cannot_replace_current_wrong_lineage(tmp_path):
    case = load_orchestration_cases()[0]
    report = evaluate(
        BogusWriter("wrong-parameters", once=True), cases=[case], evidence_dir=tmp_path
    )
    assert report["passed"] == 1
    parent, children, _, _ = records(tmp_path, report["cases"][0])
    journal = parent["parent_completion_stages"]["r1"]
    # Both research attempts are valid, but the current DAG owns the second.
    old_source = parent["parent_completion_stages"]["r0"]["source"]
    journal["source"]["children"][0] = copy.deepcopy(old_source["children"][0])
    journal["source"]["receipts"][0] = copy.deepcopy(old_source["receipts"][0])
    journal["source_digest"] = digest(journal["source"])
    checks = score(case, parent, children, "plan-and-execute")
    assert not checks["current_lineage"] and not checks["parent_completion"]


def test_frozen_source_revision_can_precede_current_child_revision(tmp_path):
    case = load_orchestration_cases()[0]
    report = evaluate(OfflineOrchestrationProvider(), cases=[case], evidence_dir=tmp_path)
    parent, children, _, _ = records(tmp_path, report["cases"][0])
    children[0]["revision"] += 2
    assert score(case, parent, children, "plan-and-execute")["parent_completion"]


def test_actual_patched_dag_retains_original_r0_node_evidence(tmp_path):
    from ralf_agent.dag_planning import DAGProposal
    from ralf_agent.orchestration_evaluation import _assembly

    case = load_orchestration_cases()[0]

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class PausedResearcher(OfflineOrchestrationProvider):
            async def complete(self, messages, tools):
                if any(t["function"]["name"] == "inventory_lookup" for t in tools) and any(
                    m["role"] == "tool" for m in messages
                ):
                    started.set()
                    await release.wait()
                return await super().complete(messages, tools)

        builder, profile, harness = _assembly(
            case, PausedResearcher(), "plan-and-execute", tmp_path, completion_gate=True
        )
        async with await builder.abuild(profile, tmp_path / "patched.sqlite") as runtime:
            handle = runtime.submit(
                harness.definition,
                {
                    "task": case["task"],
                    "request": case["request"],
                },
                command_id="patch-evaluation",
                budget=32,
            )
            driving = asyncio.create_task(runtime.drive(handle.run_id))
            try:
                await asyncio.wait_for(started.wait(), 2)
                parent = runtime.store.run(handle.run_id)
                proposal = copy.deepcopy(parent["orchestration"]["dag"]["proposal"])
                proposal["nodes"][1]["id"] = "writer-final"
                proposal["output"]["source"] = "writer-final"
                runtime.patch_plan(
                    handle.run_id,
                    DAGProposal.from_dict(proposal),
                    expected_plan_revision=0,
                    command_id="retain-original-research",
                )
            finally:
                release.set()
                snapshot = await driving
            assert snapshot.state == "succeeded"
            parent = runtime.store.run(handle.run_id)
            children = [runtime.store.run(c["run_id"]) for c in parent["orchestration"]["children"]]
            assert parent["orchestration"]["plan_revision"] == 1
            assert [c["call_id"] for c in children] == ["r0.step.step-0", "r0.step.writer-final"]
            assert all(
                v
                for k, v in score(case, parent, children, "plan-and-execute").items()
                if k != "recovery"
            )

    asyncio.run(scenario())


def test_forged_accept_cannot_make_original_missing_receipts_true(tmp_path):
    case = load_orchestration_cases()[0]
    report = evaluate(BogusWriter("fake-total"), cases=[case], evidence_dir=tmp_path)
    parent, children, _, _ = records(tmp_path, report["cases"][0])
    journal = parent["parent_completion_stages"]["r1"]
    accept = {"status": "accept", "feedback": None, "evidence_ids": []}
    journal.update(gate_verdict=accept, received_proposal=accept, adopted_verdict=accept)
    parent.update(state="succeeded", result=case["expected"])
    checks = score(case, parent, children, "plan-and-execute")
    assert checks["total"] and checks["current_lineage"]
    assert not checks["calculator_receipt"] and not checks["parent_completion"]


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_original_provider_tool_call_ids_need_not_equal_action_ids(kind, tmp_path):
    class ExplicitCalls(OfflineOrchestrationProvider):
        async def complete(self, messages, tools):
            response = await super().complete(messages, tools)
            return ModelResponse(
                response.output,
                tuple(
                    ToolCall(call.name, call.arguments, call_id="provider-" + call.name)
                    for call in response.tool_calls
                ),
                usage=response.usage,
            )

    case = load_orchestration_cases()[0]
    report = evaluate(ExplicitCalls(), kind=kind, cases=[case], evidence_dir=tmp_path)
    assert report["passed"] == 1
    parent, children, _, _ = records(tmp_path, report["cases"][0])
    tools = [a for child in children for a in child["actions"] if a["kind"] == "tool"]
    assert all(a["call_id"] != a["id"] for a in tools)
    assert score(case, parent, children, kind)["parent_completion"]


@pytest.mark.parametrize("value", [None, 0, 1, "true", []])
def test_invalid_completion_gate_rejected_before_provider_or_evidence_construction(value, tmp_path):
    assert "completion_gate" in inspect.signature(evaluate_orchestration).parameters

    class Unconstructed:
        @property
        def identity(self):
            pytest.fail("Invalid gate flag must fail before touching provider")

    with pytest.raises(ValidationError, match="boolean"):
        asyncio.run(
            evaluate_orchestration(Unconstructed(), completion_gate=value, evidence_dir=tmp_path)
        )
    assert not list(tmp_path.iterdir())


def test_cli_opt_in_and_old_report_remain_compatible(tmp_path):
    from ralf_agent.orchestration_evaluation_cli import arguments, run

    args = arguments(
        ["--offline", "--completion-gate", "--max-cases", "1", "--evidence-dir", str(tmp_path)]
    )
    report = asyncio.run(run(args))
    assert report["passed"] == 1 and report["cases"][0]["checks"]["parent_completion"]
    old = asyncio.run(
        evaluate_orchestration(OfflineOrchestrationProvider(), cases=load_orchestration_cases()[:1])
    )
    assert old["passed"] == 1 and old["version"] == "1"
    assert "completion_gate" not in old and "completion" not in old["cases"][0]
    assert "current_lineage" not in old["cases"][0]["checks"]
    assert "parent_completion" not in old["cases"][0]["checks"]


def test_invalid_cli_gate_fails_before_owned_provider_construction(monkeypatch):
    from ralf_agent import orchestration_evaluation_cli as cli

    args = cli.arguments(["--provider", "openai", "--model", "placeholder"])
    args.completion_gate = "yes"
    monkeypatch.setattr(
        cli, "_http_provider", lambda *a: pytest.fail("Owned provider was constructed")
    )
    with pytest.raises(ValidationError, match="boolean"):
        asyncio.run(cli.run(args))
