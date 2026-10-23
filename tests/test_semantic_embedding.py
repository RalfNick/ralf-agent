import asyncio

import httpx
import pytest

from relf_agent.errors import ProviderError, ValidationError


def response():
    return {
        "object": "list",
        "model": "fixture",
        "data": [{"object": "embedding", "index": 0, "embedding": [1, 0]}],
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


def test_owned_embedding_real_transport_close_failure_can_retry(monkeypatch):
    from relf_agent.semantic_embedding import ManagedEmbeddingProvider

    class Transport(httpx.MockTransport):
        attempts = 0
        released = False

        async def aclose(self):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("failed release")
            self.released = True

    transport = Transport(lambda r: httpx.Response(200, json=response()))
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: transport)

    async def run():
        provider = ManagedEmbeddingProvider("fixture", dimensions=2, base_url="http://rank.test/v1")
        assert provider._client is None
        assert await provider.embed(["vehicle"]) == [[1.0, 0.0]]
        with pytest.raises(ProviderError):
            await provider.aclose()
        assert provider._client.is_closed and not transport.released
        with pytest.raises(ValidationError):
            await provider.embed(["vehicle"])
        await provider.aclose()
        assert transport.released and transport.attempts == 2

    asyncio.run(run())


def test_embedding_stream_all_task_cancel_retains_release_for_retry(monkeypatch):
    from relf_agent.semantic_embedding import ManagedEmbeddingProvider

    async def run():
        reading, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                reading.set()
                await asyncio.Event().wait()
                yield b"unreachable"

            async def aclose(self):
                closing.set()
                await release.wait()
                self.closed = True

        stream = Stream()
        monkeypatch.setattr(
            httpx,
            "AsyncHTTPTransport",
            lambda **kwargs: httpx.MockTransport(lambda r: httpx.Response(200, stream=stream)),
        )
        provider = ManagedEmbeddingProvider("fixture", dimensions=2, base_url="http://rank.test/v1")
        task = asyncio.create_task(provider.embed(["vehicle"]))
        await asyncio.wait_for(reading.wait(), 2)
        task.cancel()
        await asyncio.wait_for(closing.wait(), 2)
        others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for other in others:
            other.cancel()
        await asyncio.gather(*others, return_exceptions=True)
        assert not stream.closed
        close = asyncio.create_task(provider.aclose())
        await asyncio.sleep(0)
        assert not close.done()
        release.set()
        await asyncio.wait_for(close, 2)
        assert stream.closed and provider._closed

    asyncio.run(run())
