import asyncio
import json

from relf_agent import DynamicWorkflowSpec, RuntimeBuilder, RuntimeProfile, load_spec


def test_default_dag_factory_and_nested_file_codec(tmp_path):
    declaration = {
        "kind": "dynamic",
        "name": "dag",
        "plan_mode": "dag",
        "members": {
            "inner": {
                "kind": "team",
                "name": "inner",
                "members": {"leaf": {"name": "leaf", "instructions": "Answer"}},
                "child_budget": 2,
            }
        },
        "child_budget": 4,
        "max_depth": 4,
    }
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(declaration))
    spec = load_spec(path)
    assert isinstance(spec, DynamicWorkflowSpec)
    profile = RuntimeProfile(
        "dag", "1", {"default": {"adapter": "offline-echo"}}, {"planners": {"adapter": "dag-rule"}}
    )
    with RuntimeBuilder().build(profile, tmp_path / "dag.sqlite") as runtime:
        handle = runtime.submit(spec, "task", command_id="start", budget=4)
        result = asyncio.run(runtime.drive(handle.run_id))
        assert result.state == "succeeded"


def test_async_network_port_and_dag_public_exports():
    import relf_agent
    from relf_agent import (
        AsyncExecutionEngine,
        AsyncRuntimeDiagnostics,
        DAGNode,
        DAGProposal,
        ModelDAGPlanner,
        PlanningConclusion,
    )

    assert AsyncExecutionEngine and AsyncRuntimeDiagnostics
    assert DAGNode and DAGProposal and ModelDAGPlanner and PlanningConclusion
    assert len(relf_agent.__all__) == len(set(relf_agent.__all__))
