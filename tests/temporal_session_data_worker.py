"""Actual SQLite Session reads and original History recovery in separate Workers."""

import asyncio
import json
import os
import sqlite3
from pathlib import Path

import ralf_agent as r
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_session_data import private_address
from ralf_agent.types import digest


class AuditedSession(r.SQLiteMemory):
    def read_page(self, scope, address, query):
        with sqlite3.connect(self.store.path) as db:
            db.execute("INSERT INTO audit VALUES (?,?)", ("read", address))
        return super().read_page(scope, address, query)


class Provider:
    identity = {"kind": "temporal-session-read-worker", "version": "1"}

    def __init__(self, root):
        self.root = root

    async def complete(self, messages, tools):
        seen = []
        for message in messages:
            if message.get("content", "").startswith("Reference memory;"):
                for reference in json.loads(message["content"].partition("\n")[2]):
                    seen.extend(item["content"] for item in reference.get("session", []))
        with sqlite3.connect(self.root / "data.sqlite") as db:
            db.execute("INSERT INTO audit VALUES (?,?)", ("model", json.dumps(seen)))
        return r.ModelResponse(output={"seen": seen})


def runtime(root, queue, kind, managed):
    root = Path(root)
    store = r.SQLiteStore(root / "data.sqlite")
    store.conn.execute("CREATE TABLE IF NOT EXISTS audit (kind TEXT,value TEXT)")
    scope = r.Scope("session-read", queue)
    backend = AuditedSession(store)
    resource = r.SessionBindingResource(backend, namespaces=("A", "B"), default_namespace="A")
    run_id = "ralf-temporal-" + digest(
        [{"workspace": scope.workspace, "principal": scope.principal}, "s"]
    )
    spec = r.AgentSpec("a", "Answer")
    paths = ["agent"] if kind == "native" else ["sequence/steps/0", "sequence/steps/1"]
    bindings = {}
    for index, path in enumerate(paths):
        namespace = "A" if index == 0 else "B"
        view = resource.select({"namespace": namespace}, scope)
        address = view.storage_key(private_address(run_id, index))
        if backend.inspect_message(scope, address, "seed")["receipt"] is None:
            backend.append(
                scope,
                address,
                {"role": "assistant", "task": "old", "content": namespace + " evidence"},
                expected_revision=0,
                message_id="seed",
            )
        bindings[path] = r.AgentBindingDescriptor(
            session=r.BindingSelection.ref("data", "1", selector={"namespace": namespace})
        )
    catalog = r.BindingCatalog(scope=scope)
    catalog.register("session", "data", "1", resource)
    definition = (
        r.AgentDefinition(spec, bindings["agent"])
        if kind == "native"
        else r.BoundDefinition(r.WorkflowSpec("sequence", [spec, spec]), bindings)
    )

    class Gated(TemporalRuntime):
        async def gate(self, request):
            if (
                kind == "sequence"
                and os.getenv("RALF_SESSION_READ_MODE") == "crash"
                and request.get("session_data_node") == 1
            ):
                (root / "read-ready").write_text(request["run_id"])
                await asyncio.Event().wait()

        async def prepare_context(self, request):
            await self.gate(request)
            return await super().prepare_context(request)

        async def manage_context(self, request, *, dispatch_guard=None):
            if request["phase"] == "plan":
                await self.gate(request)
            return await super().manage_context(request, dispatch_guard=dispatch_guard)

    execution = Gated(
        providers={"default": Provider(root)},
        tools=r.ToolRegistry(),
        binding_catalog=catalog,
        context_builder=r.ManagedContextPipeline() if managed else None,
    )
    return execution, definition, store, scope


async def run():
    import signal

    from temporalio import workflow
    from temporalio.client import Client
    from temporalio.worker import (
        Interceptor,
        WorkflowInboundInterceptor,
        WorkflowOutboundInterceptor,
    )

    root = Path(os.environ["RALF_SESSION_READ_ROOT"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, store, _ = runtime(
        root,
        queue,
        os.environ["RALF_SESSION_READ_KIND"],
        os.environ["RALF_SESSION_READ_MANAGED"] == "1",
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])

    class BeforeModel(WorkflowOutboundInterceptor):
        def start_activity(self, input):
            if (
                input.activity == "ralf.temporal.model.v1"
                and os.environ["RALF_SESSION_READ_KIND"] == "native"
                and os.environ["RALF_SESSION_READ_MODE"] == "crash"
            ):
                # Fault injection before the model command is scheduled, not an
                # unknown started Activity (which must never be retried implicitly).
                assert input.args[0]["context"]["session_data"]["revision"] == 1
                with workflow.unsafe.sandbox_unrestricted():
                    (root / "read-ready").write_text(input.args[0]["run_id"])
                    os.kill(os.getpid(), signal.SIGSTOP)
            return self.next.start_activity(input)

    class Inbound(WorkflowInboundInterceptor):
        def init(self, outbound):
            self.next.init(BeforeModel(outbound))

    class FaultWindow(Interceptor):
        def workflow_interceptor_class(self, input):
            return Inbound

    try:
        async with build_temporal_worker(
            client, task_queue=queue, runtime=execution, interceptors=[FaultWindow()]
        ):
            print("SESSION_READ_WORKER_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        store.close()
