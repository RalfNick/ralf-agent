"""Bounded managed protocol/scenario checks, separate from general model quality."""

import copy
import math
from contextlib import aclosing
from dataclasses import asdict

from .errors import BudgetExceeded, ProviderError, ValidationError
from .model_protocol import ModelCapabilities, ModelStreamEvent, json_object
from .planning_evaluation import (
    EvaluationLimits,
    _AuditedProvider,
    _evidence_directory,
    _new_evidence_path,
)
from .ports import _complete_sync_none, is_sync_callable
from .types import AgentSpec, canonical, digest

CASES = ("text", "structured", "tool", "stream", "stream_close")
_PUBLIC_CODES = frozenset(
    {
        "ralf_error",
        "validation_error",
        "idempotency_conflict",
        "budget_exceeded",
        "authorization_denied",
        "definition_mismatch",
        "coordinator_busy",
        "not_found",
        "provider_error",
        "memory_backend_error",
        "execution_failed",
        "unexpected_error",
    }
)


def _public_identity(provider):
    identity = copy.deepcopy(provider.identity)
    canonical(identity)
    safe = {"configuration_sha256": digest(identity)}
    for name in ("kind", "version", "model", "token_parameter", "api_version"):
        value = identity.get(name)
        if isinstance(value, str) and len(value) <= 128:
            safe[name] = value
    for name in ("max_output_tokens", "timeout"):
        value = identity.get(name)
        if (type(value) is int or type(value) is float and math.isfinite(value)) and value > 0:
            safe[name] = value
    for name in ("stream", "json_mode"):
        if type(identity.get(name)) is bool:
            safe[name] = identity[name]
    generation = identity.get("generation")
    if isinstance(generation, dict):
        options = {
            name: value
            for name in ("temperature", "top_p", "seed")
            if type(value := generation.get(name)) is int
            or type(value) is float
            and math.isfinite(value)
        }
        if options:
            safe["generation"] = options
    return safe


def _public_code(error):
    code = None if error is None else error.get("code")
    return (
        None
        if error is None
        else code
        if isinstance(code, str) and code in _PUBLIC_CODES
        else "provider_error"
    )


class _ModeProvider:
    def __init__(self, provider, mode):
        self.provider, self.mode = provider, mode
        self.consumer_closed = False

    @property
    def identity(self):
        return {
            "kind": "model-check-mode",
            "version": "1",
            "provider": self.provider.identity,
            "mode": self.mode,
        }

    def validate_request(self, messages, tools):
        callback = getattr(self.provider, "validate_request", None)
        if callback is not None:
            if not is_sync_callable(callback):
                raise ValidationError("Provider preflight must be synchronous")
            _complete_sync_none(callback(messages, tools), "Provider preflight")

    async def complete(self, messages, tools):
        if self.mode not in {"stream", "stream_close"}:
            return await self.provider.complete(messages, tools)
        stream = self.provider.stream(messages, tools)
        if not callable(getattr(stream, "aclose", None)):
            raise ValidationError("Stream checks require a closable async iterator")
        completed = None
        size = 0
        interrupted = False
        async with aclosing(stream):
            async for event in stream:
                if not isinstance(event, ModelStreamEvent) or completed is not None:
                    raise ValidationError("Invalid complete stream boundary")
                size += len(canonical(asdict(event)).encode("utf-8"))
                if size > 4_000_000:
                    raise ValidationError("Compatibility stream exceeds bound")
                if event.kind == "response":
                    completed = copy.deepcopy(event.response)
                elif event.text and self.mode == "stream_close":
                    interrupted = True
                    break
        if interrupted:
            self.consumer_closed = True
            raise ProviderError("Compatibility consumer intentionally closed before final response")
        if completed is None or self.mode == "stream_close":
            raise ProviderError("Compatibility stream did not satisfy the selected check")
        return completed


class _ProbeProvider(_AuditedProvider):
    async def complete(self, messages, tools):
        from .planning_evaluation import _usage

        result = await super().complete(messages, tools)
        if result.usage is not None and _usage(result.usage) is None:
            self.attempts[-1]["status"] = "invalid_usage"
            raise ValidationError("Provided usage must contain valid token counts")
        return result

    def validate_request(self, messages, tools):
        if len(self.attempts) >= self.limits.max_calls:
            raise BudgetExceeded("Model compatibility call allowance reached")
        self.provider.validate_request(messages, tools)


def _tools():
    from .tools import ToolRegistry

    tools = ToolRegistry()

    @tools.tool(
        effect="read_only",
        name="ralf_model_echo",
        description="Read-only echo for protocol checking",
    )
    def echo(value: str):
        return {"echo": value}

    return tools


