"""Receipt gates preserve one actual matching receipt and inventory dataflow."""

import copy

import pytest

from relf_agent.errors import ValidationError
from tests.test_parent_completion import child, receipt, request


def receipt_gate(**changes):
    from relf_agent.parent_completion_rules import ReceiptParentCompletionGate

    rule = {
        "id": "lookup",
        "member_path": ["worker"],
        "tool": "lookup",
        "argument_bindings": {"sku": {"source": "task", "pointer": "/sku"}},
        "output_bindings": {"/total": {"source": "candidate", "pointer": "/total"}},
    }
    rule.update(changes)
    return ReceiptParentCompletionGate([rule], required_members=[["worker"]])


def test_minimal_receipt_rule_normalizes_defaults_and_identity():
    from relf_agent.parent_completion_rules import ReceiptParentCompletionGate

    gate = ReceiptParentCompletionGate(
        [{"id": "rule", "member_path": ["worker"], "tool": "lookup"}]
    )
    assert gate.identity["rules"][0] == {
        "id": "rule",
        "member_path": ["worker"],
        "tool": "lookup",
        "when": None,
        "result_schema": None,
        "argument_bindings": {},
        "output_bindings": {},
        "require_consumed": True,
    }
    with pytest.raises(ValidationError):
        ReceiptParentCompletionGate(
            [{"id": "rule", "member_path": ["worker"], "tool": "lookup", "typo": True}]
        )


def test_receipt_gate_accepts_one_exact_consumed_tool_result():
    item = child()
    tool = receipt(item, arguments={"sku": "wire"}, result={"total": 20})
    verdict = receipt_gate().verify(request(children=[item], receipts=[tool]))
    assert verdict.status == "accept"
    assert set(verdict.evidence_ids) == {item["id"], tool["id"]}


@pytest.mark.parametrize(
    "fault",
    ["argument", "output", "unconsumed", "input-unconsumed", "missing-child", "schema", "split"],
)
def test_receipt_gate_rejects_missing_or_mismatching_evidence(fault):
    item = child()
    tool = receipt(item, arguments={"sku": "wire"}, result={"total": 20})
    gate = receipt_gate()
    tools = [tool]
    if fault == "argument":
        tool["arguments"] = {"sku": "bolts"}
    elif fault == "output":
        tool["result"] = {"total": 21}
    elif fault == "unconsumed":
        tool["consumed_by"] = []
    elif fault == "input-unconsumed":
        item["input_consumed"] = False
        item["final_models"][0]["input_consumed"] = False
    elif fault == "missing-child":
        item = child(path=("other",))
        tools = []
    elif fault == "schema":
        gate = receipt_gate(result_schema={"type": "object", "required": ["ok"]})
    else:
        other = receipt(item, arguments={"sku": "wire"}, result={"total": 0}, action_id="tool-2")
        tool["arguments"] = {"sku": "wrong"}
        tools.append(other)
    assert gate.verify(request(children=[item], receipts=tools)).status == "reject"


def test_conditional_rule_does_not_bypass_unconditional_member():
    gate = receipt_gate(
        when={"properties": {"status": {"const": "completed"}}, "required": ["status"]}
    )
    assert gate.verify(request(children=[], candidate={"status": "needs_input"})).status == "reject"


def test_remote_schema_reference_fails_locally_and_team_replan_preflight_fails():
    from relf_agent.parent_completion import ParentCompletionPolicy
    from relf_agent.parent_completion_protocol import validate_policy

    gate = receipt_gate(when={"$ref": "https://example.invalid/schema"})
    with pytest.raises(ValidationError):
        gate.verify(request())
    from relf_agent.parent_completion_rules import ReceiptParentCompletionGate

    policy = ParentCompletionPolicy(
        ReceiptParentCompletionGate(
            [{"id": "a", "member_path": ["worker"], "tool": "lookup"}], on_missing="replan"
        )
    )
    with pytest.raises(ValidationError):
        validate_policy(policy, parent_kind="team")


DATASET = {
    "id": "warehouse-a",
    "inventory": [{"sku": "wire", "units_available": 40, "unit_price_cents": 425}],
}


def inventory_source(*, target="wire", quantity=3, kind="dynamic"):
    from relf_agent.parent_completion import ParentCompletionRequest

    structured = {"dataset_id": "warehouse-a", "target": target, "quantity": quantity}
    item = DATASET["inventory"][0] if target == "wire" else None
    lookup = (
        None
        if target is None or quantity is None
        else {
            "found": item is not None,
            "dataset_id": "warehouse-a",
            "target": target,
            "item": copy.deepcopy(item),
        }
    )
    evidence = {"request": structured, "lookup": lookup}
    status = (
        "needs_input"
        if lookup is None or item is not None and quantity > 40
        else "not_found"
        if item is None
        else "completed"
    )
    result = {"status": status, "total": quantity * 425 if status == "completed" else None}
    task = {"instruction": "Use actual inventory evidence", "request": structured}
    researcher = child(("researcher",), run_id="researcher-run", input=task, result=evidence)
    writer = child(
        ("writer",),
        run_id="writer-run",
        input={"task": task, "results": {"researcher": evidence}} if kind == "team" else evidence,
        result=result,
    )
    tools = []
    if lookup is not None:
        tools.append(
            receipt(
                researcher,
                tool="inventory_lookup",
                arguments={"dataset_id": "warehouse-a", "target": target},
                result=lookup,
            )
        )
    if status == "completed":
        tools.append(
            receipt(
                writer,
                tool="calculator",
                arguments={"quantity": quantity, "unit_price_cents": 425},
                result={"total": quantity * 425},
            )
        )
    constraints = {
        "remaining_steps": 4,
        "remaining_revisions": 0 if kind == "team" else 1,
        "max_concurrency": 1,
        "verifier_budget": 1,
        "parent_budget": {"available": 10, "held": 0, "spent": 0},
    }
    value = request(
        parent_kind=kind,
        task=task,
        children=[researcher, writer],
        receipts=tools,
        candidate=result,
        constraints=constraints,
    ).to_dict()
    if kind == "team":
        value["constraints"]["remaining_revisions"] = 0
    return ParentCompletionRequest.from_dict(value)


