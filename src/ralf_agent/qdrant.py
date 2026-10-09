"""Async scoped Cosine index over Qdrant's HTTP API.

Only source identities and vectors are stored here. VectorRetriever hydrates
every hit from the authoritative KnowledgeStore before exposing source text.
Initialization is explicit; this adapter never replaces an existing collection.
"""

import asyncio
import json
import math
import uuid
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import httpx

from .errors import MemoryBackendError, ValidationError
from .retrieval import _integer, _scope, _text
from .types import canonical
from .vector import VectorHit, _entries, _unit

_MAX_RESPONSE_BYTES = 4_000_000
_MISSING = object()


@dataclass(frozen=True)
class _Configuration:
    url: str
    collection: str
    dimensions: int
    backend_id: str
    timeout: float
    api_key: str | None = field(repr=False)


def _url(value):
    _text(value, "Qdrant URL")
    try:
        parsed = urlsplit(value)
        if (
            any(character.isspace() for character in value)
            or parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in value
            or "#" in value
        ):
            raise ValueError
        # Validate ports and HTTP representability without creating a client.
        _ = parsed.port
        httpx.URL(value)
    except (ValueError, httpx.InvalidURL):
        raise ValidationError("Qdrant URL must be HTTP(S) without credentials or query") from None
    return value.rstrip("/")


def _timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("Qdrant timeout must be a finite positive number")
    try:
        value = float(value)
    except OverflowError:
        raise ValidationError("Qdrant timeout must be a finite positive number") from None
    if not math.isfinite(value) or value <= 0:
        raise ValidationError("Qdrant timeout must be a finite positive number")
    return value


def _prefix(scope, namespace):
    prefix = _scope(scope, namespace)
    _text(prefix[0], "Workspace")
    _text(prefix[1], "Principal")
    return prefix


def _filter(prefix, document_id=None):
    conditions = [
        {"key": key, "match": {"value": value}}
        for key, value in zip(("workspace", "principal", "namespace"), prefix, strict=True)
    ]
    if document_id is not None:
        conditions.append({"key": "document_id", "match": {"value": document_id}})
    return {"must": conditions}


def _point_id(prefix, chunk_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, canonical([*prefix, chunk_id])))


