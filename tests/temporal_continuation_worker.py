"""Signed Gemini wire fixture; real Worker/History with no public model traffic."""

import asyncio
import json
import os
from pathlib import Path

import httpx

from ralf_agent import (
    AgentSpec,
    GraphNode,
    GraphWorkflowSpec,
    ManagedContextPipeline,
    ToolExecutionOwner,
    ToolRegistry,
)
from ralf_agent.gemini_functions import GeminiFunctionProvider
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.types import digest

PARTS = [
    {"text": "private fixture reasoning", "thought": True, "thoughtSignature": "dGhvdWdodA=="},
    {
        "functionCall": {"name": "calculate", "args": {"quantity": 3}, "id": "native-quantity"},
        "thoughtSignature": "c2lnbmF0dXJl",
    },
]


def runtime(root, kind="native", managed=False):
    root = Path(root)

    def audit(row):
        with (root / "continuation-audit.jsonl").open("a") as output:
            output.write(json.dumps(row) + "\n")

    def reply(request):
        body = json.loads(request.content)
        responses = [
            part["functionResponse"]
            for content in body["contents"]
            for part in content["parts"]
            if "functionResponse" in part
        ]
        if responses:
            originals = [content for content in body["contents"] if content["role"] == "model"]
            assert originals == [{"role": "model", "parts": PARTS}]
            assert responses == [
                {"name": "calculate", "id": "native-quantity", "response": {"result": 6}}
            ]
            parts = [{"text": '{"amount":6}'}]
            phase = "continued"
        else:
            declaration = body["tools"][0]["functionDeclarations"][0]
            assert declaration["name"] == "calculate"
            assert declaration["parametersJsonSchema"]["required"] == ["quantity"]
            parts, phase = PARTS, "initial"
        audit({"kind": "model", "phase": phase, "request_digest": digest(body)})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    provider = GeminiFunctionProvider("fixture", api_key="dummy", client=client)
    tools = ToolRegistry()

    def calculate(quantity: int, price: int = 2):
        audit({"kind": "tool", "quantity": quantity, "price": price})
        return quantity * price

    tools.register_function(calculate, effect="read_only", requires_approval=True, cost=0)
    agent = AgentSpec(
        "account",
        "Calculate three units",
        ("calculate",),
        max_decisions=4,
        output_schema={
            "type": "object",
            "properties": {"amount": {"const": 6}},
            "required": ["amount"],
            "additionalProperties": False,
        },
    )
    definition = (
        agent
        if kind == "native"
        else GraphWorkflowSpec("account-graph", [GraphNode("account", agent=agent)])
    )

    class GatedRuntime(TemporalRuntime):
        async def adopt_model(self, request):
            if (
                os.environ.get("RALF_CONTINUATION_MODE") == "original"
                and os.environ.get("RALF_CONTINUATION_WINDOW") == "receipt"
            ):
                (root / "receipt-ready").write_text(request["original_request"]["run_id"])
                await asyncio.Event().wait()
            return await super().adopt_model(request)

    execution = GatedRuntime(
        providers={"default": provider},
        tools=tools,
        model_continuation=True,
        context_builder=ManagedContextPipeline() if managed else None,
        context_reads=managed,
        tool_execution=ToolExecutionOwner(version="continuation-fixture-1") if managed else None,
    )
    return execution, definition, client


async def run():
    from temporalio.client import Client

    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, provider_client = runtime(
        os.environ["RALF_CONTINUATION_ROOT"],
        os.environ["RALF_CONTINUATION_KIND"],
        os.environ["RALF_CONTINUATION_MANAGED"] == "1",
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            print("TEMPORAL_CONTINUATION_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        await execution.close_context_execution(wait_timeout=2)
        await provider_client.aclose()
