import asyncio
from dataclasses import asdict

import pytest

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    BoundDefinition,
    ContextAssembler,
    GraphNode,
    GraphWorkflowSpec,
    InMemoryMemory,
    ManagedMemoryPolicy,
    ModelResponse,
    Scope,
    TeamSpec,
    ToolRegistry,
    WorkflowSpec,
)
from relf_agent.errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from relf_agent.temporal_activities import TemporalRuntime
from relf_agent.temporal_parent_state import TemporalParentState
from relf_agent.temporal_state import TemporalRunState, validate_request
from relf_agent.types import submission_request


class Provider:
    def __init__(self, label):
        self.label, self.calls = label, 0
        self.identity = {"kind": "temporal-binding-fixture", "label": label}

    async def complete(self, messages, tools):
        self.calls += 1
        return ModelResponse(output={"name": self.label})


def setup():
    scope = Scope()
    catalog = BindingCatalog(scope=scope)
    first, second = Provider("first"), Provider("second")
    catalog.register("provider", "chosen", "1", second)
    catalog.register("context", "plain", "1", ContextAssembler())
    catalog.register("stage_policy", "facts", "1", ManagedMemoryPolicy(InMemoryMemory()))
    runtime = TemporalRuntime(
        providers={"default": first}, tools=ToolRegistry(), binding_catalog=catalog
    )
    return runtime, catalog, first, second


async def grant(state, request):
    from relf_agent.types import digest

    return state.admit_context_dispatch(
        {
            "scope": request["scope"],
            "action_id": request["action_id"],
            "release_digest": request["release_digest"],
            "phase": request.get("phase", "model"),
            "request_digest": digest(request),
        }
    )


def test_bound_agent_dispatches_selected_provider_and_fixed_context():
    async def run():
        runtime, catalog, first, second = setup()
        spec = AgentDefinition(
            AgentSpec("a", "answer"),
            AgentBindingDescriptor(
                provider=BindingSelection.ref("chosen", "1"),
                context=BindingSelection.ref("plain", "1"),
            ),
        )
        from relf_agent.temporal_bindings import normalize_request

        request = normalize_request(submission_request(spec, "task"))
        state = TemporalRunState("run", asdict(Scope()), "s", request, runtime.manifest)
        for _ in range(5):
            operation = state.next_operation()
            if operation is None:
                break
            action, value = operation
            if action["kind"] == "context":
                state.accept_context(action["id"], await runtime.prepare_context(value))
            else:
                state.accept_model(
                    action["id"],
                    await runtime.complete_model(value, dispatch_guard=lambda r: grant(state, r)),
                )
        assert state.result == {"name": "second"}
        assert first.calls == 0 and second.calls == 1
        catalog.unregister("provider", "chosen", "1")
        with pytest.raises(DefinitionMismatch):
            runtime.validate_release()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["graph", "team", "nested"])
def test_original_parent_projects_each_declared_binding_subtree(kind):
    runtime, _, _, _ = setup()
    a = AgentSpec("same", "answer")
    if kind == "graph":
        spec = GraphWorkflowSpec("g", [GraphNode("a", agent=a)])
        path, child_path = "graph/nodes/a", "agent"
    elif kind == "team":
        spec = TeamSpec("t", {"a": a})
        path, child_path = "team/members/a", "agent"
    else:
        spec = TeamSpec("t", {"a": WorkflowSpec("w", [a])})
        path, child_path = "team/members/a/sequence/steps/0", "sequence/steps/0"
    descriptor = AgentBindingDescriptor(provider=BindingSelection.ref("chosen", "1"))
    from relf_agent.temporal_bindings import normalize_request

    request = normalize_request(
        submission_request(BoundDefinition(spec, {path: descriptor}), "task")
    )
    state = TemporalParentState(
        "parent", asdict(Scope()), "s", request, runtime.orchestration_release
    )
    from relf_agent.orchestration_types import ChildCall

    call = state.delegate(ChildCall("one", "a", "task"))
    assert set(call["request"]["agent_bindings"]) == {child_path}
    child = TemporalRunState(
        "child", asdict(Scope()), "s", call["request"], runtime.orchestration_release
    )
    assert child.step["provider"] != "default"


