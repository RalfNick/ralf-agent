"""Bounded inventory tasks through the original managed Plan and Team runtime.

The offline provider verifies execution and evidence flow; it makes no model
quality claim. Raw tasks, model outputs and tool receipts remain in private
execution databases. Exported measurements contain allowlisted fields only.
"""

from __future__ import annotations

import copy
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from .errors import BudgetExceeded, ValidationError
from .evaluation_summary import summarize_evaluation
from .planning_evaluation import (
    EvaluationLimits,
    _cost,
    _evidence_directory,
    _new_evidence_path,
    _prices,
    _safe_identity,
)
from .recommended import recommended_profile
from .recommended_orchestration import recommended_harness
from .runtime_builder import ComponentRegistry, RuntimeBuilder
from .task_evaluation_provider import PinnedEvaluationProvider
from .tools import ToolRegistry, ToolSpec
from .types import AgentSpec, ModelResponse, ToolCall, canonical, digest

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "total"],
    "properties": {
        "status": {"enum": ["completed", "needs_input", "not_found"]},
        "total": {"type": ["integer", "null"], "minimum": 0},
    },
}

_ID = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_.-]{0,63}$"}
_REQUEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dataset_id", "target", "quantity"],
    "properties": {
        "dataset_id": _ID,
        "target": {"type": ["string", "null"], "pattern": _ID["pattern"]},
        "quantity": {"type": ["integer", "null"], "minimum": 1, "maximum": 100000},
    },
}
_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sku", "units_available", "unit_price_cents"],
    "properties": {
        "sku": _ID,
        "units_available": {"type": "integer", "minimum": 1, "maximum": 100000},
        "unit_price_cents": {"type": "integer", "minimum": 0, "maximum": 100000000},
    },
}
_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["request", "lookup"],
    "properties": {
        "request": _REQUEST_SCHEMA,
        "lookup": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["found", "dataset_id", "target", "item"],
                    "properties": {
                        "found": {"type": "boolean"},
                        "dataset_id": _ID,
                        "target": _ID,
                        "item": {"oneOf": [{"type": "null"}, _ITEM_SCHEMA]},
                    },
                },
            ]
        },
    },
}
_CASE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "category", "task", "dataset", "request", "expected"],
    "properties": {
        "id": _ID,
        "category": {"type": "string", "minLength": 1, "maxLength": 64},
        "task": {"type": "string", "minLength": 1, "maxLength": 16000},
        "dataset": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "inventory"],
            "properties": {
                "id": _ID,
                "inventory": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1000,
                    "items": _ITEM_SCHEMA,
                },
            },
        },
        "request": _REQUEST_SCHEMA,
        "expected": OUTPUT_SCHEMA,
    },
}
_CHECKS = (
    "status",
    "total",
    "stopped",
    "lookup_receipt",
    "calculator_receipt",
    "prior_evidence",
    "managed_members",
    "recovery",
)


def _lookup(dataset, arguments):
    """The trusted tool and oracle independently use the frozen inventory."""
    item = (
        next((item for item in dataset["inventory"] if item["sku"] == arguments["target"]), None)
        if arguments["dataset_id"] == dataset["id"]
        else None
    )
    return {
        "found": item is not None,
        "dataset_id": arguments["dataset_id"],
        "target": arguments["target"],
        "item": copy.deepcopy(item),
    }


def _expected(dataset, request):
    if request["target"] is None or request["quantity"] is None:
        return {"status": "needs_input", "total": None}
    receipt = _lookup(dataset, request)
    if not receipt["found"]:
        return {"status": "not_found", "total": None}
    if request["quantity"] > receipt["item"]["units_available"]:
        return {"status": "needs_input", "total": None}
    return {
        "status": "completed",
        "total": request["quantity"] * receipt["item"]["unit_price_cents"],
    }


