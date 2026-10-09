import asyncio
import copy
import importlib
import importlib.util
import json
import math
import os
import time
import uuid

import httpx
import pytest

from ralf_agent.errors import MemoryBackendError, ValidationError
from ralf_agent.retrieval import Document, InMemoryKnowledgeStore, RetrievalQuery
from ralf_agent.types import Scope
from ralf_agent.vector import VectorEntry, VectorHit, VectorRetriever


def adapter():
    name = "ralf_agent.qdrant"
    assert importlib.util.find_spec(name) is not None, "Missing QdrantVectorIndex adapter"
    return importlib.import_module(name).QdrantVectorIndex


def construct(**kwargs):
    config = {
        "url": "http://qdrant.invalid:6333",
        "collection": "tests",
        "dimensions": 2,
        "backend_id": "qdrant:test",
    }
    config.update(kwargs)
    return adapter()(**config)


def envelope(result):
    return {"result": result, "status": "ok", "time": 0.001}


class QdrantHTTP:
    """External HTTP fixture; the adapter and knowledge authority stay real."""

    def __init__(self, *, exists=True, vectors=None):
        self.exists = exists
        self.vectors = vectors if vectors is not None else {"size": 2, "distance": "Cosine"}
        self.requests = []
        self.points = {}
        self.mutation_result = {"operation_id": 1, "status": "completed"}
        self.query_result = None

    def __call__(self, request):
        body = json.loads(request.content) if request.content else None
        self.requests.append((request, body))
        path = request.url.path
        if path == "/collections/tests" and request.method == "GET":
            if not self.exists:
                return httpx.Response(404, json={"status": {"error": "not found"}})
            result = {
                "status": "green",
                "optimizer_status": "ok",
                "points_count": len(self.points),
                "config": {"params": {"vectors": self.vectors}},
            }
        elif path == "/collections/tests" and request.method == "PUT":
            self.exists = True
            self.vectors = body["vectors"]
            result = True
        elif path == "/collections/tests/points" and request.method == "PUT":
            for point in body["points"]:
                self.points[point["id"]] = copy.deepcopy(point)
            result = self.mutation_result
        elif path == "/collections/tests/points/query" and request.method == "POST":
            if self.query_result is not None:
                # Raw JSON permits nonfinite values to test defensive decoding.
                return httpx.Response(200, content=json.dumps(envelope(self.query_result)).encode())
            points = []
            for point in self.points.values():
                if all(
                    point["payload"].get(condition["key"]) == condition["match"]["value"]
                    for condition in body["filter"]["must"]
                ):
                    points.append(
                        {
                            "id": point["id"],
                            "version": 0,
                            "score": sum(
                                a * b for a, b in zip(point["vector"], body["query"], strict=True)
                            ),
                            "payload": copy.deepcopy(point["payload"]),
                        }
                    )
            points.sort(key=lambda point: -point["score"])
            result = {"points": points[: body["limit"]]}
        elif path == "/collections/tests/points/delete" and request.method == "POST":
            for point_id, point in tuple(self.points.items()):
                if all(
                    point["payload"].get(condition["key"]) == condition["match"]["value"]
                    for condition in body["filter"]["must"]
                ):
                    del self.points[point_id]
            result = self.mutation_result
        else:
            raise AssertionError(f"Unexpected adapter request: {request.method} {path}")
        return httpx.Response(200, json=envelope(result))


@pytest.mark.parametrize("identity", [None, "", "  ", 123, False])
def test_backend_identity_is_explicit_nonempty_text(identity):
    with pytest.raises(ValidationError):
        construct(backend_id=identity)


