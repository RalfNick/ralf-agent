"""Bounded proposal-quality evaluation through the managed model planner.

Workers are not executed. This measures proposed DAG semantics and explicit
stop decisions, not application completion, DAG recovery, or framework parity.
Offline scripted fixtures are always reported separately from model quality.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as SchemaValidationError

from .errors import BudgetExceeded, ValidationError
from .evaluation_cases import CASES_SCHEMA, frozen_cases_document
from .types import ModelResponse, canonical, digest


@dataclass(frozen=True)
class EvaluationLimits:
    max_cases: int = 20
    max_calls: int = 20
    max_output_tokens: int = 2048
    timeout_seconds: float = 60
    repeats: int = 1
    max_cost_usd: float | None = None

    def __post_init__(self):
        for name, maximum in [
            ("max_cases", 1000),
            ("max_calls", 10000),
            ("max_output_tokens", 100000),
            ("repeats", 100),
        ]:
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValidationError(f"{name} requires a bounded positive integer")
        for name in ("timeout_seconds", "max_cost_usd"):
            value = getattr(self, name)
            if value is None and name == "max_cost_usd":
                continue
            minimum = 0 if name == "max_cost_usd" else 0.000001
            if type(value) not in {int, float} or not math.isfinite(value) or value < minimum:
                raise ValidationError(f"{name} requires finite non-negative bounded configuration")
        if self.timeout_seconds > 3600:
            raise ValidationError("timeout_seconds must be at most one hour")


def _validate_cases(document):
    try:
        canonical(document)
        Draft202012Validator(CASES_SCHEMA).validate(document)
    except (SchemaValidationError, TypeError) as exc:
        raise ValidationError("Planning cases do not match the frozen case schema") from exc
    cases = document["cases"]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValidationError("Planning case IDs must be unique")
    for case in cases:
        names = [member["name"] for member in case["members"]]
        if len(set(names)) != len(names):
            raise ValidationError("Planning member names must be unique")
        try:
            for member in case["members"]:
                Draft202012Validator.check_schema(member["input_schema"])
        except SchemaError as exc:
            raise ValidationError("Planning member input schema is invalid") from exc
        oracle = case["oracle"]
        if oracle["status"] == "plan":
            mentioned = (
                set(oracle["required_members"])
                | set(oracle["allowed_members"])
                | set(oracle["member_counts"])
                | set(oracle["arguments"])
                | set(oracle.get("allow_skipped", []))
            )
            mentioned.update(
                name for pair in oracle["dependencies"] + oracle["independent"] for name in pair
            )
            for condition in oracle["conditions"]:
                mentioned.update([condition["member"], condition["source_member"]])
            for fields in oracle["arguments"].values():
                mentioned.update(
                    item["source_member"] for item in fields.values() if "source_member" in item
                )
            if "source_member" in oracle["output"]:
                mentioned.add(oracle["output"]["source_member"])
            if not mentioned <= set(names) or not set(oracle["required_members"]) <= set(
                oracle["allowed_members"]
            ):
                raise ValidationError(
                    "Planning oracle refers to an unregistered or disallowed member"
                )
    return copy.deepcopy(cases)


def load_planning_cases(path=None):
    """Return detached cases; defaults are also available in an installed wheel."""
    if path is None:
        document = frozen_cases_document()
    else:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValidationError("Planning case document cannot be read") from exc
    return _validate_cases(document)


def _source_matches(binding, expected, by_id):
    if not isinstance(binding, dict):
        return False
    if "literal" in expected:
        return binding.get("kind") == "literal" and canonical(binding.get("value")) == canonical(
            expected["literal"]
        )
    if binding.get("kind") != "ref" or binding.get("path", []) != expected.get("path", []):
        return False
    source = binding.get("source", "input")
    if "source_member" in expected:
        if by_id.get(source, {}).get("member") != expected["source_member"]:
            return False
    elif source != expected["source"]:
        return False
    return all(
        canonical(binding.get(name, True if name == "required" else None))
        == canonical(expected[name])
        for name in ("required", "default")
        if name in expected
    )


def _fields(binding):
    if not isinstance(binding, dict):
        return {}
    if binding.get("kind") == "object" and isinstance(binding.get("fields"), dict):
        return binding["fields"]
    if binding.get("kind") == "literal" and isinstance(binding.get("value"), dict):
        return {
            name: {"kind": "literal", "value": value} for name, value in binding["value"].items()
        }
    return {}


def _argument_schema(binding, schema):
    if not isinstance(binding, dict):
        return False
    try:
        if binding.get("kind") == "literal":
            Draft202012Validator(schema).validate(binding.get("value"))
            return True
        if binding.get("kind") == "object":
            fields = _fields(binding)
            if not isinstance(schema, dict):
                return schema is True
            if schema.get("type", "object") != "object":
                return False
            if not set(schema.get("required", [])) <= set(fields):
                return False
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False and not set(fields) <= set(properties):
                return False
            return all(
                item.get("kind") == "ref"
                or _argument_schema(
                    item, properties.get(name, schema.get("additionalProperties", {}))
                )
                for name, item in fields.items()
            )
        # The proposal cannot assert the unknown output type of another member.
        # The shared binding validator checks provenance and runtime resolution.
        return binding.get("kind") == "ref" and schema is not False
    except (SchemaValidationError, TypeError):
        return False


def _ancestors(nodes):
    by_id = {node["id"]: node for node in nodes}
    result = {}

    def visit(id, active):
        if id in active or id not in by_id:
            raise ValidationError("Planning graph has a cycle or missing dependency")
        if id in result:
            return result[id]
        value = set()
        for parent in by_id[id].get("depends_on", []):
            value.add(parent)
            value.update(visit(parent, active | {id}))
        result[id] = value
        return value

    for id in by_id:
        visit(id, set())
    return result


def score_planning_proposal(case, proposal):
    """Pure semantic oracle; node labels and serialization order are irrelevant."""
    from .dag_planning import DAGProposal, PlanningConclusion

    checks = {
        name: False
        for name in (
            "decision",
            "dag",
            "members",
            "required_steps",
            "dependencies",
            "arguments",
            "conditions",
            "output",
            "stop",
        )
    }
    if hasattr(proposal, "to_dict"):
        proposal = proposal.to_dict()
    if not isinstance(proposal, dict):
        return {"passed": False, "checks": checks}
    oracle = case["oracle"]
    status = proposal.get("status")
    checks["decision"] = status == oracle["status"]
    if status in {"refused", "needs_input"}:
        try:
            if set(proposal) != {"status", "reason"}:
                raise ValidationError("A stop decision requires only status and reason")
            PlanningConclusion(status, proposal["reason"])
            checks["stop"] = checks["decision"]
        except (ValidationError, TypeError, KeyError):
            pass
        for name in (
            "dag",
            "members",
            "required_steps",
            "dependencies",
            "arguments",
            "conditions",
            "output",
        ):
            checks[name] = checks["stop"]
        return {"passed": all(checks.values()), "checks": checks}
    if status != "plan" or oracle["status"] != "plan":
        return {"passed": False, "checks": checks}
    checks["stop"] = True
    nodes = proposal.get("nodes")
    if (
        not isinstance(nodes, list)
        or not nodes
        or any(not isinstance(node, dict) for node in nodes)
    ):
        return {"passed": False, "checks": checks}
    if any(
        not isinstance(node.get("id"), str)
        or not isinstance(node.get("member"), str)
        or not isinstance(node.get("depends_on", []), list)
        or any(not isinstance(parent, str) for parent in node.get("depends_on", []))
        for node in nodes
    ):
        return {"passed": False, "checks": checks}
    by_id = {node["id"]: node for node in nodes}
    by_member = {}
    for node in nodes:
        by_member.setdefault(node["member"], []).append(node)
    registered = {member["name"] for member in case["members"]}
    checks["members"] = set(by_member) <= registered & set(oracle["allowed_members"])
    checks["required_steps"] = (
        set(oracle["required_members"]) <= set(by_member)
        and len(nodes) <= oracle["max_nodes"]
        and all(
            len(by_member.get(member, [])) == count
            for member, count in oracle["member_counts"].items()
        )
    )
    try:
        validated = DAGProposal.from_dict(proposal)
        validated.validate_members(registered)
        checks["dag"] = len(by_id) == len(nodes)
    except (ValidationError, TypeError, KeyError, ValueError):
        pass
    try:
        ancestors = _ancestors(nodes)
        checks["dependencies"] = all(
            by_member.get(before)
            and by_member.get(after)
            and all(
                any(source["id"] in ancestors[target["id"]] for source in by_member[before])
                for target in by_member[after]
            )
            for before, after in oracle["dependencies"]
        ) and all(
            by_member.get(left)
            and by_member.get(right)
            and all(
                a["id"] not in ancestors[b["id"]] and b["id"] not in ancestors[a["id"]]
                for a in by_member[left]
                for b in by_member[right]
            )
            for left, right in oracle["independent"]
        )
    except ValidationError:
        checks["dependencies"] = False
    schemas = {member["name"]: member["input_schema"] for member in case["members"]}
    checks["arguments"] = all(
        by_member.get(member)
        and all(
            _source_matches(node.get("input"), fields["$"], by_id)
            if "$" in fields
            else all(
                _source_matches(_fields(node.get("input")).get(field), expected, by_id)
                for field, expected in fields.items()
            )
            for node in by_member[member]
        )
        for member, fields in oracle["arguments"].items()
    ) and all(
        _argument_schema(node.get("input"), schemas.get(node["member"], False)) for node in nodes
    )
    conditions = {condition["member"]: condition for condition in oracle["conditions"]}
    skipped = set(oracle.get("allow_skipped", []))
    checks["conditions"] = all(
        (
            node.get("when") is None
            if member not in conditions
            else (
                isinstance(node.get("when"), dict)
                and _source_matches(node["when"].get("value"), conditions[member], by_id)
                and canonical(node["when"].get("equals")) == canonical(conditions[member]["equals"])
                and node["when"].get("negate", False) is conditions[member]["negate"]
            )
        )
        and node.get("allow_skipped_dependencies", False) is (member in skipped)
        for member, group in by_member.items()
        for node in group
    ) and all(member in by_member for member in conditions)
    checks["output"] = _source_matches(proposal.get("output"), oracle["output"], by_id)
    return {
        "passed": all(checks.values()),
        "checks": {name: bool(value) for name, value in checks.items()},
    }


def _usage(value):
    if not isinstance(value, dict) or any(
        type(value.get(name)) is not int or value[name] < 0
        for name in ("input_tokens", "output_tokens")
    ):
        return None
    return {name: value[name] for name in ("input_tokens", "output_tokens")}


def _prices(value):
    if value is None:
        return None
    names = {"input_per_million_usd", "output_per_million_usd"}
    if (
        not isinstance(value, dict)
        or set(value) != names
        or any(
            type(item) not in {int, float} or not math.isfinite(item) or item < 0
            for item in value.values()
        )
    ):
        raise ValidationError(
            "Prices require finite non-negative input/output USD per million tokens"
        )
    return copy.deepcopy(value)


def _cost(usage, prices):
    if usage is None or prices is None:
        return None
    return (
        usage["input_tokens"] * prices["input_per_million_usd"]
        + usage["output_tokens"] * prices["output_per_million_usd"]
    ) / 1_000_000


def _safe_identity(provider):
    identity = copy.deepcopy(provider.identity)
    canonical(identity)
    safe = {
        name: identity[name]
        for name in (
            "kind",
            "version",
            "model",
            "max_output_tokens",
            "timeout",
            "generation",
            "stream",
            "token_parameter",
            "json_mode",
            "api_version",
        )
        if name in identity
    }
    # Credentials, URLs and arbitrary adapter-specific fields stay in the local
    # runtime. A digest still distinguishes all full configuration identities.
    safe["configuration_sha256"] = digest(identity)
    return safe


def _evidence(value):
    if value is None:
        return None

    def normalize(item, active):
        if isinstance(item, (dict, list, tuple)):
            if id(item) in active:
                return {"invalid_json_type": "cycle"}
            active = active | {id(item)}
            if isinstance(item, dict):
                return {
                    key
                    if isinstance(key, str)
                    else "invalid-key-type:" + type(key).__name__: normalize(child, active)
                    for key, child in item.items()
                }
            return [normalize(child, active) for child in item]
        if isinstance(item, float) and not math.isfinite(item):
            return {"invalid_json_type": "nonfinite-number", "number": str(item)}
        if item is None or type(item) in {str, int, float, bool}:
            return item
        return {"invalid_json_type": type(item).__name__}

    def redact(item):
        if isinstance(item, str):
            return {"type": "string", "sha256": digest(item), "length": len(item)}
        if isinstance(item, dict):
            known = {
                "status",
                "reason",
                "nodes",
                "output",
                "output_schema",
                "id",
                "member",
                "depends_on",
                "input",
                "when",
                "allow_skipped_dependencies",
                "kind",
                "source",
                "path",
                "required",
                "default",
                "value",
                "fields",
                "equals",
                "negate",
            }
            return {
                (key if key in known else "key:" + digest(key)): redact(value)
                for key, value in item.items()
            }
        if isinstance(item, list):
            return [redact(child) for child in item]
        return {"type": type(item).__name__, "sha256": digest(item)}

    try:
        checksum = digest(value)
    except (ValidationError, RecursionError):
        value = normalize(value, set())
        return {
            "sha256": digest(value),
            "hash_basis": "normalized-non-json-evidence",
            "invalid_json": True,
            "redacted": redact(value),
        }
    return {"sha256": checksum, "hash_basis": "canonical-json", "redacted": redact(value)}


def _evidence_directory(evidence_dir, selection):
    owned = (
        tempfile.TemporaryDirectory(prefix="ralf-planning-eval-") if evidence_dir is None else None
    )
    directory = Path(owned.name if owned else evidence_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in selection:
        path = directory / f"{item['case_id']}-{item['repeat']}.sqlite"
        if path.exists() or path.is_symlink():
            if owned:
                owned.cleanup()
            raise ValidationError(
                "Use a fresh evidence directory; existing evaluation records are immutable"
            )
    return owned, directory


def _new_evidence_path(directory, case_id, repeat):
    path = directory / f"{case_id}-{repeat}.sqlite"
    # Restrict raw evidence before SQLite writes it and reject symlink races.
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    return path


class _AuditedProvider:
    def __init__(self, provider, limits):
        self.provider, self.limits = provider, limits
        self.attempts = []

    @property
    def identity(self):
        return {
            "kind": "evaluation-accounted-provider",
            "version": "1",
            "provider": self.provider.identity,
            "limits": asdict(self.limits),
        }

    def validate_request(self, messages, tools):
        validate = getattr(self.provider, "validate_request", None)
        if callable(validate):
            validate(messages, tools)

    async def complete(self, messages, tools):
        if len(self.attempts) >= self.limits.max_calls:
            raise BudgetExceeded("Planning evaluation call limit reached")
        started = time.perf_counter()
        record = {"usage": None, "output": None, "status": "unknown"}
        self.attempts.append(record)
        try:
            response = await asyncio.wait_for(
                self.provider.complete(messages, tools), self.limits.timeout_seconds
            )
            if not isinstance(response, ModelResponse):
                raise ValidationError("Planning provider must return a ModelResponse")
            record.update(
                usage=_usage(response.usage),
                output=copy.deepcopy(response.output),
                status="responded",
            )
            return response
        except TimeoutError:
            record["status"] = "timeout"
            raise
        except asyncio.CancelledError:
            record["status"] = "cancelled_unknown"
            raise
        except Exception as exc:
            record["status"] = getattr(exc, "code", "provider_failure")
            raise
        finally:
            record["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)


class _ManagedEvaluationCaller:
    def __init__(self, engine, planner):
        self.engine, self.planner, self.run_id = engine, planner, None

    async def call(self, call_id, member, input):
        if member != "@planner" or self.run_id is not None:
            raise ValidationError("Evaluation permits exactly one managed planner child")
        handle = self.engine.submit(
            self.planner.agent, input, command_id=f"evaluate:{call_id}", budget=1
        )
        self.run_id = handle.run_id
        return await self.engine.drive(handle.run_id)


async def evaluate_planning(
    provider=None, *, cases=None, limits=None, prices=None, evidence_dir=None, offline=False
):
    """Evaluate a frozen selection using one managed ModelDAGPlanner child each.

    Supplying a monetary cap fails closed: the generic provider contract has no
    guaranteed upper input/billing bound. Token usage and cost remain null when
    any attempted request lacks provider usage; failures stay in the denominator.
    Raw response evidence stays in permission-restricted local SQLite records;
    exported report evidence contains hashes and redacted structure only.
    """
    from .dag_planning import ModelDAGPlanner
    from .engine import LocalEngine
    from .planning import PlanningRequest
    from .storage import SQLiteStore
    from .tools import ToolRegistry

    limits = EvaluationLimits() if limits is None else limits
    if not isinstance(limits, EvaluationLimits):
        raise ValidationError("Planning evaluation requires EvaluationLimits")
    prices = _prices(prices)
    cases = (
        load_planning_cases()
        if cases is None
        else _validate_cases({"version": "1", "cases": cases})
    )
    selected = cases[: limits.max_cases]
    frozen = [
        {"case_id": case["id"], "repeat": repeat}
        for case in selected
        for repeat in range(limits.repeats)
    ]
    identity = None if provider is None else _safe_identity(provider)
    fixture = offline or (
        identity is not None
        and any(
            token in identity.get("kind", "").lower() for token in ("scripted", "fixture", "test")
        )
    )
    report = {
        "scope": "offline-planning-fixture" if fixture else "model-planning-quality",
        "status": "not_run",
        "reason": None,
        "model_quality": None,
        "suite_version": "1",
        "suite_sha256": digest(selected),
        "limits": asdict(limits),
        "prices": prices,
        "provider": identity,
        "planner": None,
        "total": len(frozen),
        "passed": 0,
        "pass_rate": None,
        "calls": 0,
        "usage": None,
        "cost_usd": None,
        "cases": [],
        "frozen_selection": frozen,
        "evaluates": "proposal semantics and stop decisions through managed planner child Runs",
        "does_not_establish": [
            "worker completion",
            "application outcome",
            "parent DAG recovery",
            "framework parity",
        ],
    }
    if provider is None:
        report["reason"] = "provider_not_configured"
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
    audited = _AuditedProvider(provider, limits)
    planner = ModelDAGPlanner()
    report["planner"] = {
        "identity_sha256": digest(planner.identity),
        "agent_name": planner.agent.name,
        "tools": list(planner.agent.tools),
        "max_decisions": planner.agent.max_decisions,
    }
    if planner.agent.tools or planner.agent.max_decisions != 1 or planner.agent.model_credits != 1:
        raise ValidationError(
            "Planning evaluation requires a fixed single-decision tool-free planner"
        )
    owned_temp, directory = _evidence_directory(evidence_dir, frozen)
    try:
        for case in selected:
            for repeat in range(limits.repeats):
                result = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "repeat": repeat,
                    "passed": False,
                    "status": "budget_exhausted",
                    "run_id": None,
                    "calls": 0,
                    "usage": None,
                    "usage_source": "unavailable",
                    "cost_usd": None,
                    "latency_ms": 0,
                    "checks": {},
                    "evidence": None,
                }
                if len(audited.attempts) >= limits.max_calls:
                    report["cases"].append(result)
                    continue
                before = len(audited.attempts)
                started = time.perf_counter()
                path = _new_evidence_path(directory, case["id"], repeat)
                with LocalEngine(
                    SQLiteStore(path), providers={"default": audited}, tools=ToolRegistry()
                ) as engine:
                    caller = _ManagedEvaluationCaller(engine, planner)
                    request = PlanningRequest(
                        {
                            "instruction": case["task"],
                            "context": case["context"],
                            "capabilities": case["members"],
                        },
                        [member["name"] for member in case["members"]],
                        [],
                        0,
                    )
                    try:
                        proposed = await planner.plan(request, caller)
                        score = score_planning_proposal(case, proposed)
                        result.update(
                            score, status="passed" if score["passed"] else "oracle_failed"
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        result["status"] = (
                            "rejected_proposal"
                            if isinstance(exc, ValidationError)
                            else getattr(exc, "code", "planning_failed")
                        )
                    result["run_id"] = caller.run_id
                    attempts = audited.attempts[before:]
                    if any(attempt["status"] == "timeout" for attempt in attempts):
                        result["status"] = "timeout"
                    elif attempts and attempts[-1]["status"] not in {"responded", "unknown"}:
                        result["status"] = "provider_failed"
                    result["calls"] = len(attempts)
                    if attempts and all(attempt["usage"] is not None for attempt in attempts):
                        result["usage"] = {
                            name: sum(attempt["usage"][name] for attempt in attempts)
                            for name in ("input_tokens", "output_tokens")
                        }
                        result["usage_source"] = "provider"
                    result["cost_usd"] = _cost(result["usage"], prices)
                    if attempts:
                        result["evidence"] = _evidence(attempts[-1]["output"])
                    if caller.run_id:
                        result["managed_run_state"] = engine.status(caller.run_id).state
                        result["event_kinds"] = [
                            event.kind for event in engine.events(caller.run_id)
                        ]
                    await engine.wait_for_threads()
                result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
                report["cases"].append(result)
        report.update(
            status="completed",
            passed=sum(case["passed"] for case in report["cases"]),
            calls=len(audited.attempts),
        )
        report["pass_rate"] = report["passed"] / report["total"]
        report["model_quality"] = None if fixture else report["pass_rate"]
        report["dimensions"] = {
            name: sum(case.get("checks", {}).get(name) is True for case in report["cases"])
            / report["total"]
            for name in (
                "decision",
                "dag",
                "members",
                "required_steps",
                "dependencies",
                "arguments",
                "conditions",
                "output",
                "stop",
            )
        }
        report["outcomes"] = dict(Counter(case["status"] for case in report["cases"]))
        if audited.attempts and all(attempt["usage"] is not None for attempt in audited.attempts):
            report["usage"] = {
                name: sum(attempt["usage"][name] for attempt in audited.attempts)
                for name in ("input_tokens", "output_tokens")
            }
        report["cost_usd"] = _cost(report["usage"], prices)
        report["evidence_retained"] = evidence_dir is not None
        return report
    finally:
        if owned_temp:
            owned_temp.cleanup()
