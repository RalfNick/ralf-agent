"""Complete signed final fixture; actual Worker/History without paid model I/O."""

import asyncio
import json
import os
import signal
from pathlib import Path

import httpx

from ralf_agent import AgentSpec, CompletionVerdict, GraphNode, GraphWorkflowSpec
from ralf_agent.context import ContextAssembler
from ralf_agent.gemini_functions import GeminiFunctionProvider
from ralf_agent.managed_context import ManagedContextPipeline
from ralf_agent.model_history import CompleteModelHistory
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.tools import ToolRegistry
from ralf_agent.types import digest

FIRST_TEXT = ' { "answer" : 42 } '
SECOND_TEXT = ' { "answer" : 43 } '
FEEDBACK = "Completion verification: Refine the answer to 43"
FIRST_PARTS = [
    {"text": "private first fixture reasoning", "thought": True, "thoughtSignature": "Zmlyc3Q="},
    {"text": FIRST_TEXT, "thoughtSignature": "ZmluYWwtZmlyc3Q="},
]
SECOND_PARTS = [
    {"text": "private second fixture reasoning", "thought": True, "thoughtSignature": "c2Vjb25k"},
    {"text": SECOND_TEXT, "thoughtSignature": "ZmluYWwtc2Vjb25k"},
]


class RefineVerifier:
    """Pure business rule; the original History decides whether to retry."""

    identity = {"kind": "model-history-refinement-fixture", "version": "1"}

    def verify(self, request):
        if request.output == {"answer": 42}:
            return CompletionVerdict("retry", "Refine the answer to 43")
        if request.output == {"answer": 43}:
            return CompletionVerdict("accept")
        return CompletionVerdict("reject", "Unexpected answer")


class EmptyKnowledge:
    """Exercise an actual original Context read with the unmodified native builder."""

    identity = {"kind": "model-history-empty-knowledge-fixture", "version": "1"}
    limit, max_chars = 1, 64

    async def references(self, scope, query):
        return []

    async def validate(self, scope, references):
        assert references == []


def runtime(root, kind="native", managed=False):
    root = Path(root)

    def audit(row):
        with (root / "history-audit.jsonl").open("a") as output:
            output.write(json.dumps(row) + "\n")

    def reply(request):
        body = json.loads(request.content)
        originals = [item for item in body["contents"] if item["role"] == "model"]
        if originals:
            assert originals == [{"role": "model", "parts": FIRST_PARTS}]
            assert body["contents"][-1] == {"role": "user", "parts": [{"text": FEEDBACK}]}
            parts, phase = SECOND_PARTS, "continued"
        else:
            assert body["contents"] == [{"role": "user", "parts": [{"text": "Question"}]}]
            parts, phase = FIRST_PARTS, "initial"
        assert "tools" not in body
        audit({"kind": "model", "phase": phase, "request_digest": digest(body), "body": body})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
            },
        )

    provider_client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    provider = GeminiFunctionProvider("fixture", api_key="dummy", client=provider_client)
    agent = AgentSpec(
        "answer",
        "Answer the question",
        max_decisions=4,
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "integer"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    )
    definition = (
        agent
        if kind == "native"
        else GraphWorkflowSpec("answer-graph", [GraphNode("answer", agent=agent)])
    )

    class GatedRuntime(TemporalRuntime):
        async def adopt_model(self, request):
            if (
                os.environ.get("RALF_HISTORY_MODE") == "original"
                and os.environ.get("RALF_HISTORY_WINDOW") == "receipt"
            ):
                (root / "window-ready").write_text(request["original_request"]["run_id"])
                await asyncio.Event().wait()
            return await super().adopt_model(request)

        async def _gate_context(self, request):
            if (
                os.environ.get("RALF_HISTORY_MODE") == "original"
                and os.environ.get("RALF_HISTORY_WINDOW") == "verified"
                and any(
                    message.get("content") == FEEDBACK for message in request.get("messages", [])
                )
            ):
                (root / "window-ready").write_text(request["run_id"])
                await asyncio.Event().wait()

        async def prepare_context(self, request, *, dispatch_guard=None, on_end=None):
            await self._gate_context(request)
            return await super().prepare_context(
                request, dispatch_guard=dispatch_guard, on_end=on_end
            )

        async def manage_context(self, request, *, dispatch_guard=None, on_end=None):
            if request.get("phase") == "plan":
                await self._gate_context(request)
            return await super().manage_context(
                request, dispatch_guard=dispatch_guard, on_end=on_end
            )

    execution = GatedRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        verifier=RefineVerifier(),
        model_continuation=True,
        model_history=CompleteModelHistory(),
        context_builder=ManagedContextPipeline() if managed else ContextAssembler(),
        knowledge=None if managed else EmptyKnowledge(),
        context_reads=True,
    )
    return execution, definition, provider_client


async def run():
    from temporalio.client import Client

    root = Path(os.environ["RALF_HISTORY_ROOT"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, provider_client = runtime(
        root,
        os.environ["RALF_HISTORY_KIND"],
        os.environ["RALF_HISTORY_MANAGED"] == "1",
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            print("TEMPORAL_MODEL_HISTORY_READY", flush=True)
            await stopped.wait()
    finally:
        await execution.close_context_execution(wait_timeout=5)
        await provider_client.aclose()
        (root / ("worker-closed-" + os.environ["RALF_HISTORY_MODE"])).write_text("closed")
