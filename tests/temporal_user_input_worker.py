"""Independent actual Worker fixture; no model-quality claim."""

import asyncio
import json
import os
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from relf_agent import (
    AgentSpec,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    PlanProposal,
    TeamSpec,
    ToolCall,
    ToolRegistry,
)
from relf_agent.dag_planning import DAGNode, DAGProposal, PlanningConclusion
from relf_agent.model_continuation import ContinuedModelResponse, ModelContinuation
from relf_agent.model_history import CompleteModelHistory
from relf_agent.orchestration_types import ChildCall
from relf_agent.temporal import _workflow_runner
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.types import digest
from relf_agent.user_input import UserInputPolicy, register_user_input
from relf_agent.workflow import Literal, ValueRef

FENCE_REQUESTED = "input-fence-requested"
FENCE_ENTERED = "input-fence-entered.jsonl"
FENCE_RELEASED = "input-fence-released"


def fenced_activities(execution, client, root):
    """Hold only a real original retryable Context, before its handler runs."""
    from temporalio import activity

    from relf_agent.temporal_activities import registered_activities
    from relf_agent.temporal_control_activities import registered_parent_activities
    from relf_agent.temporal_session_activities import registered_session_activities
    from relf_agent.temporal_state import CONTEXT_ACTIVITY

    originals = (
        registered_activities(execution, client)
        + registered_parent_activities(execution, client)
        + registered_session_activities(execution, client)
    )
    original = next(
        operation
        for operation in originals
        if activity._Definition.must_from_callable(operation).name == CONTEXT_ACTIVITY
    )

    @activity.defn(name=CONTEXT_ACTIVITY)
    async def context(request: dict) -> dict:
        if (root / FENCE_REQUESTED).exists() and not (root / FENCE_RELEASED).exists():
            info = activity.info()
            entry = {
                "pid": os.getpid(),
                "workflow_id": info.workflow_id,
                "activity_id": info.activity_id,
                "attempt": info.attempt,
                "activity": CONTEXT_ACTIVITY,
                "request": request,
                "request_digest": digest(request),
            }
            with (root / FENCE_ENTERED).open("a") as output:
                output.write(json.dumps(entry) + "\n")
            while not (root / FENCE_RELEASED).exists():  # noqa: ASYNC110 -- actual subprocess fence
                await asyncio.sleep(0.01)
        return await original(request)

    return [context if operation is original else operation for operation in originals]


class SignedQuestion:
    identity = {"kind": "actual-input-signed-fixture", "version": "1"}

    def __init__(self, root):
        self.root = root

    @property
    def continuation_identity(self):
        return {"protocol": "actual-input-signed-v1", "owner_digest": digest(self.identity)}

    async def complete(self, messages, tools):
        receipts = [m for m in messages if m["role"] == "tool"]
        if tools and not receipts:
            output, calls, phase = (
                None,
                [ToolCall("request_input", {"prompt": "Which item?"}, "native-question")],
                "question",
            )
        else:
            output, calls, phase = "Selected wire", [], "continued" if tools else "worker"
            if tools:
                assert receipts[-1] == {
                    "role": "tool",
                    "tool_call_id": "native-question",
                    "content": '"wire"',
                }
                original = next(m for m in messages if m["role"] == "assistant")
                assert original["model_continuation"]["data"] == {"signature": "signed-question"}
        with (self.root / "input-audit.jsonl").open("a") as output_file:
            output_file.write(json.dumps({"phase": phase, "messages": messages}) + "\n")
        return ContinuedModelResponse(
            output,
            tuple(calls),
            continuation=ModelContinuation(
                "actual-input-signed-v1",
                digest(self.identity),
                digest({"output": output, "tool_calls": [asdict(c) for c in calls]}),
                {"signature": "signed-question" if calls else "signed-final"},
            ),
        )