@pytest.mark.parametrize(
    "config",
    [
        {"url": "ftp://qdrant.invalid"},
        {"url": "http://secret:password@qdrant.invalid"},
        {"url": "http://qdrant.invalid/?api-key=secret"},
        {"url": "http://qdrant.invalid/#secret"},
        {"url": "http:///"},
        {"url": " http://qdrant.invalid"},
        {"url": None},
        {"collection": ""},
        {"collection": "  "},
        {"dimensions": 0},
        {"dimensions": True},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"timeout": float("nan")},
        {"timeout": True},
        {"api_key": "  "},
        {"api_key": 123},
        {"client": object()},
    ],
)
def test_configuration_rejected_before_network_or_client_creation(config, monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("Invalid configuration allocated a client")

    if importlib.util.find_spec("ralf_agent.qdrant") and "client" not in config:
        module = importlib.import_module("ralf_agent.qdrant")
        monkeypatch.setattr(module.httpx, "AsyncClient", unexpected_client)
    with pytest.raises(ValidationError):
        construct(**config)


@pytest.mark.parametrize(
    "field", ["backend_id", "dimensions", "collection", "url", "timeout", "api_key", "identity"]
)
def test_public_configuration_cannot_change_after_construction(field):
    async def scenario():
        index = construct()
        try:
            with pytest.raises(AttributeError):
                setattr(index, field, "changed")
            identity = index.identity
            identity["dimensions"] = 999
            assert index.identity["dimensions"] == 2
            assert "api_key" not in index.identity
        finally:
            await index.aclose()

    asyncio.run(scenario())


def test_initialize_creates_missing_cosine_collection_and_reads_it_back():
    async def scenario():
        service = QdrantHTTP(exists=False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client, api_key="credential", timeout=1.25)
            await index.initialize()
            assert [request.method for request, _ in service.requests] == ["GET", "PUT", "GET"]
            assert service.requests[1][1] == {"vectors": {"size": 2, "distance": "Cosine"}}
            assert all(
                request.headers["api-key"] == "credential" for request, _ in service.requests
            )
            assert all(
                request.extensions["timeout"]["read"] == 1.25 for request, _ in service.requests
            )
            await index.aclose()
            assert not client.is_closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "vectors",
    [
        {"size": 3, "distance": "Cosine"},
        {"size": 2, "distance": "Dot"},
        {"named": {"size": 2, "distance": "Cosine"}},
        {"size": True, "distance": "Cosine"},
        None,
    ],
)
def test_initialize_rejects_incompatible_or_malformed_collection_without_replacing(vectors):
    async def scenario():
        service = QdrantHTTP()
        service.vectors = vectors
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client)
            with pytest.raises((ValidationError, MemoryBackendError)):
                await index.initialize()
            assert [request.method for request, _ in service.requests] == ["GET"]
            with pytest.raises(ValidationError):
                await index.search(Scope(), "n", [1, 0], limit=1)
            await index.aclose()

    asyncio.run(scenario())


def test_initialize_without_create_leaves_missing_collection_untouched():
    async def scenario():
        service = QdrantHTTP(exists=False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client)
            with pytest.raises(MemoryBackendError):
                await index.initialize(create=False)
            assert len(service.requests) == 1
            assert not service.exists

    asyncio.run(scenario())


@pytest.mark.parametrize("result", [None, False, {}, {"config": {"params": {}}}])
def test_malformed_collection_response_never_triggers_creation(result):
    async def scenario():
        methods = []

        def handler(request):
            methods.append(request.method)
            return httpx.Response(200, json=envelope(result))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            index = construct(client=client)
            with pytest.raises(MemoryBackendError):
                await index.initialize()
            assert methods == ["GET"]

    asyncio.run(scenario())


@pytest.mark.parametrize("created", [False, None, {}, {"status": "acknowledged"}])
def test_incomplete_collection_creation_cannot_enable_operations(created):
    async def scenario():
        def handler(request):
            if request.method == "GET":
                return httpx.Response(404, json={"status": {"error": "not found"}})
            return httpx.Response(200, json=envelope(created))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            index = construct(client=client)
            with pytest.raises(MemoryBackendError):
                await index.initialize()
            with pytest.raises(ValidationError):
                await index.search(Scope(), "n", [1, 0], limit=1)

    asyncio.run(scenario())


