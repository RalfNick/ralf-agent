"""Facts are selected by the host and accepted by the original Temporal state."""

import asyncio
import copy
from dataclasses import asdict

import pytest

from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    FactsBindingResource,
    InMemoryMemory,
    ManagedContextPipeline,
    ModelResponse,
    Scope,
    ToolRegistry,
)
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request
from tests.test_temporal_binding_isolation import advance


class Provider:
    identity = {"kind": "temporal-facts-test", "version": "1"}

    def __init__(self):
        self.messages = []

    async def complete(self, messages, tools):
        self.messages.append(copy.deepcopy(messages))
        return ModelResponse(output="answer")


def setup(managed=False):
    scope = Scope("facts", "alice")
    memory = InMemoryMemory(backend_id="facts-source")
    memory.put_fact(scope, "allowed", "preference", "likes tea", expected_version=0)
    memory.put_fact(scope, "private", "secret", "hidden", expected_version=0)
    memory.put_fact(Scope("facts", "bob"), "allowed", "secret", "foreign", expected_version=0)
    catalog = BindingCatalog(scope=scope)
    catalog.register(
        "facts",
        "personal",
        "1",
        FactsBindingResource(memory, namespaces=("allowed",), default_namespace="allowed"),
    )
    provider = Provider()
    runtime = TemporalRuntime(
        providers={"default": provider},
        tools=ToolRegistry(),
        binding_catalog=catalog,
        context_builder=ManagedContextPipeline() if managed else None,
    )
    definition = AgentDefinition(
        AgentSpec("different-logical-name", "answer"),
        AgentBindingDescriptor(
            facts=BindingSelection.ref("personal", "1", selector={"namespace": "allowed"})
        ),
    )
    state = TemporalRunState(
        "run",
        asdict(scope),
        "session",
        normalize_request(submission_request(definition, "task")),
        runtime.manifest,
    )
    return runtime, state, memory, provider, scope


@pytest.mark.parametrize("managed", [False, True])
def test_scoped_facts_are_adopted_once_and_survive_restore(managed):
    async def run():
        runtime, state, memory, provider, scope = setup(managed)
        for _ in range(12):
            if state.context_snapshot is not None:
                break
            await advance(runtime, state)
        assert state.context_snapshot is not None, state.snapshot()
        snapshot = copy.deepcopy(state.context_snapshot)
        assert snapshot["facts"][0]["value"] == "likes tea"
        assert snapshot["facts"][0]["_facts_binding"]["namespace"] == "allowed"
        restored = copy.deepcopy(state)
        await advance(runtime, restored)
        assert restored.state == "succeeded", restored.snapshot()
        assert restored.context_snapshot == snapshot
        assert len(provider.messages) == 1
        payload = str(provider.messages[0])
        assert "likes tea" in payload and "hidden" not in payload and "foreign" not in payload
        memory.put_fact(scope, "allowed", "preference", "likes coffee", expected_version=1)
        assert restored.result == "answer"  # completed response remains historical evidence

    asyncio.run(run())


@pytest.mark.parametrize("managed", [False, True])
def test_changed_facts_block_fresh_model_dispatch(managed):
    async def run():
        runtime, state, memory, provider, scope = setup(managed)
        for _ in range(12):
            if state.context_snapshot is not None:
                break
            await advance(runtime, state)
        assert state.context_snapshot is not None
        memory.put_fact(scope, "allowed", "preference", "likes coffee", expected_version=1)
        await advance(runtime, copy.deepcopy(state))
        assert provider.messages == []

    asyncio.run(run())


def test_foreign_scope_and_ungranted_namespace_are_refused():
    from ralf_agent.errors import AuthorizationDenied
    from ralf_agent.temporal_state import validate_request

    runtime, state, _, _, _ = setup()
    request = copy.deepcopy(state.request)
    request["agent_bindings"]["agent"]["facts"]["selector"] = {"namespace": "private"}
    with pytest.raises(AuthorizationDenied):
        validate_request(request, runtime.manifest)
    with pytest.raises(AuthorizationDenied):
        TemporalRunState(
            "other", asdict(Scope("facts", "bob")), "s", state.request, runtime.manifest
        )


