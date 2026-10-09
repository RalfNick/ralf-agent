"""Mandatory host limits, selectable member policies and explicit factories."""

import asyncio

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    DynamicWorkflowSpec,
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    ModelResponse,
    Scope,
    SQLiteStore,
    TeamSpec,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.agent_limits import FixedAgentLimits
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.runtime_builder import ComponentRegistry, RuntimeBuilder
from ralf_agent.runtime_config import RuntimeProfile

from .helpers import ScriptedProvider


@pytest.mark.parametrize("mode", ["inherit", "ref", "disabled"])
def test_selected_policy_cannot_relax_host_caps(mode, tmp_path):
    catalog = BindingCatalog(scope=Scope())
    catalog.register(
        "limits",
        "loose",
        "1",
        FixedAgentLimits(max_decisions=99, max_context_chars=99999, max_tool_actions=99),
    )
    selection = BindingSelection.ref("loose", "1") if mode == "ref" else BindingSelection(mode)
    spec = AgentDefinition(AgentSpec("a", "a"), AgentBindingDescriptor(limits=selection))
    with LocalEngine(
        SQLiteStore(tmp_path / "host.sqlite"),
        providers={"default": ScriptedProvider([])},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        limits=FixedAgentLimits(max_decisions=1, max_context_chars=1000, max_tool_actions=0),
    ) as runtime:
        handle = runtime.submit(spec, "q", command_id="s")
        run = runtime.store.run(handle.run_id)
        assert runtime._agent_step(run)["max_decisions"] == 1
        assert runtime._agent_step(run)["max_context_chars"] == 1000
        manifest = runtime.diagnostics(handle.run_id).manifest
        assert manifest["kernel"] == (
            "local-bindings-1" if mode == "inherit" else "local-bindings-6"
        )
        assert "limits" in runtime.binding_capabilities["supported_binding_roles"]


