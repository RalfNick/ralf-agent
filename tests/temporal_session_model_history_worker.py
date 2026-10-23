"""Process-owned native Session fixture; paid model I/O is never used."""

import asyncio
import json
import os
import signal
from pathlib import Path

from relf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, SQLiteMemory, ToolRegistry
from relf_agent.managed_context import ManagedContextPipeline
from relf_agent.model_history import CompleteModelHistory
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_session_topology import CompositeSessionTopology
from tests.test_temporal_session_model_history import SignedTools


def runtime(root, *, kind="native", managed=False):
    root = Path(root)

    def audit(row):
        with (root / "native-audit.jsonl").open("a") as output:
            output.write(json.dumps(row) + "\n")

    class Provider(SignedTools):
        async def complete(self, messages, tools):
            audit({"kind": "model", "messages": messages})
            return await super().complete(messages, tools)

    def one():
        audit({"kind": "tool", "name": "one"})
        return {"exact": "one"}

    def two():
        audit({"kind": "tool", "name": "two"})
        return {"exact": "two"}

    class Gated(TemporalRuntime):
        async def adopt_model(self, request):
            if (
                os.getenv("RALF_NATIVE_HISTORY_WORKER_MODE") == "original"
                and request["model_receipt"]["received_response"]["output"] is not None
            ):
                (root / "native-window-ready").write_text(request["original_request"]["run_id"])
                await asyncio.Event().wait()
            return await super().adopt_model(request)

    provider, tools = Provider(), ToolRegistry()
    tools.register_function(one, effect="read_only")
    tools.register_function(two, effect="read_only")
    backend = SQLiteMemory(root / "native.sqlite")
    execution = Gated(
        providers={"default": provider},
        tools=tools,
        enable_sessions=True,
        model_continuation=True,
        model_history=CompleteModelHistory(scope="session"),
        context_builder=ManagedContextPipeline() if managed else None,
        session_store=backend,
        session_writes=True,
        session_topology=CompositeSessionTopology() if kind == "graph" else None,
    )
    agent = AgentSpec("answer", "Answer", tools=("one", "two"))
    definition = (
        agent if kind == "native" else GraphWorkflowSpec("graph", [GraphNode("one", agent=agent)])
    )
    return execution, definition, backend


async def run():
    from temporalio.client import Client

    root = Path(os.environ["RALF_NATIVE_HISTORY_ROOT"])
    execution, _, backend = runtime(
        root,
        kind=os.environ["RALF_NATIVE_HISTORY_KIND"],
        managed=os.environ["RALF_NATIVE_HISTORY_MANAGED"] == "1",
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
            print("TEMPORAL_NATIVE_HISTORY_READY", flush=True)
            await stopped.wait()
    finally:
        await execution.close_context_execution(wait_timeout=5)
        await execution.close_session_execution(wait_timeout=5)
        backend.store.close()
        (
            root / ("native-worker-closed-" + os.environ["RALF_NATIVE_HISTORY_WORKER_MODE"])
        ).write_text("closed")
