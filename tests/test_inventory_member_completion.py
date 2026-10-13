"""Reference inventory members must finish from their own committed receipts."""

import asyncio
import importlib
import json
import sqlite3

import pytest

from ralf_agent.completion import CompletionRequest
from ralf_agent.errors import ValidationError
from ralf_agent.orchestration_evaluation import (
    OfflineOrchestrationProvider,
    _assembly,
    _OrchestrationProvider,
    evaluate_orchestration,
    load_orchestration_cases,
)
from ralf_agent.parent_completion_starter import (
    OfflineInventoryProvider,
    _definition,
    run_reference,
)
from ralf_agent.planning_evaluation import EvaluationLimits
from ralf_agent.types import ModelResponse, digest

REQUEST = {"dataset_id": "warehouse-a", "target": "wire", "quantity": 3}
LOOKUP = {
    "found": True,
    "dataset_id": "warehouse-a",
    "target": "wire",
    "item": {"sku": "wire", "units_available": 40, "unit_price_cents": 425},
}


def verifier(member, **options):
    try:
        module = importlib.import_module("ralf_agent.inventory_member_completion")
    except ModuleNotFoundError:
        pytest.fail("Inventory member completion policy is missing")
    return module.InventoryMemberCompletionVerifier(member, **options)


def receipt(tool, arguments, result):
    return {
        "id": "original-tool-action",
        "tool": tool,
        "arguments": arguments,
        "result": result,
        "receipt": {"effect_key": "original-effect", "status": "completed"},
        "effect_key": "original-effect",
    }


def lookup_receipt(**changes):
    record = receipt("inventory_lookup", {"dataset_id": "warehouse-a", "target": "wire"}, LOOKUP)
    return {**record, **changes}


def calculator_receipt(**changes):
    record = receipt("calculator", {"quantity": 3, "unit_price_cents": 425}, {"total": 1275})
    return {**record, **changes}


@pytest.mark.parametrize("fault", ["absent", "arguments", "result", "task", "false-negative"])
def test_researcher_requires_exact_original_lookup(fault):
    output = {"request": REQUEST, "lookup": LOOKUP}
    records = [lookup_receipt()]
    if fault == "absent":
        records = []
    elif fault == "arguments":
        records = [lookup_receipt(arguments={"dataset_id": "warehouse-b", "target": "wire"})]
    elif fault == "result":
        records = [
            lookup_receipt(result={**LOOKUP, "item": {**LOOKUP["item"], "unit_price_cents": 1}})
        ]
    elif fault == "task":
        output = {"request": {**REQUEST, "quantity": 4}, "lookup": LOOKUP}
    else:
        output = {"request": REQUEST, "lookup": {**LOOKUP, "found": False, "item": None}}
        records = []
    verdict = verifier("researcher").verify(CompletionRequest(REQUEST, output, records))
    assert verdict.status == "retry" and "inventory_lookup" in verdict.feedback


@pytest.mark.parametrize(
    "pointer,task",
    [
        ("", REQUEST),
        ("", {"task": REQUEST}),
        ("/request", {"task": "Do the inventory task", "request": REQUEST}),
    ],
)
def test_researcher_accepts_actual_lookup_in_supported_task_shapes(pointer, task):
    selected = verifier("researcher", request_pointer=pointer)
    request = CompletionRequest(task, {"request": REQUEST, "lookup": LOOKUP}, [lookup_receipt()])
    assert selected.verify(request).status == "accept"
    changed = selected.identity
    changed["member"] = "writer"
    assert selected.identity["member"] == "researcher"


@pytest.mark.parametrize("missing", ["target", "quantity"])
def test_researcher_missing_input_requires_no_lookup(missing):
    incoming = {**REQUEST, missing: None}
    output = {"request": incoming, "lookup": None}
    selected = verifier("researcher")
    assert selected.verify(CompletionRequest(incoming, output, [])).status == "accept"
    assert (
        selected.verify(CompletionRequest(incoming, output, [lookup_receipt()])).status == "retry"
    )


