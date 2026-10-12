import asyncio
import json

import pytest

from ralf_agent.model_compatibility import evaluate_model_compatibility
from ralf_agent.model_protocol import ModelStreamEvent
from ralf_agent.types import ModelResponse, ToolCall


class OutcomeProvider:
    identity = {"kind": "offline-outcome-fixture", "version": "1"}

    def __init__(self, output):
        self.output = output

    async def complete(self, messages, tools):
        if tools and not any(message["role"] == "tool" for message in messages):
            return ModelResponse(
                tool_calls=[ToolCall("ralf_model_echo", {"value": "RALF_TOOL_CHECK"}, "echo")]
            )
        if tools:
            assert any(
                message["role"] == "tool"
                and json.loads(message["content"]) == {"echo": "RALF_TOOL_CHECK"}
                for message in messages
            )
        return ModelResponse(output=self.output)

    async def stream(self, messages, tools):
        yield ModelStreamEvent("text", text="protocol-response")
        yield ModelStreamEvent("response", response=ModelResponse(output=self.output))


@pytest.mark.parametrize("case", ["text", "tool", "stream"])
@pytest.mark.parametrize(
    "output",
    [
        {"ok": False},
        '{"ok":false}',
        {"ok": 1},
        {"ok": True, "extra": "unexpected"},
        "not JSON",
        '{"ok":false,"ok":true}',
    ],
)
def test_wrong_final_response_cannot_pass_protocol_case(tmp_path, case, output):
    report = asyncio.run(
        evaluate_model_compatibility(
            OutcomeProvider(output), cases=[case], evidence_dir=tmp_path / "evidence"
        )
    )
    assert report["passed"] == 0 and report["total"] == 1
    row = report["cases"][0]
    assert row["state"] == "succeeded" and row["checks"]["runtime"] is True
    assert row["checks"]["output"] is False
    assert report["calls"] == (2 if case == "tool" else 1)
    if case == "tool":
        assert row["checks"]["tool_receipt"] is True
    assert report["model_quality"] is None


@pytest.mark.parametrize("case", ["text", "structured", "tool", "stream"])
@pytest.mark.parametrize("output", [{"ok": True}, ' \n{"ok":true}\n '])
def test_requested_final_response_passes_protocol_case(tmp_path, case, output):
    report = asyncio.run(
        evaluate_model_compatibility(
            OutcomeProvider(output), cases=[case], evidence_dir=tmp_path / "evidence"
        )
    )
    assert report["passed"] == report["total"] == 1
    assert report["cases"][0]["checks"]["output"] is True
    assert report["model_quality"] is None
