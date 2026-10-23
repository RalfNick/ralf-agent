"""Fixed member bindings, managed descendants and original approval receipts."""

import asyncio

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    ModelPlanner,
    ModelResponse,
    TeamSpec,
    ToolRegistry,
    ToolSpec,
    WorkflowSpec,
)
from relf_agent.errors import DefinitionMismatch, IdempotencyConflict
from relf_agent.types import ToolCall

from .helpers import ScriptedProvider
from .test_binding_execution import RecordingProvider, TaggedContext, bound_catalog, choice, engine


@pytest.mark.parametrize("strategy", ["sequential", "router", "supervisor"])
def test_team_children_select_fixed_provider_and_context(tmp_path, strategy):
    catalog = bound_catalog()
    for color in ("red", "blue"):
        catalog.register("provider", color, "1", RecordingProvider(color))
        catalog.register("context", color, "1", TaggedContext(color))
    config = (
        {"routes": {"blue": "blue"}}
        if strategy == "router"
        else {"supervisor": "blue"}
        if strategy == "supervisor"
        else {}
    )
    wrapped = BoundDefinition(
        TeamSpec(
            "team",
            {color: AgentSpec("shared", "Answer", provider="unused") for color in ("red", "blue")},
            strategy=strategy,
            strategy_config=config,
            max_concurrency=2,
        ),
        {
            f"team/members/{color}": AgentBindingDescriptor(
                provider=choice(color), context=choice(color)
            )
            for color in ("red", "blue")
        },
    )
    with engine(tmp_path / "team.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, {"route": "blue"}, command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert done.result["provider"] == "blue"
        details = runtime.diagnostics(handle.run_id)
        assert details.manifest["kernel"] == "local-bindings-2"
        for call in details.workflow["children"]:
            output = runtime.status(call["run_id"]).result
            assert output["provider"] == call["member"]
            assert "context:" + call["member"] in output["request"]
            assert runtime.store.run(call["run_id"])["parent_id"] == handle.run_id
        assert details.budget["held"] == 0
        assert details.budget["spent"] == (1 if strategy == "router" else 2)


@pytest.mark.parametrize("mode", ["flat", "dag"])
def test_dynamic_plans_use_fixed_member_binding_not_plan_node_position(tmp_path, mode):
    catalog = bound_catalog()
    for name in ("one", "two"):
        catalog.register("provider", name, "1", RecordingProvider(name))
    wrapped = BoundDefinition(
        DynamicWorkflowSpec(
            "dynamic",
            {name: AgentSpec("same", "Answer") for name in ("one", "two")},
            plan_mode=mode,
            max_concurrency=2,
        ),
        {
            f"dynamic/members/{name}": AgentBindingDescriptor(provider=choice(name))
            for name in ("one", "two")
        },
    )
    with engine(tmp_path / "dynamic.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "task", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        calls = runtime.diagnostics(handle.run_id).workflow["children"]
        assert len(calls) == 2
        for call in calls:
            assert runtime.status(call["run_id"]).result["provider"] == call["member"]
        assert runtime.diagnostics(handle.run_id).budget["spent"] == 2


@pytest.mark.parametrize("kind", ["sequence", "graph", "team", "dynamic"])
def test_nested_member_projection_preserves_original_leaf_binding(tmp_path, kind):
    agent = AgentSpec("worker", "Answer")
    nested = {
        "sequence": WorkflowSpec("inner", [agent]),
        "graph": GraphWorkflowSpec("inner", [GraphNode("worker", agent=agent)], max_concurrency=2),
        "team": TeamSpec("inner", {"worker": agent}, child_budget=4),
        "dynamic": DynamicWorkflowSpec("inner", {"worker": agent}, plan_mode="dag", child_budget=4),
    }[kind]
    suffix = {
        "sequence": "sequence/steps/0",
        "graph": "graph/nodes/worker",
        "team": "team/members/worker",
        "dynamic": "dynamic/members/worker",
    }[kind]
    catalog = bound_catalog()
    catalog.register("provider", "chosen", "1", RecordingProvider("chosen"))
    wrapped = BoundDefinition(
        TeamSpec("outer", {"nested": nested}, child_budget=12),
        {
            "team/members/nested/" + suffix: AgentBindingDescriptor(provider=choice("chosen")),
        },
    )
    with engine(tmp_path / "nested.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "task", command_id="s", budget=16)
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        output = done.result["worker"] if kind == "graph" else done.result
        assert output["provider"] == "chosen"
        assert runtime.diagnostics(handle.run_id).budget == {"limit": 16, "held": 0, "spent": 1}


def test_parent_replay_survives_catalog_removal_but_resume_has_no_fallback(tmp_path):
    catalog = bound_catalog()
    catalog.register("provider", "chosen", "1", RecordingProvider("chosen"))
    spec = TeamSpec("team", {"worker": AgentSpec("worker", "Answer")})
    wrapped = BoundDefinition(
        spec, {"team/members/worker": AgentBindingDescriptor(provider=choice("chosen"))}
    )
    with engine(tmp_path / "replay.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "task", command_id="s")
        catalog.unregister("provider", "chosen", "1")
        assert runtime.submit(wrapped, "task", command_id="s") == handle
        with pytest.raises(IdempotencyConflict):
            runtime.submit(BoundDefinition(spec, {}), "task", command_id="s")
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(handle.run_id))
        assert runtime.status(handle.run_id).state == "queued"
        assert runtime.diagnostics(handle.run_id).workflow["children"] == []


def test_unselected_router_member_binding_is_validated_before_acceptance(tmp_path):
    spec = TeamSpec(
        "router",
        {name: AgentSpec(name, "Answer") for name in ("one", "two")},
        strategy="router",
        strategy_config={"routes": {"one": "one"}},
    )
    wrapped = BoundDefinition(
        spec, {"team/members/two": AgentBindingDescriptor(provider=choice("missing"))}
    )
    with engine(tmp_path / "reject.sqlite", bound_catalog()) as runtime:
        with pytest.raises(DefinitionMismatch):
            runtime.submit(wrapped, {"route": "one"}, command_id="s")


def test_stateless_managed_child_omits_session_writes(tmp_path):
    catalog = bound_catalog()
    wrapped = BoundDefinition(
        TeamSpec("team", {"worker": AgentSpec("worker", "Answer")}),
        {
            "team/members/worker": AgentBindingDescriptor(session=BindingSelection.disabled()),
        },
    )
    with engine(tmp_path / "stateless.sqlite", catalog) as runtime:
        handle = runtime.submit(wrapped, "task", command_id="s", session_id="parent")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        child = runtime.diagnostics(handle.run_id).workflow["children"][0]
        record = runtime.store.run(child["run_id"])
        assert runtime.sessions.read(runtime.scope, record["session_id"])[1] == []


@pytest.mark.parametrize("cancel", [False, True])
def test_bound_child_approval_restart_duplicate_control_and_parent_cancellation(tmp_path, cancel):
    catalog = bound_catalog()
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=(ToolCall("write", {}),)), ModelResponse(output="done")]
    )
    catalog.register("provider", "chosen", "1", provider)
    writes, tools = [], ToolRegistry()
    tools.register(
        ToolSpec(
            "write", "Write", {"type": "object"}, effect="unqueryable_write", requires_approval=True
        ),
        lambda a, c: writes.append(c.effect_key) or "written",
    )
    wrapped = BoundDefinition(
        TeamSpec("team", {"worker": AgentSpec("worker", "Act", tools=("write",))}),
        {
            "team/members/worker": AgentBindingDescriptor(provider=choice("chosen")),
        },
    )
    path = tmp_path / "approval.sqlite"
    with engine(path, catalog, tools=tools) as runtime:
        handle = runtime.submit(wrapped, "task", command_id="s")
        waiting = asyncio.run(runtime.drive(handle.run_id))
        assert waiting.state == "waiting_approval" and not writes
        child = runtime.diagnostics(handle.run_id).workflow["children"][0]
        action = runtime.store.run(child["run_id"])["actions"][-1]
    with engine(path, catalog, tools=tools) as runtime:
        if cancel:
            runtime.cancel(handle.run_id, command_id="cancel")
            done = asyncio.run(runtime.drive(handle.run_id))
            assert done.state == "cancelled" and writes == []
            assert runtime.status(child["run_id"]).state == "cancelled"
        else:
            receipt = runtime.approve(
                child["run_id"], action["id"], action["digest"], command_id="approve"
            )
            assert (
                runtime.approve(
                    child["run_id"], action["id"], action["digest"], command_id="approve"
                )
                == receipt
            )
            done = asyncio.run(runtime.drive(handle.run_id))
            assert done.state == "succeeded" and done.result == "done"
            assert len(writes) == 1 and provider.calls == 2
            assert runtime.diagnostics(handle.run_id).budget["held"] == 0


def test_dynamic_model_planner_stays_host_pinned_while_worker_selects_own_model(tmp_path):
    catalog = bound_catalog()
    catalog.register("provider", "worker", "1", RecordingProvider("worker"))
    plan_provider = ScriptedProvider(
        [ModelResponse(output={"steps": [{"id": "stable", "member": "worker", "input": "q"}]})]
    )
    wrapped = BoundDefinition(
        DynamicWorkflowSpec("plan", {"worker": AgentSpec("worker", "Answer")}, planner="model"),
        {
            "dynamic/members/worker": AgentBindingDescriptor(provider=choice("worker")),
        },
    )
    with engine(
        tmp_path / "planning.sqlite", catalog, planners={"model": ModelPlanner(provider="planner")}
    ) as runtime:
        runtime.providers["planner"] = plan_provider
        handle = runtime.submit(wrapped, "task", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert done.result["provider"] == "worker" and plan_provider.calls == 1
        assert runtime.diagnostics(handle.run_id).budget["spent"] == 2
