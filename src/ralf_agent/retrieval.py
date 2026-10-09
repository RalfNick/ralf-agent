"""Scoped plaintext knowledge and bounded lexical retrieval, not semantic search.

SQLite is coordinator-thread affine. Injected remote stores can implement the
same methods asynchronously. Scope is trusted host input, not enterprise ACL.
"""

import copy
import json
import math
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .errors import DefinitionMismatch, ValidationError
from .memory import memory_call
from .storage import SQLiteStore
from .types import Scope, canonical, digest


class KnowledgeVersionConflict(ValidationError):
    code = "knowledge_version_conflict"


def _text(value, label, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValidationError(f"{label} must be a {'string' if empty else 'non-empty string'}")
    return value


def _integer(value, label, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValidationError(f"{label} must be an integer of at least {minimum}")
    return value


def _expiry(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("expires_at must be finite Unix seconds or None")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValidationError("expires_at must be finite Unix seconds or None") from exc
    if not math.isfinite(result):
        raise ValidationError("expires_at must be finite Unix seconds or None")
    return result


def _scope(scope, namespace):
    if not isinstance(scope, Scope):
        raise ValidationError("Knowledge access requires a trusted Scope")
    _text(namespace, "Namespace")
    return scope.workspace, scope.principal, namespace


class _MetadataView:
    """Nested metadata access is a detached view, including on frozen DTOs."""

    def __getattribute__(self, name):
        value = object.__getattribute__(self, name)
        return copy.deepcopy(value) if name == "metadata" else value

    def _validate_metadata(self):
        metadata = object.__getattribute__(self, "metadata")
        if not isinstance(metadata, dict):
            raise ValidationError("Document metadata must be a finite JSON object")
        canonical(metadata)
        object.__setattr__(self, "metadata", copy.deepcopy(metadata))


@dataclass(frozen=True)
class Document(_MetadataView):
    document_id: str
    text: str
    source_uri: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        _text(self.document_id, "Document identity")
        _text(self.text, "Document text", empty=True)
        _text(self.source_uri, "Source URI", empty=True)
        self._validate_metadata()


@dataclass(frozen=True, kw_only=True)
class DocumentRecord(Document):
    version: int
    expires_at: float | None
    scope: Scope
    namespace: str

    def __post_init__(self):
        super().__post_init__()
        _integer(self.version, "Document version", minimum=1)
        _scope(self.scope, self.namespace)
        object.__setattr__(self, "expires_at", _expiry(self.expires_at))


@dataclass(frozen=True)
class Chunk(_MetadataView):
    document_id: str
    chunk_id: str
    version: int
    text: str
    source_uri: str
    metadata: dict
    expires_at: float | None
    scope: Scope
    namespace: str

    def __post_init__(self):
        _text(self.document_id, "Document identity")
        _text(self.chunk_id, "Chunk identity")
        _integer(self.version, "Chunk version", minimum=1)
        _text(self.text, "Chunk text", empty=True)
        _text(self.source_uri, "Source URI", empty=True)
        self._validate_metadata()
        _scope(self.scope, self.namespace)
        object.__setattr__(self, "expires_at", _expiry(self.expires_at))

    @property
    def text_digest(self):
        return digest(self.text)


@dataclass(frozen=True)
class RetrievedChunk(Chunk):
    score: float = 0.0

    def __post_init__(self):
        super().__post_init__()
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise ValidationError("Retrieval score must be finite")
        try:
            score = float(self.score)
        except OverflowError as exc:
            raise ValidationError("Retrieval score must be finite") from exc
        if not math.isfinite(score):
            raise ValidationError("Retrieval score must be finite")
        object.__setattr__(self, "score", score)


@dataclass(frozen=True)
class RetrievalQuery:
    text: str
    limit: int = 5
    max_chars: int = 8000

    def __post_init__(self):
        _text(self.text, "Query text", empty=True)
        _integer(self.limit, "Retrieval limit", minimum=1)
        if self.limit > 2**63 - 1:
            raise ValidationError("Retrieval limit exceeds the supported integer range")
        _integer(self.max_chars, "Retrieval character budget", minimum=2)


@dataclass(frozen=True)
class RetrievalResult:
    items: tuple[RetrievedChunk, ...]
    mode: str
    used_chars: int

    def __post_init__(self):
        if not isinstance(self.items, (tuple, list)) or not all(
            isinstance(item, RetrievedChunk) for item in self.items
        ):
            raise ValidationError("Retrieval items must be RetrievedChunk values")
        _text(self.mode, "Retrieval mode")
        _integer(self.used_chars, "Retrieval character count")
        object.__setattr__(self, "items", tuple(copy.deepcopy(item) for item in self.items))
        canonical([asdict(item) for item in self.items])


class KnowledgeStore(Protocol):
    backend_id: str

    def put(
        self, scope, namespace, document: Document, *, expected_version, expires_at=None
    ) -> int: ...
    def get(self, scope, namespace, document_id) -> DocumentRecord | None: ...
    def get_chunk(self, scope, namespace, chunk_id) -> Chunk | None: ...
    def chunks(self, scope, namespace, document_id) -> list[Chunk]: ...
    def delete(self, scope, namespace, document_id, *, expected_version) -> int: ...
    def lexical(self, scope, namespace, query: RetrievalQuery) -> RetrievalResult: ...


class KnowledgeRetriever(Protocol):
    identity: dict

    async def retrieve(self, scope, namespace, query: RetrievalQuery) -> RetrievalResult: ...
    async def validate(self, scope, namespace, items) -> None: ...


class KnowledgeContextPort(Protocol):
    identity: dict
    limit: int
    max_chars: int

    async def references(self, scope: Scope, text: str) -> list[dict]: ...
    async def validate(self, scope: Scope, references: list[dict]) -> None: ...


def _tokens(text):
    tokens = set()
    for word in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text.lower()):
        if "\u3400" <= word[0] <= "\u9fff":
            tokens.update(word[i : i + 2] for i in range(max(1, len(word) - 1)))
        else:
            tokens.add(word)
    return tokens


def _chunk_config(chunk_size, overlap):
    _integer(chunk_size, "Chunk size", minimum=1)
    _integer(overlap, "Chunk overlap")
    if overlap >= chunk_size:
        raise ValidationError("Chunk overlap must be smaller than chunk size")


def _make_chunks(record, chunk_size, overlap):
    result = []
    start = 0
    while start < len(record.text):
        end = min(start + chunk_size, len(record.text))
        result.append(
            Chunk(
                record.document_id,
                digest([record.document_id, record.version, start]),
                record.version,
                record.text[start:end],
                record.source_uri,
                record.metadata,
                record.expires_at,
                record.scope,
                record.namespace,
            )
        )
        if end == len(record.text):
            break
        start += chunk_size - overlap
    return result


def _retrieved(chunk, score):
    return RetrievedChunk(
        chunk.document_id,
        chunk.chunk_id,
        chunk.version,
        chunk.text,
        chunk.source_uri,
        chunk.metadata,
        chunk.expires_at,
        chunk.scope,
        chunk.namespace,
        score,
    )


def _items_chars(items):
    return len(canonical([asdict(item) for item in items])) if items else 0


def _bounded_result(items, query, mode):
    selected = []
    for item in items:
        if len(selected) >= query.limit:
            break
        if _items_chars([*selected, item]) <= query.max_chars:
            selected.append(item)
    return RetrievalResult(tuple(selected), mode, _items_chars(selected))


def _validate_result(result, scope, namespace, query):
    if not isinstance(result, RetrievalResult):
        raise ValidationError("Retriever must return RetrievalResult")
    result = RetrievalResult(result.items, result.mode, result.used_chars)
    if len(result.items) > query.limit or _items_chars(result.items) > query.max_chars:
        raise ValidationError("Retriever exceeded the requested item or character budget")
    if result.used_chars != _items_chars(result.items):
        raise ValidationError("Retriever reported an incorrect character count")
    if any(item.scope != scope or item.namespace != namespace for item in result.items):
        raise ValidationError("Knowledge source is unavailable in the requested scope")
    return result


class InMemoryKnowledgeStore:
    def __init__(self, *, chunk_size=1000, overlap=100, backend_id=None):
        _chunk_config(chunk_size, overlap)
        self.chunk_size, self.overlap = chunk_size, overlap
        self.backend_id = backend_id or f"knowledge-memory:{uuid.uuid4().hex}"
        _text(self.backend_id, "Knowledge backend identity")
        self._versions, self._documents, self._chunks = {}, {}, {}
        self._ingestions = {}
        self._lock = threading.RLock()

    def put(self, scope, namespace, document, *, expected_version, expires_at=None):
        return self._put(
            scope, namespace, document, expected_version=expected_version, expires_at=expires_at
        )

    def ingestion_receipt(self, scope, namespace, command_id):
        from .knowledge_ingestion import memory_receipt

        return memory_receipt(self, scope, namespace, command_id)

    def ingest(self, scope, namespace, prepared, *, command_id):
        from .knowledge_ingestion import memory_ingest

        return memory_ingest(self, scope, namespace, prepared, command_id=command_id)

    def _put(self, scope, namespace, document, *, expected_version, expires_at=None, prepared=None):
        prefix = _scope(scope, namespace)
        if not isinstance(document, Document):
            raise ValidationError("Knowledge writes require a Document")
        _integer(expected_version, "Expected document version")
        expires_at = _expiry(expires_at)
        identity = (*prefix, document.document_id)
        with self._lock:
            actual = self._versions.get(identity, 0)
            if actual != expected_version:
                raise KnowledgeVersionConflict("Knowledge document version conflict")
            record = DocumentRecord(
                document.document_id,
                document.text,
                document.source_uri,
                document.metadata,
                version=actual + 1,
                expires_at=expires_at,
                scope=scope,
                namespace=namespace,
            )
            chunks = (
                _make_chunks(record, self.chunk_size, self.overlap)
                if prepared is None
                else prepared.chunks(record)
            )
            self._versions[identity] = record.version
            self._documents[identity] = record
            self._chunks[identity] = chunks
            return record.version

    def get(self, scope, namespace, document_id):
        identity = (*_scope(scope, namespace), _text(document_id, "Document identity"))
        with self._lock:
            record = self._documents.get(identity)
            if record is None or (
                record.expires_at is not None and record.expires_at <= time.time()
            ):
                return None
            return copy.deepcopy(record)

    def chunks(self, scope, namespace, document_id):
        identity = (*_scope(scope, namespace), _text(document_id, "Document identity"))
        with self._lock:
            return (
                copy.deepcopy(self._chunks.get(identity, []))
                if self.get(scope, namespace, document_id)
                else []
            )

    def get_chunk(self, scope, namespace, chunk_id):
        prefix = _scope(scope, namespace)
        _text(chunk_id, "Chunk identity")
        with self._lock:
            for identity, chunks in self._chunks.items():
                if identity[:3] == prefix and self.get(scope, namespace, identity[3]):
                    for chunk in chunks:
                        if chunk.chunk_id == chunk_id:
                            return copy.deepcopy(chunk)
        return None

    def delete(self, scope, namespace, document_id, *, expected_version):
        identity = (*_scope(scope, namespace), _text(document_id, "Document identity"))
        _integer(expected_version, "Expected document version")
        with self._lock:
            actual = self._versions.get(identity, 0)
            if actual != expected_version:
                raise KnowledgeVersionConflict("Knowledge document version conflict")
            self._versions[identity] = actual + 1
            self._documents[identity] = None
            self._chunks.pop(identity, None)
            return actual + 1

    def lexical(self, scope, namespace, query):
        prefix = _scope(scope, namespace)
        if not isinstance(query, RetrievalQuery):
            raise ValidationError("Knowledge retrieval requires RetrievalQuery")
        tokens, candidates = _tokens(query.text), []
        with self._lock:
            for identity, chunks in self._chunks.items():
                if identity[:3] != prefix or self.get(scope, namespace, identity[3]) is None:
                    continue
                for chunk in chunks:
                    score = len(tokens & _tokens(chunk.text))
                    if score:
                        candidates.append(_retrieved(chunk, score))
        candidates.sort(key=lambda item: (-item.score, item.document_id, item.chunk_id))
        return _bounded_result(candidates[: query.limit], query, "lexical")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class SQLiteKnowledgeStore:
    def __init__(self, path_or_store, *, chunk_size=1000, overlap=100, backend_id=None):
        _chunk_config(chunk_size, overlap)
        self.chunk_size, self.overlap = chunk_size, overlap
        self._owns_store = not isinstance(path_or_store, SQLiteStore)
        self.store = SQLiteStore(path_or_store) if self._owns_store else path_or_store
        try:
            if self.store.readonly:
                raise ValidationError("Knowledge store requires a writable database")
            self.backend_id = (
                backend_id or f"{self.store.backend_id}:knowledge:{chunk_size}:{overlap}"
            )
            _text(self.backend_id, "Knowledge backend identity")
            self.store.conn.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_ingestions (
                    workspace TEXT, principal TEXT, namespace TEXT, command_id TEXT,
                    request_digest TEXT NOT NULL, receipt TEXT NOT NULL,
                    PRIMARY KEY(workspace,principal,namespace,command_id));
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    workspace TEXT, principal TEXT, namespace TEXT, document_id TEXT,
                    version INTEGER NOT NULL, text TEXT NOT NULL, source_uri TEXT NOT NULL,
                    metadata TEXT NOT NULL, expires_at REAL, deleted INTEGER NOT NULL,
                    PRIMARY KEY(workspace,principal,namespace,document_id));
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    workspace TEXT, principal TEXT, namespace TEXT, chunk_id TEXT,
                    document_id TEXT NOT NULL, version INTEGER NOT NULL, position INTEGER NOT NULL,
                    text TEXT NOT NULL, source_uri TEXT NOT NULL, metadata TEXT NOT NULL, expires_at REAL,
                    PRIMARY KEY(workspace,principal,namespace,chunk_id));
                CREATE INDEX IF NOT EXISTS knowledge_chunk_document
                    ON knowledge_chunks(workspace,principal,namespace,document_id,position);
                CREATE TABLE IF NOT EXISTS knowledge_terms (
                    workspace TEXT, principal TEXT, namespace TEXT, chunk_id TEXT, term TEXT,
                    PRIMARY KEY(workspace,principal,namespace,chunk_id,term));
                CREATE INDEX IF NOT EXISTS knowledge_term_lookup
                    ON knowledge_terms(workspace,principal,namespace,term,chunk_id);
            """)
        except BaseException:
            if self._owns_store:
                self.store.close()
            raise

    def _remove_chunks(self, prefix, document_id):
        self.store.conn.execute(
            "DELETE FROM knowledge_terms WHERE workspace=? AND principal=? AND namespace=? AND chunk_id IN "
            "(SELECT chunk_id FROM knowledge_chunks WHERE workspace=? AND principal=? AND namespace=? AND document_id=?)",
            (*prefix, *prefix, document_id),
        )
        self.store.conn.execute(
            "DELETE FROM knowledge_chunks WHERE workspace=? AND principal=? AND namespace=? AND document_id=?",
            (*prefix, document_id),
        )

    def put(self, scope, namespace, document, *, expected_version, expires_at=None):
        return self._put(
            scope, namespace, document, expected_version=expected_version, expires_at=expires_at
        )

    def ingestion_receipt(self, scope, namespace, command_id):
        from .knowledge_ingestion import sqlite_receipt

        return sqlite_receipt(self, scope, namespace, command_id)

    def ingest(self, scope, namespace, prepared, *, command_id):
        from .knowledge_ingestion import sqlite_ingest

        return sqlite_ingest(self, scope, namespace, prepared, command_id=command_id)

    def _put(self, scope, namespace, document, *, expected_version, expires_at=None, prepared=None):
        prefix = _scope(scope, namespace)
        if not isinstance(document, Document):
            raise ValidationError("Knowledge writes require a Document")
        _integer(expected_version, "Expected document version")
        expires_at = _expiry(expires_at)
        with self.store.transaction():
            row = self.store.conn.execute(
                "SELECT version FROM knowledge_documents WHERE workspace=? AND principal=? AND namespace=? AND document_id=?",
                (*prefix, document.document_id),
            ).fetchone()
            actual = row[0] if row else 0
            if actual != expected_version:
                raise KnowledgeVersionConflict("Knowledge document version conflict")
            record = DocumentRecord(
                document.document_id,
                document.text,
                document.source_uri,
                document.metadata,
                version=actual + 1,
                expires_at=expires_at,
                scope=scope,
                namespace=namespace,
            )
            chunks = (
                _make_chunks(record, self.chunk_size, self.overlap)
                if prepared is None
                else prepared.chunks(record)
            )
            self.store.conn.execute(
                "INSERT INTO knowledge_documents VALUES (?,?,?,?,?,?,?,?,?,0) "
                "ON CONFLICT(workspace,principal,namespace,document_id) DO UPDATE SET "
                "version=excluded.version,text=excluded.text,source_uri=excluded.source_uri,"
                "metadata=excluded.metadata,expires_at=excluded.expires_at,deleted=0",
                (
                    *prefix,
                    record.document_id,
                    record.version,
                    record.text,
                    record.source_uri,
                    canonical(record.metadata),
                    record.expires_at,
                ),
            )
            self._remove_chunks(prefix, record.document_id)
            for position, chunk in enumerate(chunks):
                self.store.conn.execute(
                    "INSERT INTO knowledge_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        *prefix,
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.version,
                        position,
                        chunk.text,
                        chunk.source_uri,
                        canonical(chunk.metadata),
                        chunk.expires_at,
                    ),
                )
                self.store.conn.executemany(
                    "INSERT INTO knowledge_terms VALUES (?,?,?,?,?)",
                    [(*prefix, chunk.chunk_id, term) for term in sorted(_tokens(chunk.text))],
                )
            return record.version

    def get(self, scope, namespace, document_id):
        prefix = _scope(scope, namespace)
        self.store._assert_file_identity()
        row = self.store.conn.execute(
            "SELECT * FROM knowledge_documents WHERE workspace=? AND principal=? AND namespace=? AND document_id=? "
            "AND deleted=0 AND (expires_at IS NULL OR expires_at>?)",
            (*prefix, _text(document_id, "Document identity"), time.time()),
        ).fetchone()
        if row is None:
            return None
        return DocumentRecord(
            row["document_id"],
            row["text"],
            row["source_uri"],
            json.loads(row["metadata"]),
            version=row["version"],
            expires_at=row["expires_at"],
            scope=scope,
            namespace=namespace,
        )

    def _chunk(self, row, scope, namespace):
        return Chunk(
            row["document_id"],
            row["chunk_id"],
            row["version"],
            row["text"],
            row["source_uri"],
            json.loads(row["metadata"]),
            row["expires_at"],
            scope,
            namespace,
        )

    def _active_chunks(self, prefix, condition, value):
        self.store._assert_file_identity()
        return self.store.conn.execute(
            "SELECT c.* FROM knowledge_chunks c JOIN knowledge_documents d "
            "ON c.workspace=d.workspace AND c.principal=d.principal AND c.namespace=d.namespace "
            "AND c.document_id=d.document_id AND c.version=d.version "
            f"WHERE c.workspace=? AND c.principal=? AND c.namespace=? AND c.{condition}=? "
            "AND d.deleted=0 AND (d.expires_at IS NULL OR d.expires_at>?) ORDER BY c.position",
            (*prefix, value, time.time()),
        )

    def get_chunk(self, scope, namespace, chunk_id):
        prefix = _scope(scope, namespace)
        row = self._active_chunks(prefix, "chunk_id", _text(chunk_id, "Chunk identity")).fetchone()
        return self._chunk(row, scope, namespace) if row else None

    def chunks(self, scope, namespace, document_id):
        prefix = _scope(scope, namespace)
        return [
            self._chunk(row, scope, namespace)
            for row in self._active_chunks(
                prefix, "document_id", _text(document_id, "Document identity")
            )
        ]

    def delete(self, scope, namespace, document_id, *, expected_version):
        prefix = _scope(scope, namespace)
        _text(document_id, "Document identity")
        _integer(expected_version, "Expected document version")
        with self.store.transaction():
            row = self.store.conn.execute(
                "SELECT version FROM knowledge_documents WHERE workspace=? AND principal=? AND namespace=? AND document_id=?",
                (*prefix, document_id),
            ).fetchone()
            actual = row[0] if row else 0
            if actual != expected_version:
                raise KnowledgeVersionConflict("Knowledge document version conflict")
            self.store.conn.execute(
                "INSERT INTO knowledge_documents VALUES (?,?,?,?,?,'','','{}',NULL,1) "
                "ON CONFLICT(workspace,principal,namespace,document_id) DO UPDATE SET "
                "version=excluded.version,text='',source_uri='',metadata='{}',expires_at=NULL,deleted=1",
                (*prefix, document_id, actual + 1),
            )
            self._remove_chunks(prefix, document_id)
            return actual + 1

    def lexical(self, scope, namespace, query):
        prefix = _scope(scope, namespace)
        self.store._assert_file_identity()
        if not isinstance(query, RetrievalQuery):
            raise ValidationError("Knowledge retrieval requires RetrievalQuery")
        tokens = sorted(_tokens(query.text))
        if not tokens:
            return RetrievalResult((), "lexical", 0)
        placeholders = ",".join("?" for _ in tokens)
        rows = self.store.conn.execute(
            "SELECT c.*,COUNT(*) AS score FROM knowledge_terms t JOIN knowledge_chunks c "
            "ON t.workspace=c.workspace AND t.principal=c.principal AND t.namespace=c.namespace AND t.chunk_id=c.chunk_id "
            "JOIN knowledge_documents d ON c.workspace=d.workspace AND c.principal=d.principal "
            "AND c.namespace=d.namespace AND c.document_id=d.document_id AND c.version=d.version "
            "WHERE c.workspace=? AND c.principal=? AND c.namespace=? "
            f"AND t.term IN ({placeholders}) AND d.deleted=0 AND (d.expires_at IS NULL OR d.expires_at>?) "
            "GROUP BY c.workspace,c.principal,c.namespace,c.chunk_id "
            "ORDER BY score DESC,c.document_id,c.chunk_id LIMIT ?",
            (*prefix, *tokens, time.time(), query.limit),
        )
        return _bounded_result(
            [_retrieved(self._chunk(row, scope, namespace), row["score"]) for row in rows],
            query,
            "lexical",
        )

    def close(self):
        if self._owns_store:
            self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _store_identity(store):
    return {
        "backend": _text(getattr(store, "backend_id", None), "Knowledge backend identity"),
        "chunk_size": getattr(store, "chunk_size", None),
        "overlap": getattr(store, "overlap", None),
    }


def _component_identity(component):
    identity = getattr(component, "identity", None)
    if not isinstance(identity, dict) or not identity:
        raise ValidationError("Knowledge components require a non-empty JSON identity")
    canonical(identity)
    return copy.deepcopy(identity)


def _check_store(owner, captured, identity):
    if owner.store is not captured or digest(_store_identity(captured)) != digest(identity):
        raise DefinitionMismatch("The executing knowledge store changed during the operation")


async def _validate_chunks(store, scope, namespace, items):
    for item in items:
        if not isinstance(item, Chunk) or item.scope != scope or item.namespace != namespace:
            raise ValidationError("Knowledge source is unavailable in the requested scope")
        current = await memory_call(store.get_chunk, scope, namespace, item.chunk_id)
        if (
            not isinstance(current, Chunk)
            or (current.expires_at is not None and current.expires_at <= time.time())
            or any(
                getattr(current, name) != getattr(item, name)
                for name in (
                    "document_id",
                    "chunk_id",
                    "version",
                    "text",
                    "source_uri",
                    "metadata",
                    "expires_at",
                    "scope",
                    "namespace",
                )
            )
        ):
            raise ValidationError("Knowledge source is unavailable or has changed")
    _validate_expiry(items)


def _validate_expiry(items):
    # A later asynchronous source read can outlive an earlier source's TTL.
    # Recheck every known expiry after the last await, before disclosure.
    now = time.time()
    if any(item.expires_at is not None and item.expires_at <= now for item in items):
        raise ValidationError("Knowledge source is unavailable or has expired")


class LexicalRetriever:
    def __init__(self, store):
        self.store = store
        _store_identity(store)
        if not all(callable(getattr(store, name, None)) for name in ("lexical", "get_chunk")):
            raise ValidationError("Knowledge store must provide lexical and get_chunk")

    @property
    def identity(self):
        return {"kind": "lexical-retriever", "version": "1", "store": _store_identity(self.store)}

    async def retrieve(self, scope, namespace, query):
        _scope(scope, namespace)
        store, identity = self.store, _store_identity(self.store)
        result = await memory_call(store.lexical, scope, namespace, query)
        _check_store(self, store, identity)
        return _validate_result(result, scope, namespace, query)

    async def validate(self, scope, namespace, items):
        _scope(scope, namespace)
        store, identity = self.store, _store_identity(self.store)
        await _validate_chunks(store, scope, namespace, tuple(items))
        _check_store(self, store, identity)


class KnowledgeContext:
    """Bounded, provenance-preserving façade; it does not own the retriever."""

    def __init__(self, retriever, *, namespace="default", limit=5, max_chars=8000):
        self.retriever = retriever
        self.namespace, self.limit, self.max_chars = namespace, limit, max_chars
        _text(namespace, "Namespace")
        RetrievalQuery("", limit, max_chars)
        _component_identity(retriever)
        if not all(callable(getattr(retriever, name, None)) for name in ("retrieve", "validate")):
            raise ValidationError("Knowledge retriever must implement retrieve and validate")

    @property
    def identity(self):
        return {
            "kind": "knowledge-context",
            "version": "1",
            "retriever": _component_identity(self.retriever),
            "namespace": self.namespace,
            "limit": self.limit,
            "max_chars": self.max_chars,
        }

    def _capture(self):
        return self.retriever, _component_identity(self.retriever), copy.deepcopy(self.identity)

    def _check(self, captured, retriever_identity, context_identity):
        if (
            self.retriever is not captured
            or digest(_component_identity(captured)) != digest(retriever_identity)
            or digest(self.identity) != digest(context_identity)
        ):
            raise DefinitionMismatch(
                "The executing knowledge retriever changed during the operation"
            )

    async def references(self, scope, text):
        _scope(scope, self.namespace)
        retriever, identity, configuration = self._capture()
        namespace = self.namespace
        query = RetrievalQuery(text, self.limit, self.max_chars)
        result = await memory_call(retriever.retrieve, scope, namespace, query)
        self._check(retriever, identity, configuration)
        result = _validate_result(result, scope, namespace, query)
        references = []
        for item in result.items:
            reference = {
                "key": "knowledge:" + item.chunk_id,
                "version": item.version,
                "value": {
                    "text": item.text,
                    "document_id": item.document_id,
                    "source_uri": item.source_uri,
                    "metadata": item.metadata,
                },
                "_knowledge": {
                    "scope": asdict(scope),
                    "namespace": namespace,
                    "document_id": item.document_id,
                    "chunk_id": item.chunk_id,
                    "version": item.version,
                    "text_digest": item.text_digest,
                    "expires_at": item.expires_at,
                },
            }
            if len(canonical([*references, reference])) <= query.max_chars:
                references.append(reference)
        return references

    async def validate(self, scope, references):
        retriever, identity, configuration = self._capture()
        _scope(scope, self.namespace)
        if not isinstance(references, (list, tuple)):
            raise ValidationError("Knowledge source is unavailable: invalid references")
        chunks = []
        try:
            canonical(references)
            if len(references) > self.limit or (
                references and len(canonical(references)) > self.max_chars
            ):
                raise ValidationError("Knowledge references exceeded the configured budget")
            for reference in references:
                source, value = reference["_knowledge"], reference["value"]
                if source["scope"] != asdict(scope) or source["namespace"] != self.namespace:
                    raise ValidationError("Knowledge source is unavailable in the requested scope")
                if (
                    reference["key"] != "knowledge:" + source["chunk_id"]
                    or reference["version"] != source["version"]
                    or value["document_id"] != source["document_id"]
                    or digest(value["text"]) != source["text_digest"]
                ):
                    raise ValidationError("Knowledge source is unavailable: reference changed")
                chunks.append(
                    Chunk(
                        source["document_id"],
                        source["chunk_id"],
                        source["version"],
                        value["text"],
                        value["source_uri"],
                        value["metadata"],
                        source["expires_at"],
                        scope,
                        self.namespace,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Knowledge source is unavailable: invalid references") from exc
        outcome = await memory_call(retriever.validate, scope, self.namespace, tuple(chunks))
        self._check(retriever, identity, configuration)
        if outcome is not None:
            raise ValidationError("Knowledge validation must return None")
        _validate_expiry(chunks)