def test_mutation_awaits_completed_response_and_cancellation_propagates():
    async def scenario():
        service = QdrantHTTP()
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(request):
            if request.method == "PUT":
                entered.set()
                await release.wait()
            return service(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            index = construct(client=client)
            await index.initialize()
            entry = VectorEntry("c", "d", 1, "x", [1, 0])
            pending = asyncio.create_task(index.upsert(Scope(), "n", [entry]))
            await entered.wait()
            assert not pending.done()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert service.points == {}
            entered.clear()
            pending = asyncio.create_task(index.upsert(Scope(), "n", [entry]))
            await entered.wait()
            assert not pending.done()
            release.set()
            await pending
            assert (await index.search(Scope(), "n", [1, 0], limit=1))[0].chunk_id == "c"

    asyncio.run(scenario())


def test_close_during_initialize_cannot_reopen_index():
    async def scenario():
        service = QdrantHTTP()
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(request):
            entered.set()
            await release.wait()
            return service(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            index = construct(client=client)
            pending = asyncio.create_task(index.initialize())
            await entered.wait()
            await index.aclose()
            release.set()
            with pytest.raises(ValidationError):
                await pending
            with pytest.raises(ValidationError):
                await index.search(Scope(), "n", [1, 0], limit=1)
            assert not client.is_closed

    asyncio.run(scenario())


def test_explicit_initialization_and_open_lifetime_are_required():
    async def scenario():
        service = QdrantHTTP()
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client)
            entry = VectorEntry("c", "d", 1, "digest", [1, 0])
            with pytest.raises(ValidationError):
                await index.upsert(Scope(), "n", [entry])
            with pytest.raises(ValidationError):
                await index.search(Scope(), "n", [1, 0], limit=1)
            with pytest.raises(ValidationError):
                await index.delete_document(Scope(), "n", "d")
            assert service.requests == []
            await index.initialize()
            await index.aclose()
            await index.aclose()
            with pytest.raises(ValidationError):
                await index.initialize()
            with pytest.raises(ValidationError):
                await index.search(Scope(), "n", [1, 0], limit=1)
            assert len(service.requests) == 1

    asyncio.run(scenario())


def test_owned_client_closes_with_index(monkeypatch):
    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(QdrantHTTP()))
        module = importlib.import_module("ralf_agent.qdrant")
        monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client)
        index = construct()
        await index.initialize()
        await index.aclose()
        assert client.is_closed

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["exception", "cancellation"])
def test_owned_close_failure_is_retryable_but_keeps_operation_gate_closed(monkeypatch, failure):
    async def scenario():
        started = asyncio.Event()
        client = httpx.AsyncClient(transport=httpx.MockTransport(QdrantHTTP()))
        close_client = client.aclose
        calls = 0

        async def flaky_close():
            nonlocal calls
            calls += 1
            if calls == 1:
                if failure == "exception":
                    raise RuntimeError("temporary failure")
                started.set()
                await asyncio.Event().wait()
            await close_client()

        client.aclose = flaky_close
        module = importlib.import_module("ralf_agent.qdrant")
        monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client)
        index = construct()
        try:
            await index.initialize()
            if failure == "exception":
                with pytest.raises(MemoryBackendError):
                    await index.aclose()
            else:
                task = asyncio.create_task(index.aclose())
                await started.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert not client.is_closed
            with pytest.raises(ValidationError):
                await index.initialize()
            await asyncio.gather(index.aclose(), index.aclose())
            assert client.is_closed and calls == 2
        finally:
            await close_client()

    asyncio.run(scenario())