@pytest.mark.parametrize(
    "kind", ["agent", "sequence", "graph", "parallel", "team", "dynamic", "dag", "nested"]
)
def test_limits_ref_enforces_decision_cap_through_all_local_boundaries(kind, tmp_path):
    catalog = BindingCatalog(scope=Scope())
    catalog.register("limits", "tiny", "1", FixedAgentLimits(max_decisions=1))
    agent = AgentSpec("a", "a", ("read",))
    if kind == "agent":
        raw, path = agent, "agent"
    elif kind == "sequence":
        raw, path = WorkflowSpec("s", [agent]), "sequence/steps/0"
    elif kind in {"graph", "parallel"}:
        raw, path = (
            GraphWorkflowSpec(
                "g", [GraphNode("a", agent=agent)], max_concurrency=2 if kind == "parallel" else 1
            ),
            "graph/nodes/a",
        )
    elif kind == "nested":
        raw, path = (
            TeamSpec("t", {"member": WorkflowSpec("s", [agent])}),
            "team/members/member/sequence/steps/0",
        )
    else:
        raw = (
            TeamSpec("t", {"member": agent})
            if kind == "team"
            else DynamicWorkflowSpec(
                "d",
                {"member": agent},
                plan_mode="dag" if kind == "dag" else "flat",
                planner="dag-rule" if kind == "dag" else "rule",
            )
        )
        path = ("team" if kind == "team" else "dynamic") + "/members/member"
    bound = (
        AgentDefinition(raw, AgentBindingDescriptor(limits=BindingSelection.ref("tiny", "1")))
        if kind == "agent"
        else BoundDefinition(
            raw, {path: AgentBindingDescriptor(limits=BindingSelection.ref("tiny", "1"))}
        )
    )
    from ralf_agent import ToolSpec
    from ralf_agent.types import ToolCall

    tools = ToolRegistry()
    tools.register(
        ToolSpec("read", "Read", {"type": "object"}, effect="read_only"),
        lambda a, ctx: {"seen": True},
    )
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=[ToolCall("read", {})]), ModelResponse(output="should not reach")]
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "member.sqlite"),
        providers={"default": provider},
        tools=tools,
        binding_catalog=catalog,
    ) as runtime:
        handle = runtime.submit(bound, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and provider.calls == 1
        assert runtime.diagnostics(handle.run_id).manifest["kernel"] == "local-bindings-6"


@pytest.mark.parametrize("kind", ["sequence", "graph", "parallel", "team", "dynamic", "nested"])
def test_each_agent_node_has_an_independent_tool_action_quota(kind, tmp_path):
    from ralf_agent import ToolSpec
    from ralf_agent.types import ToolCall

    class Provider:
        def __init__(self, label):
            self.label, self.calls = label, 0

        @property
        def identity(self):
            return {"kind": "one-tool-per-node", "version": "1", "label": self.label}

        async def complete(self, messages, tools):
            self.calls += 1
            if not any(message["role"] == "tool" for message in messages):
                return ModelResponse(tool_calls=[ToolCall("read", {})])
            return ModelResponse(output="ok")

    members = {
        name: AgentSpec("same", "Read once", ("read",), provider=name) for name in ("one", "two")
    }
    graph = GraphWorkflowSpec(
        "g",
        [GraphNode(name, agent=spec) for name, spec in members.items()],
        max_concurrency=2 if kind == "parallel" else 1,
    )
    if kind == "sequence":
        spec = WorkflowSpec("s", list(members.values()))
    elif kind in {"graph", "parallel"}:
        spec = graph
    elif kind == "nested":
        spec = TeamSpec("nested", {"member": graph})
    else:
        spec = (TeamSpec if kind == "team" else DynamicWorkflowSpec)("t", members)
    tools = ToolRegistry()
    reads = []
    tools.register(
        ToolSpec("read", "Read", {"type": "object"}, effect="read_only"),
        lambda a, ctx: reads.append(ctx.action_id) or {"seen": True},
    )
    providers = {name: Provider(name) for name in members}
    with LocalEngine(
        SQLiteStore(tmp_path / "independent.sqlite"),
        providers=providers,
        tools=tools,
        limits=FixedAgentLimits(max_tool_actions=1),
    ) as runtime:
        handle = runtime.submit(spec, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert len(reads) == 2 and len(set(reads)) == 2
        assert all(provider.calls == 2 for provider in providers.values())


def test_parallel_projection_cannot_replace_parent_accepted_caps(tmp_path):
    import inspect

    from ralf_agent import AgentLimitProposal, ToolSpec
    from ralf_agent.types import ToolCall

    class Policy:
        identity = {"kind": "projection-sensitive-policy", "version": "1"}

        def propose(self, spec):
            # Model a nondeterministic extension whose virtual frame differs
            # from parent admission, while its claimed identity stays fixed.
            owner = next(
                frame.frame.f_locals.get("self")
                for frame in inspect.stack()
                if frame.function == "_manifest"
            )
            return AgentLimitProposal(
                max_decisions=8 if type(owner).__name__ == "NodeEngine" else 1
            )

    tools = ToolRegistry()
    tools.register(
        ToolSpec("read", "Read", {"type": "object"}, effect="read_only"),
        lambda a, ctx: {"seen": True},
    )
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=[ToolCall("read", {})]), ModelResponse(output="should not reach")]
    )
    graph = GraphWorkflowSpec(
        "g", [GraphNode("a", agent=AgentSpec("a", "a", ("read",)))], max_concurrency=2
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "projection.sqlite"),
        providers={"default": provider},
        tools=tools,
        limits=Policy(),
    ) as runtime:
        handle = runtime.submit(graph, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and provider.calls <= 1


@pytest.mark.parametrize("kind", ["team", "dynamic", "dag", "sequence", "graph", "nested-team"])
@pytest.mark.parametrize("bound", [False, True])
def test_managed_children_cannot_replace_parent_accepted_caps(kind, bound, tmp_path):
    import inspect

    from ralf_agent import AgentLimitProposal, ToolSpec
    from ralf_agent.types import ToolCall

    class Policy:
        identity = {"kind": "delegation-sensitive-policy", "version": "1"}

        def propose(self, spec):
            parent_context = any(
                frame.function == "manifest"
                and (
                    frame.frame.f_globals.get("__name__") == "ralf_agent.orchestration"
                    or frame.frame.f_globals.get("__name__") == "ralf_agent.binding_runtime"
                    and frame.frame.f_locals.get("definition", {}).get("kind")
                    in {"team", "dynamic"}
                )
                for frame in inspect.stack()
            )
            return AgentLimitProposal(max_decisions=1 if parent_context else 8)

    policy = Policy()
    agent = AgentSpec("a", "a", ("read",))
    member = (
        WorkflowSpec("s", [agent])
        if kind == "sequence"
        else GraphWorkflowSpec("g", [GraphNode("a", agent=agent)], max_concurrency=2)
        if kind == "graph"
        else TeamSpec("inner", {"a": agent})
        if kind == "nested-team"
        else agent
    )
    raw = (
        DynamicWorkflowSpec(
            "d",
            {"member": member},
            plan_mode="dag" if kind == "dag" else "flat",
            planner="dag-rule" if kind == "dag" else "rule",
        )
        if kind in {"dynamic", "dag"}
        else TeamSpec("t", {"member": member})
    )
    catalog = BindingCatalog(scope=Scope())
    catalog.register("limits", "policy", "1", policy)
    if bound:
        path = ("dynamic" if kind in {"dynamic", "dag"} else "team") + "/members/member"
        if kind == "sequence":
            path += "/sequence/steps/0"
        if kind == "graph":
            path += "/graph/nodes/a"
        if kind == "nested-team":
            path += "/team/members/a"
        raw = BoundDefinition(
            raw, {path: AgentBindingDescriptor(limits=BindingSelection.ref("policy", "1"))}
        )
    tools = ToolRegistry()
    tools.register(
        ToolSpec("read", "Read", {"type": "object"}, effect="read_only"),
        lambda a, ctx: {"seen": True},
    )
    provider = ScriptedProvider(
        [ModelResponse(tool_calls=[ToolCall("read", {})]), ModelResponse(output="should not reach")]
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "child-snapshot.sqlite"),
        providers={"default": provider},
        tools=tools,
        limits=policy,
        binding_catalog=catalog,
    ) as runtime:
        handle = runtime.submit(raw, "q", command_id="s")
        done = asyncio.run(runtime.drive(handle.run_id))
        assert done.state == "failed" and provider.calls <= 1
        assert runtime.diagnostics(handle.run_id).budget["held"] == 0


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_limit_configuration_round_trip_and_effective_snapshot(extension, tmp_path):
    import json

    from ralf_agent.runtime_config import load_catalog

    path = tmp_path / ("profile." + extension)
    if extension == "json":
        profile = RuntimeProfile(
            "p",
            "1",
            {"default": {"adapter": "offline-echo"}},
            components={"limits": {"adapter": "fixed", "config": {"max_decisions": 2}}},
            binding_components=[
                {
                    "role": "limits",
                    "component_id": "agent",
                    "version": "1",
                    "component": {"adapter": "fixed", "config": {"max_decisions": 1}},
                }
            ],
        )
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "default": {"name": "p", "version": "1"},
                    "profiles": [
                        {
                            "name": profile.name,
                            "version": profile.version,
                            "providers": profile.providers,
                            "components": profile.components,
                            "binding_components": profile.binding_components,
                        }
                    ],
                }
            )
        )
    else:
        path.write_text("""schema_version = 2
[default]
name = "p"
version = "1"
[[profiles]]
name = "p"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.limits]
adapter = "fixed"
[profiles.components.limits.config]
max_decisions = 2
[[profiles.binding_components]]
role = "limits"
component_id = "agent"
version = "1"
[profiles.binding_components.component]
adapter = "fixed"
[profiles.binding_components.component.config]
max_decisions = 1
""")
    with RuntimeBuilder().build(load_catalog(path).default, tmp_path / "config.sqlite") as runtime:
        spec = AgentDefinition(
            AgentSpec("a", "a"), AgentBindingDescriptor(limits=BindingSelection.ref("agent", "1"))
        )
        handle = runtime.submit(spec, "q", command_id="s")
        assert asyncio.run(runtime.drive(handle.run_id)).state == "succeeded"