@pytest.mark.parametrize("role", ["session", "sandbox"])
def test_unavailable_temporal_binding_refused_before_run(role):
    runtime, _, _, _ = setup()
    descriptor = AgentBindingDescriptor(**{role: BindingSelection.ref("missing", "1")})
    from relf_agent.temporal_bindings import normalize_request

    request = normalize_request(
        submission_request(AgentDefinition(AgentSpec("a", "answer"), descriptor), "task")
    )
    # Session and Sandbox are selectable; the missing version/protocol still refuses before dispatch.
    with pytest.raises(DefinitionMismatch):
        validate_request(request, runtime.manifest)


def test_foreign_catalog_scope_cannot_accept_bound_agent():
    runtime, _, _, _ = setup()
    from relf_agent.temporal_bindings import normalize_request

    request = normalize_request(
        submission_request(
            AgentDefinition(
                AgentSpec("a", "answer"),
                AgentBindingDescriptor(provider=BindingSelection.ref("chosen", "1")),
            ),
            "task",
        )
    )
    with pytest.raises(AuthorizationDenied):
        TemporalRunState("run", asdict(Scope("other", "owner")), "s", request, runtime.manifest)


def test_selected_context_and_knowledge_reach_actual_model():
    class Knowledge:
        identity = {"kind": "fixture-knowledge", "version": "1"}
        limit, max_chars = 2, 2048

        async def references(self, scope, query):
            return [{"label": "selected-evidence", "content": "selected knowledge", "version": "1"}]

        async def validate(self, scope, references):
            assert references[0]["content"] == "selected knowledge"

    class Check(Provider):
        async def complete(self, messages, tools):
            assert "selected knowledge" in str(messages)
            return await super().complete(messages, tools)

    async def run():
        runtime, catalog, _, _ = setup()
        # Construct a new fixed release after adding a component; no mutation of an accepted release.
        catalog.register("knowledge", "kb", "1", Knowledge())
        provider = Check("evidence")
        runtime = TemporalRuntime(
            providers={"default": provider}, tools=ToolRegistry(), binding_catalog=catalog
        )
        from relf_agent.temporal_bindings import normalize_request

        request = normalize_request(
            submission_request(
                AgentDefinition(
                    AgentSpec("a", "answer"),
                    AgentBindingDescriptor(knowledge=BindingSelection.ref("kb", "1")),
                ),
                "task",
            )
        )
        state = TemporalRunState("run", asdict(Scope()), "s", request, runtime.manifest)
        action, value = state.next_operation()
        state.accept_context(action["id"], await runtime.prepare_context(value))
        action, value = state.next_operation()
        state.accept_model(
            action["id"],
            await runtime.complete_model(value, dispatch_guard=lambda r: grant(state, r)),
        )
        assert state.result == {"name": "evidence"}

    asyncio.run(run())


def test_tool_set_cannot_expand_declared_business_grant():
    runtime, catalog, _, _ = setup()
    catalog.register("tool_set", "tools", "1", ["undeclared"])
    runtime = TemporalRuntime(
        providers=runtime.providers, tools=ToolRegistry(), binding_catalog=catalog
    )
    from relf_agent.temporal_bindings import normalize_request

    request = normalize_request(
        submission_request(
            AgentDefinition(
                AgentSpec("a", "answer"),
                AgentBindingDescriptor(tool_set=BindingSelection.ref("tools", "1")),
            ),
            "task",
        )
    )
    with pytest.raises(AuthorizationDenied):
        validate_request(request, runtime.manifest)


def test_binding_can_supply_provider_when_legacy_default_alias_is_unconfigured():
    runtime, catalog, first, second = setup()
    runtime = TemporalRuntime(
        providers={"business": first}, tools=ToolRegistry(), binding_catalog=catalog
    )
    from relf_agent.temporal_bindings import normalize_request

    request = normalize_request(
        submission_request(
            AgentDefinition(
                AgentSpec("a", "answer"),
                AgentBindingDescriptor(provider=BindingSelection.ref("chosen", "1")),
            ),
            "task",
        )
    )
    state = TemporalRunState("run", asdict(Scope()), "s", request, runtime.manifest)
    assert state.step["provider"] in runtime.providers


def test_resource_selectors_are_rejected_without_silent_fallback():
    runtime, _, _, _ = setup()
    from relf_agent.temporal_bindings import normalize_request

    request = normalize_request(
        submission_request(
            AgentDefinition(
                AgentSpec("a", "answer"),
                AgentBindingDescriptor(
                    stage_policy=BindingSelection.ref("facts", "1", selector={"namespace": "other"})
                ),
            ),
            "task",
        )
    )
    with pytest.raises(ValidationError):
        validate_request(request, runtime.manifest)
