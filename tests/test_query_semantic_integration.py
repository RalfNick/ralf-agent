import asyncio

from relf_agent import (
    AgentBindingDescriptor,
    AgentSpec,
    BindingSelection,
    BoundDefinition,
    ComponentRegistry,
    GraphNode,
    GraphWorkflowSpec,
    ModelResponse,
    RuntimeBuilder,
    Scope,
    SemanticMemoryStore,
    TaskRecallPlanner,
    recommended_profile,
)
from tests.test_h3_semantic_http import synonym_endpoint  # noqa: F401


def test_real_embedding_protocol_and_scoped_fact_bindings_in_graph(tmp_path, request):
    from .semantic_fixture import Embedding, facts
    from .test_binding_execution import bound_catalog, choice, engine

    async def graph():
        catalog = bound_catalog()
        backend = facts()
        memory = SemanticMemoryStore(backend, Embedding())
        catalog.register("facts", "semantic", "1", memory)

        class Reader:
            identity = {"kind": "semantic-graph", "version": "1"}

            async def complete(self, messages, tools):
                assert "automobile servicing" in str(messages)
                return ModelResponse(output="done")

        catalog.register("provider", "semantic", "1", Reader())
        graph = GraphWorkflowSpec(
            "graph", [GraphNode("read", agent=AgentSpec("assistant", "Use facts"))]
        )
        bound = BoundDefinition(
            graph,
            {
                "graph/nodes/read": AgentBindingDescriptor(
                    facts=choice("semantic"),
                    provider=choice("semantic"),
                    session=BindingSelection.disabled(),
                )
            },
        )
        with engine(
            tmp_path / "graph.sqlite", catalog, recall_planner=TaskRecallPlanner()
        ) as runtime:
            run = runtime.submit(bound, "vehicle", command_id="graph")
            done = await runtime.drive(run.run_id)
            assert done.state == "succeeded", done.error

    asyncio.run(graph())
    endpoint, seen = request.getfixturevalue("synonym_endpoint")

    class Reader:
        identity = {"kind": "semantic-http-reader", "version": "1"}

        async def complete(self, messages, tools):
            assert "automobile servicing" in str(messages)
            return ModelResponse(output="done")

    registry = ComponentRegistry()
    registry.register("provider", "reader", lambda c, ctx: Reader())
    selected = recommended_profile(
        "semantic-memory",
        provider={"adapter": "reader"},
        embedding={
            "type": "openai",
            "config": {
                "model": "fixture",
                "dimensions": 2,
                "base_url": endpoint,
                "anonymous": True,
            },
        },
    )

    async def http():
        instance = await RuntimeBuilder(registry).abuild(selected, tmp_path / "http.sqlite")
        try:
            instance.memory.put_fact(
                Scope(), "assistant", "a", "maritime transport", expected_version=0
            )
            instance.memory.put_fact(
                Scope(), "assistant", "b", "automobile servicing", expected_version=0
            )
            run = instance.submit(AgentSpec("assistant", "Use facts"), "car", command_id="http")
            done = await instance.drive(run.run_id)
            assert done.state == "succeeded", done.error
            refs = instance.store.run(run.run_id)["actions"][0]["memory_references"]
            assert refs[0]["key"] == "b"
            assert seen and "assistant" not in str(seen[0]["input"])
        finally:
            await instance.aclose()

    asyncio.run(http())


def test_semantic_fact_source_changed_during_http_cannot_reach_model(tmp_path):
    import httpx

    from relf_agent import LocalEngine, OpenAIEmbeddingProvider, SQLiteStore, ToolRegistry

    from .semantic_fixture import facts

    async def run():
        backend = facts()

        def changed(request):
            backend.put_fact(Scope(), "assistant", "b", "changed", expected_version=1)
            texts = __import__("json").loads(request.content)["input"]
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "fixture",
                    "data": [
                        {"object": "embedding", "index": i, "embedding": [1, 0]}
                        for i in range(len(texts))
                    ],
                },
            )

        class Forbidden:
            identity = {"kind": "forbidden", "version": "1"}

            async def complete(self, *args):
                raise AssertionError("Stale Facts reached model")

        async with httpx.AsyncClient(transport=httpx.MockTransport(changed)) as client:
            embed = OpenAIEmbeddingProvider(
                "fixture", dimensions=2, client=client, base_url="http://rank.test/v1"
            )
            with LocalEngine(
                SQLiteStore(tmp_path / "changed.sqlite"),
                providers={"default": Forbidden()},
                tools=ToolRegistry(),
                memory_store=SemanticMemoryStore(backend, embed),
                recall_planner=TaskRecallPlanner(),
            ) as runtime:
                handle = runtime.submit(
                    AgentSpec("assistant", "Use facts"), "car", command_id="changed"
                )
                done = await runtime.drive(handle.run_id)
                assert done.state == "failed" and done.error["code"] == "validation_error"
            await embed.aclose()

    asyncio.run(run())
