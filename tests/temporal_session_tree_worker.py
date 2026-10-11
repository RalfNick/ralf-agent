"""Independent Workers for actual original Parent/member Session crash windows."""

import asyncio
import json
import os
import signal
import sqlite3
from pathlib import Path

from ralf_agent import (
    ManagedContextPipeline,
    ModelResponse,
    Scope,
    SessionBindingResource,
    SQLiteMemory,
    ToolRegistry,
)
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_topology import CompositeSessionTopology


def audit(root, kind, value):
    with sqlite3.connect(root / "audit.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS audit (kind TEXT,value TEXT)")
        db.execute("INSERT INTO audit VALUES (?,?)", (kind, json.dumps(value)))


def freeze(root, value):
    (root / "window-ready").write_text(json.dumps(value))
    os.kill(os.getpid(), signal.SIGSTOP)


class AuditedSession(SQLiteMemory):
    def __init__(self, root):
        super().__init__(root / "data.sqlite")
        self.root = root

    def read_page(self, scope, address, query):
        page = super().read_page(scope, address, query)
        audit(self.root, "read", {"address": address})
        return page

    def append(self, scope, address, message, *, expected_revision, message_id):
        result = super().append(
            scope, address, message, expected_revision=expected_revision, message_id=message_id
        )
        value = {"address": address, "message_id": message_id}
        audit(self.root, "append", value)
        window = os.getenv("RALF_TREE_WINDOW")
        if (
            window == "root-committed"
            and "ralf-temporal-member-v1:" not in address
            or window == "member-committed"
            and "ralf-temporal-member-v1:" in address
        ):
            freeze(self.root, value)
        return result


class Provider:
    identity = {"kind": "tree-crash-worker", "version": "1"}

    def __init__(self, root):
        self.root = root

    async def complete(self, messages, tools):
        audit(self.root, "model", {"messages": messages})
        return ModelResponse(output="answer")


def runtime(root, queue, managed):
    backend = AuditedSession(Path(root))
    execution = TemporalRuntime(
        providers={"default": Provider(Path(root))},
        tools=ToolRegistry(),
        enable_sessions=True,
        session_writes=True,
        session_topology=CompositeSessionTopology(),
        session_store=SessionBindingResource(
            backend, namespaces=("chat",), default_namespace="chat"
        ),
        context_builder=ManagedContextPipeline() if managed else None,
    )
    return execution, backend, Scope("tree-crash", queue)


async def run():
    from temporalio import workflow
    from temporalio.client import Client
    from temporalio.worker import (
        Interceptor,
        WorkflowInboundInterceptor,
        WorkflowOutboundInterceptor,
    )

    root = Path(os.environ["RALF_TREE_ROOT"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, backend, _ = runtime(root, queue, os.environ["RALF_TREE_MANAGED"] == "1")
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])

    class Window(WorkflowOutboundInterceptor):
        def start_child_workflow(self, value):
            if (
                os.getenv("RALF_TREE_WINDOW") == "root-read-adopted"
                and "session_root_snapshot" in value.args[0]["request"]
            ):
                with workflow.unsafe.sandbox_unrestricted():
                    freeze(root, value.args[0])
            return self.next.start_child_workflow(value)

        def start_activity(self, value):
            request = value.args[0] if value.args else {}
            window, phase = os.environ["RALF_TREE_WINDOW"], request.get("phase")
            if (
                value.activity == "ralf.temporal.session-save.v1"
                and request.get("session_source") == "root"
                and (
                    window == "root-prepared"
                    and phase == "session-write"
                    or window == "root-received"
                    and phase == "adopt"
                )
            ):
                with workflow.unsafe.sandbox_unrestricted():
                    freeze(root, request)
            return self.next.start_activity(value)

    class Inbound(WorkflowInboundInterceptor):
        def init(self, outbound):
            self.next.init(Window(outbound))

    class Fault(Interceptor):
        def workflow_interceptor_class(self, input):
            return Inbound

    try:
        async with build_temporal_worker(
            client, task_queue=queue, runtime=execution, interceptors=[Fault()]
        ):
            print("TREE_WORKER_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        await execution.close_session_execution()
        backend.store.close()


if __name__ == "__main__":
    asyncio.run(run())