@pytest.mark.parametrize("mutation", ["method", "backend_id", "resource"])
def test_source_change_during_recall_is_not_adopted(mutation):
    async def run():
        runtime, state, memory, provider, _ = setup()
        original = memory.recall

        # Register the instrumented real method before fixing the worker release.
        async def change(*args):
            page = original(*args)
            if mutation == "method":
                memory.recall = original
            elif mutation == "backend_id":
                memory.backend_id = "replaced"
            else:
                resource = runtime.binding_catalog._entries[("facts", "personal", "1")][0]
                object.__setattr__(resource, "backend", InMemoryMemory(backend_id="facts-source"))
            await asyncio.sleep(0)
            return page

        memory.recall = change
        catalog = BindingCatalog(scope=Scope("facts", "alice"))
        catalog.register(
            "facts",
            "personal",
            "1",
            FactsBindingResource(memory, namespaces=("allowed",), default_namespace="allowed"),
        )
        runtime = TemporalRuntime(
            providers={"default": provider}, tools=ToolRegistry(), binding_catalog=catalog
        )
        state = TemporalRunState("run", state.scope, "s", state.request, runtime.manifest)
        await advance(runtime, state)
        assert state.state == "failed" and state.error["code"] == "definition_mismatch"
        assert state.context_snapshot is None and provider.messages == []

    asyncio.run(run())


def test_knowledge_and_facts_have_independent_validation_formats():
    class Knowledge:
        identity = {"kind": "separate-knowledge-test", "version": "1"}
        limit, max_chars = 1, 1024

        async def references(self, scope, query):
            return [{"content": "knowledge", "version": "K1"}]

        async def validate(self, scope, references):
            assert references == [{"content": "knowledge", "version": "K1"}]

    async def run():
        runtime, state, _, provider, _ = setup(True)
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            binding_catalog=runtime.binding_catalog,
            knowledge=Knowledge(),
            context_builder=ManagedContextPipeline(),
        )
        state = TemporalRunState("run", state.scope, "s", state.request, runtime.manifest)
        for _ in range(12):
            if state.state in {"succeeded", "failed"}:
                break
            await advance(runtime, state)
        assert state.state == "succeeded", state.snapshot()
        assert "knowledge" in str(provider.messages) and "likes tea" in str(provider.messages)

    asyncio.run(run())


def test_task_planner_and_disabled_selection_use_original_facts_port():
    from ralf_agent import TaskRecallPlanner

    async def run():
        scope, memory, provider = Scope(), InMemoryMemory(), Provider()
        memory.put_fact(scope, "a", "tea", "tea preference", expected_version=0)
        memory.put_fact(scope, "a", "coffee", "coffee preference", expected_version=0)
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            facts=memory,
            recall_planner=TaskRecallPlanner(),
        )
        state = TemporalRunState(
            "run",
            asdict(scope),
            "s",
            submission_request(AgentSpec("a", "answer"), "tea"),
            runtime.manifest,
        )
        await advance(runtime, state)
        assert [f["key"] for f in state.context_snapshot["facts"]] == ["tea"]
        await advance(runtime, state)
        assert state.state == "succeeded"
        disabled = AgentDefinition(
            AgentSpec("a", "answer"), AgentBindingDescriptor(facts=BindingSelection.disabled())
        )
        state = TemporalRunState(
            "disabled",
            asdict(scope),
            "s",
            normalize_request(submission_request(disabled, "tea")),
            runtime.manifest,
        )
        await advance(runtime, state)
        assert state.state == "succeeded" and "tea preference" not in str(provider.messages[-1])

    asyncio.run(run())