def _validate_cases(cases):
    canonical(cases)
    if not isinstance(cases, list) or not 1 <= len(cases) <= 1000:
        raise ValidationError("Orchestration evaluation requires bounded cases")
    try:
        validator = Draft202012Validator(_CASE_SCHEMA)
        for case in cases:
            validator.validate(case)
    except SchemaValidationError as exc:
        raise ValidationError("Invalid orchestration evaluation case") from exc
    if len({case["id"] for case in cases}) != len(cases):
        raise ValidationError("Orchestration evaluation case IDs must be unique")
    for case in cases:
        dataset, request = case["dataset"], case["request"]
        if len({item["sku"] for item in dataset["inventory"]}) != len(dataset["inventory"]):
            raise ValidationError("Inventory item IDs must be unique")
        if request["dataset_id"] != dataset["id"]:
            raise ValidationError("Inventory request must select its frozen dataset")
        if case["expected"] != _expected(dataset, request):
            raise ValidationError("Inventory oracle must match its frozen dataset")
    return copy.deepcopy(cases)


def load_orchestration_cases(path=None):
    """Load detached finite inventory tasks, including stops and distinct prices."""
    if path is not None:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
            if (
                not isinstance(document, dict)
                or set(document) != {"version", "cases"}
                or document["version"] != "1"
            ):
                raise ValueError("case version")
            return _validate_cases(document["cases"])
        except (OSError, ValueError, TypeError) as exc:
            raise ValidationError("Invalid orchestration case document") from exc
    datasets = {
        "warehouse-a": {
            "id": "warehouse-a",
            "inventory": [
                {"sku": "wire", "units_available": 40, "unit_price_cents": 425},
                {"sku": "bolts", "units_available": 80, "unit_price_cents": 120},
            ],
        },
        "warehouse-b": {
            "id": "warehouse-b",
            "inventory": [
                {"sku": "wire", "units_available": 30, "unit_price_cents": 799},
                {"sku": "bolts", "units_available": 60, "unit_price_cents": 65},
            ],
        },
    }
    cases = []
    for id, category, dataset_id, target, quantity in [
        ("wire-a", "inventory-total", "warehouse-a", "wire", 3),
        ("wire-b", "distinct-dataset-price", "warehouse-b", "wire", 5),
        ("bolts-a", "distinct-item-price", "warehouse-a", "bolts", 7),
        ("missing-target", "missing-input", "warehouse-a", None, 2),
        ("unknown-target", "not-found", "warehouse-b", "unknown-sku", 4),
    ]:
        request = {"dataset_id": dataset_id, "target": target, "quantity": quantity}
        dataset = datasets[dataset_id]
        cases.append(
            {
                "id": id,
                "category": category,
                "task": "Look up the requested inventory item in the specified dataset and calculate the total cost in integer cents for the requested quantity. Use actual tool evidence. Request input when a required field is missing or stock is insufficient; return not_found for an unknown item.",
                "dataset": dataset,
                "request": request,
                "expected": _expected(dataset, request),
            }
        )
    return _validate_cases(cases)


def _tools(dataset):
    dataset = copy.deepcopy(dataset)
    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            "inventory_lookup",
            "Read a frozen inventory item; unknown targets return found=false.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["dataset_id", "target"],
                "properties": {"dataset_id": _ID, "target": _ID},
            },
            config={"dataset_sha256": digest(dataset)},
        ),
        lambda arguments, context: _lookup(dataset, arguments),
    )
    tools.register(
        ToolSpec(
            "calculator",
            "Multiply quantity by the inventory unit_price_cents; return integer cents.",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["quantity", "unit_price_cents"],
                "properties": {
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 100000},
                    "unit_price_cents": {"type": "integer", "minimum": 0, "maximum": 100000000},
                },
            },
            config={"arithmetic": "integer-cents-v1"},
        ),
        lambda arguments, context: {"total": arguments["quantity"] * arguments["unit_price_cents"]},
    )
    return tools


