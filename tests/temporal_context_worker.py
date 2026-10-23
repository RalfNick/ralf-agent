"""Actual-service worker for registered context, approvals and managed summaries."""

import asyncio
import os

from relf_agent import (
    BudgetedContextAssembler,
    ModelResponse,
    ToolCall,
    ToolRegistry,
    ToolSpec,
    UTF8TokenEstimator,
)
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime


class Provider:
    identity = {"kind": "temporal-custom-context-probe", "version": "1"}

    async def complete(self, messages, tools):
        if "context-summary:" in messages[0]["content"]:
            return ModelResponse(output={"text": "zh-CN. INC-POOL remains unresolved."})
        if not any(m.get("role") == "tool" for m in messages):
            return ModelResponse(tool_calls=(ToolCall("observe", {}, "observe-1"),))
        return ModelResponse(output={"language": "zh-CN", "observed": True})


def runtime():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            "observe",
            "Observe fixture preference",
            {"type": "object", "additionalProperties": False},
            requires_approval=True,
        ),
        lambda arguments, context: {"language": "zh-CN"},
    )
    return TemporalRuntime(
        providers={"default": Provider()},
        tools=registry,
        context_builder=BudgetedContextAssembler(counter=UTF8TokenEstimator(), max_units=2048),
    )


async def run():
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    worker = build_temporal_worker(
        client, task_queue=os.environ["RALF_TEST_TEMPORAL_QUEUE"], runtime=runtime()
    )
    async with worker:
        print("TEMPORAL_CONTEXT_READY", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run())
