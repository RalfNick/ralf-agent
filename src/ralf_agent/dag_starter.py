"""Installed DAG/nesting starters reuse the versioned offline SDK profile."""

import json

from .orchestration_starter import PLAN_FILES


def _files(nested):
    files = dict(PLAN_FILES)
    spec = json.loads(files["workflow.json"])
    spec.update(
        name="offline-nested" if nested else "offline-dag", plan_mode="dag", planner="dag-rule"
    )
    if nested:
        spec.update(child_budget=8, max_depth=4)
        spec["members"]["research"] = {
            "kind": "team",
            "name": "research-team",
            "child_budget": 2,
            "members": {
                "analyst": {"name": "analyst", "instructions": "Analyze the task"},
                "reviewer": {"name": "reviewer", "instructions": "Review the analysis"},
            },
        }
    files["workflow.json"] = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    files["README.md"] = """# Offline DAG/nesting starter

Run from this directory after installing relf-agent:

```shell
python -m agent_app --input hello --command-id first
python -m agent_app --input hello --command-id first
python -m agent_app --input queued --command-id queued --submit-only
python -m agent_app --resume RUN_ID
ralf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

workflow.json declares the DAG mode and registered capabilities. The rule
planner produces a dependency chain with confirmed result bindings. Register
a custom Planner returning DAGProposal for branches/parallel roots, or replace
the planner with dag-model and configure a real Provider in runtime.toml.
Offline Echo proves runtime behavior only; it has no model quality score.

Nested members accept Agent, sequence, static graph, team and dynamic specs.
Every delegated definition has its own Run, isolated Session and pinned release;
the parent's credits reserve each child's complete cap. max_depth is an
execution limit, separate from the definition tree's finite size limit.

Inspect child Runs for approval or unknown effects, control the original child
and resume the parent. Keep original profiles/code available for recovery.
Use LocalEngine.patch_plan with expected_plan_revision and a stable command_id
to change pending nodes; dispatched/settled definitions cannot change.
See the dynamic DAG guide for bindings, conditions, limits and compatibility.
"""
    return files


DAG_FILES = _files(False)
NESTED_FILES = _files(True)
