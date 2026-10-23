"""Actual process-loss fixture: gate only a safe read after accepted verification."""

import asyncio
import json
import os
from pathlib import Path

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    CompletionVerdict,
    ContextAssembler,
    DynamicWorkflowSpec,
    FixedAgentLimits,
    GraphNode,
    GraphWorkflowSpec,
    ManagedContextPipeline,
    ManagedMemoryPolicy,
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
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime


class Context:
    identity = {"kind": "completion-worker-context", "version": "1"}

    def assemble(self, history, references, max_chars):
        return ContextAssembler().assemble(history, references, max_chars)


class ReceiptVerifier:
    identity = {"kind": "custom-completion-worker", "version": "1"}

    def verify(self, request):
        if any(
            r["tool"] == "lookup"
            and r["arguments"] == {"target": "demo"}
            and r["result"] == {"found": True}
            for r in request.receipts
        ):
            return CompletionVerdict("accept")
        return CompletionVerdict("retry", "need original lookup evidence")


class Provider:
    identity = {"kind": "completion-worker-provider", "version": "1"}

    def __init__(self, root):
        self.root = root

    async def complete(self, messages, tools):
        if not any(m["role"] == "tool" for m in messages) and any(
            isinstance(m.get("content"), str)
            and m["content"].startswith("Completion verification:")
            for m in messages
        ):
            result = ModelResponse(tool_calls=[ToolCall("lookup", {"target": "demo"}, "lookup")])
        else:
            result = ModelResponse(output={"status": "resolved", "target": "demo"})
        with (self.root / "audit.jsonl").open("a") as out:
            out.write(json.dumps({"kind": "model"}) + "\n")
        return result


def runtime(root, queue, kind, managed):
    root = Path(root)
    scope = Scope("temporal-completion", queue)
    store = SQLiteStore(root / "memory.sqlite")
    memory = SQLiteMemory(store)
    catalog = BindingCatalog(scope=scope)
    catalog.register(
        "verifier",
        "A",
        "1",
        ToolReceiptVerifier(
            "lookup",
            argument_bindings={"target": "/target"},
            result_schema={
                "type": "object",
                "required": ["found"],
                "properties": {"found": {"const": True}},
            },
        ),
    )
    catalog.register("verifier", "B", "1", ReceiptVerifier())

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
        path: AgentBindingDescriptor(verifier=BindingSelection.ref(label, "1"))
        for path, label in zip(paths, ("A", "B"), strict=False)
    }
    definition = (
        AgentDefinition(agent, bindings["agent"])
        if kind == "native"
        else BoundDefinition(definition, bindings)
    )

    class GatedRuntime(TemporalRuntime):
        async def verify_completion(self, request):
            response = await super().verify_completion(request)
            if response["ok"]:
                assert not isinstance(request["completion"]["task"], str)
                with (root / "audit.jsonl").open("a") as out:
                    out.write(
                        json.dumps(
                            {
                                "kind": "verify",
                                "action_id": request["action_id"],
                                "status": response["verdict"]["status"],
                            }
                        )
                        + "\n"
                    )
            return response

        async def gate(self, request, window):
            selected = request["step_bindings"]["verifier"]["component_id"]
            target = "A" if kind == "native" else "B"
            if (
                os.environ.get("RALF_COMPLETION_MODE") == "crash"
                and os.environ.get("RALF_COMPLETION_WINDOW") == window
                and selected == target
            ):
                (root / "read-ready").write_text(request["run_id"])
                await asyncio.Event().wait()

        async def prepare_context(self, request, *, dispatch_guard=None, on_end=None):
            if any(
                isinstance(m.get("content"), str)
                and m["content"].startswith("Completion verification:")
                for m in request["messages"]
            ) and not any(m["role"] == "tool" for m in request["messages"]):
                await self.gate(request, "retry")
            return await super().prepare_context(
                request, dispatch_guard=dispatch_guard, on_end=on_end
            )

        async def manage_context(self, request, *, dispatch_guard=None, on_end=None):
            if (
                request["phase"] == "plan"
                and any(
                    isinstance(m.get("content"), str)
                    and m["content"].startswith("Completion verification:")
                    for m in request["messages"]
                )
                and not any(m["role"] == "tool" for m in request["messages"])
            ):
                await self.gate(request, "retry")
            return await super().manage_context(
                request, dispatch_guard=dispatch_guard, on_end=on_end
            )

        async def manage_memory(self, request, *, dispatch_guard=None):
            if request["phase"] == "plan":
                await self.gate(request, "accept")
            return await super().manage_memory(request, dispatch_guard=dispatch_guard)

    execution = GatedRuntime(
        providers={"default": Provider(root)},
        tools=tools,
        binding_catalog=catalog,
        limits=FixedAgentLimits(max_decisions=4, max_tool_actions=1),
        stage_policy=ManagedMemoryPolicy(memory, scope=scope),
        context_builder=ManagedContextPipeline() if managed else Context(),
    )
    return execution, definition, store, memory


async def run():
    from temporalio.client import Client

    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _, store, _ = runtime(
        Path(os.environ["RALF_COMPLETION_ROOT"]),
        queue,
        os.environ["RALF_COMPLETION_KIND"],
        os.environ["RALF_COMPLETION_MANAGED"] == "1",
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    try:
        async with build_temporal_worker(client, task_queue=queue, runtime=execution):
            print("TEMPORAL_COMPLETION_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        store.close()