class ClarifyingPlanner:
    identity = {"kind": "actual-input-planner-fixture", "version": "1"}

    async def plan(self, request, caller):
        if not getattr(request, "clarifications", None):
            return PlanningConclusion("needs_input", "Which item?")
        return PlanProposal(
            [ChildCall("worker", "worker", {"selected": request.clarifications[-1]["value"]})]
        )


class ClarifyingDAGPlanner(ClarifyingPlanner):
    identity = {"kind": "actual-input-dag-planner-fixture", "version": "1"}

    async def plan(self, request, caller):
        if not getattr(request, "clarifications", None):
            return PlanningConclusion("needs_input", "Which item?")
        return DAGProposal(
            [
                DAGNode(
                    "worker",
                    "worker",
                    input=Literal({"selected": request.clarifications[-1]["value"]}),
                )
            ],
            output=ValueRef("worker"),
        )


def runtime(root, kind):
    tools = ToolRegistry()
    register_user_input(tools)
    execution = TemporalRuntime(
        providers={"default": SignedQuestion(root)},
        tools=tools,
        enable_sessions=True,
        model_continuation=True,
        model_history=CompleteModelHistory(scope="session"),
        user_input_policies={"ask": UserInputPolicy()},
        planners={"clarify": ClarifyingPlanner(), "clarify-dag": ClarifyingDAGPlanner()},
    )
    leaf = AgentSpec(
        "ask", "Ask for the item and consume its exact reply", ("request_input",), max_decisions=3
    )
    if kind == "agent":
        definition = leaf
    elif kind == "graph":
        definition = GraphWorkflowSpec(
            "graph", [GraphNode("leaf", agent=leaf)], output=ValueRef("leaf")
        )
    elif kind == "team":
        definition = TeamSpec("team", {"worker": leaf}, child_budget=4)
    elif kind == "nested":
        definition = TeamSpec(
            "outer",
            {
                "inner": GraphWorkflowSpec(
                    "graph", [GraphNode("leaf", agent=leaf)], output=ValueRef("leaf")
                )
            },
            child_budget=8,
        )
    else:
        definition = DynamicWorkflowSpec(
            "plan",
            {"worker": AgentSpec("worker", "Answer using supplied selection")},
            planner="clarify-dag" if kind == "dag" else "clarify",
            plan_mode="dag" if kind == "dag" else "flat",
            max_revisions=2,
            input_policy="ask",
        )
    return execution, definition


async def run():
    from temporalio.client import Client
    from temporalio.worker import Worker

    from relf_agent.temporal_parent_workflow import TemporalParentWorkflow
    from relf_agent.temporal_session_workflow import TemporalSessionWorkflow
    from relf_agent.temporal_state import text
    from relf_agent.temporal_workflow import (
        TemporalCommandRegistryWorkflow,
        TemporalRunWorkflow,
    )

    root = Path(os.environ["RALF_INPUT_ROOT"])
    execution, _ = runtime(root, os.environ["RALF_INPUT_KIND"])
    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    queue = os.environ["RALF_TEST_TEMPORAL_QUEUE"]
    text(queue, "Temporal task queue")
    execution.validate_release()
    manifest = execution.manifest
    worker = Worker(
        client,
        task_queue=queue,
        workflows=[
            TemporalRunWorkflow,
            TemporalCommandRegistryWorkflow,
            TemporalParentWorkflow,
            TemporalSessionWorkflow,
        ],
        activities=fenced_activities(execution, client, root),
        workflow_runner=_workflow_runner(),
        identity="ralf-temporal:" + digest(manifest),
        build_id=digest(manifest),
        sticky_queue_schedule_to_start_timeout=timedelta(seconds=1),
        disable_eager_activity_execution=True,
    )
    async with worker:
        print("TEMPORAL_INPUT_READY", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    # The host imports this module. Match its concrete planner method owners
    # when launched with -m instead of registering __main__ implementations.
    from tests.temporal_user_input_worker import run as canonical_run

    asyncio.run(canonical_run())
