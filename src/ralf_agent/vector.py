"""Exact, linear-scan cosine indexes for small local corpora.

There is no default or synthesized embedding provider. Query character limits
bound returned evidence, not embedding fees or corpus scan work.
"""

import copy
import heapq
import json
import math
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from .errors import DefinitionMismatch, ValidationError
from .memory import memory_call
from .ports import is_async_callable
from .retrieval import (
    Chunk,
    DocumentRecord,
    RetrievalQuery,
    _bounded_result,
    _component_identity,
    _integer,
    _retrieved,
    _scope,
    _store_identity,
    _text,
    _validate_chunks,
)
from .storage import SQLiteStore
from .types import canonical, digest


def _vector(values, dimensions=None):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValidationError("Embedding vector must be a non-empty numeric sequence")
    if dimensions is not None and len(values) != dimensions:
        raise ValidationError("Embedding vector dimensions do not match the index")
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError("Embedding vector must contain finite numbers")
        try:
            value = float(value)
        except OverflowError as exc:
            raise ValidationError("Embedding vector must contain finite numbers") from exc
        if not math.isfinite(value):
            raise ValidationError("Embedding vector must contain finite numbers")
        result.append(value)
    if not any(result):
        raise ValidationError("Embedding vector must have a non-zero norm")
    return tuple(result)


def _unit(values, dimensions):
    values = _vector(values, dimensions)
    scale = max(abs(value) for value in values)
    scaled = tuple(value / scale for value in values)
    norm = math.sqrt(sum(value * value for value in scaled))
    return tuple(value / norm for value in scaled)


@dataclass(frozen=True)
class VectorEntry:
    chunk_id: str
    document_id: str
    version: int
    text_digest: str
    vector: tuple[float, ...]

    def __post_init__(self):
        _text(self.chunk_id, "Chunk identity")
        _text(self.document_id, "Document identity")
        _integer(self.version, "Vector source version", minimum=1)
        _text(self.text_digest, "Vector source digest")
        object.__setattr__(self, "vector", _vector(self.vector))


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    document_id: str
    version: int
    text_digest: str
    score: float

    def __post_init__(self):
        _text(self.chunk_id, "Chunk identity")
        _text(self.document_id, "Document identity")
        _integer(self.version, "Vector source version", minimum=1)
        _text(self.text_digest, "Vector source digest")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise ValidationError("Cosine score must be finite")
        try:
            score = float(self.score)
        except OverflowError as exc:
            raise ValidationError("Cosine score must be finite") from exc
        if not math.isfinite(score) or not -1.00000001 <= score <= 1.00000001:
            raise ValidationError("Cosine score must be between -1 and 1")
        object.__setattr__(self, "score", max(-1.0, min(1.0, score)))


class EmbeddingProvider(Protocol):
    identity: dict
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorIndex(Protocol):
    backend_id: str
    dimensions: int

    def upsert(self, scope, namespace, entries) -> None: ...
    def search(self, scope, namespace, vector, *, limit) -> list[VectorHit]: ...
    def delete_document(self, scope, namespace, document_id) -> None: ...


def _entries(entries, dimensions):
    if not isinstance(entries, (list, tuple)) or not all(
        isinstance(entry, VectorEntry) for entry in entries
    ):
        raise ValidationError("Vector writes require VectorEntry values")
    return [(entry, _unit(entry.vector, dimensions)) for entry in entries]


def _hit(entry, unit, query):
    score = max(-1.0, min(1.0, sum(a * b for a, b in zip(unit, query, strict=True))))
    return VectorHit(entry.chunk_id, entry.document_id, entry.version, entry.text_digest, score)


