import asyncio
import importlib
import json

import pytest

from ralf_agent import EvaluationLimits, ModelResponse, ModelStreamEvent, ToolCall
from ralf_agent.errors import ValidationError


class Provider:
    identity = {"kind": "offline-model-check-fixture", "version": "1"}

    def __init__(self):
        self.calls = 0
        self.closed = False
        self.stream_closed = 0

    async def complete(self, messages, tools):
        self.calls += 1
        if tools and not any(m["role"] == "tool" for m in messages):
            return ModelResponse(
                tool_calls=(ToolCall("ralf_model_echo", {"value": "RALF_TOOL_CHECK"}, "call"),),
                usage={"input_tokens": 2, "output_tokens": 1},
            )
        return ModelResponse({"ok": True}, usage={"input_tokens": 2, "output_tokens": 1})

    async def stream(self, messages, tools):
        self.calls += 1
        try:
            yield ModelStreamEvent("text", text='{"ok":true}')
            yield ModelStreamEvent(
                "response",
                response=ModelResponse({"ok": True}, usage={"input_tokens": 2, "output_tokens": 1}),
            )
        finally:
            self.stream_closed += 1

    async def aclose(self):
        self.closed = True


def evaluate(*args, **kwargs):
    api = importlib.import_module("ralf_agent")
    assert hasattr(api, "evaluate_model_compatibility"), "Model compatibility suite is missing"
    return api.evaluate_model_compatibility(*args, **kwargs)


def test_no_provider_returns_not_run_without_creating_private_evidence(tmp_path):
    result = asyncio.run(evaluate(evidence_dir=tmp_path / "absent"))
    assert result["status"] == "not_run" and result["reason"] == "provider_not_configured"
    assert result["calls"] == 0 and result["model_quality"] is None
    assert not (tmp_path / "absent").exists()


def test_managed_probe_checks_actual_tool_receipt_and_stream_lifetime(tmp_path):
    provider = Provider()
    result = asyncio.run(evaluate(provider, evidence_dir=tmp_path / "evidence"))
    assert result["status"] == "completed" and result["passed"] == 5 and result["total"] == 5
    assert result["offline"] is True and result["model_quality"] is None
    assert result["calls"] == 6 and provider.calls == 6 and provider.closed is False
    assert provider.stream_closed == 2
    tool = next(c for c in result["cases"] if c["case_id"] == "tool")
    assert tool["checks"]["tool_receipt"] and tool["model_calls"] == 2
    closed = next(c for c in result["cases"] if c["case_id"] == "stream_close")
    assert closed["state"] == "waiting_reconciliation" and closed["checks"]["consumer_closed"]
    assert result["usage"] is None and result["known_usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
    }
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (tmp_path / "evidence").glob("*.sqlite"))
    assert "secret" not in json.dumps(result)
    with pytest.raises(ValidationError):
        asyncio.run(evaluate(provider, evidence_dir=tmp_path / "evidence"))
    assert provider.calls == 6


def test_probe_budget_stops_calls_without_reporting_success(tmp_path):
    provider = Provider()
    limits = EvaluationLimits(max_cases=5, max_calls=2, max_output_tokens=32, timeout_seconds=0.2)
    result = asyncio.run(evaluate(provider, limits=limits, evidence_dir=tmp_path / "evidence"))
    assert result["calls"] == 2 and provider.calls == 2 and result["passed"] == 2
    assert all(not c["passed"] for c in result["cases"][2:])


def test_wrong_tool_arguments_are_not_a_valid_compatibility_result(tmp_path):
    class Wrong(Provider):
        async def complete(self, messages, tools):
            self.calls += 1
            if tools and not any(m["role"] == "tool" for m in messages):
                return ModelResponse(
                    tool_calls=(ToolCall("ralf_model_echo", {"value": "wrong"}, "call"),)
                )
            return ModelResponse({"ok": True})

    result = asyncio.run(evaluate(Wrong(), cases=["tool"], evidence_dir=tmp_path / "evidence"))
    assert result["passed"] == 0 and result["cases"][0]["checks"]["tool_receipt"] is False


def test_provider_errors_and_identity_are_sanitized_in_public_probe_report(tmp_path):
    class Broken(Provider):
        identity = {"kind": "custom", "api_key": "PRIVATE_SENTINEL"}

        async def complete(self, messages, tools):
            raise RuntimeError("PRIVATE_SENTINEL")

    result = asyncio.run(evaluate(Broken(), cases=["text"], evidence_dir=tmp_path / "evidence"))
    assert result["passed"] == 0 and "PRIVATE_SENTINEL" not in json.dumps(result)


@pytest.mark.parametrize("cases", [["unknown"], ["text", "text"], "text", {"text"}])
def test_invalid_suite_selection_fails_before_evidence_allocation(tmp_path, cases):
    with pytest.raises(ValidationError):
        asyncio.run(evaluate(Provider(), cases=cases, evidence_dir=tmp_path / "absent"))
    assert not (tmp_path / "absent").exists()


def test_stream_unsupported_is_explicit_without_a_model_call(tmp_path):
    class Plain:
        identity = {"kind": "plain", "version": "1"}

        async def complete(self, messages, tools):
            raise AssertionError("No call expected")

    result = asyncio.run(evaluate(Plain(), cases=["stream"], evidence_dir=tmp_path / "evidence"))
    assert result["calls"] == 0 and result["passed"] == 0
    assert result["cases"][0]["state"] == "unsupported"


def test_provided_invalid_usage_cannot_pass_a_compatibility_check(tmp_path):
    class InvalidUsage(Provider):
        async def complete(self, messages, tools):
            return ModelResponse({"ok": True}, usage={"input_tokens": True, "output_tokens": 1})

    result = asyncio.run(
        evaluate(InvalidUsage(), cases=["text"], evidence_dir=tmp_path / "evidence")
    )
    assert result["passed"] == 0 and result["usage"] is None
