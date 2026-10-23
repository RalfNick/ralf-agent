"""Explicit indexed-results rerank HTTP protocol with borrowed/owned lifetime."""

import asyncio
import json
import math

import httpx

from .errors import DefinitionMismatch, ProviderError, ValidationError
from .qdrant import _url
from .rerank_response import RerankResponse, finite_score
from .retrieval import _integer, _text
from .retrieval_ranking import _candidates
from .task_controls import _binding
from .tools import _callable_identity
from .types import canonical, digest


def _unicode(value):
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValidationError("Rerank text must contain valid Unicode scalars") from None


class _ResponseStream(httpx.AsyncByteStream):
    """Record completed release, independently of HTTPX's early closed flag."""

    def __init__(self, stream):
        self.stream = stream
        self.closed = False

    async def __aiter__(self):
        async for data in self.stream:
            yield data

    async def aclose(self):
        if not self.closed:
            await self.stream.aclose()
            self.closed = True


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport(trust_env=False)
        self.closed = False

    async def handle_async_request(self, request):
        return await self.transport.handle_async_request(request)

    async def aclose(self):
        if not self.closed:
            await self.transport.aclose()
            self.closed = True


class HTTPReranker:
    def __init__(
        self,
        model,
        *,
        base_url,
        api_key=None,
        client=None,
        timeout=60,
        max_documents=256,
        max_query_chars=4096,
        max_document_chars=32768,
        max_total_chars=262144,
        max_response_bytes=1048576,
    ):
        _text(model, "Rerank model")
        _unicode(model)
        for name, value, maximum in [
            ("max_documents", max_documents, 256),
            ("max_query_chars", max_query_chars, 65536),
            ("max_document_chars", max_document_chars, 32768),
            ("max_total_chars", max_total_chars, 1048576),
            ("max_response_bytes", max_response_bytes, 1048576),
        ]:
            _integer(value, name, minimum=1)
            if value > maximum:
                raise ValidationError("Rerank limit exceeds supported bound")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 300
            or not math.isfinite(timeout)
        ):
            raise ValidationError("Rerank timeout must be finite in (0,300]")
        if api_key is not None:
            _text(api_key, "Rerank credential")
            try:
                api_key.encode("ascii")
            except UnicodeError:
                raise ValidationError("Rerank credential must be ASCII") from None
        if client is not None and not isinstance(client, httpx.AsyncClient):
            raise ValidationError("Borrowed rerank client must be httpx.AsyncClient")
        url = _url(base_url)
        _unicode(url)
        self._config_json = canonical(
            dict(
                kind="indexed-http-reranker",
                version="1",
                protocol="indexed-results-v1",
                model=model,
                base_url=url,
                timeout=timeout,
                max_documents=max_documents,
                max_query_chars=max_query_chars,
                max_document_chars=max_document_chars,
                max_total_chars=max_total_chars,
                max_response_bytes=max_response_bytes,
            )
        )
        self._config_pin = self._config_json
        self._api_key = self._key_pin = api_key
        self._client = self._client_pin = client
        self._owned = self._owned_pin = client is None
        self._loop = None
        self._active = set()
        self._streams = set()
        self._transport = self._transport_pin = None
        self._closed = self._closing = False
        self._close_active = False
        self._hooks = {
            name: _binding(getattr(self, name))
            for name in (
                "rerank",
                "rerank_result",
                "_inputs",
                "_request",
                "_parse",
                "_ready",
                "aclose",
            )
        }
        self._implementation = {
            name: digest(_callable_identity(getattr(self, name))) for name in self._hooks
        }

    def _check(self):
        if (
            self._config_json != self._config_pin
            or self._api_key != self._key_pin
            or self._client is not self._client_pin
            or self._owned is not self._owned_pin
            or self._transport is not self._transport_pin
            or any(
                _binding(getattr(self, name)) != original for name, original in self._hooks.items()
            )
        ):
            raise DefinitionMismatch("Rerank configuration, implementation or client changed")

    @property
    def identity(self):
        self._check()
        return {**json.loads(self._config_json), "implementation": dict(self._implementation)}

    def _ready(self):
        self._check()
        if self._closed or self._closing:
            raise ValidationError("Reranker is closed or closing")
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise ValidationError("Reranker belongs to another event loop")
        self._loop = loop

    def _inputs(self, query, candidates, limit, config):
        _candidates(query, candidates, limit)
        if len(candidates) > config["max_documents"] or len(query) > config["max_query_chars"]:
            raise ValidationError("Rerank query or candidate count exceeds limit")
        ids, texts = [], []
        _unicode(query)
        for chunk in candidates:
            _text(chunk.chunk_id, "Rerank candidate ID")
            _text(chunk.text, "Rerank candidate text", empty=True)
            if len(chunk.text) > config["max_document_chars"]:
                raise ValidationError("Rerank candidate text exceeds limit")
            _unicode(chunk.text)
            ids.append(chunk.chunk_id)
            texts.append(chunk.text)
        if len(query) + sum(map(len, texts)) > config["max_total_chars"]:
            raise ValidationError("Rerank request text exceeds total limit")
        if texts and not query.strip():
            raise ValidationError("Rerank query must be nonblank for nonempty candidates")
        return ids, texts

    def _parse(self, value, ids, limit, config):
        if (
            not isinstance(value, dict)
            or "error" in value
            or "model" in value
            and value["model"] != config["model"]
        ):
            raise ValueError("Unexpected rerank response")
        entries = value.get("results")
        if not isinstance(entries, list) or len(entries) != min(limit, len(ids)):
            raise ValueError("Rerank result count mismatch")
        selected, scores, seen = [], [], set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid rerank result")
            index = entry.get("index")
            if type(index) is not int or not 0 <= index < len(ids) or index in seen:
                raise ValueError("Invalid rerank index")
            seen.add(index)
            selected.append(ids[index])
            scores.append(finite_score(entry.get("relevance_score")))
        meta = value.get("meta")
        if meta is not None and not isinstance(meta, dict):
            raise ValueError("Invalid rerank metadata")
        usage = None if meta is None else meta.get("billed_units")
        if usage is not None:
            if not isinstance(usage, dict) or "search_units" not in usage:
                raise ValueError("Invalid rerank billing")
            usage = {"search_units": usage["search_units"]}
        return RerankResponse(selected, scores, usage)

    async def _request(self, query, ids, texts, limit, config):
        headers = {} if self._api_key is None else {"Authorization": "Bearer " + self._api_key}
        body = {
            "model": config["model"],
            "query": query,
            "documents": texts,
            "top_n": min(limit, len(texts)),
        }
        stream = None
        try:
            async with self._client.stream(
                "POST",
                config["base_url"] + "/rerank",
                json=body,
                headers=headers,
                timeout=config["timeout"],
                follow_redirects=False,
            ) as response:
                stream = _ResponseStream(response.stream)
                self._streams.add(stream)
                response.stream = stream
                if response.status_code != 200:
                    raise ValueError("Unsuccessful rerank response")
                content = bytearray()
                async for data in response.aiter_bytes(chunk_size=65536):
                    if len(content) + len(data) > config["max_response_bytes"]:
                        raise ValueError("Rerank response exceeded bound")
                    content.extend(data)
            self._check()
            return self._parse(json.loads(content), ids, limit, config)
        except DefinitionMismatch:
            raise
        except Exception:
            raise ProviderError("Rerank request failed or returned invalid bounded data") from None
        finally:
            if stream is not None and stream.closed:
                self._streams.discard(stream)

    async def rerank_result(self, query, candidates, *, limit):
        self._ready()
        config = self.identity
        ids, texts = self._inputs(query, candidates, limit, config)
        if not texts:
            return RerankResponse([], [])
        if self._client is None:
            if self._transport is None:
                self._transport = self._transport_pin = _Transport()
            self._client = self._client_pin = httpx.AsyncClient(
                transport=self._transport, follow_redirects=False, trust_env=False
            )
        task = asyncio.current_task()
        self._active.add(task)
        try:
            result = await self._request(query, ids, texts, limit, config)
            self._check()
            return result
        finally:
            self._active.discard(task)

    async def rerank(self, query, candidates, *, limit):
        return tuple((await self.rerank_result(query, candidates, limit=limit)).ids)

    async def aclose(self):
        self._check()
        if self._closed:
            return
        if self._close_active:
            raise ValidationError("Reranker close is already in progress")
        if self._active:
            raise ValidationError("Cannot close reranker while requests are active")
        if self._loop is not None and self._loop is not asyncio.get_running_loop():
            raise ValidationError("Reranker belongs to another event loop")
        self._closing = True
        self._close_active = True
        try:
            for stream in tuple(self._streams):
                await stream.aclose()
                self._streams.discard(stream)
            if self._owned:
                if self._client is not None:
                    await self._client.aclose()
                if self._transport is not None:
                    await self._transport.aclose()
            self._check()
            self._closed = True
        except DefinitionMismatch:
            raise
        except Exception:
            raise ProviderError("Rerank resource close failed; retry aclose") from None
        finally:
            self._close_active = False

    async def __aenter__(self):
        self._ready()
        return self

    async def __aexit__(self, *args):
        await self.aclose()