@pytest.mark.parametrize("kind", ["team", "dynamic", "nested"])
@pytest.mark.parametrize("bound", [False, True])
def test_fixed_member_caps_survive_approval_and_engine_restart(kind, bound, tmp_path):
    from ralf_agent import ToolSpec
    from ralf_agent.types import ToolCall

    agent = AgentSpec("a", "a", ("change",))
    member = WorkflowSpec("s", [agent]) if kind == "nested" else agent
    raw = (DynamicWorkflowSpec if kind == "dynamic" else TeamSpec)("t", {"member": member})
    path = ("dynamic" if kind == "dynamic" else "team") + "/members/member"
    if kind == "nested":
        path += "/sequence/steps/0"
    if bound:
        raw = BoundDefinition(
            raw, {path: AgentBindingDescriptor(limits=BindingSelection.ref("cap", "1"))}
        )
    writes = []
    tools = ToolRegistry()
    tools.register(
        ToolSpec("change", "Change", {"type": "object"}, requires_approval=True),
        lambda a, ctx: writes.append(ctx.effect_key) or {"changed": True},
    )
    database = tmp_path / "restart.sqlite"

    def runtime(provider):
        catalog = BindingCatalog(scope=Scope())
        catalog.register("limits", "cap", "1", FixedAgentLimits(max_tool_actions=1))
        return LocalEngine(
            SQLiteStore(database),
            providers={"default": provider},
            tools=tools,
            binding_catalog=catalog,
            limits=FixedAgentLimits(max_decisions=2, max_tool_actions=2),
        )

    first = ScriptedProvider([ModelResponse(tool_calls=[ToolCall("change", {})])])
    with runtime(first) as engine:
        handle = engine.submit(raw, "q", command_id="s")
        waiting = asyncio.run(engine.drive(handle.run_id))
        assert waiting.state == "waiting_approval", waiting.error
        child_id = engine.diagnostics(handle.run_id).workflow["children"][0]["run_id"]
        action = engine.status(child_id).pending[0]
        binding = engine.store.run(child_id)["parent_call"]
        assert binding["limits_member"] == "member"
        manifest = engine.diagnostics(child_id).manifest
        receipt = engine.approve(child_id, action["action_id"], action["digest"], command_id="a")
    second = ScriptedProvider([ModelResponse(output="ok")])
    with runtime(second) as engine:
        assert engine.submit(raw, "q", command_id="s") == handle
        assert engine.diagnostics(child_id).manifest == manifest
        assert (
            engine.approve(child_id, action["action_id"], action["digest"], command_id="a")
            == receipt
        )
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded", done.error
        assert asyncio.run(engine.drive(handle.run_id)) == done
        assert first.calls == second.calls == 1 and len(writes) == 1
        assert engine.diagnostics(handle.run_id).budget["held"] == 0


