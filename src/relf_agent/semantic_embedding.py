"""Owned HTTP embedding composition with genuine retryable resource release.

The original embedding protocol and existing Profile identities are unchanged.
This explicit semantic-Facts factory resource uses its own tracked transport.
"""

import asyncio

import httpx

from .embedding_http import OpenAIEmbeddingProvider
from .errors import DefinitionMismatch, ProviderError, ValidationError
from .rerank_http import _ResponseStream, _Transport
from .task_controls import _binding
from .tools import _callable_identity
from .types import digest


class _Stream(_ResponseStream):
    def __init__(self, stream, records):
        super().__init__(stream)
        self.records = records

    async def aclose(self):
        await super().aclose()
        self.records.discard(self)


class _Client(httpx.AsyncClient):
    def __init__(self, records, **options):
        self.records = records
        super().__init__(**options)

    async def send(self, *args, **kwargs):
        response = await super().send(*args, **kwargs)
        if kwargs.get("stream", False) and not response.is_closed:
            stream = _Stream(response.stream, self.records)
            self.records.add(stream)
            response.stream = stream
        return response


class ManagedEmbeddingProvider(OpenAIEmbeddingProvider):
    def __init__(self, *args, **options):
        if "client" in options:
            raise ValidationError("Managed embedding owns its explicit HTTP client")
        super().__init__(*args, **options)
        self._client_pin = None
        self._transport = self._transport_pin = None
        self._streams = set()
        self._close_active = False
        self._config_pin, self._key_pin = self._config_json, self._api_key
        self._hooks = {
            name: _binding(getattr(self, name))
            for name in ("embed", "embed_result", "_batch", "_ready", "_inputs", "aclose", "_check")
        }

    def _check(self):
        if (
            self._config_json != self._config_pin
            or self._api_key != self._key_pin
            or self._client is not self._client_pin
            or self._transport is not self._transport_pin
            or not self._owned
            or any(_binding(getattr(self, n)) != pin for n, pin in self._hooks.items())
        ):
            raise DefinitionMismatch("Managed embedding registration changed")

    @property
    def identity(self):
        self._check()
        return {
            **super().identity,
            "lifetime": "explicit-owned-transport-v1",
            "implementation": {
                name: digest(_callable_identity(getattr(self, name))) for name in self._hooks
            },
            "stream_implementation": digest(_callable_identity(_Stream.aclose)),
            "client_implementation": digest(_callable_identity(_Client.send)),
        }

    async def embed_result(self, texts):
        self._check()
        self._ready()
        texts = self._inputs(texts, self.identity)
        if texts and self._client is None:
            if self._transport is None:
                self._transport = self._transport_pin = _Transport()
            self._client = self._client_pin = _Client(
                self._streams, transport=self._transport, follow_redirects=False, trust_env=False
            )
        result = await super().embed_result(texts)
        self._check()
        return result

    async def aclose(self):
        self._check()
        if self._closed:
            return
        if self._close_active or self._active:
            raise ValidationError("Managed embedding close/request is in progress")
        if self._loop is not None and self._loop is not asyncio.get_running_loop():
            raise ValidationError("Managed embedding belongs to another event loop")
        self._closing = self._close_active = True
        try:
            for stream in tuple(self._streams):
                await stream.aclose()
            if self._client is not None:
                await self._client.aclose()
            if self._transport is not None:
                await self._transport.aclose()
            self._check()
            self._closed = True
        except DefinitionMismatch:
            raise
        except Exception:
            raise ProviderError("Managed embedding resource close failed; retry aclose") from None
        finally:
            self._close_active = False
