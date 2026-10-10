"""Real Worker crash probe: no production gate or alternate execution state."""

import asyncio
import json
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
    Document,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    KnowledgeBindingResource,
    KnowledgeContext,
    LexicalRetriever,
    ManagedContextPipeline,
    ModelResponse,
    Scope,
    SQLiteKnowledgeStore,
    SQLiteStore,
    TeamSpec,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime


class AuditedKnowledge(SQLiteKnowledgeStore):
    def lexical(self, scope, namespace, query):
        with sqlite3.connect(self.store.path) as db:
            db.execute("INSERT INTO audit VALUES ('retrieve', ?)", (namespace,))
        return super().lexical(scope, namespace, query)


class Provider:
    identity = {"kind": "temporal-knowledge-worker", "version": "1"}

    def __init__(self, root):
        self.root = root

    async def complete(self, messages, tools):
        values = []
        for message in messages:
            if message.get("content", "").startswith("Reference memory;"):
                values = [
                    r["value"]["text"] for r in json.loads(message["content"].partition("\n")[2])
                ]
        with sqlite3.connect(self.root / "knowledge.sqlite") as db:
            db.execute("INSERT INTO audit VALUES ('model', ?)", (json.dumps(values),))
        return ModelResponse(output="pool")


def runtime(root, queue, kind, managed):
    root = Path(root)
    store = SQLiteStore(root / "knowledge.sqlite")
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS audit (kind TEXT, value TEXT)")
    scope = Scope("temporal-knowledge", queue)
    knowledge = AuditedKnowledge(store)
    for owner, ns in (
        (scope, "A"),
        (scope, "B"),
        (scope, "private"),
        (Scope("temporal-knowledge", "foreign"), "B"),
    ):
        if knowledge.get(owner, ns, "guide") is None:
            knowledge.put(
                owner, ns, Document("guide", "pool " + ns + " evidence"), expected_version=0
            )
    catalog = BindingCatalog(scope=scope)
    catalog.register(
        "knowledge",
        "guides",
        "1",
        KnowledgeBindingResource(
            KnowledgeContext(LexicalRetriever(knowledge)),
            namespaces=("A", "B"),
            default_namespace="A",
        ),
    )
    agent = AgentSpec("same", "answer")
    if kind == "native":
        definition, paths = agent, ["agent"]
    elif kind == "sequence":
        definition, paths = (
            WorkflowSpec("sequence", [agent, agent]),
            ["sequence/steps/0", "sequence/steps/1"],
        )
    elif kind == "graph":
        definition = GraphWorkflowSpec(
            "graph", [GraphNode("a", agent=agent), GraphNode("b", agent=agent, depends_on=["a"])]
        )
        paths = ["graph/nodes/a", "graph/nodes/b"]
    elif kind == "dynamic":
        definition = DynamicWorkflowSpec(
            "dynamic", {"a": agent, "b": agent}, planner="dag-rule", plan_mode="dag", child_budget=4
        )
        paths = ["dynamic/members/a", "dynamic/members/b"]
    else:
        member = WorkflowSpec("nested", [agent]) if kind == "nested" else agent
        definition = TeamSpec("team", {"a": member, "b": agent}, child_budget=4)
        paths = [
            "team/members/a/sequence/steps/0" if kind == "nested" else "team/members/a",
            "team/members/b",
        ]
    bindings = {
        path: AgentBindingDescriptor(
            knowledge=BindingSelection.ref("guides", "1", selector={"namespace": ns})
        )
        for path, ns in zip(paths, ("A", "B"), strict=False)
    }
    definition = (
        AgentDefinition(agent, bindings["agent"])
        if kind == "native"
        else BoundDefinition(definition, bindings)
    )

    class GatedRuntime(TemporalRuntime):
        async def gate(self, request):
            selected = request.get("step_bindings", {}).get("knowledge", {})
            target = "A" if kind == "native" else "B"
            if (
                os.environ.get("RALF_KNOWLEDGE_MODE") == "crash"
                and selected.get("selector", {}).get("namespace") == target
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

    execution = GatedRuntime(
        providers={"default": Provider(root)},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        context_builder=ManagedContextPipeline() if managed else None,
    )
    return execution, definition, store


async def run():
    from temporalio.client import Client

    root = Path(os.environ["RALF_KNOWLEDGE_ROOT"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, store = runtime(
        root, queue, os.environ["RALF_KNOWLEDGE_KIND"], os.environ["RALF_KNOWLEDGE_MANAGED"] == "1"
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            print("TEMPORAL_KNOWLEDGE_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        store.close()
