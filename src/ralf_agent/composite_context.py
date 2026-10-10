"""Read-only validation of auxiliary evidence in original parallel Run frames."""

import copy

from .errors import DefinitionMismatch


def validate_frames(engine, run):
    from .context_artifacts import validate_journal as artifacts
    from .context_preparation import validate_journal as contexts
    from .managed_memory_stage import validate_journal as memories
    from .node_execution import NodeEngine

    for action in run["actions"]:
        if (
            action.get("context_preparation") is not None
            or action.get("context_manifest", {}).get("artifact_projection")
            or "memory_stage" in action
        ):
            index = action.get("node")
            if type(index) is not int or not 0 <= index < len(run["plan"]["nodes"]):
                raise DefinitionMismatch("Managed Action lost its original node")
            node_id = run["plan"]["nodes"][index]["id"]
            if "execution" not in run["workflow"]["nodes"][node_id]:
                raise DefinitionMismatch("Managed Action lost its original execution frame")
    for index, node in enumerate(run["plan"]["nodes"]):
        execution = run["workflow"]["nodes"][node["id"]].get("execution")
        if execution is None:
            continue
        frame = copy.deepcopy(execution)
        frame["actions"] = [
            dict(copy.deepcopy(a), node=0) for a in run["actions"] if a["node"] == index
        ]
        view = NodeEngine(engine, run["id"], node["id"])
        contexts(view, frame)
        artifacts(view, frame)
        memories(view, frame)


def query(engine, run, field, validator):
    parallel = run.get("plan", {}).get("schema_version") == 3
    validator(engine, {**run, "actions": []} if parallel else run)
    records = copy.deepcopy(list(run.get(field, {}).values()))
    if parallel:
        validate_frames(engine, run)
        for node_id, node in run["workflow"]["nodes"].items():
            records.extend(
                {**copy.deepcopy(record), "workflow_node": node_id}
                for record in node.get("execution", {}).get(field, {}).values()
            )
    return records


async def recover_terminal_frames(engine, run_id):
    from .context_preparation import recover_terminal_context
    from .managed_memory_stage import recover_terminal_memory
    from .node_execution import NodeEngine

    run = engine._authorized(run_id)
    validate_frames(engine, run)
    for node_id, node in run["workflow"]["nodes"].items():
        if "context_preparations" in node.get("execution", {}):
            await recover_terminal_context(NodeEngine(engine, run_id, node_id), run_id)
        if "memory_stages" in node.get("execution", {}):
            await recover_terminal_memory(NodeEngine(engine, run_id, node_id), run_id)
