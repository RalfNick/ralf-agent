import asyncio
import json

import pytest

from relf_agent import AgentSpec, RuntimeBuilder, Scope, load_catalog
from relf_agent.errors import BudgetExceeded


@pytest.mark.parametrize("extension", ["json", "toml"])
def test_indexed_facts_factory_owns_resources_and_restores_original_index_and_run(
    tmp_path, extension
):
    profile = {
        "name": "app",
        "version": "1",
        "providers": {"default": {"adapter": "offline-echo"}},
        "components": {
            "memory_store": {
                "adapter": "indexed-recall-async",
                "config": {
                    "backend": {"adapter": "sqlite", "config": {"path": "facts.sqlite"}},
                    "embedding": {"adapter": "hash", "config": {"dimensions": 8}},
                },
            },
            "recall_planner": {"adapter": "task-text"},
        },
    }
    path = tmp_path / ("runtime." + extension)
    if extension == "json":
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "default": {"name": "app", "version": "1"},
                    "profiles": [profile],
                }
            )
        )
    else:
        path.write_text("""schema_version = 1
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.memory_store]
adapter = "indexed-recall-async"
[profiles.components.memory_store.config.backend]
adapter = "sqlite"
[profiles.components.memory_store.config.backend.config]
path = "facts.sqlite"
[profiles.components.memory_store.config.embedding]
adapter = "hash"
[profiles.components.memory_store.config.embedding.config]
dimensions = 8
[profiles.components.recall_planner]
adapter = "task-text"
""")

    async def run():
        catalog = load_catalog(path)
        builder = RuntimeBuilder(base_dir=tmp_path)
        runtime = await builder.abuild(catalog.default, tmp_path / "runs.sqlite")
        try:
            runtime.memory.put_fact(Scope(), "answer", "preference", "needle", expected_version=0)
            original = await runtime.memory.rebuild(Scope(), "answer")
            assert original["status"] == "ready"
            handle = runtime.submit(AgentSpec("answer", "Answer"), "needle", command_id="same")
            assert (await runtime.drive(handle.run_id)).state == "succeeded"
            action = next(
                a for a in runtime.store.run(handle.run_id)["actions"] if a["kind"] == "model"
            )
            assert [i["key"] for i in action["memory_references"]] == ["preference"]
            assert action["memory_references"][0]["_fact_index"]["build_id"] == original["build_id"]
            manifest = runtime.diagnostics(handle.run_id).manifest
        finally:
            await runtime.aclose()
        restored = await builder.abuild(catalog.default, tmp_path / "runs.sqlite")
        try:
            assert (await restored.memory.rebuild(Scope(), "answer"))["build_id"] == original[
                "build_id"
            ]
            assert (
                restored.submit(AgentSpec("answer", "Answer"), "needle", command_id="same")
                == handle
            )
            assert restored.diagnostics(handle.run_id).manifest == manifest
        finally:
            await restored.aclose()

    asyncio.run(run())


def test_qdrant_factory_indexes_authoritative_facts_and_closes_owned_transport(
    tmp_path, monkeypatch
):
    import httpx

    from relf_agent import ComponentRegistry, RecallQuery, RuntimeProfile
    from tests.test_fact_index import Embedding
    from tests.test_qdrant_adapter import QdrantHTTP

    service = QdrantHTTP(exists=False)
    native = httpx.AsyncClient

    class Client(native):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(service), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setenv("RALF_TEST_FACT_QDRANT_URL", "http://qdrant.invalid")
    registry = ComponentRegistry()
    registry.register("embedding_provider", "fixture", lambda config, context: Embedding())
    selected = RuntimeProfile(
        "indexed",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "memory_store": {
                "adapter": "indexed-recall-async",
                "config": {
                    "embedding": {"adapter": "fixture"},
                    "index": {
                        "adapter": "qdrant",
                        "config": {
                            "url_env": "RALF_TEST_FACT_QDRANT_URL",
                            "backend_id": "qdrant:corpus",
                            "collection": "tests",
                            "dimensions": 2,
                            "initialize": True,
                        },
                    },
                },
            },
        },
    )

    async def run():
        runtime = await RuntimeBuilder(registry=registry, base_dir=tmp_path).abuild(
            selected, tmp_path / "runs.sqlite"
        )
        transport = runtime.memory.index._client
        try:
            runtime.memory.put_fact(Scope(), "facts", "one", "background", expected_version=0)
            runtime.memory.put_fact(Scope(), "facts", "target", "needle", expected_version=0)
            receipt = await runtime.memory.rebuild(Scope(), "facts")
            assert receipt["status"] == "ready" and receipt["indexed"] == 2
            page = await runtime.memory.recall(
                Scope(), "facts", RecallQuery(text="needle", max_items=1)
            )
            assert [i["key"] for i in page.items] == ["target"]
            assert page.items[0]["value"] == "needle" and page.items[0]["version"] == 1
        finally:
            await runtime.aclose()
        assert transport.is_closed

    asyncio.run(run())


def test_configured_record_allowance_stops_before_index_publication(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default": {"name": "app", "version": "1"},
                "profiles": [
                    {
                        "name": "app",
                        "version": "1",
                        "providers": {"default": {"adapter": "offline-echo"}},
                        "components": {
                            "memory_store": {
                                "adapter": "indexed-recall-async",
                                "config": {"max_records": 1},
                            }
                        },
                    }
                ],
            }
        )
    )

    async def run():
        runtime = await RuntimeBuilder(base_dir=tmp_path).abuild(
            load_catalog(path).default, tmp_path / "runs.sqlite"
        )
        try:
            runtime.memory.put_fact(Scope(), "facts", "one", "needle", expected_version=0)
            runtime.memory.put_fact(Scope(), "facts", "two", "needle", expected_version=0)
            with pytest.raises(BudgetExceeded):
                await runtime.memory.rebuild(Scope(), "facts")
        finally:
            await runtime.aclose()

    asyncio.run(run())
