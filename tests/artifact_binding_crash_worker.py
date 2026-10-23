"""Separate offline Worker with selected persistent Artifact fault windows."""

import asyncio
import json
import os
import signal
import sqlite3
from pathlib import Path

import relf_agent as r
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime

from .test_artifact_binding_execution import Reader


def audit(root, kind):
    with sqlite3.connect(root / "audit.sqlite") as database:
        database.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT)")
        database.execute("INSERT INTO calls VALUES (?)", (kind,))


def runtime(root, queue, backend_kind):
    root = Path(root)
    root_text = str(root)
    scope = r.Scope("artifact-worker-crash", queue)
    base = r.SQLiteArtifactStore if backend_kind == "sqlite" else r.FileArtifactStore

    class Durable(base):
        def put(self, *args, **kwargs):
            reference = super().put(*args, **kwargs)
            audit(Path(self.test_root), "put")
            if os.getenv("RALF_ARTIFACT_WINDOW") == "receipt":
                (Path(self.test_root) / "window-ready").write_text(
                    json.dumps({"reference": reference.to_dict()})
                )
                os.kill(os.getpid(), signal.SIGSTOP)
            return reference

    target = Durable(root / "selected-artifacts", backend_id="alpha")
    target.test_root = root_text
    original = r.InMemoryArtifactStore(backend_id="original")
    catalog = r.BindingCatalog(scope=scope)
    catalog.register(
        "artifacts",
        "alpha",
        "1",
        r.ArtifactBindingResource(
            target, version="1", namespaces=["alpha"], default_namespace="alpha"
        ),
    )
    tools = r.ToolRegistry()

    def lookup(arguments, context):
        audit(Path(root_text), "tool")
        return "EVIDENCE" * 1600

    tools.register(
        r.ToolSpec("lookup", "Read", {"type": "object"}, effect="read_only", cost=0),
        lookup,
    )

    class OfflineProvider(Reader):
        async def complete(self, messages, tools):
            audit(Path(root_text), "model")
            return await super().complete(messages, tools)

    execution = TemporalRuntime(
        providers={"default": OfflineProvider()},
        tools=tools,
        context_builder=r.ManagedDataContext(
            original, scope=scope, tool_result_chars=1024, preview_chars=64
        ),
        binding_catalog=catalog,
        context_reads=True,
    )
    return execution, target, original, scope


async def run():
    from temporalio.client import Client
    from temporalio.worker import ActivityInboundInterceptor, Interceptor

    root = Path(os.environ["RALF_ARTIFACT_ROOT"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, target, original, _ = runtime(root, queue, os.environ["RALF_ARTIFACT_BACKEND"])

    class Window(ActivityInboundInterceptor):
        async def execute_activity(self, value):
            request = value.args[0]
            if (
                os.environ["RALF_ARTIFACT_WINDOW"] == "intent"
                and request.get("phase") == "read"
                and request.get("artifact")
            ):
                (root / "window-ready").write_text(
                    json.dumps({"reference": request["artifact"]["reference"], "request": request})
                )
                os.kill(os.getpid(), signal.SIGSTOP)
            return await self.next.execute_activity(value)

    class Fault(Interceptor):
        def intercept_activity(self, next):
            return Window(next)

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    try:
        async with build_temporal_worker(
            client, task_queue=queue, runtime=execution, interceptors=[Fault()]
        ):
            try:
                print("ARTIFACT_WORKER_READY", flush=True)
                await stop.wait()
            finally:
                await execution.close_context_execution(wait_timeout=5)
    finally:
        target.close()
        original.close()


if __name__ == "__main__":
    asyncio.run(run())