@pytest.mark.parametrize(
    "fault", ["absent", "arguments", "result", "output", "false-stop", "changed-price"]
)
def test_writer_requires_calculator_for_actual_predecessor_evidence(fault):
    incoming = {"request": REQUEST, "lookup": LOOKUP}
    output = {"status": "completed", "total": 1275}
    records = [calculator_receipt()]
    if fault == "absent":
        records = []
    elif fault == "arguments":
        records = [calculator_receipt(arguments={"quantity": 1, "unit_price_cents": 425})]
    elif fault == "result":
        records = [calculator_receipt(result={"total": 999})]
    elif fault == "output":
        output = {"status": "completed", "total": 999}
    elif fault == "false-stop":
        output = {"status": "needs_input", "total": None}
    else:
        incoming = {
            "request": REQUEST,
            "lookup": {**LOOKUP, "item": {**LOOKUP["item"], "unit_price_cents": 799}},
        }
    verdict = verifier("writer").verify(CompletionRequest(incoming, output, records))
    assert verdict.status == "retry" and "calculator" in verdict.feedback


@pytest.mark.parametrize("wrapped", [False, True])
def test_writer_accepts_same_committed_total(wrapped):
    incoming = {"request": REQUEST, "lookup": LOOKUP}
    if wrapped:
        incoming = {"task": REQUEST, "results": {"researcher": incoming}}
    assert (
        verifier("writer")
        .verify(
            CompletionRequest(
                incoming, {"status": "completed", "total": 1275}, [calculator_receipt()]
            )
        )
        .status
        == "accept"
    )


@pytest.mark.parametrize("stop", ["missing", "unknown", "stock"])
def test_writer_accepts_truthful_stops_and_refuses_calculator(stop):
    incoming = {"request": REQUEST, "lookup": LOOKUP}
    status = "needs_input"
    if stop == "missing":
        incoming = {"request": {**REQUEST, "target": None}, "lookup": None}
    elif stop == "unknown":
        incoming = {"request": REQUEST, "lookup": {**LOOKUP, "found": False, "item": None}}
        status = "not_found"
    else:
        incoming = {"request": {**REQUEST, "quantity": 41}, "lookup": LOOKUP}
    selected = verifier("writer")
    output = {"status": status, "total": None}
    assert selected.verify(CompletionRequest(incoming, output, [])).status == "accept"
    assert (
        selected.verify(CompletionRequest(incoming, output, [calculator_receipt()])).status
        == "retry"
    )