def test_multiple_pages_keep_cursor_query_and_total_budget():
    from ralf_agent import MemoryRecallPolicy, RecallQuery

    async def run():
        memory, provider, scope = InMemoryMemory(), Provider(), Scope()
        for i, value in enumerate(("hit", "noise", "hit", "noise")):
            memory.put_fact(scope, "a", str(i), value, expected_version=0)
        runtime = TemporalRuntime(
            providers={"default": provider},
            tools=ToolRegistry(),
            facts=memory,
            recall_policy=MemoryRecallPolicy(
                facts=RecallQuery(max_items=4, max_chars=1600, scan_limit=4, text="hit"),
                max_pages=2,
            ),
        )
        state = TemporalRunState(
            "r",
            asdict(scope),
            "s",
            submission_request(AgentSpec("a", "answer"), "task"),
            runtime.manifest,
        )
        await advance(runtime, state)
        assert state.state != "failed", state.snapshot()
        assert [item["key"] for item in state.context_snapshot["facts"]] == ["0", "2"]
        assert sum(page["scanned"] for page in state.context_snapshot["facts_recall"]["pages"]) == 4

    asyncio.run(run())


@pytest.mark.parametrize("change", ["prefix", "client", "pool", "database"])
def test_native_redis_actual_resource_is_fixed_without_serializing_credentials(change):
    redis = pytest.importorskip("redis.asyncio")
    from ralf_agent import RedisMemory
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        client = redis.Redis.from_url("redis://localhost:6379/0")
        replacement = redis.Redis.from_url("redis://localhost:6379/1")
        try:
            source = RedisMemory(client, backend_id="redis-facts", prefix="original")
            runtime = TemporalRuntime(
                providers={"default": Provider()}, tools=ToolRegistry(), facts=source
            )
            if change == "prefix":
                source._prefix = "other"
            elif change == "client":
                source._client = replacement
            elif change == "pool":
                client.connection_pool = replacement.connection_pool
            else:
                client.connection_pool.connection_kwargs["db"] = 1
            with pytest.raises(DefinitionMismatch):
                runtime.validate_release()
        finally:
            await client.aclose()
            await replacement.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("field", ["facts", "knowledge_references", "facts_recall"])
def test_managed_finalize_cannot_reclassify_original_facts(field):
    from ralf_agent.errors import ValidationError

    async def run():
        runtime, state, _, _, _ = setup(True)
        await advance(runtime, state)
        action, request = state.next_operation()
        assert action["phase"] == "finalize"
        response = await runtime.manage_context(request)
        response[field] = (
            response["references"]
            if field == "knowledge_references"
            else []
            if field == "facts"
            else {}
        )
        with pytest.raises(ValidationError):
            state.accept_managed_context(action["id"], response)

    asyncio.run(run())


def test_cancel_during_final_facts_validation_denies_dispatch():
    from tests.test_temporal_memory_bindings import grant

    async def run():
        scope, provider = Scope(), Provider()
        state = None

        class Memory(InMemoryMemory):
            calls = 0

            async def validate_facts(self, *args):
                self.calls += 1
                result = super().validate_facts(*args)
                if self.calls == 3:
                    state.command("cancel", {"kind": "cancel", "scope": state.scope})
                await asyncio.sleep(0)
                return result

        memory = Memory()
        memory.put_fact(scope, "a", "one", "evidence", expected_version=0)
        runtime = TemporalRuntime(
            providers={"default": provider}, tools=ToolRegistry(), facts=memory
        )
        state = TemporalRunState(
            "run",
            asdict(scope),
            "s",
            submission_request(AgentSpec("a", "answer"), "task"),
            runtime.manifest,
        )
        await advance(runtime, state)
        action, request = state.next_operation()
        response = await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r))
        assert response["ok"] is False and response["dispatched"] is False
        assert state.state == "cancelled" and provider.messages == []

    asyncio.run(run())


def test_unknown_facts_protocol_is_rejected_before_acceptance():
    from ralf_agent.errors import DefinitionMismatch
    from ralf_agent.temporal_state import validate_manifest

    runtime, _, _, _, _ = setup()
    manifest = runtime.manifest
    manifest["facts_protocol"] = 2
    with pytest.raises(DefinitionMismatch):
        validate_manifest(manifest)


def test_plain_context_cannot_reclassify_facts_as_knowledge():
    from ralf_agent.errors import ValidationError

    async def run():
        runtime, state, _, _, _ = setup()
        action, request = state.next_operation()
        response = await runtime.prepare_context(request)
        response["knowledge_references"] = response["facts"]
        response["facts"] = []
        with pytest.raises(ValidationError):
            state.accept_context(action["id"], response)

    asyncio.run(run())