class InMemoryVectorIndex:
    def __init__(self, *, dimensions, backend_id=None):
        self.dimensions = _integer(dimensions, "Index dimensions", minimum=1)
        self.backend_id = backend_id or f"vector-memory:{uuid.uuid4().hex}"
        _text(self.backend_id, "Vector backend identity")
        self._entries = {}
        self._lock = threading.RLock()

    def upsert(self, scope, namespace, entries):
        prefix = _scope(scope, namespace)
        prepared = _entries(entries, self.dimensions)
        with self._lock:
            for entry, unit in prepared:
                self._entries[(*prefix, entry.chunk_id)] = (entry, unit)

    def search(self, scope, namespace, vector, *, limit=5):
        prefix = _scope(scope, namespace)
        query = _unit(vector, self.dimensions)
        _integer(limit, "Vector result limit", minimum=1)
        with self._lock:
            return heapq.nsmallest(
                limit,
                (
                    _hit(entry, unit, query)
                    for key, (entry, unit) in self._entries.items()
                    if key[:3] == prefix
                ),
                key=lambda item: (-item.score, item.document_id, item.chunk_id),
            )

    def delete_document(self, scope, namespace, document_id):
        prefix = _scope(scope, namespace)
        _text(document_id, "Document identity")
        with self._lock:
            self._entries = {
                key: value
                for key, value in self._entries.items()
                if key[:3] != prefix or value[0].document_id != document_id
            }

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class SQLiteVectorIndex:
    def __init__(self, path_or_store, *, dimensions, backend_id=None):
        self.dimensions = _integer(dimensions, "Index dimensions", minimum=1)
        self._owns_store = not isinstance(path_or_store, SQLiteStore)
        self.store = SQLiteStore(path_or_store) if self._owns_store else path_or_store
        try:
            if self.store.readonly:
                raise ValidationError("Vector index requires a writable database")
            self.backend_id = backend_id or f"{self.store.backend_id}:cosine:{dimensions}"
            _text(self.backend_id, "Vector backend identity")
            self.store.conn.executescript("""
                CREATE TABLE IF NOT EXISTS vector_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS vector_entries (
                    workspace TEXT,principal TEXT,namespace TEXT,chunk_id TEXT,
                    document_id TEXT NOT NULL,version INTEGER NOT NULL,text_digest TEXT NOT NULL,vector TEXT NOT NULL,
                    PRIMARY KEY(workspace,principal,namespace,chunk_id));
                CREATE INDEX IF NOT EXISTS vector_document
                    ON vector_entries(workspace,principal,namespace,document_id);
            """)
            with self.store.transaction():
                row = self.store.conn.execute(
                    "SELECT value FROM vector_metadata WHERE key='dimensions'"
                ).fetchone()
                if row is not None and row[0] != str(dimensions):
                    raise ValidationError("Existing vector index dimensions do not match")
                self.store.conn.execute(
                    "INSERT OR IGNORE INTO vector_metadata VALUES ('dimensions',?)",
                    (str(dimensions),),
                )
        except BaseException:
            if self._owns_store:
                self.store.close()
            raise

    def upsert(self, scope, namespace, entries):
        prefix = _scope(scope, namespace)
        prepared = _entries(entries, self.dimensions)
        with self.store.transaction():
            for entry, unit in prepared:
                self.store.conn.execute(
                    "INSERT INTO vector_entries VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(workspace,principal,namespace,chunk_id) DO UPDATE SET "
                    "document_id=excluded.document_id,version=excluded.version,text_digest=excluded.text_digest,vector=excluded.vector",
                    (
                        *prefix,
                        entry.chunk_id,
                        entry.document_id,
                        entry.version,
                        entry.text_digest,
                        canonical(unit),
                    ),
                )

    def search(self, scope, namespace, vector, *, limit=5):
        prefix = _scope(scope, namespace)
        query = _unit(vector, self.dimensions)
        _integer(limit, "Vector result limit", minimum=1)
        self.store._assert_file_identity()
        rows = self.store.conn.execute(
            "SELECT * FROM vector_entries WHERE workspace=? AND principal=? AND namespace=?",
            prefix,
        )

        def hits():
            for row in rows:
                unit = _unit(json.loads(row["vector"]), self.dimensions)
                entry = VectorEntry(
                    row["chunk_id"], row["document_id"], row["version"], row["text_digest"], unit
                )
                yield _hit(entry, unit, query)

        return heapq.nsmallest(
            limit, hits(), key=lambda item: (-item.score, item.document_id, item.chunk_id)
        )

    def delete_document(self, scope, namespace, document_id):
        prefix = _scope(scope, namespace)
        _text(document_id, "Document identity")
        with self.store.transaction():
            self.store.conn.execute(
                "DELETE FROM vector_entries WHERE workspace=? AND principal=? AND namespace=? AND document_id=?",
                (*prefix, document_id),
            )

    def close(self):
        if self._owns_store:
            self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _index_identity(index):
    return {
        "backend": _text(getattr(index, "backend_id", None), "Vector backend identity"),
        "dimensions": _integer(getattr(index, "dimensions", None), "Index dimensions", minimum=1),
    }


def _embedding_identity(embedding):
    return {
        "provider": _component_identity(embedding),
        "dimensions": _integer(
            getattr(embedding, "dimensions", None), "Embedding dimensions", minimum=1
        ),
    }


