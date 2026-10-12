"""Real Responses HTTP codec in evaluators; scripted replies prove protocol only."""

import asyncio
import copy
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
from ralf_agent.storage import SQLiteStore
from ralf_agent.types import canonical
from tests.test_responses_reasoning_runtime import provider, text_item, wire_response

_PRIVATE = "opaque-encrypted-evaluation-evidence"


def standard_request(body):
    """Policy fixture consumes public SDK text/functions, not its scoring oracle."""
    messages = []
    for item in body["input"]:
        kind = item.get("type")
        if kind == "reasoning":
            continue
        if kind == "message":
            if item.get("phase") != "commentary":
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(part["text"] for part in item["content"]),
                    }
                )
        elif kind == "function_call":
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": item["call_id"],
                            "type": "function",
                            "function": {"name": item["name"], "arguments": item["arguments"]},
                        }
                    ],
                }
            )
        elif kind == "function_call_output":
            messages.append(
                {"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]}
            )
        else:
            messages.append(copy.deepcopy(item))
    tools = [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item.get("description", ""),
                "parameters": item["parameters"],
            },
        }
        for item in body.get("tools", [])
    ]
    return messages, tools


def evaluation_wire(fixture, observed, supplied):
    async def reply(request):
        body = json.loads(request.content)
        observed.append(copy.deepcopy(body))
        assert body["store"] is False and body["include"] == ["reasoning.encrypted_content"]
        assert body["reasoning"] == {"effort": "high", "context": "all_turns"}
        assert "model_continuation" not in canonical(body)
        prior = [item for response in supplied for item in response]
        for item in body["input"]:
            if item.get("type") in {"reasoning", "message", "function_call"}:
                assert item in prior
        messages, tools = standard_request(body)
        result = await fixture.complete(messages, tools)
        sequence = str(len(observed))
        output = [
            {
                "id": "reasoning-" + sequence,
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "private evaluation summary"}],
                "encrypted_content": _PRIVATE + "-" + sequence,
            },
            text_item(
                "commentary-" + sequence, "private commentary is not the answer", "commentary"
            ),
        ]
        if result.output is not None:
            output.append(
                text_item(
                    "answer-" + sequence,
                    result.output if isinstance(result.output, str) else canonical(result.output),
                )
            )
        for index, call in enumerate(result.tool_calls):
            output.append(
                {
                    "id": f"function-{sequence}-{index}",
                    "type": "function_call",
                    "status": "completed",
                    "call_id": call.call_id or f"wire-{sequence}-{index}",
                    "name": call.name,
                    "arguments": " \n " + canonical(call.arguments) + " \t ",
                }
            )
        supplied.append(copy.deepcopy(output))
        return wire_response(output, stream=body.get("stream", False))

    return httpx.MockTransport(reply)


def test_responses_reasoning_passes_compatibility_protocol_cases_without_quality_claim(tmp_path):
    async def run():
        observed, supplied = [], []
        async with httpx.AsyncClient(
            transport=evaluation_wire(OfflineCompatibilityProvider(), observed, supplied)
        ) as client:
            report = await evaluate_model_compatibility(
                provider("fixture", client),
                offline=True,
                model_continuation=True,
                evidence_dir=tmp_path,
            )
            assert report["passed"] == report["total"] == 5, report
            assert report["calls"] == len(observed) == 6
            assert report["model_quality"] is None and report["offline"] is True
            assert _PRIVATE not in canonical(report) and "private commentary" not in canonical(
                report
            )
            assert client.is_closed is False
            tool = next(row for row in report["cases"] if row["case_id"] == "tool")
            with SQLiteStore(tmp_path / "tool-0.sqlite", readonly=True) as store:
                record = store.run(tool["run_id"])
            models = [a for a in record["actions"] if a["kind"] == "model"]
            assert models[0]["received_response"]["continuation"]["data"]["output"] == supplied[2]
            assert models[0]["received_response"]["tool_calls"][0]["arguments"] == {
                "value": "RALF_TOOL_CHECK"
            }
            assert (
                models[0]["received_response"]["continuation"]["data"]["output"][-1]["arguments"]
                == ' \n {"value":"RALF_TOOL_CHECK"} \t '
            )
        assert client.is_closed is True

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["rag", "plan-and-execute", "team"])
def test_responses_reasoning_recommended_tasks_preserve_native_groups_and_observation_only_recovery(
    tmp_path, kind
):
    async def run():
        observed, supplied = [], []
        fixture = OfflineRAGProvider() if kind == "rag" else OfflineOrchestrationProvider()
        async with httpx.AsyncClient(
            transport=evaluation_wire(fixture, observed, supplied)
        ) as client:
            selected = provider("fixture", client, max_output_tokens=2048)
            options = {"evidence_dir": tmp_path, "offline": True, "model_continuation": True}
            if kind == "rag":
                report = await evaluate_rag(selected, cases=load_rag_cases()[:1], **options)
                assert report["cases"][0]["recovery"]["additional_model_calls"] == 0
                with SQLiteStore(
                    tmp_path / (report["cases"][0]["case_id"] + "-0.sqlite"), readonly=True
                ) as store:
                    record = store.run(report["cases"][0]["run_id"])
                model = next(a for a in record["actions"] if a["kind"] == "model")
                assert model["received_response"]["continuation"]["data"] == {"output": supplied[0]}
            else:
                report = await evaluate_orchestration(
                    selected, kind=kind, cases=load_orchestration_cases()[:1], **options
                )
                assert report["cases"][0]["recovery"]["additional_calls"] == 0
                assert (
                    sum(
                        any(item.get("type") == "function_call_output" for item in body["input"])
                        for body in observed
                    )
                    == 2
                )
            assert report["passed"] == report["total"] == 1, report
            assert report["model_quality"] is None and report["offline"] is True
            assert _PRIVATE not in canonical(report) and "private commentary" not in canonical(
                report
            )
            assert client.is_closed is False

    asyncio.run(run())
