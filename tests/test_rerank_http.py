import asyncio
import copy
import json
from dataclasses import replace

import httpx
import pytest

from relf_agent import Document, InMemoryKnowledgeStore, Scope
from relf_agent.errors import DefinitionMismatch, ProviderError, ValidationError
from relf_agent.retrieval import _retrieved


def candidates():
    store = InMemoryKnowledgeStore()
    for name, text in (("a", "car warranty"), ("b", "automobile safety")):
        store.put(
            Scope(),
            "docs",
            Document(name, text, metadata={"private": "local-only"}),
            expected_version=0,
        )
    return tuple(_retrieved(store.chunks(Scope(), "docs", name)[0], 1) for name in ("a", "b"))


def api(**kwargs):
    from relf_agent import HTTPReranker

    return HTTPReranker("fixture", base_url="http://rank.test/v2", **kwargs)


def response():
    return {
        "results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}],
        "id": "request",
        "meta": {"api_version": {"version": "2"}, "billed_units": {"search_units": 1}},
    }


def test_remote_order_maps_original_ids_and_report_usage_is_detached():
    async def run():
        original = candidates()
        before = copy.deepcopy(original)
        seen = []

        def service(request):
            seen.append(json.loads(request.content))
            assert (
                request.url.path == "/v2/rerank"
                and request.headers["authorization"] == "Bearer private"
            )
            return httpx.Response(200, json=response())

        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            ranker = api(api_key="private", client=client)
            report = await ranker.rerank_result("safety", original, limit=2)
            assert report.ids == [original[1].chunk_id, original[0].chunk_id]
            assert report.scores == [0.9, 0.1] and report.usage == {"search_units": 1}
            report.ids.clear()
            report.usage["search_units"] = 99
            assert len(report.ids) == 2 and report.usage == {"search_units": 1}
            assert "private" not in json.dumps(ranker.identity)
            assert original == before
            await ranker.aclose()
            assert not client.is_closed
            assert seen == [
                {
                    "model": "fixture",
                    "query": "safety",
                    "documents": ["car warranty", "automobile safety"],
                    "top_n": 2,
                }
            ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "duplicate",
        "bool",
        "outside",
        "nan",
        "bool-score",
        "ascending",
        "model",
        "error",
        "bad-usage",
        "wrongtype",
    ],
)
def test_invalid_response_is_rejected_without_leaking_input_or_error(damage):
    async def run():
        value = response()
        if damage == "missing":
            value["results"].pop()
        elif damage == "empty":
            value["results"] = []
        elif damage == "duplicate":
            value["results"][1]["index"] = 1
        elif damage == "bool":
            value["results"][0]["index"] = True
        elif damage == "outside":
            value["results"][0]["index"] = 3
        elif damage == "nan":
            value["results"][0]["relevance_score"] = float("nan")
        elif damage == "bool-score":
            value["results"][0]["relevance_score"] = True
        elif damage == "ascending":
            value["results"].reverse()
        elif damage == "model":
            value["model"] = "other"
        elif damage == "error":
            value["error"] = "private credential"
        elif damage == "bad-usage":
            value["meta"]["billed_units"]["search_units"] = -1
        else:
            value["results"] = {}
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=json.dumps(value)))
        ) as client:
            ranker = api(client=client)
            with pytest.raises(ProviderError) as error:
                await ranker.rerank("safety", candidates(), limit=2)
            assert "private" not in str(error.value) and "safety" not in str(error.value)
            await ranker.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,value",
    [
        ("timeout", True),
        ("timeout", float("nan")),
        ("timeout", 10**1000),
        ("max_documents", 257),
        ("max_query_chars", 0),
        ("max_document_chars", 32769),
        ("max_total_chars", True),
        ("max_response_bytes", 1048577),
    ],
)
def test_invalid_configuration_fails_before_client_allocation(name, value, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Allocated client before validation")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected)
    with pytest.raises(ValidationError):
        api(**{name: value})


def test_full_input_preflight_empty_candidates_and_missing_usage():
    async def run():
        seen = []
        value = response()
        value.pop("meta")
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: (seen.append(r), httpx.Response(200, json=value))[1]
            )
        ) as client:
            ranker = api(client=client)
            assert await ranker.rerank("", (), limit=2) == () and seen == []
            for query, values, limit in [
                ("\ud800", candidates(), 2),
                (" ", candidates(), 2),
                ("safety", candidates(), True),
                ("safety", (candidates()[0],) * 2, 2),
            ]:
                with pytest.raises(ValidationError):
                    await ranker.rerank(query, values, limit=limit)
            assert seen == []
            assert (await ranker.rerank_result("safety", candidates(), limit=2)).usage is None
            await ranker.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["redirect", "large", "transport"])