class QdrantVectorIndex:
    """Explicit collection configuration, with owned or borrowed async HTTP client.

    An uncertain or partial mutation raises MemoryBackendError. A caller can
    explicitly reindex from authority; automatic retries cannot imply atomicity.
    Supplied clients remain the host's responsibility, including their lifespan.
    """

    def __init__(
        self, url, *, collection, dimensions, backend_id, api_key=None, client=None, timeout=10
    ):
        configuration = _Configuration(
            url=_url(url),
            collection=_text(collection, "Qdrant collection"),
            dimensions=_integer(dimensions, "Index dimensions", minimum=1),
            backend_id=_text(backend_id, "Vector backend identity"),
            timeout=_timeout(timeout),
            api_key=None if api_key is None else _text(api_key, "Qdrant API key"),
        )
        if client is not None and not isinstance(client, httpx.AsyncClient):
            raise ValidationError("Qdrant client must be an httpx.AsyncClient")
        self._configuration = configuration
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(follow_redirects=False)
        self._initialized = False
        self._closed = False
        self._cleanup_complete = False
        self._close_lock = asyncio.Lock()
        self._initialize_lock = asyncio.Lock()

    @property
    def url(self):
        return self._configuration.url

    @property
    def collection(self):
        return self._configuration.collection

    @property
    def dimensions(self):
        return self._configuration.dimensions

    @property
    def backend_id(self):
        return self._configuration.backend_id

    @property
    def timeout(self):
        return self._configuration.timeout

    @property
    def api_key(self):
        return self._configuration.api_key

    @property
    def identity(self):
        return {
            "kind": "qdrant-vector",
            "version": "1",
            "backend": self.backend_id,
            "url": self.url,
            "collection": self.collection,
            "dimensions": self.dimensions,
            "distance": "Cosine",
        }

    def _assert_open(self, *, initialized=True):
        if self._closed:
            raise ValidationError("Qdrant index is closed")
        if initialized and not self._initialized:
            raise ValidationError("Qdrant index requires explicit initialize")

    async def _request(self, method, suffix="", *, body=None, wait=False, allow_missing=False):
        self._assert_open(initialized=False)
        url = f"{self.url}/collections/{quote(self.collection, safe='')}{suffix}"
        try:
            async with self._client.stream(
                method,
                url,
                json=body,
                headers={"api-key": self.api_key} if self.api_key is not None else {},
                params={"wait": "true"} if wait else None,
                timeout=self.timeout,
                follow_redirects=False,
            ) as response:
                if allow_missing and response.status_code == 404:
                    return _MISSING
                if not 200 <= response.status_code < 300:
                    raise MemoryBackendError(f"Qdrant returned HTTP {response.status_code}")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise MemoryBackendError("Qdrant response exceeds limit")
                    content.extend(chunk)
                data = json.loads(content)
                if not isinstance(data, dict) or data.get("status") != "ok" or "result" not in data:
                    raise MemoryBackendError("Qdrant returned an invalid response")
                return data["result"]
        except MemoryBackendError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, RecursionError, RuntimeError):
            raise MemoryBackendError(
                "Qdrant operation failed or returned an invalid response"
            ) from None

    async def initialize(self, create=True):
        """Create if missing, then verify an unnamed Cosine vector configuration."""
        if type(create) is not bool:
            raise ValidationError("Qdrant create must be a boolean")
        self._assert_open(initialized=False)
        async with self._initialize_lock:
            self._assert_open(initialized=False)
            if self._initialized:
                return
            result = await self._request("GET", allow_missing=create)
            if result is _MISSING:
                created = await self._request(
                    "PUT", body={"vectors": {"size": self.dimensions, "distance": "Cosine"}}
                )
                if created is not True:
                    raise MemoryBackendError("Qdrant collection creation did not complete")
                result = await self._request("GET")
            try:
                vectors = result["config"]["params"]["vectors"]
                size = _integer(vectors["size"], "Collection dimensions", minimum=1)
                distance = vectors["distance"]
            except (KeyError, TypeError, ValidationError):
                raise MemoryBackendError(
                    "Qdrant collection has an invalid vector configuration"
                ) from None
            if size != self.dimensions or distance != "Cosine":
                raise ValidationError("Qdrant collection dimensions or metric do not match")
            self._assert_open(initialized=False)
            self._initialized = True

    @staticmethod
    def _completed(result):
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise MemoryBackendError("Qdrant mutation did not complete")

    async def upsert(self, scope, namespace, entries):
        prefix = _prefix(scope, namespace)
        prepared = _entries(entries, self.dimensions)
        self._assert_open()
        if not prepared:
            return
        points = [
            {
                "id": _point_id(prefix, entry.chunk_id),
                "vector": list(unit),
                "payload": {
                    "workspace": prefix[0],
                    "principal": prefix[1],
                    "namespace": prefix[2],
                    "chunk_id": entry.chunk_id,
                    "document_id": entry.document_id,
                    "version": entry.version,
                    "text_digest": entry.text_digest,
                },
            }
            for entry, unit in prepared
        ]
        self._completed(await self._request("PUT", "/points", body={"points": points}, wait=True))

    async def search(self, scope, namespace, vector, *, limit=5):
        prefix = _prefix(scope, namespace)
        query = _unit(vector, self.dimensions)
        _integer(limit, "Vector result limit", minimum=1)
        self._assert_open()
        result = await self._request(
            "POST",
            "/points/query",
            body={
                "query": list(query),
                "filter": _filter(prefix),
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )
        try:
            points = result["points"]
            if not isinstance(points, list) or len(points) > limit:
                raise ValueError
            hits, seen = [], set()
            for point in points:
                payload = point["payload"]
                if any(
                    payload[key] != value
                    for key, value in zip(
                        ("workspace", "principal", "namespace"), prefix, strict=True
                    )
                ):
                    raise ValueError
                hit = VectorHit(
                    payload["chunk_id"],
                    payload["document_id"],
                    payload["version"],
                    payload["text_digest"],
                    point["score"],
                )
                if point["id"] != _point_id(prefix, hit.chunk_id) or hit.chunk_id in seen:
                    raise ValueError
                seen.add(hit.chunk_id)
                hits.append(hit)
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
            raise MemoryBackendError("Qdrant returned invalid or foreign vector hits") from None
        return sorted(hits, key=lambda hit: (-hit.score, hit.document_id, hit.chunk_id))

    async def delete_document(self, scope, namespace, document_id):
        prefix = _prefix(scope, namespace)
        _text(document_id, "Document identity")
        self._assert_open()
        self._completed(
            await self._request(
                "POST", "/points/delete", body={"filter": _filter(prefix, document_id)}, wait=True
            )
        )

    async def aclose(self):
        self._closed = True
        async with self._close_lock:
            if self._cleanup_complete:
                return
            if self._owns_client:
                try:
                    await self._client.aclose()
                except (httpx.HTTPError, RuntimeError):
                    raise MemoryBackendError("Qdrant client close failed") from None
            self._cleanup_complete = True

    async def __aenter__(self):
        self._assert_open(initialized=False)
        return self

    async def __aexit__(self, *args):
        await self.aclose()