class FakeFinalThenFollowFeedback:
    """Actual complete initially invents a final; feedback leads to normal tools."""

    identity = {"kind": "offline-inventory-member-retry-fixture", "version": "1"}

    def __init__(self, *, starter=False):
        self.starter = starter

    async def complete(self, messages, tools):
        incoming = json.loads(messages[1]["content"])
        names = {item["function"]["name"] for item in tools}
        feedback = any(
            message["role"] == "user" and message["content"].startswith("Completion verification:")
            for message in messages
        )
        receipts = any(message["role"] == "tool" for message in messages)
        if not feedback and not receipts:
            if names == {"inventory_lookup"}:
                request = incoming if self.starter else incoming["request"]
                return ModelResponse(
                    {
                        "request": request,
                        "lookup": {
                            "found": False,
                            "dataset_id": request["dataset_id"],
                            "target": request["target"],
                            "item": None,
                        },
                    }
                )
            if names == {"calculator"}:
                return ModelResponse({"status": "completed", "total": 999})
        provider = OfflineInventoryProvider() if self.starter else OfflineOrchestrationProvider()
        return await provider.complete(messages, tools)


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_original_managed_members_retry_fake_final_then_consume_committed_receipts(tmp_path, kind):
    selected = [load_orchestration_cases()[0]]
    legacy = asyncio.run(
        evaluate_orchestration(
            FakeFinalThenFollowFeedback(), kind=kind, cases=selected, completion_gate=True
        )
    )
    assert legacy["passed"] == 0
    assert all(member["tool_actions"] == 0 for member in legacy["cases"][0]["members"])
    evidence = tmp_path / "original-runs"
    report = asyncio.run(
        evaluate_orchestration(
            FakeFinalThenFollowFeedback(),
            kind=kind,
            cases=selected,
            completion_gate=True,
            member_verification=True,
            evidence_dir=evidence,
        )
    )
    assert report["passed"] == report["total"] == 1
    assert report["member_verification"] is True
    assert report["calls"] == 6
    row = report["cases"][0]
    assert [member["model_actions"] for member in row["members"]] == [3, 3]
    assert [member["tool_actions"] for member in row["members"]] == [1, 1]
    assert row["completion"]["adopted"] and row["recovery"]["additional_calls"] == 0
    with sqlite3.connect(evidence / "wire-a-0.sqlite") as connection:
        records = [json.loads(row[0]) for row in connection.execute("SELECT data FROM runs")]
    parent = next(record for record in records if "orchestration" in record)
    children = [record for record in records if record["id"] != parent["id"]]
    assert len(children) == 2
    for child in children:
        verdicts = [
            action["completion_verification"]["verdict"]["status"]
            for action in child["actions"]
            if "completion_verification" in action
        ]
        assert verdicts == ["retry", "accept"]
    assert parent["parent_completion_stages"]["r0"]["adopted_verdict"]["status"] == "accept"


@pytest.mark.parametrize("kind", ["plan", "team"])
def test_reference_binds_only_business_members_and_keeps_reviewer_separate(tmp_path, kind):
    report = asyncio.run(
        run_reference(
            kind,
            business_provider=FakeFinalThenFollowFeedback(starter=True),
            model_verification=True,
            member_verification=True,
            db_path=tmp_path / "reference.sqlite",
        )
    )
    assert report["state"] == "succeeded" and report["result"] == {
        "status": "completed",
        "total": 1275,
    }
    assert report["adopted_verdict"]["status"] == "accept"
    assert [child["role"] for child in report["children"]] == ["worker", "worker", "verifier"]
    assert report["budget"]["held"] == 0 and report["budget"]["spent"] == 9


@pytest.mark.parametrize(
    "kind,profile_hash,harness_hash,definition_hash",
    [
        (
            "plan-and-execute",
            "167931f879df2c14d20de6ef6a0c274f8ca6e345fea99a1806927d6aa0813de9",
            "5f13df4c6f46d9bee130fec36eb195c610914500403973c5c3079955155d2e93",
            "342013dbeaa598058a92829d69b04ab858516f2d86d810313b7e58fa512e0735",
        ),
        (
            "team",
            "9e0c7b93350b17aac4dca0346945dcb869c27dde09d0126ab47532638fdfc2e2",
            "3a393f78421310b5a7dec3f53c9d6a18d297c5e01857d87fac8a365d39244895",
            "1cbd830de1694facd0bc698a5417241a53fcb6f20790b08a0c9b78a20efdb644",
        ),
    ],
)
def test_false_opt_in_preserves_original_profile_definition_and_report(
    tmp_path, kind, profile_hash, harness_hash, definition_hash
):
    _, profile, harness = _assembly(
        load_orchestration_cases()[0],
        OfflineOrchestrationProvider(),
        kind,
        tmp_path,
        completion_gate=True,
        member_verification=False,
    )
    assert digest(profile.identity) == profile_hash
    assert digest(harness.identity) == harness_hash
    assert (
        digest(
            _definition(
                "plan" if kind == "plan-and-execute" else "team", member_verification=False
            ).to_dict()
        )
        == definition_hash
    )
    report = asyncio.run(
        evaluate_orchestration(
            OfflineOrchestrationProvider(),
            kind=kind,
            cases=[load_orchestration_cases()[0]],
            member_verification=False,
        )
    )
    assert report["passed"] == 1 and report["calls"] == 4
    assert "member_verification" not in report