async def evaluate_model_compatibility(
    provider=None, *, cases=CASES, limits=None, evidence_dir=None, offline=False
):
    """Explicit provider enables calls; None returns not_run without allocating files.

    Providers are borrowed. Local records contain raw responses; public reports
    contain checks/usage only. Stream-close checks consumer cleanup, not server
    cancellation or billing. Model quality remains null even for online probes.
    """
    from .engine import LocalEngine
    from .storage import SQLiteStore

    if (
        not isinstance(cases, (tuple, list))
        or not cases
        or len(cases) > 5
        or any(not isinstance(c, str) or c not in CASES for c in cases)
        or len(set(cases)) != len(cases)
    ):
        raise ValidationError("Select unique known compatibility cases")
    limits = (
        EvaluationLimits(max_cases=5, max_calls=6, max_output_tokens=1024, timeout_seconds=30)
        if limits is None
        else limits
    )
    if not isinstance(limits, EvaluationLimits) or limits.repeats != 1:
        raise ValidationError("Model compatibility requires single-pass EvaluationLimits")
    selected = list(cases[: limits.max_cases])
    report = {
        "kind": "model-compatibility",
        "version": "1",
        "status": "not_run",
        "offline": bool(offline),
        "model_quality": None,
        "calls": 0,
        "passed": 0,
        "total": len(selected),
        "cases": [],
        "limits": asdict(limits),
        "usage": None,
        "known_usage": {"input_tokens": 0, "output_tokens": 0},
        "cost_usd": None,
    }
    if provider is None:
        report["reason"] = "provider_not_configured"
        return report
    if limits.max_cost_usd is not None:
        report["reason"] = "hard_currency_bound_unavailable"
        return report
    report["provider"] = _public_identity(provider)
    report["offline"] = bool(offline) or any(
        token in str(report["provider"].get("kind", "")).lower()
        for token in ("fixture", "scripted", "offline", "test")
    )
    identity = provider.identity
    if "max_output_tokens" in identity and (
        type(identity["max_output_tokens"]) is not int
        or identity["max_output_tokens"] > limits.max_output_tokens
    ):
        raise ValidationError("Provider output allowance exceeds probe configuration")
    owned, directory = _evidence_directory(
        evidence_dir, [{"case_id": c, "repeat": 0} for c in selected]
    )
    attempts = []
    try:
        for case in selected:
            capabilities = getattr(provider, "capabilities", None)
            unsupported = (
                case in {"stream", "stream_close"}
                and not callable(getattr(provider, "stream", None))
            ) or (
                isinstance(capabilities, ModelCapabilities)
                and (
                    (case == "tool" and not capabilities.tools)
                    or (case in {"stream", "stream_close"} and not capabilities.streaming)
                )
            )
            if unsupported:
                report["cases"].append(
                    {
                        "case_id": case,
                        "state": "unsupported",
                        "passed": False,
                        "model_calls": 0,
                        "checks": {},
                    }
                )
                continue
            mode = _ModeProvider(provider, case)
            audited = _ProbeProvider(mode, limits)
            audited.attempts = attempts
            start = len(attempts)
            spec = AgentSpec(
                "model-compatibility-" + case,
                "model-check:"
                + case
                + ': Return JSON {"ok":true}. '
                + (
                    "First call ralf_model_echo with value RALF_TOOL_CHECK exactly once, then stop."
                    if case == "tool"
                    else "Use no tools."
                ),
                ("ralf_model_echo",) if case == "tool" else (),
                max_decisions=2 if case == "tool" else 1,
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ok"],
                    "properties": {"ok": {"const": True}},
                }
                if case == "structured"
                else None,
            )
            with LocalEngine(
                SQLiteStore(_new_evidence_path(directory, case, 0)),
                providers={"default": audited},
                tools=_tools(),
            ) as engine:
                handle = engine.submit(
                    spec,
                    "Run the selected protocol check.",
                    command_id="check:first",
                    budget=3 if case == "tool" else 1,
                )
                snapshot = await engine.drive(handle.run_id)
                checks = {"runtime": snapshot.state == "succeeded"}
                if case != "stream_close":
                    try:
                        output = (
                            json_object(snapshot.result)
                            if isinstance(snapshot.result, str)
                            else snapshot.result
                        )
                        checks["output"] = canonical(output) == canonical({"ok": True})
                    except (ValueError, ValidationError):
                        checks["output"] = False
                if case == "tool":
                    tools = [a for a in snapshot.actions if a.get("kind") == "tool"]
                    checks["tool_receipt"] = (
                        len(tools) == 1
                        and tools[0]["status"] == "completed"
                        and tools[0]["arguments"] == {"value": "RALF_TOOL_CHECK"}
                        and tools[0].get("result") == {"echo": "RALF_TOOL_CHECK"}
                    )
                elif case == "stream_close":
                    checks = {
                        "consumer_closed": mode.consumer_closed
                        and snapshot.state == "waiting_reconciliation"
                    }
                row = {
                    "case_id": case,
                    "run_id": handle.run_id,
                    "state": snapshot.state,
                    "passed": all(checks.values()),
                    "checks": checks,
                    "model_calls": len(attempts) - start,
                    "error_code": _public_code(snapshot.error),
                }
                report["cases"].append(row)
        report["status"] = "completed"
        report["calls"] = len(attempts)
        report["passed"] = sum(c["passed"] for c in report["cases"])
        known = [a["usage"] for a in attempts if a["usage"] is not None]
        report["known_usage"] = {
            name: sum(u[name] for u in known) for name in ("input_tokens", "output_tokens")
        }
        if attempts and len(known) == len(attempts):
            report["usage"] = dict(report["known_usage"])
        return report
    finally:
        if owned:
            owned.cleanup()
