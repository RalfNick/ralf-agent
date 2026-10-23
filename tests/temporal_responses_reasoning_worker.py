"""Native Responses HTTP fixture behind real Workers; no public model traffic."""

import asyncio
import copy
import json
import os
import signal
from pathlib import Path

import httpx

from relf_agent import (
    AgentSpec,
    CompleteModelHistory,
    GraphNode,
    GraphWorkflowSpec,
    SQLiteMemory,
    ToolRegistry,
)
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime
from tests.test_responses_reasoning_runtime import audit_row, native_output, provider, wire_response

MODEL = "temporal-fixture"
NATIVE_OUTPUT = native_output(MODEL)


def final_output(task="task"):
    output = native_output(MODEL, "final", task)
    output[-1]["content"][0]["text"] = ' { "amount" : 6 } '
    return output


FINAL_OUTPUT = final_output()


def runtime(root, kind="native", *, session=False):
    root = Path(root)

    def audit(row):
        audit_row(root / "responses-audit.jsonl", row)

    def reply(request):
        body = json.loads(request.content)
        assert body["model"] == MODEL
        assert body["store"] is False and body["include"] == ["reasoning.encrypted_content"]
        assert body["reasoning"] == {"effort": "high", "context": "all_turns"}
        assert not ({"previous_response_id", "conversation", "background"} & body.keys())
        current = next(
            item["content"]
            for item in reversed(body["input"])
            if item.get("role") == "user" and not item["content"].startswith("Reference memory;")
        )
        task = "turn-two" if current == "turn-two" else "task"
        originals = [
            item
            for item in body["input"]
            if item.get("type") in {"reasoning", "message", "function_call"}
        ]
        past = NATIVE_OUTPUT + FINAL_OUTPUT if task == "turn-two" else []
        assert originals[: len(past)] == past
        active = originals[len(past) :]
        results = [item for item in body["input"] if item.get("type") == "function_call_output"]
        assert results[: int(task == "turn-two")] == (
            [
                {
                    "type": "function_call_output",
                    "call_id": "native-call-temporal-fixture-task-tool-1",
                    "output": '{"amount":6}',
                }
            ]
            if task == "turn-two"
            else []
        )
        if active:
            assert active == native_output(MODEL, task=task)
            assert results[-1] == {
                "type": "function_call_output",
                "call_id": "native-call-" + MODEL + "-" + task + "-tool-1",
                "output": '{"amount":6}',
            }
            output, phase = final_output(task), "final"
        else:
            declaration = body["tools"][0]
            assert declaration["name"] == "calculate"
            assert declaration["parameters"]["required"] == ["quantity"]
            assert declaration["parameters"]["properties"]["price"]["type"] == "integer"
            output, phase = native_output(MODEL, task=task), "initial"
        audit({"kind": "model", "phase": phase, "task": task, "body": copy.deepcopy(body)})
        return wire_response(output, stream=body.get("stream", False))

    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    selected, tools = provider(MODEL, client), ToolRegistry()

    def calculate(quantity: int, price: int = 2):
        audit({"kind": "tool", "quantity": quantity, "price": price})
        return {"amount": quantity * price}

    tools.register_function(calculate, effect="read_only", requires_approval=not session, cost=0)
    agent = AgentSpec(
        "account",
        "Calculate three units",
        ("calculate",),
        max_decisions=4,
        max_context_chars=24000,
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
            window = os.environ.get("RALF_RESPONSES_WORKER_WINDOW")
            received = request["model_receipt"]["received_response"]
            if os.environ.get("RALF_RESPONSES_WORKER_MODE") == "original" and (
                window == "receipt" or window == "final-session" and received["output"] is not None
            ):
                (root / "receipt-ready").write_text(request["original_request"]["run_id"])
                await asyncio.Event().wait()
            return await super().adopt_model(request)

    backend = SQLiteMemory(root / "session.sqlite") if session else None
    execution = GatedRuntime(
        providers={"default": selected},
        tools=tools,
        model_continuation=True,
        model_history=CompleteModelHistory(scope="session" if session else "run"),
        **(
            {"enable_sessions": True, "session_store": backend, "session_writes": True}
            if session
            else {}
        ),
    )
    return execution, definition, client, backend


async def run():
    from temporalio.client import Client

    root = Path(os.environ["RALF_RESPONSES_WORKER_ROOT"])
    window = os.environ["RALF_RESPONSES_WORKER_WINDOW"]
    execution, _, provider_client, backend = runtime(
        root, os.environ["RALF_RESPONSES_WORKER_KIND"], session=window == "final-session"
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    try:
        async with build_temporal_worker(
            client, task_queue=os.environ["RALF_TEST_TEMPORAL_QUEUE"], runtime=execution
        ):
            print("TEMPORAL_RESPONSES_REASONING_READY", flush=True)
            await stopped.wait()
    finally:
        await execution.close_context_execution(wait_timeout=5)
        await execution.close_session_execution(wait_timeout=5)
        await provider_client.aclose()
        if backend is not None:
            backend.store.close()
        (root / ("worker-closed-" + os.environ["RALF_RESPONSES_WORKER_MODE"])).write_text("closed")
