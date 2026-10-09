"""Explicit float embeddings HTTP protocol, bounded requests and owned lifetime."""

import asyncio
import json
import math

import httpx

from .embedding_response import EmbeddingResponse, embedding_usage
from .errors import ProviderError, ValidationError
from .qdrant import _url
from .retrieval import _integer, _text
from .types import canonical
from .vector import _vector


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        model,
        *,
        dimensions,
        base_url="https://api.openai.com/v1",
        api_key=None,
        send_dimensions=False,
        batch_size=32,
        max_text_chars=32768,
        max_batch_chars=262144,
        max_response_bytes=8 * 1024 * 1024,
        timeout=60,
        client=None,
    ):
        _text(model, "Embedding model")
        _integer(dimensions, "Embedding dimensions", minimum=1)
        if dimensions > 65536:
            raise ValidationError("Embedding dimensions exceed limit")
        _integer(batch_size, "Embedding batch size", minimum=1)
        if batch_size > 256:
            raise ValidationError("Embedding batch size exceeds limit")
        for name, value, maximum in [
            ("Text", max_text_chars, 32768),
            ("Batch", max_batch_chars, 262144),
            ("Response", max_response_bytes, 8 * 1024 * 1024),
        ]:
            _integer(value, f"{name} limit", minimum=1)
            if value > maximum:
                raise ValidationError(f"{name} limit exceeds supported range")
        if type(send_dimensions) is not bool:
            raise ValidationError("send_dimensions must be boolean")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 300
            or not math.isfinite(timeout)
        ):
            raise ValidationError("Embedding timeout must be finite in (0,300]")
        if api_key is not None:
            _text(api_key, "Embedding credential")
        if client is not None and not isinstance(client, httpx.AsyncClient):
            raise ValidationError("Borrowed embedding client must be httpx.AsyncClient")
        self._config_json = canonical(
            dict(
                kind="openai-float-embeddings",
                version="1",
                model=model,
                dimensions=dimensions,
                base_url=_url(base_url),
                send_dimensions=send_dimensions,
                batch_size=batch_size,
                max_text_chars=max_text_chars,
                max_batch_chars=max_batch_chars,
                max_response_bytes=max_response_bytes,
                timeout=timeout,
            )
        )
        self._api_key = api_key
        self._client = client
        self._owned = client is None
        self._loop = None
        self._active = set()
        self._closed = False
        self._closing = False

    @property
    def identity(self):
        return json.loads(self._config_json)

    @property
    def dimensions(self):
        return self.identity["dimensions"]

    def _ready(self):
        if self._closed or self._closing:
            raise ValidationError("Embedding provider is closed or closing")
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise ValidationError("Embedding provider belongs to another event loop")
        self._loop = loop

    def _inputs(self, texts, config):
        if (
            not isinstance(texts, list)
            or len(texts) > 4096
            or len(texts) * self.dimensions > 4000000
        ):
            raise ValidationError("Embedding input count/volume exceeds limit")
        if (
            any(
                not isinstance(t, str)
                or not t
                or len(t) > config["max_text_chars"]
                or len(t) > config["max_batch_chars"]
                for t in texts
            )
            or sum(len(t) for t in texts) > 4 * 1024 * 1024
        ):
            raise ValidationError("Embedding requires bounded nonempty text strings")
        try:
            for text in texts:
                text.encode("utf-8")
        except UnicodeError:
            raise ValidationError("Embedding text must contain valid Unicode scalars") from None
        return list(texts)

    async def _batch(self, texts, config):
        body = {"model": config["model"], "input": texts, "encoding_format": "float"}
        if config["send_dimensions"]:
            body["dimensions"] = config["dimensions"]
        headers = {"Authorization": "Bearer " + self._api_key} if self._api_key is not None else {}
        try:
            async with self._client.stream(
                "POST",
                config["base_url"] + "/embeddings",
                json=body,
                headers=headers,
                timeout=config["timeout"],
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise ValueError("Unsuccessful embedding response")
                content = bytearray()
                async for data in response.aiter_bytes(chunk_size=65536):
                    if len(content) + len(data) > config["max_response_bytes"]:
                        raise ValueError("Embedding response exceeded bound")
                    content.extend(data)
            value = json.loads(content)
            if (
                not isinstance(value, dict)
                or "error" in value
                or value.get("model") != config["model"]
                or value.get("object") != "list"
            ):
                raise ValueError("Unexpected embedding response")
            entries = value.get("data")
            if not isinstance(entries, list) or len(entries) != len(texts):
                raise ValueError("Embedding response count mismatch")
            vectors = [None] * len(texts)
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("object") != "embedding":
                    raise ValueError("Invalid embedding entry")
                index = entry.get("index")
                if (
                    type(index) is not int
                    or not 0 <= index < len(texts)
                    or vectors[index] is not None
                ):
                    raise ValueError("Invalid embedding index")
                vectors[index] = list(_vector(entry["embedding"], config["dimensions"]))
            return vectors, embedding_usage(value.get("usage"))
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
            raise ProviderError(
                "Embedding request failed or returned invalid bounded data"
            ) from None

    async def embed_result(self, texts):
        self._ready()
        config = self.identity
        texts = self._inputs(texts, config)
        if not texts:
            return EmbeddingResponse([], [], dimensions=self.dimensions)
        if self._client is None:
            self._client = httpx.AsyncClient(follow_redirects=False)
        task = asyncio.current_task()
        self._active.add(task)
        vectors, usage = [], []
        try:
            batch, chars = [], 0
            for text in texts:
                if batch and (
                    len(batch) >= config["batch_size"]
                    or chars + len(text) > config["max_batch_chars"]
                ):
                    values, measured = await self._batch(batch, config)
                    vectors.extend(values)
                    usage.append(measured)
                    batch, chars = [], 0
                batch.append(text)
                chars += len(text)
            if batch:
                values, measured = await self._batch(batch, config)
                vectors.extend(values)
                usage.append(measured)
            return EmbeddingResponse(vectors, usage, dimensions=config["dimensions"])
        finally:
            self._active.discard(task)

    async def embed(self, texts):
        return (await self.embed_result(texts)).vectors

    async def aclose(self):
        if self._closed:
            return
        if self._active:
            raise ValidationError("Cannot close embedding provider while requests are active")
        if self._loop is not None and self._loop is not asyncio.get_running_loop():
            raise ValidationError("Embedding provider belongs to another event loop")
        self._closing = True
        if self._owned and self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                raise ProviderError("Embedding client close failed; retry aclose") from None
        self._closed = True

    async def __aenter__(self):
        self._ready()
        return self

    async def __aexit__(self, *args):
        await self.aclose()
