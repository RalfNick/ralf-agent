"""Actual Worker fixture with offline models and a shared durable fact target."""

import asyncio
import os
import sqlite3
from pathlib import Path

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    ManagedContextPipeline,
    ManagedMemoryPolicy,
    ManagedModelMemoryPolicy,
    MemoryAdmissionPolicy,
    ModelResponse,
    Scope,
    SQLiteMemory,
    TeamSpec,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime


def runtime(root, queue):
    root = Path(root)
    scope = Scope("temporal-memory", queue)
    with sqlite3.connect(root / "audit.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS calls (kind TEXT, label TEXT)")

    def audit(kind, label):
        with sqlite3.connect(root / "audit.sqlite") as db:
            db.execute("INSERT INTO calls VALUES (?, ?)", (kind, label))

    class Provider:
        def __init__(self, label):
            self.label = label
            self.identity = {"kind": "offline-memory-worker", "version": "1", "label": label}

        async def complete(self, messages, tools):
            selection = messages[0]["content"].startswith("memory-field-selector:")
            audit("selector" if selection else "business", self.label)
            return ModelResponse(
                output={"keys": ["name"]} if selection else {"name": messages[0]["content"]}
            )

    class Memory(SQLiteMemory):
        async def inspect_fact(self, *args):
            if (
                os.getenv("RALF_MEMORY_MODE") == "cancel-read"
                and not (root / "read-ready").exists()
            ):
                (root / "read-ready").touch()
                for _ in range(600):
                    if (root / "read-release").exists():
                        break
                    await asyncio.sleep(0.05)
            return super().inspect_fact(*args)

        async def put_fact(self, *args, **kwargs):
            if os.getenv("RALF_MEMORY_MODE") == "no-fact":
                audit("dispatch", args[1])
                from ralf_agent.errors import MemoryBackendError

                raise MemoryBackendError("not visible yet")
            result = super().put_fact(*args, **kwargs)
            audit("cas", args[1])
            if os.getenv("RALF_MEMORY_MODE") == "cas-active":
                (root / "cas-ready").touch()
                await asyncio.Event().wait()
            from ralf_agent.errors import MemoryBackendError

            if os.getenv("RALF_MEMORY_WINDOW") == "cas":
                raise MemoryBackendError("lost CAS acknowledgement")
            return result

    memory = Memory(root / "facts.sqlite")
    admission = MemoryAdmissionPolicy({"name": ("result", "name")})
    rule = ManagedMemoryPolicy(memory, admission=admission, namespace="one", scope=scope)
    model = ManagedModelMemoryPolicy(
        memory, admission=admission, namespace="two", scope=scope, provider="selector"
    )
    catalog = BindingCatalog(scope=scope)
    catalog.register("provider", "first", "1", Provider("first"))
    catalog.register("provider", "second", "1", Provider("second"))
    catalog.register("context", "compressed", "1", ManagedContextPipeline())
    catalog.register("stage_policy", "first", "1", rule)
    catalog.register("stage_policy", "second", "1", model)

    class Runtime(TemporalRuntime):
        async def manage_memory(self, request, *, dispatch_guard=None):
            phase = "adopt" if os.getenv("RALF_MEMORY_WINDOW") == "selector" else "verify"
            if (
                os.getenv("RALF_MEMORY_MODE") == "crash"
                and request["phase"] == phase
                and not (root / "pause-ready").exists()
            ):
                (root / "pause-ready").touch()
                await asyncio.Event().wait()
            return await super().manage_memory(request, dispatch_guard=dispatch_guard)

    execution = Runtime(
        providers={"default": Provider("default"), "selector": Provider("selector")},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        stage_policy=model,
    )
    return execution, memory


def definition(kind):
    a, b = AgentSpec("same", "first-result"), AgentSpec("same", "second-result")
    first = AgentBindingDescriptor(
        provider=BindingSelection.ref("first", "1"), stage_policy=BindingSelection.ref("first", "1")
    )
    second = AgentBindingDescriptor(
        provider=BindingSelection.ref("second", "1"),
        stage_policy=BindingSelection.ref("second", "1"),
        context=BindingSelection.ref("compressed", "1"),
    )
    if kind == "native":
        return AgentDefinition(b, second)
    if kind == "sequence":
        return BoundDefinition(
            WorkflowSpec("w", [a, b]), {"sequence/steps/0": first, "sequence/steps/1": second}
        )
    if kind == "parallel":
        spec = GraphWorkflowSpec(
            "g", [GraphNode("a", agent=a), GraphNode("b", agent=b)], max_concurrency=2
        )
        return BoundDefinition(spec, {"graph/nodes/a": first, "graph/nodes/b": second})
    if kind == "dynamic-dag":
        spec = DynamicWorkflowSpec("d", {"a": a, "b": b}, plan_mode="dag", child_budget=12)
        return BoundDefinition(spec, {"dynamic/members/a": first, "dynamic/members/b": second})
    spec = TeamSpec(
        "t", {"a": WorkflowSpec("w", [a]) if kind == "nested" else a, "b": b}, child_budget=12
    )
    return BoundDefinition(
        spec,
        {
            "team/members/a/sequence/steps/0" if kind == "nested" else "team/members/a": first,
            "team/members/b": second,
        },
    )


async def run():
    from temporalio.client import Client

    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, memory = runtime(Path(os.environ["RALF_MEMORY_ROOT"]), queue)
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(
            client, task_queue=queue, runtime=execution, release=execution.orchestration_release
        ):
            print("TEMPORAL_MEMORY_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        memory.close()