def test_uuid_upsert_replaces_only_full_scope_namespace_chunk_identity():
    async def scenario():
        service = QdrantHTTP()
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client)
            await index.initialize()
            entry = VectorEntry("shared", "a", 1, "v1", [3, 4])
            for scope, namespace in [
                (Scope(), "n"),
                (Scope("foreign", "local-owner"), "n"),
                (Scope("default", "foreign"), "n"),
                (Scope(), "other"),
            ]:
                await index.upsert(scope, namespace, [entry])
            assert len(service.points) == 4
            assert all(str(uuid.UUID(point_id)) == point_id for point_id in service.points)
            await index.upsert(Scope(), "n", [VectorEntry("shared", "b", 2, "v2", [0, 1])])
            assert len(service.points) == 4
            points = [
                point
                for point in service.points.values()
                if point["payload"]["namespace"] == "n"
                and point["payload"]["workspace"] == "default"
                and point["payload"]["principal"] == "local-owner"
            ]
            assert points[0]["payload"] == {
                "workspace": "default",
                "principal": "local-owner",
                "namespace": "n",
                "chunk_id": "shared",
                "document_id": "b",
                "version": 2,
                "text_digest": "v2",
            }
            assert points[0]["vector"] == [0.0, 1.0]
            first_written = service.requests[1][1]["points"][0]
            assert first_written["vector"] == pytest.approx([0.6, 0.8])
            assert "text" not in first_written["payload"]
            assert all(
                request.url.params["wait"] == "true"
                for request, _ in service.requests
                if request.method == "PUT"
            )

    asyncio.run(scenario())


def test_search_and_delete_use_all_scope_filters_and_preserve_other_corpora():
    async def scenario():
        service = QdrantHTTP()
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client)
            await index.initialize()
            entries = [
                VectorEntry("parallel", "a", 1, "a", [1, 0]),
                VectorEntry("diagonal", "b", 1, "b", [1, 1]),
                VectorEntry("orthogonal", "c", 1, "c", [0, 1]),
            ]
            for scope, namespace in [
                (Scope(), "n"),
                (Scope("foreign", "local-owner"), "n"),
                (Scope("default", "foreign"), "n"),
                (Scope(), "other"),
            ]:
                await index.upsert(scope, namespace, entries)
            hits = await index.search(Scope(), "n", [10, 0], limit=3)
            assert [hit.chunk_id for hit in hits] == ["parallel", "diagonal", "orthogonal"]
            assert all(isinstance(hit, VectorHit) for hit in hits)
            assert [hit.score for hit in hits] == pytest.approx([1, math.sqrt(0.5), 0])
            query = service.requests[-1][1]
            required = [
                {"key": "workspace", "match": {"value": "default"}},
                {"key": "principal", "match": {"value": "local-owner"}},
                {"key": "namespace", "match": {"value": "n"}},
            ]
            assert query == {
                "query": [1.0, 0.0],
                "filter": {"must": required},
                "limit": 3,
                "with_payload": True,
                "with_vector": False,
            }
            await index.delete_document(Scope(), "n", "a")
            request, body = service.requests[-1]
            assert request.url.params["wait"] == "true"
            assert body == {
                "filter": {"must": required + [{"key": "document_id", "match": {"value": "a"}}]}
            }
            assert [
                hit.document_id for hit in await index.search(Scope(), "n", [1, 0], limit=3)
            ] == ["b", "c"]
            assert (
                len(await index.search(Scope("foreign", "local-owner"), "n", [1, 0], limit=3)) == 3
            )
            assert len(await index.search(Scope("default", "foreign"), "n", [1, 0], limit=3)) == 3
            assert len(await index.search(Scope(), "other", [1, 0], limit=3)) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["upsert", "delete"])