@pytest.mark.parametrize("flag", [None, 0, "true"])
def test_member_flag_refuses_non_boolean_before_calls(flag):
    with pytest.raises(ValidationError):
        asyncio.run(evaluate_orchestration(member_verification=flag))
    with pytest.raises(ValidationError):
        asyncio.run(run_reference(member_verification=flag))


def test_member_policy_requires_parent_gate_before_evidence_allocation(tmp_path):
    evidence = tmp_path / "must-not-create"
    with pytest.raises(ValidationError):
        asyncio.run(
            evaluate_orchestration(
                OfflineOrchestrationProvider(),
                member_verification=True,
                evidence_dir=evidence,
            )
        )
    assert not evidence.exists()


@pytest.mark.parametrize("kind", ["plan", "team"])
@pytest.mark.parametrize("stop", ["missing", "unknown", "stock"])
def test_actual_opted_in_reference_preserves_truthful_stops(kind, stop):
    task = {**REQUEST}
    status = "needs_input"
    if stop == "missing":
        task["quantity"] = None
        expected_tools = []
    elif stop == "unknown":
        task["target"] = "unknown-sku"
        status = "not_found"
        expected_tools = ["inventory_lookup"]
    else:
        task["quantity"] = 41
        expected_tools = ["inventory_lookup"]
    report = asyncio.run(run_reference(kind, task=task, member_verification=True))
    assert report["state"] == "succeeded"
    assert report["result"] == {"status": status, "total": None}
    assert [item["tool"] for item in report["receipts"]] == expected_tools
    assert report["adopted_verdict"]["status"] == "accept" and report["budget"]["held"] == 0


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_persistent_fake_final_exhausts_original_member_limit_without_false_success(tmp_path, kind):
    class PersistentFake(FakeFinalThenFollowFeedback):
        async def complete(self, messages, tools):
            incoming = json.loads(messages[1]["content"])["request"]
            return ModelResponse(
                {
                    "request": incoming,
                    "lookup": {
                        "found": False,
                        "dataset_id": incoming["dataset_id"],
                        "target": incoming["target"],
                        "item": None,
                    },
                }
            )

    report = asyncio.run(
        evaluate_orchestration(
            PersistentFake(),
            kind=kind,
            cases=[load_orchestration_cases()[0]],
            limits=EvaluationLimits(max_calls=8),
            completion_gate=True,
            member_verification=True,
            evidence_dir=tmp_path / "bounded-runs",
        )
    )
    assert report["passed"] == 0 and report["calls"] == 4
    row = report["cases"][0]
    assert row["state"] == "failed" and len(row["members"]) == 1
    assert row["members"][0]["tool_actions"] == 0
    assert row["recovery"]["additional_calls"] == 0


def test_writer_rejects_evidence_for_a_different_original_team_request():
    incoming = {
        "task": {**REQUEST, "quantity": 4},
        "results": {"researcher": {"request": REQUEST, "lookup": LOOKUP}},
    }
    assert (
        verifier("writer")
        .verify(
            CompletionRequest(
                incoming,
                {"status": "completed", "total": 1275},
                [calculator_receipt()],
            )
        )
        .status
        == "reject"
    )


@pytest.mark.parametrize("member,pointer", [("judge", ""), ("researcher", "/hidden"), (None, "")])
def test_policy_constructor_restricts_declared_reference_member_and_input_shape(member, pointer):
    with pytest.raises(ValidationError):
        verifier(member, request_pointer=pointer)


