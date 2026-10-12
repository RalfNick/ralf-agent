"""Native HTTP fixture behind real Temporal Workers; no public model traffic."""

import asyncio
import json
import os
from pathlib import Path

import httpx

from ralf_agent import AgentSpec, CompleteModelHistory, GraphNode, GraphWorkflowSpec, ToolRegistry
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.types import digest

RAW_ARGUMENTS = ' \n { "quantity" : 3 } \t '
NATIVE_MESSAGE = {
    "role": "assistant",
    "content": "Checking three units",
    "reasoning_content": "原始审批前推理，保留原参数字节",
    "tool_calls": [
        {
            "id": "native-quantity",
            "type": "function",
            "function": {"name": "calculate", "arguments": RAW_ARGUMENTS},
        }
    ],
}
FINAL_MESSAGE = {
    "role": "assistant",
    "content": ' { "amount" : 6 } ',
    "reasoning_content": "最终原始推理，在完整History重放后仍保留",
}


def runtime(root, kind="native"):
    from ralf_agent.deepseek_thinking import DeepSeekThinkingProvider

    root = Path(root)

    def audit(row):
        with (root / "deepseek-audit.jsonl").open("a") as output:
            output.write(json.dumps(row) + "\n")

    def reply(request):
        body = json.loads(request.content)
        assert body["model"] == "deepseek-fixture"
        assert body["thinking"] == {"type": "enabled"}
        assert body["reasoning_effort"] == "high"
        originals = [message for message in body["messages"] if message["role"] == "assistant"]
        results = [message for message in body["messages"] if message["role"] == "tool"]
        if results:
            assert originals == [NATIVE_MESSAGE]
            assert results == [
                {"role": "tool", "tool_call_id": "native-quantity", "content": '{"amount":6}'}
            ]
            message, phase = FINAL_MESSAGE, "final"
        else:
            assert originals == []
            declaration = body["tools"][0]["function"]
            assert declaration["name"] == "calculate"
            assert declaration["parameters"]["required"] == ["quantity"]
            message, phase = NATIVE_MESSAGE, "initial"
        audit({"kind": "model", "phase": phase, "request_digest": digest(body)})
        return httpx.Response(
            200,
            json={
                "id": "deepseek-fixture-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-fixture",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    provider = DeepSeekThinkingProvider(
        "deepseek-fixture", api_key="fixture", client=client, reasoning_effort="high"
    )
    tools = ToolRegistry()

    def calculate(quantity: int, price: int = 2):
        audit({"kind": "tool", "quantity": quantity, "price": price})
        return {"amount": quantity * price}

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
                os.environ.get("RALF_DEEPSEEK_WORKER_MODE") == "original"
                and os.environ.get("RALF_DEEPSEEK_WORKER_WINDOW") == "receipt"
            ):
                (root / "receipt-ready").write_text(request["original_request"]["run_id"])
                await asyncio.Event().wait()
            return await super().adopt_model(request)

    execution = GatedRuntime(
        providers={"default": provider},
        tools=tools,
        model_continuation=True,
        model_history=CompleteModelHistory(),
    )
    return execution, definition, client


async def run():
    from temporalio.client import Client

    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, provider_client = runtime(
        os.environ["RALF_DEEPSEEK_WORKER_ROOT"], os.environ["RALF_DEEPSEEK_WORKER_KIND"]
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            print("TEMPORAL_DEEPSEEK_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        await execution.close_context_execution(wait_timeout=2)
        await provider_client.aclose()