@pytest.mark.parametrize(
    "result", [{"status": "acknowledged", "operation_id": 1}, {"status": "failed"}, {}, True, None]
)
def test_mutations_require_completed_result_even_on_http_success(operation, result):
    async def scenario():
        service = QdrantHTTP()
        service.mutation_result = result
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client)
            await index.initialize()
            with pytest.raises(MemoryBackendError):
                if operation == "upsert":
                    await index.upsert(Scope(), "n", [VectorEntry("c", "d", 1, "digest", [1, 0])])
                else:
                    await index.delete_document(Scope(), "n", "d")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "damage",
    [
        "workspace",
        "principal",
        "namespace",
        "chunk_id",
        "document_id",
        "version",
        "digest",
        "nan",
        "infinity",
        "boolean_score",
        "out_of_range",
        "point_id",
        "missing_payload",
        "duplicate",
        "over_limit",
        "missing_points",
        "wrong_points",
    ],
)
def test_search_rejects_foreign_or_malformed_results(damage):
    async def scenario():
        service = QdrantHTTP()
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client)
            await index.initialize()
            await index.upsert(Scope(), "n", [VectorEntry("c", "d", 1, "digest", [1, 0])])
            point = next(iter(service.points.values()))
            result = {
                "points": [
                    {
                        "id": point["id"],
                        "version": 0,
                        "score": 1.0,
                        "payload": copy.deepcopy(point["payload"]),
                    }
                ]
            }
            hit = result["points"][0]
            if damage in ("workspace", "principal", "namespace"):
                hit["payload"][damage] = "foreign"
            elif damage in ("chunk_id", "document_id"):
                hit["payload"][damage] = ""
            elif damage == "version":
                hit["payload"]["version"] = True
            elif damage == "digest":
                del hit["payload"]["text_digest"]
            elif damage in ("nan", "infinity"):
                hit["score"] = float("nan") if damage == "nan" else float("inf")
            elif damage == "boolean_score":
                hit["score"] = True
            elif damage == "out_of_range":
                hit["score"] = 1.1
            elif damage == "point_id":
                hit["id"] = "00000000-0000-0000-0000-000000000000"
            elif damage == "missing_payload":
                del hit["payload"]
            elif damage in ("duplicate", "over_limit"):
                result["points"].append(copy.deepcopy(hit))
            elif damage == "missing_points":
                result = {}
            elif damage == "wrong_points":
                result = {"points": {"c": hit}}
            service.query_result = result
            with pytest.raises(MemoryBackendError):
                await index.search(Scope(), "n", [1, 0], limit=1 if damage == "over_limit" else 3)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case", ["http", "timeout", "json", "top_status", "top_list", "response_limit"]
)
def test_transport_errors_are_typed_and_do_not_expose_credentials_or_body(case):
    async def scenario():
        def handler(request):
            secret = "credential-and-private-response"
            if case == "http":
                return httpx.Response(500, text=secret)
            if case == "timeout":
                raise httpx.ReadTimeout(secret, request=request)
            if case == "json":
                return httpx.Response(200, text=secret)
            if case == "top_status":
                return httpx.Response(200, json={"status": {"error": secret}, "result": {}})
            if case == "top_list":
                return httpx.Response(200, json=[secret])
            return httpx.Response(200, content=b"x" * 4_000_001)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            index = construct(client=client, api_key="credential-and-private-response")
            with pytest.raises(MemoryBackendError) as caught:
                await index.initialize()
            assert "credential" not in str(caught.value)
            assert "private-response" not in str(caught.value)
            assert caught.value.__cause__ is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case", ["scope", "namespace", "vector", "limit", "entries", "entry_dimensions", "document"]
)
def test_invalid_operation_input_does_not_reach_remote_service(case):
    async def scenario():
        service = QdrantHTTP()
        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            index = construct(client=client)
            await index.initialize()
            with pytest.raises(ValidationError):
                if case == "scope":
                    await index.search(None, "n", [1, 0], limit=1)
                elif case == "namespace":
                    await index.search(Scope(), " ", [1, 0], limit=1)
                elif case == "vector":
                    await index.search(Scope(), "n", [0, 0], limit=1)
                elif case == "limit":
                    await index.search(Scope(), "n", [1, 0], limit=True)
                elif case == "entries":
                    await index.upsert(Scope(), "n", [object()])
                elif case == "entry_dimensions":
                    await index.upsert(Scope(), "n", [VectorEntry("c", "d", 1, "x", [1])])
                else:
                    await index.delete_document(Scope(), "n", "")
            assert len(service.requests) == 1

    asyncio.run(scenario())