class OfflineOrchestrationProvider:
    """Explicit protocol fixture deriving answers from supplied input and tools.

    It has no access to a case, its expected answer, or its inventory. Lookup and
    arithmetic are executed by the managed tools and consumed from real receipts.
    """

    identity = {"kind": "offline-orchestration-fixture", "version": "1"}

    async def complete(self, messages, tools):
        incoming = json.loads(messages[1]["content"])
        names = {tool["function"]["name"] for tool in tools}
        receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if "inventory_lookup" in names:
            request = incoming["request"]
            if request["target"] is None or request["quantity"] is None:
                response = ModelResponse(output={"request": request, "lookup": None})
            elif not receipts:
                response = ModelResponse(
                    tool_calls=(
                        ToolCall(
                            "inventory_lookup",
                            {
                                "dataset_id": request["dataset_id"],
                                "target": request["target"],
                            },
                        ),
                    )
                )
            else:
                response = ModelResponse(output={"request": request, "lookup": receipts[-1]})
        elif "calculator" in names:
            evidence = incoming["results"]["researcher"] if "results" in incoming else incoming
            request, lookup = evidence["request"], evidence["lookup"]
            if lookup is None:
                response = ModelResponse(output={"status": "needs_input", "total": None})
            elif not lookup["found"]:
                response = ModelResponse(output={"status": "not_found", "total": None})
            elif request["quantity"] > lookup["item"]["units_available"]:
                response = ModelResponse(output={"status": "needs_input", "total": None})
            elif not receipts:
                response = ModelResponse(
                    tool_calls=(
                        ToolCall(
                            "calculator",
                            {
                                "quantity": request["quantity"],
                                "unit_price_cents": lookup["item"]["unit_price_cents"],
                            },
                        ),
                    )
                )
            else:
                response = ModelResponse(
                    output={"status": "completed", "total": receipts[-1]["total"]}
                )
        else:
            raise ValidationError("Offline orchestration fixture requires its managed tools")
        return ModelResponse(
            output=response.output,
            tool_calls=response.tool_calls,
            usage={"input_tokens": 0, "output_tokens": 0, "source": "offline-fixture"},
        )


class _OrchestrationProvider(PinnedEvaluationProvider):
    def validate_request(self, messages, tools):
        if len(self.attempts) >= self.limits.max_calls:
            raise BudgetExceeded("Orchestration evaluation call limit reached")
        super().validate_request(messages, tools)


def _assembly(case, provider, kind, directory, *, model_continuation=False):
    """Factories capture trusted tools and borrow the caller's audited provider."""
    registry = ComponentRegistry()
    registry.register("provider", "evaluation-borrowed", lambda config, context: provider)
    registry.register(
        "tools", "evaluation-inventory", lambda config, context: _tools(case["dataset"])
    )
    components = {"tools": {"adapter": "evaluation-inventory"}}
    if model_continuation:
        components["model_continuation"] = {"adapter": "native"}
    if kind == "plan-and-execute":
        components["planners"] = {"adapter": "dag-rule"}
    else:
        components["team_strategies"] = {"adapter": "defaults"}
    profile = recommended_profile(
        kind,
        version="2",
        provider={"adapter": "evaluation-borrowed"},
        components=components,
    )
    members = {
        "researcher": AgentSpec(
            "researcher",
            "Read the task request. If target or quantity is missing return {request,lookup:null}, without guessing. Otherwise call inventory_lookup with the exact dataset_id and target. Return only JSON {request,lookup}, preserving the original request and the actual lookup tool receipt; do not calculate or invent inventory facts. Exact output schema: "
            + canonical(_EVIDENCE_SCHEMA),
            tools=("inventory_lookup",),
            max_decisions=2,
            output_schema=_EVIDENCE_SCHEMA,
        ),
        "writer": AgentSpec(
            "writer",
            "Consume the supplied researcher evidence (for a Team, results.researcher). If required input is missing or quantity exceeds stock, return needs_input and total=null. If the actual lookup says found=false return not_found and total=null. Otherwise call calculator using exactly the original request quantity and the lookup item's unit_price_cents. Consume its actual receipt and return completed and that total in integer cents. Return only JSON matching this schema: "
            + canonical(OUTPUT_SCHEMA),
            tools=("calculator",),
            max_decisions=2,
            output_schema=OUTPUT_SCHEMA,
        ),
    }
    harness = recommended_harness(kind, members, version="2", child_budget=8)
    return RuntimeBuilder(registry, base_dir=directory), profile, harness


