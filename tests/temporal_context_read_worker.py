"""Separate Worker fault windows for lost read-end delivery and adopted snapshots."""

import asyncio
import json
import os
import signal
from pathlib import Path

from ralf_agent import ContextExecutionOwner, ManagedContextPipeline, Scope, ToolRegistry
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_topology import CompositeSessionTopology

from .temporal_session_tree_worker import AuditedSession, Provider


class ReadOwner(ContextExecutionOwner):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root)

    @property
    def identity(self):
        return {**super().identity, "kind": "test-crash-read-owner"}

    async def execute(self, operation, *, proof, on_end=None):
        async def ended(value):
            if os.getenv("RALF_READ_WINDOW") == "held-end":
                (self.root / "window-ready").write_text(json.dumps(value))
                await asyncio.Event().wait()  # Lost delivery; actual reader already ended.
            if on_end is not None:
                await on_end(value)

        return await super().execute(operation, proof=proof, on_end=ended)


def runtime(root, queue, managed):
    root = Path(root)
    backend = AuditedSession(root)
    execution = TemporalRuntime(
        providers={"default": Provider(root)},
        tools=ToolRegistry(),
        session_store=backend,
        enable_sessions=True,
        session_writes=True,
        session_topology=CompositeSessionTopology(),
        context_builder=ManagedContextPipeline() if managed else None,
        context_reads=True,
        context_execution=ReadOwner(root),
    )
    return execution, backend, Scope("read-crash", queue)


async def run():
    from temporalio import workflow
    from temporalio.client import Client
    from temporalio.worker import (
        Interceptor,
        WorkflowInboundInterceptor,
        WorkflowOutboundInterceptor,
    )

    root = Path(os.environ["RALF_READ_ROOT"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, backend, _ = runtime(root, queue, os.environ["RALF_READ_MANAGED"] == "1")
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])

    class Window(WorkflowOutboundInterceptor):
        def start_activity(self, value):
            if (
                os.getenv("RALF_READ_WINDOW") == "model-prepared"
                and value.activity == "ralf.temporal.model.v1"
            ):
                with workflow.unsafe.sandbox_unrestricted():
                    (root / "window-ready").write_text(json.dumps(value.args[0]))
                    os.kill(os.getpid(), signal.SIGSTOP)
            return self.next.start_activity(value)

    class Inbound(WorkflowInboundInterceptor):
        def init(self, outbound):
            self.next.init(Window(outbound))

    class Fault(Interceptor):
        def workflow_interceptor_class(self, input):
            return Inbound

    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    try:
        async with build_temporal_worker(
            client, task_queue=queue, runtime=execution, interceptors=[Fault()]
        ):
            try:
                print("READ_WORKER_READY", flush=True)
                await stop.wait()
            finally:
                await execution.close_context_execution(wait_timeout=3)
                await execution.close_session_execution(wait_timeout=3)
        await execution.context_execution.aclose()
    finally:
        backend.store.close()


if __name__ == "__main__":
    asyncio.run(run())