def test_failure_has_one_attempt_and_bounded_redacted_error(mode):
    async def run():
        seen = []

        def service(request):
            seen.append(request)
            if mode == "redirect":
                return httpx.Response(307, headers={"location": "http://foreign.test/rerank"})
            if mode == "large":
                return httpx.Response(200, content=b" " * 2000)
            raise httpx.ConnectError("private", request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(service), follow_redirects=True
        ) as client:
            ranker = api(client=client, max_response_bytes=1024)
            with pytest.raises(ProviderError):
                await ranker.rerank("safety", candidates(), limit=2)
            assert len(seen) == 1
            await ranker.aclose()

    asyncio.run(run())


def test_cancel_and_concurrent_requests_keep_actual_ownership_until_finished():
    async def run():
        started, done = asyncio.Event(), asyncio.Event()
        active = 0

        async def service(request):
            nonlocal active
            active += 1
            if active == 2:
                started.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1
                if not active:
                    done.set()

        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            ranker = api(client=client)
            tasks = [
                asyncio.create_task(ranker.rerank("safety", candidates(), limit=2))
                for _ in range(2)
            ]
            await asyncio.wait_for(started.wait(), 2)
            with pytest.raises(ValidationError):
                await ranker.aclose()
            tasks[0].cancel()
            await asyncio.gather(tasks[0], return_exceptions=True)
            with pytest.raises(ValidationError):
                await ranker.aclose()
            tasks[1].cancel()
            await asyncio.gather(tasks[1], return_exceptions=True)
            assert done.is_set()
            await ranker.aclose()
            assert not client.is_closed

    asyncio.run(run())


def test_lazy_owned_client_close_failure_is_retryable_but_blocks_new_dispatch(monkeypatch):
    base = httpx.AsyncClient
    allocated = []

    class Client(base):
        fail = True

        def __init__(self, **kwargs):
            allocated.append(self)
            super().__init__(**kwargs)

        async def aclose(self):
            if self.fail:
                self.fail = False
                raise RuntimeError("private")
            await super().aclose()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        httpx,
        "AsyncHTTPTransport",
        lambda **kwargs: httpx.MockTransport(lambda r: httpx.Response(200, json=response())),
    )

    async def run():
        ranker = api()
        assert not allocated
        await ranker.rerank("safety", candidates(), limit=2)
        with pytest.raises(ProviderError):
            await ranker.aclose()
        with pytest.raises(ValidationError):
            await ranker.rerank("safety", candidates(), limit=2)
        await ranker.aclose()
        assert allocated[0].is_closed

    asyncio.run(run())


def test_changed_helper_or_client_during_await_cannot_adopt_or_close_replacement():
    async def run():
        ranker = None

        async def service(request):
            ranker._inputs = lambda *args: ([], [])
            return httpx.Response(200, json=response())

        async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as client:
            ranker = api(client=client)
            original = ranker._inputs
            with pytest.raises(DefinitionMismatch):
                await ranker.rerank("safety", candidates(), limit=2)
            ranker._inputs = original
            other = httpx.AsyncClient()
            ranker._client = other
            with pytest.raises(DefinitionMismatch):
                await ranker.aclose()
            assert not other.is_closed and not client.is_closed
            ranker._client = client
            await ranker.aclose()
            await other.aclose()

    asyncio.run(run())


