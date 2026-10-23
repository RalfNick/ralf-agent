"""Process-loss probe at a safe Context read, after History has adopted limits."""

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
    ContextAssembler,
    DynamicWorkflowSpec,
    FixedAgentLimits,
    GraphNode,
    GraphWorkflowSpec,
    ManagedContextPipeline,
    ModelResponse,
    Scope,
    TeamSpec,
    ToolRegistry,
    WorkflowSpec,
)
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.types import canonical


class Context:
    identity = {"kind": "limits-recovery-context", "version": "1"}

    def assemble(self, history, references, max_chars):
        return ContextAssembler().assemble(history, references, max_chars)


class Provider:
    identity = {"kind": "limits-recovery-provider", "version": "1"}

    def __init__(self, root):
        self.root = root

    async def complete(self, messages, tools):
        assert len(canonical(messages)) <= 2000
        with (self.root / "audit.jsonl").open("a") as out:
            out.write(json.dumps({"kind": "model"}) + "\n")
        return ModelResponse(output="pool")


def runtime(root, queue, kind, managed):
    root = Path(root)
    scope = Scope("temporal-limits", queue)
    catalog = BindingCatalog(scope=scope)
    for label, cap in (("A", 1000), ("B", 2000)):
        catalog.register(
            "limits",
            label,
            "1",
            FixedAgentLimits(max_context_chars=cap, max_decisions=1, max_tool_actions=0),
        )
    agent = AgentSpec("same", "answer", max_context_chars=4096)
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
        first = WorkflowSpec("nested", [agent]) if kind == "nested" else agent
        definition = TeamSpec("team", {"a": first, "b": agent}, child_budget=4)
        paths = [
            "team/members/a/sequence/steps/0" if kind == "nested" else "team/members/a",
            "team/members/b",
        ]
    bindings = {
        path: AgentBindingDescriptor(limits=BindingSelection.ref(label, "1"))
        for path, label in zip(paths, ("A", "B"), strict=False)
    }
    definition = (
        AgentDefinition(agent, bindings["agent"])
        if kind == "native"
        else BoundDefinition(definition, bindings)
    )

    class AuditedRuntime(TemporalRuntime):
        async def propose_limits(self, request):
            response = await super().propose_limits(request)
            if response["ok"]:
                with (root / "audit.jsonl").open("a") as out:
                    out.write(
                        json.dumps(
                            {
                                "kind": "limits",
                                "action_id": request["action_id"],
                                "proposals": response["proposals"],
                            }
                        )
                        + "\n"
                    )
            return response

        async def gate(self, request):
            selection = request["step_bindings"]["limits"]["component_id"]
            expected = 1000 if selection == "A" else 2000
            assert request["step"]["max_context_chars"] == expected
            assert request["step"]["max_decisions"] == 1
            if os.environ.get("RALF_LIMITS_MODE") == "crash" and selection == (
                "A" if kind == "native" else "B"
            ):
                (root / "context-ready").write_text(request["run_id"])
                await asyncio.Event().wait()

        async def prepare_context(self, request):
            await self.gate(request)
            return await super().prepare_context(request)

        async def manage_context(self, request, *, dispatch_guard=None):
            if request["phase"] == "plan":
                await self.gate(request)
            return await super().manage_context(request, dispatch_guard=dispatch_guard)

    return AuditedRuntime(
        providers={"default": Provider(root)},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        limits=FixedAgentLimits(max_context_chars=3000),
        context_builder=ManagedContextPipeline() if managed else Context(),
    ), definition


async def run():
    from temporalio.client import Client

    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    execution, _ = runtime(
        Path(os.environ["RALF_LIMITS_ROOT"]),
        queue,
        os.environ["RALF_LIMITS_KIND"],
        os.environ["RALF_LIMITS_MANAGED"] == "1",
    )
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    async with build_temporal_worker(client, task_queue=queue, runtime=execution):
        print("TEMPORAL_LIMITS_READY", flush=True)
        await asyncio.Event().wait()
