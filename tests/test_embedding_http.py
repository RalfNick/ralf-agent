import asyncio
import importlib
import importlib.util
import json

import httpx
import pytest

from ralf_agent.errors import ProviderError, ValidationError


def provider(**kwargs):
    assert importlib.util.find_spec("ralf_agent.embedding_http"), "Missing HTTP embedding adapter"
    return importlib.import_module("ralf_agent.embedding_http").OpenAIEmbeddingProvider(
        "embed", dimensions=2, base_url="http://embedding.test/v1", **kwargs
    )


def payload(n=2):
    return {
        "object": "list",
        "model": "embed",
        "data": [{"object": "embedding", "index": i, "embedding": [i + 1, 1]} for i in range(n)],
        "usage": {"prompt_tokens": 3, "total_tokens": 3},
    }


def test_sorted_protocol_indices_batched_and_usage_explicit():
    async def run():
        bodies = []

        def service(request):
            body = json.loads(request.content)
            bodies.append(body)
            value = payload(len(body["input"]))
            value["data"].reverse()
            assert (
                request.url.path == "/v1/embeddings"
                and request.headers["authorization"] == "Bearer private-key"
            )
            return httpx.Response(200, json=value)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(service), follow_redirects=True
        ) as client:
            p = provider(client=client, api_key="private-key", batch_size=2, send_dimensions=True)
            report = await p.embed_result(["a", "b", "c"])
            assert report.vectors == [[1, 1], [2, 1], [1, 1]] and report.batches == 2
            assert report.usage == [
                {"prompt_tokens": 3, "total_tokens": 3},
                {"prompt_tokens": 3, "total_tokens": 3},
            ]
            assert bodies == [
                {
                    "input": ["a", "b"],
                    "model": "embed",
                    "encoding_format": "float",
                    "dimensions": 2,
                },
                {"input": ["c"], "model": "embed", "encoding_format": "float", "dimensions": 2},
            ]
            report.vectors[0][0] = 99
            assert report.vectors[0][0] == 1
            assert "private-key" not in json.dumps(p.identity)
            await p.aclose()
            assert not client.is_closed
            with pytest.raises(ValidationError):
                await p.embed([])

    asyncio.run(run())


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "index-bool",
        "wrongdim",
        "nan",
        "zero",
        "error",
        "model",
        "base64",
        "bool-vector",
        "bad-usage",
        "list-object",
    ],
)
def test_invalid_remote_completion_is_typed_and_redacted(damage):
    async def run():
        value = payload()
        if damage == "missing":
            value["data"].pop()
        elif damage == "duplicate":
            value["data"][1]["index"] = 0
        elif damage == "index-bool":
            value["data"][1]["index"] = True
        elif damage == "wrongdim":
            value["data"][0]["embedding"] = [1]
        elif damage == "nan":
            value["data"][0]["embedding"] = [float("nan"), 1]
        elif damage == "zero":
            value["data"][0]["embedding"] = [0, 0]
        elif damage == "error":
            value["error"] = {"message": "private credential"}
        elif damage == "model":
            value["model"] = "unexpected"
        elif damage == "base64":
            value["data"][0]["embedding"] = "encoded"
        elif damage == "bool-vector":
            value["data"][0]["embedding"] = [True, 1]
        elif damage == "bad-usage":
            value["usage"]["total_tokens"] = False
        else:
            value["object"] = "wrong"
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=json.dumps(value)))
        ) as client:
            p = provider(client=client)
            with pytest.raises(ProviderError) as error:
                await p.embed(["a", "b"])
            assert "private credential" not in str(error.value)
            await p.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "option,value",
    [
        ("batch_size", True),
        ("timeout", float("nan")),
        ("max_text_chars", 0),
        ("send_dimensions", 1),
        ("api_key", " "),
        ("max_response_bytes", False),
    ],
)
def test_invalid_config_rejected_before_client_allocation(option, value, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Allocated client before config validation")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected)
    with pytest.raises(ValidationError):
        provider(**{option: value})


def test_empty_batch_no_request_and_full_input_preflight_precedes_first_batch():
    async def run():
        seen = []
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: (seen.append(r), httpx.Response(200, json=payload(1)))[1]
            )
        ) as client:
            p = provider(client=client, batch_size=1, max_text_chars=2)
            assert await p.embed([]) == []
            with pytest.raises(ValidationError):
                await p.embed(["a", "toolong"])
            assert seen == []
            report = await p.embed_result(["a"])
            assert report.batches == 1
            await p.aclose()

    asyncio.run(run())