@pytest.mark.parametrize("bound", [False, True])
def test_managed_model_planner_and_member_keep_their_accepted_caps(bound, tmp_path):
    from ralf_agent.planning import ModelPlanner

    raw = DynamicWorkflowSpec("d", {"one": AgentSpec("one", "One")}, planner="model")
    if bound:
        raw = BoundDefinition(
            raw,
            {
                "dynamic/members/one": AgentBindingDescriptor(
                    limits=BindingSelection.ref("cap", "1")
                )
            },
        )
    catalog = BindingCatalog(scope=Scope())
    catalog.register("limits", "cap", "1", FixedAgentLimits(max_decisions=1))
    provider = ScriptedProvider(
        [
            ModelResponse(output={"steps": [{"id": "answer", "member": "one", "input": "q"}]}),
            ModelResponse(output="ok"),
        ]
    )
    with LocalEngine(
        SQLiteStore(tmp_path / "model-planner.sqlite"),
        providers={"default": provider},
        tools=ToolRegistry(),
        limits=FixedAgentLimits(max_decisions=2, max_tool_actions=0),
        binding_catalog=catalog,
        planners={"model": ModelPlanner()},
    ) as engine:
        handle = engine.submit(raw, "q", command_id="s")
        done = asyncio.run(engine.drive(handle.run_id))
        assert done.state == "succeeded" and done.result == "ok", done.error
        children = engine.diagnostics(handle.run_id).workflow["children"]
        assert [c["member"] for c in children] == ["@planner", "one"]
        for child in children:
            assert (
                engine.store.run(child["run_id"])["parent_call"]["limits_member"] == child["member"]
            )
        planner = engine.store.run(children[0]["run_id"])
        assert engine._agent_step(planner, 0)["max_decisions"] == 1
        assert provider.calls == 2 and engine.diagnostics(handle.run_id).budget["held"] == 0


