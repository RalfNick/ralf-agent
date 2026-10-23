"""Worker restart probe for selected context caches and immutable artifact evidence."""

import asyncio
import os
import sqlite3
from pathlib import Path

from relf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    ContextAssembler,
    ManagedContextPipeline,
    ModelResponse,
    Scope,
    SQLiteArtifactStore,
    ToolRegistry,
    WorkflowSpec,
)
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime
from tests.test_composite_data_context import Provider, agent, registry
from tests.test_managed_data_context import context
from tests.test_temporal_binding_isolation import LabelContext


def runtime(root, queue, kind):
    root = Path(root)
    scope = Scope("binding-isolation", queue)
    catalog = BindingCatalog(scope=scope)
    with sqlite3.connect(root / "calls.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS calls (label TEXT)")

    class RecordedProvider(Provider):
        async def complete(self, messages, tools):
            label = messages[-1]["content"] if kind == "plain-cache" else "business"
            with sqlite3.connect(root / "calls.sqlite") as db:
                db.execute("INSERT INTO calls VALUES (?)", (label,))
            if kind.endswith("cache"):
                return ModelResponse(output="task")
            return await super().complete(messages, tools)

    stores = []
    if kind.endswith("cache"):
        for label, limit in (("A", 256), ("B", 512)):
            builder = (
                ManagedContextPipeline(summary_max_chars=limit)
                if kind == "managed-cache"
                else LabelContext(label)
            )
            catalog.register("context", label, "1", builder)
        original, tools = None, ToolRegistry()
        member = AgentSpec("same", "answer")
        bindings = {
            f"sequence/steps/{i}": AgentBindingDescriptor(context=BindingSelection.ref(label, "1"))
            for i, label in enumerate(("A", "B"))
        }
    else:
        stores.append(SQLiteArtifactStore(root / "original.sqlite"))
        original = context(stores[0], scope=scope)
        next_builder = ContextAssembler()
        if kind == "artifact-managed":
            stores.append(SQLiteArtifactStore(root / "next.sqlite"))
            next_builder = context(stores[1], scope=scope)
        catalog.register("context", "next", "1", next_builder)
        tools, member = registry([]), agent()
        bindings = {
            "sequence/steps/1": AgentBindingDescriptor(context=BindingSelection.ref("next", "1"))
        }

    class GatedRuntime(TemporalRuntime):
        async def gate(self, request):
            selected = request.get("step_bindings", {}).get("context", {}).get("component_id")
            if os.environ.get("RALF_BINDING_MODE") == "crash" and selected in {"B", "next"}:
                (root / "next-context-ready").write_text("ready")
                await asyncio.Event().wait()

        async def prepare_context(self, request):
            await self.gate(request)
            return await super().prepare_context(request)

        async def manage_context(self, request, *, dispatch_guard=None):
            await self.gate(request)
            return await super().manage_context(request, dispatch_guard=dispatch_guard)

    execution = GatedRuntime(
        providers={"default": RecordedProvider()},
        tools=tools,
        binding_catalog=catalog,
        context_builder=original,
    )
    second = member
    if kind == "artifact-plain":
        second = AgentSpec("same", "Answer", tools=["lookup"], max_context_chars=32768)
    return execution, BoundDefinition(WorkflowSpec("sequence", [member, second]), bindings), stores


async def run():
    from temporalio.client import Client

    root = Path(os.environ["RALF_BINDING_ROOT"])
    queue, kind = os.environ["RALF_TEST_TEMPORAL_QUEUE"], os.environ["RALF_BINDING_KIND"]
    execution, _, stores = runtime(root, queue, kind)
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            print("TEMPORAL_BINDING_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        for store in stores:
            store.close()