def test_response_size_redirect_transport_failures_and_missing_usage():
    async def run():
        for mode in ["large", "redirect", "transport", "usage"]:
            seen = []

            def service(request, mode=mode, seen=seen):
                seen.append(request)
                if mode == "large":
                    return httpx.Response(200, content=b" " * 1000)
                if mode == "redirect":
                    return httpx.Response(
                        307, headers={"location": "http://foreign.test/v1/embeddings"}
                    )
                if mode == "transport":
                    raise httpx.ConnectError("private input and secret", request=request)
                value = payload(1)
                value.pop("usage")
                return httpx.Response(200, json=value)

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(service), follow_redirects=True
            ) as client:
                p = provider(client=client, max_response_bytes=512)
                if mode == "usage":
                    assert (await p.embed_result(["a"])).usage == [None]
                else:
                    with pytest.raises(ProviderError) as error:
                        await p.embed(["a"])
                    assert "secret" not in str(error.value)
                assert len(seen) == 1
                await p.aclose()

    asyncio.run(run())


def test_cancel_releases_actual_http_operation_before_owned_close():
    async def run():
        started = asyncio.Event()
        finished = asyncio.Event()

        async def service(request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        client = httpx.AsyncClient(transport=httpx.MockTransport(service))
        p = provider(client=client)
        t = asyncio.create_task(p.embed(["a"]))
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(ValidationError):
            await p.aclose()
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        assert finished.is_set()
        await p.aclose()
        assert not client.is_closed
        await client.aclose()

    asyncio.run(run())


def test_owned_lazy_client_failed_close_retry_and_immutable_config(monkeypatch):
    async def run():
        allocated = []
        base = httpx.AsyncClient

        class Client(base):
            fail = True

            def __init__(self, **kwargs):
                allocated.append(self)
                super().__init__(
                    transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload(1))),
                    **kwargs,
                )

            async def aclose(self):
                if self.fail:
                    self.fail = False
                    raise RuntimeError("secret close details")
                await super().aclose()

        monkeypatch.setattr(httpx, "AsyncClient", Client)
        p = provider()
        assert allocated == [] and await p.embed([]) == []
        with pytest.raises(AttributeError):
            p.dimensions = 3
        p.identity["model"] = "changed"
        assert p.identity["model"] == "embed"
        assert await p.embed(["a"]) == [[1, 1]]
        with pytest.raises(ProviderError):
            await p.aclose()
        with pytest.raises(ValidationError):
            await p.embed(["a"])
        await p.aclose()
        await p.aclose()
        assert allocated[0].is_closed

    asyncio.run(run())


def test_later_invalid_utf8_scalar_is_rejected_before_first_request():
    async def run():
        seen = []
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: (seen.append(r), httpx.Response(200, json=payload(1)))[1]
            )
        ) as client:
            p = provider(client=client, batch_size=1)
            with pytest.raises(ValidationError):
                await p.embed(["a", "\ud800"])
            assert not seen
            await p.aclose()

    asyncio.run(run())


def test_timeout_overflow_is_typed_validation():
    with pytest.raises(ValidationError):
        provider(timeout=10**1000)


@pytest.mark.parametrize(
    "option,value",
    [
        ("max_text_chars", 32769),
        ("max_batch_chars", 262145),
        ("max_response_bytes", 8 * 1024 * 1024 + 1),
    ],
)
def test_absolute_embedding_limits_cannot_be_expanded(option, value):
    with pytest.raises(ValidationError):
        provider(**{option: value})