class VectorRetriever:
    """Index IDs are hydrated from authority; stale hits may reduce result count.

    index_document is explicitly repeatable, but not a cross-service atomic
    transaction. Partial index failures require an explicit reindex. Embedding
    I/O and its cost remain the injected provider/host's responsibility.
    """

    def __init__(self, store, index, embedding):
        self.store, self.index, self.embedding = store, index, embedding
        _store_identity(store)
        if not all(callable(getattr(store, name, None)) for name in ("get", "get_chunk", "chunks")):
            raise ValidationError("Knowledge store must implement authoritative reads")
        if not all(
            callable(getattr(index, name, None)) for name in ("upsert", "search", "delete_document")
        ):
            raise ValidationError("Vector index must implement its configured port")
        if not is_async_callable(getattr(embedding, "embed", None)):
            raise ValidationError("EmbeddingProvider.embed must be async")
        if _index_identity(index)["dimensions"] != _embedding_identity(embedding)["dimensions"]:
            raise ValidationError("Embedding and vector index dimensions do not match")

    @property
    def identity(self):
        return {
            "kind": "vector-retriever",
            "version": "1",
            "store": _store_identity(self.store),
            "index": _index_identity(self.index),
            "embedding": _embedding_identity(self.embedding),
        }

    def index_namespace(self, namespace):
        _text(namespace, "Namespace")
        return "vector:" + digest(
            {"namespace": namespace, "embedding": _embedding_identity(self.embedding)}
        )

    def _capture(self):
        return self.store, self.index, self.embedding, copy.deepcopy(self.identity)

    def _check(self, store, index, embedding, identity):
        if self.store is not store or self.index is not index or self.embedding is not embedding:
            raise DefinitionMismatch("The executing vector retrieval component was replaced")
        actual = {
            "kind": "vector-retriever",
            "version": "1",
            "store": _store_identity(store),
            "index": _index_identity(index),
            "embedding": _embedding_identity(embedding),
        }
        if digest(actual) != digest(identity):
            raise DefinitionMismatch("The executing vector retrieval configuration changed")

    async def _embed(self, embedding, texts, dimensions):
        vectors = await memory_call(embedding.embed, list(texts))
        if not isinstance(vectors, (tuple, list)) or len(vectors) != len(texts):
            raise ValidationError("Embedding provider returned an incorrect vector count")
        return [_vector(vector, dimensions) for vector in vectors]

    async def index_document(self, scope, namespace, document_id):
        _scope(scope, namespace)
        _text(document_id, "Document identity")
        store, index, embedding, identity = self._capture()
        index_namespace = self.index_namespace(namespace)
        record = await memory_call(store.get, scope, namespace, document_id)
        self._check(store, index, embedding, identity)
        if (
            not isinstance(record, DocumentRecord)
            or record.scope != scope
            or record.namespace != namespace
            or record.document_id != document_id
            or (record.expires_at is not None and record.expires_at <= time.time())
        ):
            raise ValidationError("Knowledge source is unavailable")
        chunks = await memory_call(store.chunks, scope, namespace, document_id)
        self._check(store, index, embedding, identity)
        if not isinstance(chunks, (list, tuple)) or any(
            not isinstance(chunk, Chunk)
            or chunk.document_id != document_id
            or chunk.version != record.version
            or chunk.scope != scope
            or chunk.namespace != namespace
            for chunk in chunks
        ):
            raise ValidationError("Knowledge source is unavailable or has changed")
        chunks = tuple(copy.deepcopy(chunk) for chunk in chunks)
        vectors = await self._embed(
            embedding, [chunk.text for chunk in chunks], identity["embedding"]["dimensions"]
        )
        self._check(store, index, embedding, identity)
        await _validate_chunks(store, scope, namespace, chunks)
        current = await memory_call(store.get, scope, namespace, document_id)
        self._check(store, index, embedding, identity)
        if not isinstance(current, DocumentRecord) or current != record:
            raise ValidationError("Knowledge source is unavailable or has changed")
        entries = [
            VectorEntry(chunk.chunk_id, chunk.document_id, chunk.version, chunk.text_digest, vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await memory_call(index.delete_document, scope, index_namespace, document_id)
        self._check(store, index, embedding, identity)
        await memory_call(index.upsert, scope, index_namespace, entries)
        self._check(store, index, embedding, identity)

    async def retrieve(self, scope, namespace, query):
        _scope(scope, namespace)
        if not isinstance(query, RetrievalQuery):
            raise ValidationError("Knowledge retrieval requires RetrievalQuery")
        store, index, embedding, identity = self._capture()
        index_namespace = self.index_namespace(namespace)
        vectors = await self._embed(embedding, [query.text], identity["embedding"]["dimensions"])
        self._check(store, index, embedding, identity)
        hits = await memory_call(
            index.search, scope, index_namespace, vectors[0], limit=query.limit
        )
        self._check(store, index, embedding, identity)
        if (
            not isinstance(hits, (list, tuple))
            or len(hits) > query.limit
            or not all(isinstance(hit, VectorHit) for hit in hits)
        ):
            raise ValidationError("Vector index returned invalid or excessive hits")
        items = []
        for hit in hits:
            chunk = await memory_call(store.get_chunk, scope, namespace, hit.chunk_id)
            self._check(store, index, embedding, identity)
            if not isinstance(chunk, Chunk) or chunk.scope != scope or chunk.namespace != namespace:
                continue
            if (
                chunk.version != hit.version
                or chunk.document_id != hit.document_id
                or chunk.text_digest != hit.text_digest
                or (chunk.expires_at is not None and chunk.expires_at <= time.time())
            ):
                continue
            items.append(_retrieved(chunk, hit.score))
        return _bounded_result(items, query, "vector")

    async def validate(self, scope, namespace, items):
        _scope(scope, namespace)
        store, index, embedding, identity = self._capture()
        await _validate_chunks(store, scope, namespace, tuple(items))
        self._check(store, index, embedding, identity)