def inventory_gate():
    from relf_agent.parent_completion_rules import InventoryParentCompletionGate

    return InventoryParentCompletionGate(dataset=DATASET, request_pointer="/request")


@pytest.mark.parametrize(
    "target,quantity,status",
    [
        ("wire", 3, "completed"),
        (None, 3, "needs_input"),
        ("wire", None, "needs_input"),
        ("missing", 3, "not_found"),
        ("wire", 41, "needs_input"),
    ],
)
def test_inventory_gate_accepts_actual_completed_and_stop_evidence(target, quantity, status):
    value = inventory_source(target=target, quantity=quantity)
    assert value.candidate["status"] == status
    assert inventory_gate().verify(value).status == "accept"


@pytest.mark.parametrize(
    "fault",
    [
        "candidate",
        "no-calculator",
        "wrong-price",
        "no-lookup",
        "fake-negative",
        "writer-input",
        "writer-consumption",
        "stop-calculator",
        "wrong-dataset",
        "text-task",
    ],
)
def test_inventory_gate_rejects_schema_valid_false_success_and_bad_dataflow(fault):
    from relf_agent.parent_completion import ParentCompletionRequest

    value = inventory_source(target=None if fault == "stop-calculator" else "wire").to_dict()
    if fault == "candidate":
        value["candidate"]["total"] = 999
    elif fault == "no-calculator":
        value["receipts"] = value["receipts"][:1]
    elif fault == "wrong-price":
        value["receipts"][1]["arguments"]["unit_price_cents"] = 1
    elif fault == "no-lookup":
        value["receipts"] = value["receipts"][1:]
    elif fault == "fake-negative":
        value["receipts"][0]["result"] = {
            "found": False,
            "dataset_id": "warehouse-a",
            "target": "wire",
            "item": None,
        }
    elif fault == "writer-input":
        value["children"][1]["input"] = {"request": value["task"]["request"], "lookup": None}
        value["children"][1]["input_digest"] = digest(value["children"][1]["input"])
        value["children"][1]["final_models"][0]["input_digest"] = value["children"][1][
            "input_digest"
        ]
    elif fault == "writer-consumption":
        value["children"][1]["input_consumed"] = False
        value["children"][1]["final_models"][0]["input_consumed"] = False
    elif fault == "stop-calculator":
        value["receipts"] = [
            receipt(
                value["children"][1],
                tool="calculator",
                arguments={"quantity": 3, "unit_price_cents": 425},
                result={"total": 1275},
            )
        ]
    elif fault == "wrong-dataset":
        value["task"]["request"]["dataset_id"] = "warehouse-b"
    else:
        value["task"] = "Calculate wire price"
    assert inventory_gate().verify(ParentCompletionRequest.from_dict(value)).status == "reject"


def test_inventory_gate_accepts_original_team_input_and_freezes_dataset():
    gate = inventory_gate()
    assert gate.verify(inventory_source(kind="team")).status == "accept"
    projected = gate.identity
    projected["dataset"]["inventory"][0]["unit_price_cents"] = 999
    assert gate.verify(inventory_source()).status == "accept"


def test_receipt_output_binding_can_select_the_complete_literal_result():
    from relf_agent.parent_completion_rules import ReceiptParentCompletionGate

    item = child()
    tool = receipt(item, result={"total": 20})
    gate = ReceiptParentCompletionGate(
        [
            {
                "id": "whole-result",
                "member_path": ["worker"],
                "tool": "lookup",
                "output_bindings": {"": {"source": "candidate", "pointer": ""}},
            }
        ]
    )
    assert gate.verify(request(children=[item], receipts=[tool])).status == "accept"


def test_inventory_missing_input_prohibits_any_owned_tool_execution():
    from relf_agent.parent_completion import ParentCompletionRequest

    value = inventory_source(target=None).to_dict()
    unexpected = child(("other",), run_id="other-run")
    value["children"].append(unexpected)
    value["receipts"].append(receipt(unexpected, tool="unrelated", result={"changed": True}))
    assert inventory_gate().verify(ParentCompletionRequest.from_dict(value)).status == "reject"


def test_malformed_receipt_selectors_fail_with_validation_error():
    with pytest.raises(ValidationError):
        receipt_gate(argument_bindings={"sku": {"source": [], "pointer": "/sku"}})


def test_direct_graph_tool_requires_explicit_unconsumed_rule_opt_in():
    from relf_agent.parent_completion_rules import ReceiptParentCompletionGate

    owner = child(("group",))
    owner.update(
        input_consumed=None, final_action_id=None, final_snapshot_digest=None, final_models=[]
    )
    tool = receipt(owner, arguments={"value": 20}, result={"total": 20})
    tool["member_path"] = ["group", "measure"]
    tool["consumed_by"] = []
    frozen = request(children=[owner], receipts=[tool])
    rule = {
        "id": "direct-tool",
        "member_path": ["group", "measure"],
        "tool": "lookup",
        "output_bindings": {"/total": {"source": "candidate", "pointer": "/total"}},
    }
    assert ReceiptParentCompletionGate([rule]).verify(frozen).status == "reject"
    assert (
        ReceiptParentCompletionGate([{**rule, "require_consumed": False}]).verify(frozen).status
        == "accept"
    )


from relf_agent.types import digest  # noqa: E402