class ExplicitEmbedding:
    identity = {"kind": "qdrant-test-precomputed", "version": "1"}
    dimensions = 2

    async def embed(self, texts):
        return [[1, 0] if text in ("apple", "query") else [0, 1] for text in texts]


async def hydration_scenario(index, monkeypatch):
    now = time.time()
    with InMemoryKnowledgeStore() as store:
        store.put(Scope(), "n", Document("stale", "apple"), expected_version=0)
        store.put(Scope(), "n", Document("deleted", "banana"), expected_version=0)
        store.put(
            Scope(), "n", Document("expired", "apple"), expected_version=0, expires_at=now + 60
        )
        retriever = VectorRetriever(store, index, ExplicitEmbedding())
        for document_id in ("stale", "deleted", "expired"):
            await retriever.index_document(Scope(), "n", document_id)
        result = await retriever.retrieve(Scope(), "n", RetrievalQuery("query"))
        assert {item.document_id for item in result.items} == {"stale", "deleted", "expired"}
        assert {item.text for item in result.items} == {"apple", "banana"}
        store.put(Scope(), "n", Document("stale", "banana"), expected_version=1)
        store.delete(Scope(), "n", "deleted", expected_version=1)
        monkeypatch.setattr("ralf_agent.retrieval.time.time", lambda: now + 120)
        assert (await retriever.retrieve(Scope(), "n", RetrievalQuery("query"))).items == ()


def test_vector_retriever_hydrates_authority_and_discards_stale_expired_deleted_points(monkeypatch):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(QdrantHTTP())) as client:
            index = construct(client=client)
            await index.initialize()
            await hydration_scenario(index, monkeypatch)

    asyncio.run(scenario())


def test_real_qdrant_isolated_collection_and_authority_hydration(monkeypatch):
    url = os.environ.get("RALF_TEST_QDRANT_URL")
    if not url:
        pytest.skip("Set RALF_TEST_QDRANT_URL to exercise a real Qdrant service")

    async def scenario():
        collection = f"ralf_test_{uuid.uuid4().hex}"
        key = os.environ.get("RALF_TEST_QDRANT_API_KEY")
        index = construct(url=url, collection=collection, api_key=key)
        try:
            await index.initialize()
            entries = [
                VectorEntry("parallel", "a", 1, "a", [1, 0]),
                VectorEntry("diagonal", "b", 1, "b", [1, 1]),
            ]
            await index.upsert(Scope(), "n", entries)
            await index.upsert(Scope("foreign", "local-owner"), "n", entries)
            await index.upsert(Scope("default", "foreign"), "n", entries)
            await index.upsert(Scope(), "other", entries)
            hits = await index.search(Scope(), "n", [1, 0], limit=5)
            assert [hit.chunk_id for hit in hits] == ["parallel", "diagonal"]
            assert [hit.score for hit in hits] == pytest.approx([1, math.sqrt(0.5)], abs=1e-6)
            await index.delete_document(Scope(), "n", "a")
            assert [
                hit.document_id for hit in await index.search(Scope(), "n", [1, 0], limit=5)
            ] == ["b"]
            assert (
                len(await index.search(Scope("foreign", "local-owner"), "n", [1, 0], limit=5)) == 2
            )
            assert len(await index.search(Scope("default", "foreign"), "n", [1, 0], limit=5)) == 2
            assert len(await index.search(Scope(), "other", [1, 0], limit=5)) == 2
            other = construct(url=url, collection=collection, dimensions=3, api_key=key)
            try:
                with pytest.raises(ValidationError):
                    await other.initialize()
            finally:
                await other.aclose()
            await hydration_scenario(index, monkeypatch)
        finally:
            await index.aclose()
            async with httpx.AsyncClient() as cleanup:
                response = await cleanup.delete(
                    f"{url.rstrip('/')}/collections/{collection}",
                    headers={"api-key": key} if key else {},
                    timeout=10,
                )
                assert response.status_code == 200

    asyncio.run(scenario())
