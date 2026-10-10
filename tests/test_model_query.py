import asyncio

import pytest

from ralf_agent import (
    Document,
    InMemoryKnowledgeStore,
    LexicalRetriever,
    ModelResponse,
    QueryTransformRetriever,
    RetrievalQuery,
    Scope,
    ToolCall,
)
from ralf_agent.errors import DefinitionMismatch, ProviderError, ValidationError


class QueryModel:
    identity = {"kind": "model-query-fixture", "version": "1"}

    def __init__(self, response=None):
        self.response = (
            ModelResponse(output={"queries": ["automobile"]}) if response is None else response
        )
        self.calls = 0
        self.closed = False
        self.close_calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        assert tools == []
        assert [m["role"] for m in messages] == ["system", "user"]
        assert "queries" in messages[0]["content"] and "car" in messages[1]["content"]
        return self.response

    async def aclose(self):
        self.closed = True
        self.close_calls += 1


def test_model_query_retrieves_original_synonym_bodies_without_tools_or_closing_provider():
    from ralf_agent import ModelQueryTransform

    async def run():
        store = InMemoryKnowledgeStore()
        store.put(Scope(), "docs", Document("a", "car"), expected_version=0)
        store.put(Scope(), "docs", Document("b", "automobile"), expected_version=0)
        provider = QueryModel()
        transform = ModelQueryTransform(provider)
        result = await QueryTransformRetriever(LexicalRetriever(store), transform).retrieve(
            Scope(), "docs", RetrievalQuery("car")
        )
        assert [(v.document_id, v.text, v.version) for v in result.items] == [
            ("a", "car", 1),
            ("b", "automobile", 1),
        ]
        assert provider.calls == 1 and not provider.closed
        assert "car" not in str(transform.identity)

    asyncio.run(run())


@pytest.mark.parametrize(
    "output",
    [
        None,
        "",
        " ",
        "no JSON",
        [],
        {},
        {"queries": []},
        {"queries": ["x", "x"]},
        {"queries": ["x", "y", "z"]},
        {"queries": [" "]},
        {"queries": [1]},
        {"queries": ["x" * 4097]},
        {"queries": ["\ud800"]},
        {"queries": ["x"], "extra": True},
        '{"queries":["x"],"queries":["y"]}',
        " " * 32769,
    ],
)
def test_invalid_model_query_never_silently_falls_back(output):
    from ralf_agent import ModelQueryTransform

    async def run():
        provider = QueryModel(ModelResponse(output=output))
        with pytest.raises(ValidationError):
            await ModelQueryTransform(provider).transform("car")
        assert provider.calls == 1

    asyncio.run(run())


def test_model_tool_proposal_is_rejected_without_execution():
    from ralf_agent import ModelQueryTransform

    async def run():
        response = ModelResponse(
            output={"queries": ["automobile"]}, tool_calls=(ToolCall("write", {}),)
        )
        with pytest.raises(ValidationError):
            await ModelQueryTransform(QueryModel(response)).transform("car")

    asyncio.run(run())


def test_json_model_queries_preserve_original_once_and_explicit_rewrite_only_policy():
    from ralf_agent import ModelQueryTransform

    async def run():
        provider = QueryModel(ModelResponse(output='{"queries":["car","automobile"]}'))
        assert await ModelQueryTransform(provider).transform("car") == ("car", "automobile")
        provider.response = ModelResponse(output={"queries": ["automobile"]})
        assert await ModelQueryTransform(provider, include_original=False).transform("car") == (
            "automobile",
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "options",
    [
        {"max_queries": True},
        {"max_queries": 0},
        {"max_queries": 5},
        {"max_queries": 4},
        {"include_original": 1},
        {"instructions": None},
        {"instructions": "x" * 4097},
        {"instructions": "\ud800"},
    ],
)
def test_invalid_model_query_options_reject_before_provider_call(options):
    from ralf_agent import ModelQueryTransform

    provider = QueryModel()
    with pytest.raises(ValidationError):
        ModelQueryTransform(provider, **options)
    assert provider.calls == 0


@pytest.mark.parametrize("change", ["provider", "method", "identity", "messages", "tools"])
def test_provider_or_argument_drift_during_model_await_is_rejected(change):
    from ralf_agent import ModelQueryTransform

    async def run():
        transform = None

        class Mutating(QueryModel):
            async def complete(self, messages, tools):
                if change == "provider":
                    transform.provider = QueryModel()
                elif change == "method":
                    self.complete = QueryModel().complete
                elif change == "identity":
                    self.identity = {"kind": "changed"}
                elif change == "messages":
                    messages[1]["content"] = "replacement"
                else:
                    tools.append({"name": "write"})
                await asyncio.sleep(0)
                return ModelResponse(output={"queries": ["automobile"]})

        transform = ModelQueryTransform(Mutating())
        with pytest.raises((DefinitionMismatch, ValidationError)):
            await transform.transform("car")

    asyncio.run(run())


def test_cancelled_model_query_finishes_awaited_provider_and_cannot_dispatch_retrieval():
    from ralf_agent import ModelQueryTransform

    async def run():
        started, finished = asyncio.Event(), asyncio.Event()

        class Pending(QueryModel):
            async def complete(self, messages, tools):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    finished.set()

        task = asyncio.create_task(ModelQueryTransform(Pending()).transform("car"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(run())


def test_model_query_requires_async_provider_and_preserves_typed_failure():
    from ralf_agent import ModelQueryTransform

    class Sync:
        identity = {"kind": "sync"}

        def complete(self, messages, tools):
            return ModelResponse(output={"queries": ["x"]})

    with pytest.raises(ValidationError):
        ModelQueryTransform(Sync())

    async def run():
        class Failed(QueryModel):
            async def complete(self, messages, tools):
                raise ProviderError("unavailable")

        with pytest.raises(ProviderError):
            await ModelQueryTransform(Failed()).transform("car")

    asyncio.run(run())
