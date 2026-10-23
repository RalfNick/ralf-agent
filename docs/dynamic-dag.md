# Dynamic DAG and nested orchestration — dev15

The default local SDK needs no broker or database service. `DynamicWorkflowSpec`
keeps its original flat mode; opt into `plan_mode="dag"` for dependency plans.
`RuleDAGPlanner` is the default in that mode. `ModelDAGPlanner` delegates a
tool-free native child Run through the same budget/step limits and Provider.

```python
from relf_agent import AgentSpec, DynamicWorkflowSpec, DAGNode, DAGProposal, ValueRef


class ResearchPlanner:
    identity = {"kind": "research-planner", "version": "1"}

    async def plan(self, request, caller):
        return DAGProposal(
            [
                DAGNode("read", "reader"),
                DAGNode("answer", "writer", depends_on=("read",), input=ValueRef("read")),
            ],
            output=ValueRef("answer"),
        )


spec = DynamicWorkflowSpec(
    "research",
    {
        "reader": AgentSpec("reader", "Read evidence"),
        "writer": AgentSpec("writer", "Answer from confirmed evidence"),
    },
    plan_mode="dag",
    planner="research",
    child_budget=4,
    max_concurrency=2,
)
# Inject planners={"research": ResearchPlanner()} into the original LocalEngine.
# engine.submit(spec, input, command_id=..., budget=8); await engine.drive(run_id)
```

`PlanningRequest.capabilities` carries the registered member definitions;
`constraints` carries remaining steps, revisions, concurrency and credit limits.
A plan names registered members only. Each node has a stable ID, explicit
dependencies, typed input binding, optional `BranchCondition` and output Schema.
References must target input or a dependency ancestor. Cycles, undeclared members,
invalid conditions and incompatible output Schemas fail before dependent dispatch.
`Literal`, `ValueRef` and `InputMap` use the same binding validation as static graphs.
Independent ready nodes run up to the parent limit; this is bounded batch execution,
not streaming dataflow. Approval/unknown-effect branches pause and remain inspectable.

The parent commits the received proposal before adopting a revision, fixes each
node's bound input with child creation, and saves completed results. Crash recovery
uses accepted evidence instead of regenerating the plan or duplicating children.
`PlanningConclusion("refused", reason)` or `("needs_input", reason)` stops safely
with a structured result. This is a completed planning conclusion, not an interactive
`send_input` continuation protocol.

## Pending-node patches

`LocalEngine.patch_plan(run_id, DAGProposal(...), expected_plan_revision=0,
command_id="patch-1")` performs scoped command deduplication and revision CAS.
Diagnostics expose `workflow.plan_revision`, proposal digests and revision records.
Only active accepted DAGs can change. Dispatched, completed and skipped node
definitions are frozen, including dependencies and bindings. Pending nodes may be
added, removed or replaced within finite remaining limits. Replaying the original
command returns its receipt; a changed request conflicts. A patch is explicit host
control, not an unrecorded mutation by a planner.

## Nested members

Team and dynamic members accept `AgentSpec`, `WorkflowSpec` sequences,
`GraphWorkflowSpec`, `TeamSpec` and `DynamicWorkflowSpec`. Static graph nodes retain
their current Agent/Tool/Transform contract; arbitrary nested nodes are not added.
Every delegated workflow has its own Run and Session, links to its parent and pins
its own release plus the parent's release. Changes to ancestor configuration prevent
new dispatch by descendants. Parent cancellation/failure propagates to children.

The parent atomically reserves the child's entire credit cap before submission.
Recursive settlement charges actual descendant spend after completion; unresolved
effects retain conservative holds. Failure does not release the root Session while
a real descendant handler is still running. Execution depth defaults to a maximum
of eight, with `max_depth` available to tighten it. Definitions also have separate
limits of eight structural levels, 256 components and 1 MiB finite JSON.

```shell
relf init my-dag --template dag
cd my-dag
python -m agent_app --input hello --command-id first
relf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

`--template nested` creates a DAG delegating to a team. Both packaged starters use
offline Echo/rule planning and require no model key. Runtime catalogs include
`dag-rule` and `dag-model` planner factories. Preserve original profiles and code
for recovery. Existing ten dev14 starter definitions and legacy flat serialization
remain unchanged; new nested/DAG parents need dev15. Temporal's current capability
subset refuses these definitions rather than routing them to local execution.

See [orchestration](orchestration.md), [static graphs](static-workflows.md) and
[planning evaluation](planning-evaluation.md) for related contracts and evidence.

Downgrading new nested records to dev14 is unsupported: the actual old wheel stops before dispatch, but its older definition reader may raise KeyError instead of a typed compatibility error. Keep dev15 for those Runs; legacy dev14 native/static/flat Runs are verified to continue under dev15.
