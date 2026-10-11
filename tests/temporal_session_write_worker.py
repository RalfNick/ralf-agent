"""Independent real Workers for persistent Session save crash windows."""

import asyncio
import json
import os
import signal
import sqlite3
from pathlib import Path

import ralf_agent as r
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime


def audit(root, kind, value):
    with sqlite3.connect(root / "audit.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS audit (kind TEXT,value TEXT)")
        db.execute("INSERT INTO audit VALUES (?,?)", (kind, json.dumps(value)))


def freeze(root, marker, value):
    (root / marker).write_text(json.dumps(value))
    os.kill(os.getpid(), signal.SIGSTOP)


class AuditedSession(r.SQLiteMemory):
    def __init__(self, root):
        super().__init__(root / "data.sqlite")
        self.root = root

    def append(self, scope, address, message, *, expected_revision, message_id):
        result = super().append(
            scope, address, message, expected_revision=expected_revision, message_id=message_id
        )
        audit(self.root, "append", {"address": address, "message_id": message_id})
        if os.getenv("RALF_SESSION_WRITE_WINDOW") == "committed":
            freeze(self.root, "window-ready", {"address": address, "message_id": message_id})
        return result


class Provider:
    identity = {"kind": "temporal-session-write-worker", "version": "1"}

    def __init__(self, root):
        self.root = root

    async def complete(self, messages, tools):
        records = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str) and content.startswith("Reference memory;"):
                for reference in json.loads(content.partition("\n")[2]):
                    records.extend(reference.get("session", []))
        audit(self.root, "model", {"records": records})
        return r.ModelResponse(output={"seen": len(records)})


def runtime(root, queue, kind, managed):
    root = Path(root)
    backend = AuditedSession(root)
    scope = r.Scope("session-writes", queue)
    resource = r.SessionBindingResource(backend, namespaces=("chat",), default_namespace="chat")
    catalog = r.BindingCatalog(scope=scope)
    catalog.register("session", "data", "1", resource)
    binding = r.AgentBindingDescriptor(session=r.BindingSelection.ref("data", "1"))
    agent = r.AgentSpec("a", "Answer")
    definition = (
        r.AgentDefinition(agent, binding)
        if kind == "native"
        else r.BoundDefinition(
            r.WorkflowSpec("sequence", [agent, agent]),
            {"sequence/steps/0": binding, "sequence/steps/1": binding},
        )
    )
    execution = TemporalRuntime(
        providers={"default": Provider(root)},
        tools=r.ToolRegistry(),
        binding_catalog=catalog,
        context_builder=r.ManagedContextPipeline() if managed else None,
        enable_sessions=True,
        session_writes=True,
    )
    return execution, definition, backend.store, scope


async def run():
    from temporalio import workflow
    from temporalio.client import Client
    from temporalio.worker import (
        Interceptor,
        WorkflowInboundInterceptor,
        WorkflowOutboundInterceptor,
    )

    root = Path(os.environ["RALF_SESSION_WRITE_ROOT"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, store, _ = runtime(
        root,
        queue,
        os.environ["RALF_SESSION_WRITE_KIND"],
        os.environ["RALF_SESSION_WRITE_MANAGED"] == "1",
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])

    class BeforeSave(WorkflowOutboundInterceptor):
        def start_activity(self, input):
            window = os.environ["RALF_SESSION_WRITE_WINDOW"]
            phase = input.args[0].get("phase") if input.args else None
            if input.activity == "ralf.temporal.session-save.v1" and (
                window == "prepared"
                and phase == "session-write"
                or window == "received"
                and phase == "adopt"
            ):
                with workflow.unsafe.sandbox_unrestricted():
                    freeze(root, "window-ready", input.args[0])
            return self.next.start_activity(input)

    class Inbound(WorkflowInboundInterceptor):
        def init(self, outbound):
            self.next.init(BeforeSave(outbound))

    class FaultWindow(Interceptor):
        def workflow_interceptor_class(self, input):
            return Inbound

    try:
        async with build_temporal_worker(
            client, task_queue=queue, runtime=execution, interceptors=[FaultWindow()]
        ):
            print("SESSION_WRITE_WORKER_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        store.close()