def test_later_document_preflight_blocks_every_request_and_cross_loop_use():
    ranker = api()

    async def first():
        values = candidates()
        with pytest.raises(ValidationError):
            await ranker.rerank("safety", (values[0], replace(values[1], text="\ud800")), limit=2)
        assert ranker._client is None

    asyncio.run(first())

    async def other():
        with pytest.raises(ValidationError, match="event loop"):
            await ranker.rerank("safety", candidates(), limit=2)

    asyncio.run(other())


def test_actual_httpx_transport_close_failure_cannot_be_hidden_by_closed_flag(monkeypatch):
    class Transport(httpx.MockTransport):
        attempts = 0
        released = False

        async def aclose(self):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("transport cleanup failed")
            self.released = True

    transport = Transport(lambda r: httpx.Response(200, json=response()))
    base = httpx.AsyncClient

    class Client(base):
        def __init__(self, **kwargs):
            kwargs.setdefault("transport", transport)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: transport)

    async def run():
        ranker = api()
        await ranker.rerank("safety", candidates(), limit=2)
        with pytest.raises(ProviderError):
            await ranker.aclose()
        assert ranker._client.is_closed and not transport.released
        await ranker.aclose()
        assert transport.released and transport.attempts == 2

    asyncio.run(run())


def test_all_task_cancellation_retains_response_stream_for_close_retry():
    async def run():
        reading, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            closed = False
            attempts = 0

            async def __aiter__(self):
                reading.set()
                await asyncio.Event().wait()
                yield b"unreachable"

            async def aclose(self):
                self.attempts += 1
                closing.set()
                await release.wait()
                self.closed = True

        stream = Stream()
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=stream))
        )
        ranker = api(client=client)
        task = asyncio.create_task(ranker.rerank("safety", candidates(), limit=2))
        await asyncio.wait_for(reading.wait(), 2)
        task.cancel()
        await asyncio.wait_for(closing.wait(), 2)
        current = asyncio.current_task()
        others = [t for t in asyncio.all_tasks() if t is not current]
        for other in others:
            other.cancel()
        await asyncio.gather(*others, return_exceptions=True)
        assert not stream.closed
        close = asyncio.create_task(ranker.aclose())
        await asyncio.sleep(0)
        assert not close.done(), "aclose must retain and finish interrupted stream cleanup"
        release.set()
        await asyncio.wait_for(close, 2)
        assert stream.closed and stream.attempts == 2 and not client.is_closed
        await client.aclose()

    asyncio.run(run())


def test_stream_close_failure_retains_borrowed_response_but_not_client_ownership():
    async def run():
        class Stream(httpx.AsyncByteStream):
            attempts = 0
            released = False

            async def __aiter__(self):
                yield json.dumps(response()).encode()

            async def aclose(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("private stream failure")
                self.released = True

        stream = Stream()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=stream))
        ) as client:
            ranker = api(client=client)
            with pytest.raises(ProviderError):
                await ranker.rerank("safety", candidates(), limit=2)
            assert not stream.released
            await ranker.aclose()
            assert stream.released and stream.attempts == 2 and not client.is_closed

    asyncio.run(run())


def test_cancelled_owned_transport_close_is_retryable_and_serialized(monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        class Transport(httpx.MockTransport):
            released = False
            attempts = 0

            async def aclose(self):
                self.attempts += 1
                started.set()
                await release.wait()
                self.released = True

        transport = Transport(lambda r: httpx.Response(200, json=response()))
        monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: transport)
        ranker = api()
        await ranker.rerank("safety", candidates(), limit=2)
        close = asyncio.create_task(ranker.aclose())
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(ValidationError, match="already in progress"):
            await ranker.aclose()
        close.cancel()
        await asyncio.gather(close, return_exceptions=True)
        assert not transport.released and not ranker._closed
        with pytest.raises(ValidationError):
            await ranker.rerank("safety", candidates(), limit=2)
        release.set()
        await ranker.aclose()
        assert transport.released and transport.attempts == 2

    asyncio.run(run())
