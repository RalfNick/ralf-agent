"""Actual process-loss fixture: gate only a safe memory read after accepted model proposal and verification."""

import asyncio
import json
import os
from pathlib import Path

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    ContextAssembler,
    DecisionProposal,
    DynamicWorkflowSpec,
    FixedAgentLimits,
    GraphNode,
    GraphWorkflowSpec,
    ManagedContextPipeline,
    ManagedMemoryPolicy,
    ModelRequest,
    ModelResponse,
    Scope,
    SQLiteMemory,
    SQLiteStore,
    TeamSpec,
    ToolCall,
    ToolReceiptVerifier,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from ralf_agent.temporal import build_temporal_worker
from ralf_agent.temporal_activities import TemporalRuntime


class Context:
    identity = {"kind": "decision-worker-context", "version": "1"}

    def assemble(self, history, references, max_chars):
        return ContextAssembler().assemble(history, references, max_chars)


class DecisionPolicy:
    def __init__(self, label):
        self.identity = {"kind": "decision-worker-policy", "version": "1", "label": label}

    def prepare(self, spec, messages, tools):
        return ModelRequest(
            [*messages, {"role": "system", "content": "policy:" + self.identity["label"]}], tools
        )

    def propose(self, spec, response):
        if response.output["status"] == "request-tool":
            return DecisionProposal(
                tool_calls=(ToolCall("lookup", {"target": response.output["target"]}, "lookup"),)
            )
        return DecisionProposal(
            output={"status": "resolved", "target": "demo", "policy": self.identity["label"]}
        )


class DelegatingDecisionPolicy(DecisionPolicy):
    def prepare(self, spec, messages, tools):
        return super().prepare(spec, messages, tools)

    def propose(self, spec, response):
        return super().propose(spec, response)


class Provider:
    identity = {"kind": "decision-worker-provider", "version": "1"}

    def __init__(self, root):
        self.root = root

    async def complete(self, messages, tools):
        assert messages[-1]["content"].startswith("policy:")
        assert [t["function"]["name"] for t in tools] == ["lookup"]
        status = "candidate" if any(m["role"] == "tool" for m in messages) else "request-tool"
        with (self.root / "audit.jsonl").open("a") as out:
            out.write(json.dumps({"kind": "model", "policy": messages[-1]["content"]}) + "\n")
        return ModelResponse(output={"status": status, "target": "demo"}, usage={"total_tokens": 3})


def runtime(root, queue, kind, managed, *, delegate=False):
    root = Path(root)
    scope = Scope("temporal-decision", queue)
    store = SQLiteStore(root / "memory.sqlite")
    memory = SQLiteMemory(store)
    catalog = BindingCatalog(scope=scope)
    policy = DelegatingDecisionPolicy if delegate else DecisionPolicy
    catalog.register("decision_policy", "A", "1", policy("A"))
    catalog.register("decision_policy", "B", "1", policy("B"))

    async def lookup(arguments, context):
        with (root / "audit.jsonl").open("a") as out:
            out.write(json.dumps({"kind": "tool", "effect_key": context.effect_key}) + "\n")
        return {"found": True}

    tools = ToolRegistry()
    tools.register(ToolSpec("lookup", "read", {"type": "object"}, requires_approval=True), lookup)
    agent = AgentSpec("same", "answer", ("lookup",), max_decisions=4)
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
            "dynamic", {"a": agent, "b": agent}, planner="dag-rule", plan_mode="dag", child_budget=8
        )
        paths = ["dynamic/members/a", "dynamic/members/b"]
    else:
        first = WorkflowSpec("nested", [agent]) if kind == "nested" else agent
        definition = TeamSpec("team", {"a": first, "b": agent}, child_budget=8)
        paths = [
            "team/members/a/sequence/steps/0" if kind == "nested" else "team/members/a",
            "team/members/b",
        ]
    bindings = {
        path: AgentBindingDescriptor(decision_policy=BindingSelection.ref(label, "1"))
        for path, label in zip(paths, ("A", "B"), strict=False)
    }
    definition = (
        AgentDefinition(agent, bindings["agent"])
        if kind == "native"
        else BoundDefinition(definition, bindings)
    )

    class GatedRuntime(TemporalRuntime):
        async def gate(self, request):
            selected = request["step_bindings"]["decision_policy"]["component_id"]
            target = "A" if kind == "native" else "B"
            if os.environ.get("RALF_DECISION_MODE") == "crash" and selected == target:
                (root / "read-ready").write_text(request["run_id"])
                await asyncio.Event().wait()

        async def manage_memory(self, request, *, dispatch_guard=None):
            if request["phase"] == "plan":
                await self.gate(request)
            return await super().manage_memory(request, dispatch_guard=dispatch_guard)

    execution = GatedRuntime(
        providers={"default": Provider(root)},
        tools=tools,
        binding_catalog=catalog,
        verifier=ToolReceiptVerifier(
            "lookup",
            result_schema={
                "type": "object",
                "required": ["found"],
                "properties": {"found": {"const": True}},
            },
        ),
        limits=FixedAgentLimits(max_decisions=4, max_tool_actions=1),
        stage_policy=ManagedMemoryPolicy(memory, scope=scope),
        context_builder=ManagedContextPipeline() if managed else Context(),
    )
    return execution, definition, store, memory


async def run():
    from temporalio.client import Client

    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, store, _ = runtime(
        Path(os.environ["RALF_DECISION_ROOT"]),
        queue,
        os.environ["RALF_DECISION_KIND"],
        os.environ["RALF_DECISION_MANAGED"] == "1",
        delegate=os.environ.get("RALF_DECISION_SUPER") == "1",
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            print("TEMPORAL_DECISION_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        store.close()
