import asyncio

import pytest

from ralf_agent import (
    InMemoryMemory,
    ModelQueryTransform,
    ModelResponse,
    RecallQuery,
    Scope,
    SemanticMemoryStore,
    ToolCall,
)
from ralf_agent.errors import DefinitionMismatch, ValidationError
from tests.semantic_fixture import Embedding, facts
from tests.test_model_query import QueryModel


@pytest.mark.parametrize(
    "response",
    [
        ModelResponse(output={"queries": []}),
        ModelResponse(output={"queries": ["car", "car"]}),
        ModelResponse(output={"queries": ["x" * 4097]}),
        ModelResponse(output="not JSON"),
        ModelResponse(),
        ModelResponse(tool_calls=[ToolCall("write", {}, "call")]),
    ],
)
def test_rejected_model_fact_queries_do_not_read_or_validate_source(response):
    async def run():
        backend = facts()
        calls = []
        recall, validate = backend.recall, backend.validate_facts

        def counted_recall(*args):
            calls.append("recall")
            return recall(*args)

        def counted_validate(*args):
            calls.append("validate")
            return validate(*args)

        backend.recall, backend.validate_facts = counted_recall, counted_validate
        model = QueryModel(response)
        memory = SemanticMemoryStore(backend, Embedding(), ModelQueryTransform(model))
        with pytest.raises(ValidationError):
            await memory.recall(Scope(), "assistant", RecallQuery(text="car"))
        assert model.calls == 1 and calls == []

    asyncio.run(run())


@pytest.mark.parametrize("change", ["provider", "method", "identity", "messages", "tools"])
def test_model_fact_provider_drift_rejects_before_source_access(change):
    async def run():
        calls = []
        backend = facts()
        original = backend.recall

        def counted(*args):
            calls.append("source")
            return original(*args)

        backend.recall = counted
        transform = None

        class Changed(QueryModel):
            async def complete(self, messages, tools):
                if change == "provider":
                    transform.provider = QueryModel()
                elif change == "method":
                    self.complete = QueryModel().complete
                elif change == "identity":
                    self.identity = {"kind": "changed"}
                elif change == "messages":
                    messages[1]["content"] = "changed"
                else:
                    tools.append({"name": "write"})
                await asyncio.sleep(0)
                return ModelResponse(output={"queries": ["automobile"]})

        transform = ModelQueryTransform(Changed())
        memory = SemanticMemoryStore(backend, Embedding(), transform)
        with pytest.raises((ValidationError, DefinitionMismatch)):
            await memory.recall(Scope(), "assistant", RecallQuery(text="car"))
        assert calls == []

    asyncio.run(run())


def test_model_fact_query_precedes_empty_candidate_lookup_without_embedding():
    async def run():
        model = QueryModel()

        class NoEmbedding(Embedding):
            async def embed(self, texts):
                raise AssertionError("Empty Facts must not dispatch embedding")

        embedding = NoEmbedding()
        memory = SemanticMemoryStore(InMemoryMemory(), embedding, ModelQueryTransform(model))
        page = await memory.recall(Scope(), "assistant", RecallQuery(text="car"))
        assert page.items == [] and model.calls == 1

    asyncio.run(run())