def _input_model(action, expected):
    if action.get("kind") != "model" or action.get("status") != "completed":
        return False
    messages = action.get("snapshot", [])
    if len(messages) < 2 or messages[1].get("role") != "user":
        return False
    try:
        return canonical(json.loads(messages[1]["content"])) == canonical(expected)
    except (KeyError, ValueError, TypeError, ValidationError):
        return False


def _consumed(actions, receipt):
    """Require the final model action to have consumed this completed receipt."""
    if (
        not actions
        or actions[-1].get("kind") != "model"
        or actions[-1].get("status") != "completed"
    ):
        return False
    position = next((i for i, action in enumerate(actions) if action["id"] == receipt["id"]), None)
    if position is None or position >= len(actions) - 1:
        return False
    return any(
        message.get("role") == "tool"
        and message.get("tool_call_id") == receipt.get("call_id")
        and message.get("content") == canonical(receipt.get("result"))
        for message in actions[-1].get("snapshot", [])
    )


def _score(case, parent, children, kind):
    checks = dict.fromkeys(_CHECKS, False)
    output, expected = parent.get("result"), case["expected"]
    valid = Draft202012Validator(OUTPUT_SCHEMA).is_valid(output)
    checks["status"] = (
        valid and parent["state"] == "succeeded" and output["status"] == expected["status"]
    )
    checks["total"] = (
        valid
        and type(output["total"]) is type(expected["total"])
        and output["total"] == expected["total"]
    )
    calls = parent["orchestration"]["children"]
    checks["managed_members"] = (
        [call["member"] for call in calls] == ["researcher", "writer"]
        and len(children) == 2
        and all(
            child.get("parent_id") == parent["id"] and child["id"] == call["run_id"]
            for child, call in zip(children, calls, strict=True)
        )
    )
    if not checks["managed_members"]:
        return checks
    researcher, writer = children
    checks["stopped"] = parent["state"] == "succeeded" and all(
        child["state"] == "succeeded"
        and not child.get("pending")
        and all(a["status"] == "completed" for a in child["actions"])
        for child in children
    )
    lookups = [a for a in researcher["actions"] if a["kind"] == "tool"]
    calculators = [a for a in writer["actions"] if a["kind"] == "tool"]
    request = case["request"]
    missing = request["target"] is None or request["quantity"] is None
    lookup = None if missing else _lookup(case["dataset"], request)
    if missing:
        checks["lookup_receipt"] = not lookups
    else:
        checks["lookup_receipt"] = len(lookups) == 1 and all(
            a.get("tool") == "inventory_lookup"
            and a["status"] == "completed"
            and a.get("arguments")
            == {"dataset_id": request["dataset_id"], "target": request["target"]}
            and a.get("result") == lookup
            and _consumed(researcher["actions"], a)
            for a in lookups
        )
    evidence = {"request": request, "lookup": lookup}
    expected_writer_input = (
        {"task": parent["input"], "results": {"researcher": evidence}}
        if kind == "team"
        else evidence
    )
    models = [a for a in writer["actions"] if a["kind"] == "model"]
    checks["prior_evidence"] = (
        checks["lookup_receipt"]
        and researcher.get("result") == evidence
        and writer["input"] == expected_writer_input
        and bool(models)
        and all(_input_model(a, expected_writer_input) for a in models)
    )
    if expected["status"] != "completed":
        checks["calculator_receipt"] = not calculators
    else:
        arguments = {
            "quantity": request["quantity"],
            "unit_price_cents": lookup["item"]["unit_price_cents"],
        }
        checks["calculator_receipt"] = len(calculators) == 1 and all(
            a.get("tool") == "calculator"
            and a["status"] == "completed"
            and a.get("arguments") == arguments
            and a.get("result") == {"total": expected["total"]}
            and _consumed(writer["actions"], a)
            for a in calculators
        )
    return checks


def _usage(attempts):
    if not attempts or any(a["usage"] is None for a in attempts):
        return None
    return {
        name: sum(a["usage"][name] for a in attempts) for name in ("input_tokens", "output_tokens")
    }


