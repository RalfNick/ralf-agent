import pytest

import relf_agent as r
from relf_agent.errors import ValidationError


def plan(**options):
    return r.StaticWorkflowCompiler().compile(
        r.GraphWorkflowSpec(
            "parallel",
            [r.GraphNode("a", transform="identity"), r.GraphNode("b", transform="identity")],
            **options,
        )
    )


def test_parallel_plan_is_explicit_and_serial_identity_is_unchanged():
    assert plan().to_dict() == plan(max_concurrency=1).to_dict()
    assert "max_concurrency" not in plan().to_dict()
    value = plan(max_concurrency=2)
    assert value.to_dict()["schema_version"] == 3
    assert r.GraphWorkflowSpec.from_plan(value).max_concurrency == 2
    assert r.ExecutionPlan(value.to_dict()).identity == value.identity


@pytest.mark.parametrize("limit", [True, 0, -1, 33, 2.5, "2", None])
def test_parallel_limit_is_bounded_integer(limit):
    with pytest.raises(ValidationError):
        plan(max_concurrency=limit)


def test_scheduler_respects_capacity_and_waits_for_running_dependencies():
    value = plan(max_concurrency=2)
    states = {"a": {"state": "pending"}, "b": {"state": "pending"}}
    batch = r.StaticWorkflowScheduler().select(value, {"x": []}, states, 1)
    assert [s.node_id for s in batch.selections] == ["a"]
    batch.selections[0].input["x"].append(1)
    assert states["a"] == {"state": "pending"}
    states["a"] = {"state": "running"}
    states["b"] = {"state": "waiting_approval"}
    batch = r.StaticWorkflowScheduler().select(value, {}, states, 1)
    assert not batch.selections and not batch.done
    states = {"a": {"state": "completed", "result": 1}, "b": {"state": "skipped"}}
    assert r.StaticWorkflowScheduler().select(value, {}, states, 1).result == {"a": 1}


@pytest.mark.parametrize("attack", ["duplicate", "capacity", "input", "skip", "done", "empty"])
def test_common_batch_boundary_rejects_hostile_scheduler(attack):
    from relf_agent.workflow_scheduler import validate_batch

    value = plan(max_concurrency=2)
    states = {"a": {"state": "pending"}, "b": {"state": "pending"}}
    selections = [r.WorkflowSelection("a", "task")]
    kwargs = {}
    if attack in {"duplicate", "capacity"}:
        selections.append(r.WorkflowSelection("a" if attack == "duplicate" else "b", "task"))
    elif attack == "input":
        selections = [r.WorkflowSelection("a", "invented")]
    elif attack == "skip":
        kwargs["skipped"] = ("b",)
    elif attack == "done":
        kwargs.update(done=True, result={})
    elif attack == "empty":
        selections = []
    with pytest.raises(ValidationError):
        validate_batch(value, "task", states, 1, r.WorkflowBatch(selections, **kwargs))


def test_join_never_runs_while_dependency_is_blocked():
    value = r.StaticWorkflowCompiler().compile(
        r.GraphWorkflowSpec(
            "join",
            [
                r.GraphNode("a", transform="identity"),
                r.GraphNode("b", transform="identity", depends_on=("a",), input=r.ValueRef("a")),
            ],
            max_concurrency=2,
        )
    )
    states = {"a": {"state": "waiting_reconciliation"}, "b": {"state": "pending"}}
    batch = r.StaticWorkflowScheduler().select(value, "task", states, 2)
    assert not batch.done and not batch.selections
