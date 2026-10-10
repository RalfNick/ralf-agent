"""Exercise selected components and historical evidence across actual Activity awaits."""

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
    BoundDefinition,
    ContextAssembler,
    InMemoryArtifactStore,
    ManagedContextPipeline,
    ModelResponse,
    Scope,
    ToolRegistry,
    WorkflowSpec,
)
from ralf_agent.temporal_activities import TemporalRuntime
from ralf_agent.temporal_bindings import normalize_request
from ralf_agent.temporal_managed_context import artifact_records
from ralf_agent.temporal_state import TemporalRunState
from ralf_agent.types import submission_request
from tests.test_temporal_memory_bindings import grant


class LabelContext:
    def __init__(self, label):
        self.identity = {"kind": "binding-isolation-context", "label": label}

    def assemble(self, history, references, max_chars):
        return history + [{"role": "user", "content": self.identity["label"]}], self.identity


class EchoProvider:
    identity = {"kind": "binding-isolation-provider", "version": "1"}

    def __init__(self):
        self.seen = []

    async def complete(self, messages, tools):
        self.seen.append(messages[-1]["content"])
        return ModelResponse(output="task")


def state_for(runtime, definition):
    return TemporalRunState(
        "run",
        asdict(Scope()),
        "s",
        normalize_request(submission_request(definition, "task")),
        runtime.manifest,
    )


async def advance(runtime, state):
    action, request = state.next_operation()
    if action["kind"] == "context":
        state.accept_context(action["id"], await runtime.prepare_context(request))
    elif action["kind"] == "managed_context":
        state.accept_managed_context(
            action["id"],
            await runtime.manage_context(request, dispatch_guard=lambda r: grant(state, r)),
        )
    elif action["kind"] == "model":
        state.accept_model(
            action["id"],
            await runtime.complete_model(request, dispatch_guard=lambda r: grant(state, r)),
        )
    else:
        state.accept_tool(action["id"], await runtime.execute_tool(request))


@pytest.mark.parametrize("managed", [False, True])
def test_identical_sequence_steps_use_each_selected_context_after_restore(managed):
    async def run():
        catalog = BindingCatalog(scope=Scope())
        for label, limit in (("A", 256), ("B", 512)):
            builder = (
                ManagedContextPipeline(summary_max_chars=limit) if managed else LabelContext(label)
            )
            catalog.register("context", label, "1", builder)
        provider = EchoProvider()
        runtime = TemporalRuntime(
            providers={"default": provider}, tools=ToolRegistry(), binding_catalog=catalog
        )
        agent = AgentSpec("same", "answer")
        definition = BoundDefinition(
            WorkflowSpec("sequence", [agent, agent]),
            {
                f"sequence/steps/{i}": AgentBindingDescriptor(
                    context=BindingSelection.ref(label, "1")
                )
                for i, label in enumerate(("A", "B"))
            },
        )
        state = state_for(runtime, definition)
        for _ in range(30):
            if state.node == 1:
                break
            await advance(runtime, state)
        assert state.node == 1
        restored = copy.deepcopy(state)
        for _ in range(30):
            if restored.state in {"failed", "succeeded"}:
                break
            await advance(runtime, restored)
        assert restored.state == "succeeded", restored.snapshot()
        if managed:
            assert {key.split(":")[0] for key in restored.managed_context_stages} == {"0", "1"}
        else:
            assert provider.seen == ["A", "B"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "swap",
    ["validate-during-references", "references-during-references", "validate-during-validate"],
)
def test_catalog_knowledge_methods_remain_fixed_across_awaits(swap):
    async def permissive(scope, references):
        return None

    async def replacement(scope, query):
        return []

    class Knowledge:
        identity = {"kind": "binding-isolation-knowledge", "version": "1"}
        limit, max_chars = 2, 2048

        async def references(self, scope, query):
            if swap == "validate-during-references":
                self.validate = permissive
            elif swap == "references-during-references":
                self.references = replacement
            await asyncio.sleep(0)
            return [{"content": "selected evidence"}]

        async def validate(self, scope, references):
            if swap == "validate-during-validate":
                self.validate = permissive
            await asyncio.sleep(0)
            return None

    async def run():
        catalog = BindingCatalog(scope=Scope())
        catalog.register("knowledge", "kb", "1", Knowledge())
        provider = EchoProvider()
        runtime = TemporalRuntime(
            providers={"default": provider}, tools=ToolRegistry(), binding_catalog=catalog
        )
        state = state_for(
            runtime,
            AgentDefinition(
                AgentSpec("a", "answer"),
                AgentBindingDescriptor(knowledge=BindingSelection.ref("kb", "1")),
            ),
        )
        action, request = state.next_operation()
        response = await runtime.prepare_context(request)
        state.accept_context(action["id"], response)
        assert response["ok"] is False, response
        assert response["code"] == "definition_mismatch"
        assert state.state == "failed" and provider.seen == []

    asyncio.run(run())


@pytest.mark.parametrize("next_managed", [False, True])
def test_artifact_queries_keep_original_policy_after_member_switch_and_restore(next_managed):
    from tests.test_composite_data_context import Provider, agent, registry
    from tests.test_managed_data_context import context

    async def run():
        artifacts = InMemoryArtifactStore(backend_id="original-artifacts")
        original = context(artifacts)
        next_builder = (
            context(InMemoryArtifactStore(backend_id="other-artifacts"))
            if next_managed
            else ContextAssembler()
        )
        catalog = BindingCatalog(scope=Scope())
        catalog.register("context", "next", "1", next_builder)
        runtime = TemporalRuntime(
            providers={"default": Provider()},
            tools=registry([]),
            context_builder=original,
            binding_catalog=catalog,
        )
        state = state_for(
            runtime,
            BoundDefinition(
                WorkflowSpec("sequence", [agent(), agent()]),
                {
                    "sequence/steps/1": AgentBindingDescriptor(
                        context=BindingSelection.ref("next", "1")
                    )
                },
            ),
        )
        for _ in range(80):
            if state.node == 1:
                break
            await advance(runtime, state)
        assert state.node == 1, state.snapshot()
        records = artifact_records(copy.deepcopy(state))
        assert records and all(r["status"] == "verified" for r in records)
        for record in records:
            assert record["intent"]["policy"] == original.identity
            assert record["intent"]["reference"]["backend_id"] == "original-artifacts"
        assert artifact_records(state) == records

    asyncio.run(run())