@pytest.mark.parametrize("asynchronous", [False, True])
def test_profile_default_and_selected_caps_use_existing_factory_lifecycle(asynchronous, tmp_path):
    registry = ComponentRegistry()
    if asynchronous:

        async def factory(config, context):
            await asyncio.sleep(0)
            return FixedAgentLimits(max_decisions=2)

        registry.register_async("limits", "custom", factory)
    else:
        registry.register("limits", "custom", lambda c, ctx: FixedAgentLimits(max_decisions=2))
    profile = RuntimeProfile(
        "p",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={"limits": {"adapter": "custom"}},
        binding_components=[
            {
                "role": "limits",
                "component_id": "selected",
                "version": "1",
                "component": {"adapter": "fixed", "config": {"max_decisions": 1}},
            }
        ],
    )
    builder = RuntimeBuilder(registry)

    async def run():
        runtime = (
            await builder.abuild(profile, tmp_path / "build.sqlite")
            if asynchronous
            else builder.build(profile, tmp_path / "build.sqlite")
        )
        async with runtime:
            spec = AgentDefinition(
                AgentSpec("a", "a"),
                AgentBindingDescriptor(limits=BindingSelection.ref("selected", "1")),
            )
            handle = runtime.submit(spec, "q", command_id="s")
            assert (await runtime.drive(handle.run_id)).state == "succeeded"

    asyncio.run(run())


def test_configuration_invalid_caps_refused_before_database(tmp_path):
    profile = RuntimeProfile(
        "p",
        "1",
        {"default": {"adapter": "offline-echo"}},
        components={"limits": {"adapter": "fixed", "config": {"max_decisions": True}}},
    )
    with pytest.raises(ValidationError):
        RuntimeBuilder().build(profile, tmp_path / "invalid.sqlite")
    assert not (tmp_path / "invalid.sqlite").exists()


def test_missing_original_limit_ref_and_selector_refuse_without_dispatch(tmp_path):
    catalog = BindingCatalog(scope=Scope())
    catalog.register("limits", "tiny", "1", FixedAgentLimits(max_decisions=1))
    provider = ScriptedProvider([])
    with LocalEngine(
        SQLiteStore(tmp_path / "missing.sqlite"),
        providers={"default": provider},
        tools=ToolRegistry(),
        binding_catalog=catalog,
    ) as runtime:

        def selected(ref):
            return AgentDefinition(AgentSpec("a", "a"), AgentBindingDescriptor(limits=ref))

        with pytest.raises(DefinitionMismatch):
            runtime.submit(selected(BindingSelection.ref("tiny", "2")), "q", command_id="missing")
        with pytest.raises(ValidationError):
            runtime.submit(
                selected(BindingSelection.ref("tiny", "1", selector={"namespace": "n"})),
                "q",
                command_id="selector",
            )
        handle = runtime.submit(selected(BindingSelection.ref("tiny", "1")), "q", command_id="s")
        catalog.unregister("limits", "tiny", "1")
        with pytest.raises(DefinitionMismatch):
            asyncio.run(runtime.drive(handle.run_id))
        assert provider.calls == 0