def _attempts(attempts):
    allowed = {
        "responded",
        "timeout",
        "cancelled_unknown",
        "provider_failure",
        "provider_error",
        "validation_error",
        "budget_exceeded",
        "unknown",
    }
    return [
        {
            "status": a["status"]
            if type(a["status"]) is str and a["status"] in allowed
            else "provider_failure",
            "usage": copy.deepcopy(a["usage"]),
            "latency_ms": a["latency_ms"],
        }
        for a in attempts
    ]


def _usage_provenance(attempts, fixture):
    return {
        "source": "offline-fixture" if fixture else "provider-reported",
        "known_usage_calls": sum(a["usage"] is not None for a in attempts),
        "unknown_usage_calls": sum(a["usage"] is None for a in attempts),
    }


async def evaluate_orchestration(
    provider=None,
    *,
    kind="plan-and-execute",
    cases=None,
    limits=None,
    evidence_dir=None,
    offline=False,
    prices=None,
    model_continuation=False,
):
    """Measure real managed member results and receipts, without implicit I/O.

    A single audit bounds requests across every case, repeat and member. Unknown
    or unfinished runs are observed on reconnection, never resumed for scoring.
    Provider clients are borrowed; the evaluation owns and closes its runtimes.
    """
    if type(model_continuation) is not bool:
        raise ValidationError("Model continuation enablement must be boolean")
    if kind not in {"plan-and-execute", "team"} or type(offline) is not bool:
        raise ValidationError(
            "Evaluation requires a supported orchestration kind and boolean offline flag"
        )
    limits = EvaluationLimits() if limits is None else limits
    if not isinstance(limits, EvaluationLimits):
        raise ValidationError("Orchestration evaluation requires EvaluationLimits")
    selected = (load_orchestration_cases() if cases is None else _validate_cases(cases))[
        : limits.max_cases
    ]
    prices = _prices(prices)
    identity = None if provider is None else _safe_identity(provider)
    fixture = offline or identity is not None and identity["offline_fixture"]
    frozen = [
        {"case_id": case["id"], "repeat": repeat}
        for case in selected
        for repeat in range(limits.repeats)
    ]
    report = {
        "version": "1",
        "kind": "orchestration-task-evaluation",
        "orchestration_kind": kind,
        "dataset_sha256": digest({"version": "1", "cases": selected}),
        "status": "not_run",
        "reason": None,
        "offline": fixture,
        "model_quality": None,
        "provider": identity,
        "limits": asdict(limits),
        "prices": prices,
        "total": len(frozen),
        "passed": 0,
        "pass_rate": None,
        "calls": 0,
        "usage": None,
        "cost_usd": None,
        "cases": [],
        "frozen_selection": frozen,
        "usage_provenance": None,
        "evidence_retained": evidence_dir is not None,
        "evaluates": "managed inventory evidence, arithmetic receipts, final outcomes and stopping",
    }
    if provider is None:
        report["reason"] = "provider_not_configured"
        return report
    if getattr(getattr(provider, "supported", None), "tools", None) is False:
        report["reason"] = "provider_tools_unsupported"
        return report
    if limits.max_cost_usd is not None:
        report["reason"] = "cost_cap_not_enforceable"
        return report
    if not fixture and (
        identity.get("max_output_tokens") != limits.max_output_tokens
        or identity.get("timeout") != limits.timeout_seconds
    ):
        report["reason"] = "provider_bounds_unverified"
        return report
    owned, directory = _evidence_directory(evidence_dir, frozen)
    audited = _OrchestrationProvider(provider, limits)
    try:
        for case in selected:
            for repeat in range(limits.repeats):
                row = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "repeat": repeat,
                    "dataset_sha256": digest(case["dataset"]),
                    "passed": False,
                    "checks": dict.fromkeys(_CHECKS, False),
                    "calls": 0,
                    "state": "not_run",
                    "usage": None,
                    "cost_usd": None,
                    "latency_ms": 0,
                    "attempts": [],
                    "replay_same_receipt": False,
                    "recovered_after_restart": False,
                }
                report["cases"].append(row)
                if len(audited.attempts) >= limits.max_calls:
                    row["reason"] = "call_limit_reached"
                    continue
                path = _new_evidence_path(directory, case["id"], repeat)
                before, started = len(audited.attempts), time.perf_counter()
                builder, profile, harness = _assembly(
                    case, audited, kind, directory, model_continuation=model_continuation
                )
                row["runtime"] = {
                    "name": profile.name,
                    "version": profile.version,
                    "identity_sha256": digest(profile.identity),
                }
                row["harness"] = {
                    "identity_sha256": digest(harness.identity),
                    "definition_sha256": harness.identity["definition_digest"],
                }
                input = {"task": case["task"], "request": case["request"]}
                async with await builder.abuild(profile, path) as runtime:
                    handle = runtime.submit(
                        harness.definition, input, command_id="evaluate:first", budget=32
                    )
                    snapshot = await runtime.drive(handle.run_id)
                    row["replay_same_receipt"] = (
                        runtime.submit(
                            harness.definition, input, command_id="evaluate:first", budget=32
                        )
                        == handle
                    )
                    parent = runtime.store.run(handle.run_id)
                    children = [
                        runtime.store.run(c["run_id"]) for c in parent["orchestration"]["children"]
                    ]
                    row["checks"] = _score(case, parent, children, kind)
                    row["run_id"] = handle.run_id
                    row["state"] = snapshot.state
                    row["result_sha256"] = digest(snapshot.result)
                    row["components_sha256"] = digest(parent["manifest"])
                    row["release_sha256"] = parent["release_digest"]
                    row["spent_credits"] = runtime.diagnostics(handle.run_id).budget["spent"]
                    row["members"] = [
                        {
                            "member": call["member"],
                            "run_id": child["id"],
                            "state": child["state"],
                            "model_actions": sum(a["kind"] == "model" for a in child["actions"]),
                            "tool_actions": sum(a["kind"] == "tool" for a in child["actions"]),
                            "actions_sha256": digest(child["actions"]),
                        }
                        for call, child in zip(
                            parent["orchestration"]["children"], children, strict=True
                        )
                    ]
                before_recovery = len(audited.attempts)
                async with await builder.abuild(profile, path) as recovered:
                    replay = recovered.submit(
                        harness.definition, input, command_id="evaluate:first", budget=32
                    )
                    observed = recovered.status(handle.run_id)
                    unchanged = observed == snapshot
                    same_receipt = replay == handle
                additional = len(audited.attempts) - before_recovery
                terminal = snapshot.state in {"succeeded", "failed", "cancelled"}
                row["recovery"] = {
                    "mode": "terminal_replay" if terminal else "observation_only",
                    "same_receipt": same_receipt,
                    "unchanged": unchanged,
                    "additional_calls": additional,
                }
                row["recovered_after_restart"] = (
                    terminal and unchanged and same_receipt and additional == 0
                )
                row["checks"]["recovery"] = (
                    row["replay_same_receipt"] and row["recovered_after_restart"]
                )
                attempts = audited.attempts[before:]
                row["calls"] = len(attempts)
                row["attempts"] = _attempts(attempts)
                row["usage"] = _usage(attempts)
                row["usage_provenance"] = _usage_provenance(attempts, fixture)
                row["cost_usd"] = _cost(row["usage"], prices)
                row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
                row["passed"] = all(row["checks"].values())
        report["status"] = "completed"
        report["calls"] = len(audited.attempts)
        report["usage"] = _usage(audited.attempts)
        report["usage_provenance"] = _usage_provenance(audited.attempts, fixture)
        report["cost_usd"] = _cost(report["usage"], prices)
        report["passed"] = sum(row["passed"] for row in report["cases"])
        report["pass_rate"] = report["passed"] / report["total"]
        report["attempt_statuses"] = dict(Counter(a["status"] for a in _attempts(audited.attempts)))
        report["summary"] = summarize_evaluation(report["cases"])
        if not fixture:
            report["model_quality"] = {"task_success_rate": report["pass_rate"]}
        return report
    finally:
        if owned is not None:
            owned.cleanup()
