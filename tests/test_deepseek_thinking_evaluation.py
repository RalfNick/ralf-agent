"""Real HTTP codec in task evaluators; scripted wire replies prove no model quality."""

import asyncio
import importlib
import json

import httpx
import pytest

from ralf_agent.model_check_cli import OfflineCompatibilityProvider
from ralf_agent.model_compatibility import evaluate_model_compatibility
from ralf_agent.orchestration_evaluation import (
    OfflineOrchestrationProvider,
    evaluate_orchestration,
    load_orchestration_cases,
)
from ralf_agent.rag_evaluation import OfflineRAGProvider, evaluate_rag, load_rag_cases
from ralf_agent.types import canonical

_REASONING = "opaque-fixture-protocol-evidence"


def _provider_type():
    provider = getattr(importlib.import_module("ralf_agent"), "DeepSeekThinkingProvider", None)
    assert provider is not None, "Dedicated thinking adapter must be a public SDK component"
    return provider


def _wire(fixture, observed):
    async def reply(request):
        body = json.loads(request.content)
        observed.append(body)
        assert body["thinking"] == {"type": "enabled"}
        assert body["reasoning_effort"] == "high"
        assert "model_continuation" not in canonical(body)
        for message in body["messages"]:
            if message["role"] == "assistant":
                assert message["reasoning_content"] == _REASONING
        result = await fixture.complete(body["messages"], body.get("tools", []))
        content = (
            result.output
            if isinstance(result.output, str) or result.output is None
            else canonical(result.output)
        )
        calls = [
            {
                "id": call.call_id or f"wire-{index}",
                "type": "function",
                "function": {"name": call.name, "arguments": canonical(call.arguments)},
            }
            for index, call in enumerate(result.tool_calls)
        ]
        message = {
            "role": "assistant",
            "content": content,
            "reasoning_content": _REASONING,
            "tool_calls": calls,
        }
        reason = "tool_calls" if calls else "stop"
        usage = {"prompt_tokens": 2, "completion_tokens": 3}
        if body.get("stream"):
            assert not calls
            events = [
                {"choices": [{"index": 0, "delta": {"reasoning_content": _REASONING}}]},
                {"choices": [{"index": 0, "delta": {"content": content}}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
                {"choices": [], "usage": usage},
            ]
            stream = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
            return httpx.Response(
                200,
                content=stream + "data: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"index": 0, "message": message, "finish_reason": reason}],
                "usage": usage,
            },
        )

    return reply


def test_thinking_adapter_passes_all_compatibility_protocol_cases_without_quality_claim():
    provider_type = _provider_type()

    async def run():
        observed = []
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_wire(OfflineCompatibilityProvider(), observed))
        ) as client:
            report = await evaluate_model_compatibility(
                provider_type("fixture", api_key="fixture", client=client),
                offline=True,
                model_continuation=True,
            )
            assert report["passed"] == report["total"] == 5, report
            assert report["calls"] == len(observed) == 6
            assert report["model_quality"] is None and report["offline"] is True
            assert _REASONING not in canonical(report)
            assert client.is_closed is False
        assert client.is_closed is True

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["rag", "plan-and-execute", "team"])
def test_thinking_adapter_runs_recommended_tasks_and_observation_only_recovery(tmp_path, kind):
    provider_type = _provider_type()

    async def run():
        observed = []
        fixture = OfflineRAGProvider() if kind == "rag" else OfflineOrchestrationProvider()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(_wire(fixture, observed))
        ) as client:
            provider = provider_type(
                "fixture", api_key="fixture", client=client, max_output_tokens=2048
            )
            options = {"evidence_dir": tmp_path, "offline": True, "model_continuation": True}
            if kind == "rag":
                report = await evaluate_rag(provider, cases=load_rag_cases()[:1], **options)
                assert report["cases"][0]["recovery"]["additional_model_calls"] == 0
            else:
                report = await evaluate_orchestration(
                    provider, kind=kind, cases=load_orchestration_cases()[:1], **options
                )
                assert report["cases"][0]["recovery"]["additional_calls"] == 0
                assert sum(any(m["role"] == "tool" for m in r["messages"]) for r in observed) == 2
            assert report["passed"] == report["total"] == 1, report
            assert report["model_quality"] is None and report["offline"] is True
            assert _REASONING not in canonical(report)
            assert client.is_closed is False

    asyncio.run(run())