def test_reference_cli_selects_member_policy_with_separate_original_reviewer(tmp_path, capsys):
    from ralf_agent.parent_completion_starter import main

    main(
        [
            "--kind",
            "team",
            "--member-verification",
            "--model-verification",
            "--db-path",
            str(tmp_path / "cli.sqlite"),
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["member_verification"] is True
    assert report["state"] == "succeeded" and report["result"]["total"] == 1275
    assert [item["role"] for item in report["children"]] == ["worker", "worker", "verifier"]
    assert report["budget"]["held"] == 0


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_opted_business_parent_cancellation_drains_original_child_and_reopens_same_records(
    tmp_path, kind
):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        class SuspendedInventory(OfflineOrchestrationProvider):
            async def complete(self, messages, tools):
                entered.set()
                await release.wait()
                return await super().complete(messages, tools)

        provider = _OrchestrationProvider(SuspendedInventory(), EvaluationLimits())
        case = load_orchestration_cases()[0]
        builder, profile, harness = _assembly(
            case,
            provider,
            kind,
            tmp_path,
            completion_gate=True,
            member_verification=True,
        )
        incoming = {"task": case["task"], "request": case["request"]}
        database = tmp_path / "cancel.sqlite"
        instance = await builder.abuild(profile, database)
        connection, owner = instance.store.conn, instance._context
        drive = None
        try:
            handle = instance.submit(
                harness.definition, incoming, command_id="original-submit", budget=32
            )
            drive = asyncio.create_task(instance.drive(handle.run_id))
            await asyncio.wait_for(entered.wait(), 5)
            child = instance.diagnostics(handle.run_id).workflow["children"][0]["run_id"]
            before = instance.diagnostics(handle.run_id).budget
            receipt = instance.cancel(handle.run_id, command_id="original-cancel")
            assert instance.cancel(handle.run_id, command_id="original-cancel") == receipt
            for _ in range(5):
                await asyncio.sleep(0)
            assert not drive.done() and before["held"] > 0
            assert instance.status(child).state in {"cancelling", "cancelled"}
            release.set()
            final = await drive
            assert final.state == "cancelled" and final.result is None
            records = [instance.store.run(run_id) for run_id in (handle.run_id, child)]
            assert records[1]["state"] == "cancelled"
            assert records[1]["actions"][-1]["received_response"] is not None
            assert all(
                action["kind"] != "tool" for record in records for action in record["actions"]
            )
            after = instance.diagnostics(handle.run_id).budget
            assert after["held"] == 0
            assert len(provider.attempts) == 1
        finally:
            release.set()
            if drive is not None and not drive.done():
                await drive
            await instance.aclose()
        assert instance._engine_closed and not owner._resources
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        recovered = await builder.abuild(profile, database)
        recovered_connection, recovered_owner = recovered.store.conn, recovered._context
        try:
            assert (
                recovered.submit(
                    harness.definition, incoming, command_id="original-submit", budget=32
                )
                == handle
            )
            assert recovered.status(handle.run_id) == final
            assert await recovered.drive(handle.run_id) == final
            assert len(provider.attempts) == 1
            assert recovered.store.run(handle.run_id) == records[0]
            assert recovered.store.run(child) == records[1]
        finally:
            await recovered.aclose()
        assert recovered._engine_closed and not recovered_owner._resources
        with pytest.raises(sqlite3.ProgrammingError):
            recovered_connection.execute("SELECT 1")
        assert not [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        (tmp_path / "cancellation-receipt.json").write_text(
            json.dumps(
                {
                    "kind": kind,
                    "run_id": handle.run_id,
                    "child_run_id": child,
                    "budget_before": before,
                    "budget_after": after,
                    "records": records,
                    "calls": 1,
                    "additional_recovery_calls": 0,
                    "owned_resources_remaining": 0,
                    "active_tasks": 0,
                    "original_run_connection_closed": True,
                    "recovered_run_connection_closed": True,
                },
                indent=2,
            )
            + "\n"
        )

    asyncio.run(exercise())
