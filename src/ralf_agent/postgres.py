"""Native async PostgreSQL memory and plaintext knowledge adapters.

Install the ``postgres`` extra and call ``initialize()`` explicitly before use.
Borrowed psycopg AsyncConnections must already use autocommit and remain owned
by their caller. Adapter transactions on a shared connection are serialized;
callers must not independently use that connection during an adapter operation.
"""

import asyncio
import inspect
import json
import time
import weakref
from contextlib import asynccontextmanager
from dataclasses import asdict

from .errors import IdempotencyConflict, MemoryBackendError, RalfError, ValidationError
from .memory import _session_cursor, _validate_expires_at
from .recall import _binding, _current_fact, _decode_cursor, _fact_inputs, _integer, _name, _page
from .retrieval import (
    Chunk,
    Document,
    DocumentRecord,
    KnowledgeVersionConflict,
    RetrievalQuery,
    RetrievalResult,
    _bounded_result,
    _chunk_config,
    _expiry,
    _make_chunks,
    _retrieved,
    _scope,
    _text,
    _tokens,
)
from .types import Scope, canonical, digest

_CONNECTION_LOCKS = weakref.WeakKeyDictionary()

_MEMORY_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ralf_memory_sessions (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, session TEXT NOT NULL,
        revision BIGINT NOT NULL CHECK (revision >= 0),
        PRIMARY KEY (workspace,principal,session))""",
    """CREATE TABLE IF NOT EXISTS ralf_memory_messages (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, session TEXT NOT NULL,
        seq BIGINT NOT NULL CHECK (seq >= 1), message_id TEXT NOT NULL, data TEXT NOT NULL,
        PRIMARY KEY (workspace,principal,session,seq),
        UNIQUE (workspace,principal,session,message_id))""",
    """CREATE TABLE IF NOT EXISTS ralf_memory_facts (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, namespace TEXT NOT NULL,
        key TEXT NOT NULL, value TEXT NOT NULL, version BIGINT NOT NULL CHECK (version >= 1),
        expires_at DOUBLE PRECISION, position BIGSERIAL NOT NULL UNIQUE,
        PRIMARY KEY (workspace,principal,namespace,key))""",
    """CREATE INDEX IF NOT EXISTS ralf_memory_fact_recall
        ON ralf_memory_facts (workspace,principal,namespace,position)""",
    """CREATE TABLE IF NOT EXISTS ralf_memory_fact_generations (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, namespace TEXT NOT NULL,
        generation BIGINT NOT NULL CHECK (generation >= 0),
        PRIMARY KEY (workspace,principal,namespace))""",
)

_KNOWLEDGE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ralf_knowledge_documents (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, namespace TEXT NOT NULL,
        document_id TEXT NOT NULL, version BIGINT NOT NULL CHECK (version >= 1),
        text TEXT NOT NULL, source_uri TEXT NOT NULL, metadata TEXT NOT NULL,
        expires_at DOUBLE PRECISION, deleted BOOLEAN NOT NULL,
        PRIMARY KEY (workspace,principal,namespace,document_id))""",
    """CREATE TABLE IF NOT EXISTS ralf_knowledge_chunks (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, namespace TEXT NOT NULL,
        chunk_id TEXT NOT NULL, document_id TEXT NOT NULL,
        version BIGINT NOT NULL CHECK (version >= 1), position BIGINT NOT NULL,
        text TEXT NOT NULL, source_uri TEXT NOT NULL, metadata TEXT NOT NULL,
        expires_at DOUBLE PRECISION,
        PRIMARY KEY (workspace,principal,namespace,chunk_id))""",
    """CREATE INDEX IF NOT EXISTS ralf_knowledge_chunk_document
        ON ralf_knowledge_chunks (workspace,principal,namespace,document_id,position)""",
    """CREATE TABLE IF NOT EXISTS ralf_knowledge_terms (
        workspace TEXT NOT NULL, principal TEXT NOT NULL, namespace TEXT NOT NULL,
        chunk_id TEXT NOT NULL, term TEXT NOT NULL,
        PRIMARY KEY (workspace,principal,namespace,chunk_id,term))""",
    """CREATE INDEX IF NOT EXISTS ralf_knowledge_term_lookup
        ON ralf_knowledge_terms (workspace,principal,namespace,term,chunk_id)""",
)


def _prefix(scope, name):
    if not isinstance(scope, Scope):
        raise ValidationError("Memory access requires a trusted Scope")
    _name(name, "Memory namespace or session")
    return scope.workspace, scope.principal, name


def _version(value, label):
    # Leave room for the increment in PostgreSQL's signed bigint representation.
    _integer(value, label, 0, 2**63 - 2)


def _advisory_key(key):
    value = int(digest(["ralf-postgres-v1", *key])[:16], 16)
    return value if value < 2**63 else value - 2**64


async def _connect(dsn):
    _name(dsn, "PostgreSQL DSN")
    try:
        from psycopg import AsyncConnection
    except ImportError as exc:
        raise MemoryBackendError("PostgreSQL requires the optional postgres dependency") from exc
    try:
        return await AsyncConnection.connect(dsn, autocommit=True)
    except Exception as exc:
        raise MemoryBackendError("PostgreSQL connection failed") from exc


class _PostgresAdapter:
    def __init__(self, connection, *, backend_id, owns_connection=False):
        _name(backend_id, "PostgreSQL backend identity")
        if type(owns_connection) is not bool:
            raise ValidationError("PostgreSQL connection ownership must be a boolean")
        if not all(
            callable(getattr(connection, name, None)) for name in ("cursor", "transaction", "close")
        ):
            raise ValidationError("PostgreSQL requires an async connection")
        if not inspect.iscoroutinefunction(connection.close):
            raise ValidationError("PostgreSQL requires an async connection")
        if getattr(connection, "autocommit", None) is not True:
            raise ValidationError("PostgreSQL adapters require an autocommit connection")
        try:
            lock = _CONNECTION_LOCKS.get(connection)
            if lock is None:
                lock = asyncio.Lock()
                _CONNECTION_LOCKS[connection] = lock
        except TypeError as exc:
            raise ValidationError("PostgreSQL connection must support weak references") from exc
        self.connection = connection
        self.backend_id = backend_id
        self._lock = lock
        self._owns_connection = owns_connection
        self._closed = False

    @asynccontextmanager
    async def _transaction(self, key=None):
        async with self._lock:
            if self._closed:
                raise MemoryBackendError("PostgreSQL adapter is closed")
            try:
                async with self.connection.transaction():
                    await self._execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    if key is not None:
                        # Acquired before reading CAS state, including when no row exists.
                        # Every writer hashes the domain/scope/key, independent of backend_id.
                        await self._execute(
                            "SELECT pg_advisory_xact_lock(%s)", (_advisory_key(key),)
                        )
                    yield
            except RalfError:
                raise
            except Exception as exc:
                raise MemoryBackendError("PostgreSQL backend operation failed") from exc

    async def _execute(self, statement, parameters=(), *, fetch=None, many=False):
        from psycopg.rows import tuple_row

        async with self.connection.cursor(row_factory=tuple_row) as cursor:
            if many:
                await cursor.executemany(statement, parameters)
            else:
                await cursor.execute(statement, parameters)
            if fetch == "one":
                return await cursor.fetchone()
            if fetch == "all":
                return await cursor.fetchall()
            return None

    async def _initialize(self, schema):
        async with self._transaction(("schema",)):
            for statement in schema:
                await self._execute(statement)

    async def aclose(self):
        async with self._lock:
            if self._closed:
                return
            if self._owns_connection:
                try:
                    await self.connection.close()
                except Exception as exc:
                    raise MemoryBackendError("PostgreSQL connection close failed") from exc
            self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()


class PostgresMemory(_PostgresAdapter):
    """Scoped sessions, versioned facts, bounded recall and fact validation."""

    fact_inspection_version = 1

    session_receipt_version = 1

    async def inspect_message(self, scope, session_id, message_id):
        from .session_receipts import validate_inspection

        prefix = _prefix(scope, session_id)
        _name(message_id, "Message identity")
        async with self._transaction(("session", *prefix)):
            row = await self._execute(
                "SELECT revision FROM ralf_memory_sessions "
                "WHERE workspace=%s AND principal=%s AND session=%s",
                prefix,
                fetch="one",
            )
            saved = await self._execute(
                "SELECT seq,data FROM ralf_memory_messages "
                "WHERE workspace=%s AND principal=%s AND session=%s AND message_id=%s",
                (*prefix, message_id),
                fetch="one",
            )
            return validate_inspection(
                {
                    "scope": asdict(scope),
                    "session_id": session_id,
                    "message_id": message_id,
                    "revision": row[0] if row else 0,
                    "receipt": {"revision": saved[0], "message": json.loads(saved[1])}
                    if saved
                    else None,
                },
                scope,
                session_id,
                message_id,
            )

    @classmethod
    async def connect(cls, dsn, *, backend_id):
        _name(backend_id, "PostgreSQL backend identity")
        connection = await _connect(dsn)
        try:
            return cls(connection, backend_id=backend_id, owns_connection=True)
        except BaseException:
            await connection.close()
            raise

    async def initialize(self):
        from .postgres_fact_scan import SCAN_SCHEMA

        await self._initialize([*_MEMORY_SCHEMA, SCAN_SCHEMA])

    fact_scan_version = 1

    async def fact_snapshot(self, scope, namespace):
        from .postgres_fact_scan import fact_snapshot

        return await fact_snapshot(self, scope, namespace)

    async def scan_facts(self, scope, namespace, query):
        from .postgres_fact_scan import scan_facts

        return await scan_facts(self, scope, namespace, query)

    async def read(self, scope, session_id):
        prefix = _prefix(scope, session_id)
        async with self._transaction(("session", *prefix)):
            row = await self._execute(
                "SELECT revision FROM ralf_memory_sessions "
                "WHERE workspace=%s AND principal=%s AND session=%s",
                prefix,
                fetch="one",
            )
            rows = await self._execute(
                "SELECT data FROM ralf_memory_messages "
                "WHERE workspace=%s AND principal=%s AND session=%s ORDER BY seq",
                prefix,
                fetch="all",
            )
            return (row[0] if row else 0), [json.loads(item[0]) for item in rows]

    async def append(self, scope, session_id, message, *, expected_revision, message_id):
        prefix = _prefix(scope, session_id)
        _version(expected_revision, "Expected session revision")
        _name(message_id, "Message identity")
        if not isinstance(message, dict):
            raise ValidationError("Session messages must be JSON objects")
        payload = canonical(message)
        async with self._transaction(("session", *prefix)):
            duplicate = await self._execute(
                "SELECT seq,data FROM ralf_memory_messages "
                "WHERE workspace=%s AND principal=%s AND session=%s AND message_id=%s",
                (*prefix, message_id),
                fetch="one",
            )
            if duplicate:
                if duplicate[1] != payload:
                    raise IdempotencyConflict("Message identity conflict")
                return duplicate[0]
            row = await self._execute(
                "SELECT revision FROM ralf_memory_sessions "
                "WHERE workspace=%s AND principal=%s AND session=%s",
                prefix,
                fetch="one",
            )
            actual = row[0] if row else 0
            if actual != expected_revision:
                raise ValidationError("Session revision conflict")
            await self._execute(
                "INSERT INTO ralf_memory_messages "
                "(workspace,principal,session,seq,message_id,data) VALUES (%s,%s,%s,%s,%s,%s)",
                (*prefix, actual + 1, message_id, payload),
            )
            await self._execute(
                "INSERT INTO ralf_memory_sessions (workspace,principal,session,revision) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (workspace,principal,session) "
                "DO UPDATE SET revision=EXCLUDED.revision",
                (*prefix, actual + 1),
            )
            return actual + 1

    async def read_page(self, scope, session_id, query):
        binding = _binding(self.backend_id, scope, "session", session_id, query)
        prefix = _prefix(scope, session_id)
        async with self._transaction(("session", *prefix)):
            row = await self._execute(
                "SELECT revision FROM ralf_memory_sessions "
                "WHERE workspace=%s AND principal=%s AND session=%s",
                prefix,
                fetch="one",
            )
            snapshot, before = _session_cursor(query, binding, 0, row[0] if row else 0)
            rows = await self._execute(
                "SELECT seq,data FROM ralf_memory_messages "
                "WHERE workspace=%s AND principal=%s AND session=%s AND seq<%s AND seq<=%s "
                "ORDER BY seq DESC LIMIT %s",
                (*prefix, before, snapshot["revision"], query.scan_limit),
                fetch="all",
            )
            has_more = (
                bool(rows)
                and await self._execute(
                    "SELECT 1 FROM ralf_memory_messages "
                    "WHERE workspace=%s AND principal=%s AND session=%s AND seq<%s AND seq<=%s LIMIT 1",
                    (*prefix, rows[-1][0], snapshot["revision"]),
                    fetch="one",
                )
                is not None
            )
            return _page(
                [(seq, json.loads(data)) for seq, data in rows],
                query,
                "session",
                binding,
                snapshot,
                has_more=has_more,
            )

    @staticmethod
    def _fact(row):
        return {"key": row[0], "value": json.loads(row[1]), "version": row[2], "expires_at": row[3]}

    async def facts(self, scope, namespace):
        prefix = _prefix(scope, namespace)
        async with self._transaction(("facts", *prefix)):
            rows = await self._execute(
                "SELECT key,value,version,expires_at FROM ralf_memory_facts "
                "WHERE workspace=%s AND principal=%s AND namespace=%s "
                "AND (expires_at IS NULL OR expires_at>%s) ORDER BY key",
                (*prefix, time.time()),
                fetch="all",
            )
            return [self._fact(row) for row in rows]

    async def inspect_fact(self, scope, namespace, key):
        prefix = _prefix(scope, namespace)
        _name(key, "Fact key")
        async with self._transaction(("facts", *prefix)):
            row = await self._execute(
                "SELECT key,value,version,expires_at FROM ralf_memory_facts WHERE workspace=%s AND principal=%s AND namespace=%s AND key=%s",
                (*prefix, key),
                fetch="one",
            )
            return None if row is None else self._fact(row)

    async def put_fact(self, scope, namespace, key, value, *, expected_version, expires_at=None):
        prefix = _prefix(scope, namespace)
        _name(key, "Fact key")
        _version(expected_version, "Expected fact version")
        expires_at = _validate_expires_at(expires_at)
        payload = canonical(value)
        async with self._transaction(("facts", *prefix)):
            row = await self._execute(
                "SELECT version FROM ralf_memory_facts "
                "WHERE workspace=%s AND principal=%s AND namespace=%s AND key=%s",
                (*prefix, key),
                fetch="one",
            )
            actual = row[0] if row else 0
            if actual != expected_version:
                raise ValidationError("Fact version conflict")
            await self._execute(
                "INSERT INTO ralf_memory_facts "
                "(workspace,principal,namespace,key,value,version,expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (workspace,principal,namespace,key) "
                "DO UPDATE SET value=EXCLUDED.value,version=EXCLUDED.version,expires_at=EXCLUDED.expires_at",
                (*prefix, key, payload, actual + 1, expires_at),
            )
            await self._execute(
                "INSERT INTO ralf_memory_fact_generations (workspace,principal,namespace,generation) "
                "VALUES (%s,%s,%s,1) ON CONFLICT (workspace,principal,namespace) "
                "DO UPDATE SET generation=ralf_memory_fact_generations.generation+1",
                prefix,
            )
            return actual + 1

    async def recall(self, scope, namespace, query):
        binding = _binding(self.backend_id, scope, "facts", namespace, query)
        prefix = _prefix(scope, namespace)
        async with self._transaction(("facts", *prefix)):
            row = await self._execute(
                "SELECT generation FROM ralf_memory_fact_generations "
                "WHERE workspace=%s AND principal=%s AND namespace=%s",
                prefix,
                fetch="one",
            )
            snapshot = {"generation": row[0] if row else 0}
            after = 0
            decoded = _decode_cursor(query.cursor, binding)
            if decoded is not None:
                previous, after = decoded
                if set(previous) != {"generation"}:
                    raise ValidationError("Fact recall snapshot is invalid")
                _integer(previous["generation"], "Fact generation")
                if previous != snapshot:
                    raise ValidationError("Fact recall snapshot is no longer available")
            rows = await self._execute(
                "SELECT position,key,value,version,expires_at FROM ralf_memory_facts "
                "WHERE workspace=%s AND principal=%s AND namespace=%s AND position>%s "
                "ORDER BY position LIMIT %s",
                (*prefix, after, query.scan_limit),
                fetch="all",
            )
            has_more = (
                bool(rows)
                and await self._execute(
                    "SELECT 1 FROM ralf_memory_facts "
                    "WHERE workspace=%s AND principal=%s AND namespace=%s AND position>%s LIMIT 1",
                    (*prefix, rows[-1][0]),
                    fetch="one",
                )
                is not None
            )
            return _page(
                [(row[0], self._fact(row[1:])) for row in rows],
                query,
                "facts",
                binding,
                snapshot,
                has_more=has_more,
            )

    async def validate_facts(self, scope, namespace, items):
        references = _fact_inputs(scope, namespace, items)
        prefix = _prefix(scope, namespace)
        async with self._transaction(("facts", *prefix)):
            checked = []
            for reference in references:
                row = await self._execute(
                    "SELECT version,expires_at FROM ralf_memory_facts "
                    "WHERE workspace=%s AND principal=%s AND namespace=%s AND key=%s",
                    (*prefix, reference["key"]),
                    fetch="one",
                )
                if row is None:
                    raise ValidationError("Fact reference is no longer current")
                checked.append((reference, row))
            now = time.time()
            for reference, (version, expiry) in checked:
                _current_fact(reference, version, expiry, now)


class PostgresKnowledgeStore(_PostgresAdapter):
    """Versioned scoped documents and chunks with a bounded lexical baseline."""

    def __init__(
        self, connection, *, backend_id, chunk_size=1000, overlap=100, owns_connection=False
    ):
        _chunk_config(chunk_size, overlap)
        super().__init__(connection, backend_id=backend_id, owns_connection=owns_connection)
        self.chunk_size, self.overlap = chunk_size, overlap

    @classmethod
    async def connect(cls, dsn, *, backend_id, chunk_size=1000, overlap=100):
        _name(backend_id, "PostgreSQL backend identity")
        _chunk_config(chunk_size, overlap)
        connection = await _connect(dsn)
        try:
            return cls(
                connection,
                backend_id=backend_id,
                chunk_size=chunk_size,
                overlap=overlap,
                owns_connection=True,
            )
        except BaseException:
            await connection.close()
            raise

    async def initialize(self):
        from .postgres_ingestion import INGESTION_SCHEMA

        await self._initialize([*_KNOWLEDGE_SCHEMA, INGESTION_SCHEMA])

    async def _remove_chunks(self, prefix, document_id):
        await self._execute(
            "DELETE FROM ralf_knowledge_terms WHERE workspace=%s AND principal=%s AND namespace=%s "
            "AND chunk_id IN (SELECT chunk_id FROM ralf_knowledge_chunks "
            "WHERE workspace=%s AND principal=%s AND namespace=%s AND document_id=%s)",
            (*prefix, *prefix, document_id),
        )
        await self._execute(
            "DELETE FROM ralf_knowledge_chunks "
            "WHERE workspace=%s AND principal=%s AND namespace=%s AND document_id=%s",
            (*prefix, document_id),
        )

    async def put(self, scope, namespace, document, *, expected_version, expires_at=None):
        prefix = _scope(scope, namespace)
        if not isinstance(document, Document):
            raise ValidationError("Knowledge writes require a Document")
        _version(expected_version, "Expected document version")
        expires_at = _expiry(expires_at)
        async with self._transaction(("document", *prefix, document.document_id)):
            return await self._write_document(prefix, document, expected_version, expires_at)

    async def ingestion_receipt(self, scope, namespace, command_id):
        from .postgres_ingestion import postgres_receipt

        return await postgres_receipt(self, scope, namespace, command_id)

    async def ingest(self, scope, namespace, prepared, *, command_id):
        from .postgres_ingestion import postgres_ingest

        return await postgres_ingest(self, scope, namespace, prepared, command_id=command_id)

    async def _write_document(self, prefix, document, expected_version, expires_at, prepared=None):
        row = await self._execute(
            "SELECT version FROM ralf_knowledge_documents "
            "WHERE workspace=%s AND principal=%s AND namespace=%s AND document_id=%s",
            (*prefix, document.document_id),
            fetch="one",
        )
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
            scope=Scope(prefix[0], prefix[1]),
            namespace=prefix[2],
        )
        chunks = (
            _make_chunks(record, self.chunk_size, self.overlap)
            if prepared is None
            else prepared.chunks(record)
        )
        await self._execute(
            "INSERT INTO ralf_knowledge_documents "
            "(workspace,principal,namespace,document_id,version,text,source_uri,metadata,expires_at,deleted) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE) "
            "ON CONFLICT (workspace,principal,namespace,document_id) DO UPDATE SET "
            "version=EXCLUDED.version,text=EXCLUDED.text,source_uri=EXCLUDED.source_uri,"
            "metadata=EXCLUDED.metadata,expires_at=EXCLUDED.expires_at,deleted=FALSE",
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
        await self._remove_chunks(prefix, record.document_id)
        if chunks:
            await self._execute(
                "INSERT INTO ralf_knowledge_chunks "
                "(workspace,principal,namespace,chunk_id,document_id,version,position,text,source_uri,metadata,expires_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
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
                    )
                    for position, chunk in enumerate(chunks)
                ],
                many=True,
            )
            terms = [
                (*prefix, chunk.chunk_id, term)
                for chunk in chunks
                for term in sorted(_tokens(chunk.text))
            ]
            if terms:
                await self._execute(
                    "INSERT INTO ralf_knowledge_terms "
                    "(workspace,principal,namespace,chunk_id,term) VALUES (%s,%s,%s,%s,%s)",
                    terms,
                    many=True,
                )
        return record.version

    async def get(self, scope, namespace, document_id):
        prefix = _scope(scope, namespace)
        _text(document_id, "Document identity")
        async with self._transaction(("document", *prefix, document_id)):
            row = await self._execute(
                "SELECT document_id,text,source_uri,metadata,version,expires_at "
                "FROM ralf_knowledge_documents "
                "WHERE workspace=%s AND principal=%s AND namespace=%s AND document_id=%s "
                "AND deleted=FALSE AND (expires_at IS NULL OR expires_at>%s)",
                (*prefix, document_id, time.time()),
                fetch="one",
            )
            if row is None:
                return None
            return DocumentRecord(
                row[0],
                row[1],
                row[2],
                json.loads(row[3]),
                version=row[4],
                expires_at=row[5],
                scope=scope,
                namespace=namespace,
            )

    @staticmethod
    def _chunk(row, scope, namespace):
        return Chunk(
            row[0], row[1], row[2], row[3], row[4], json.loads(row[5]), row[6], scope, namespace
        )

    async def _read_chunks(self, scope, namespace, identity, *, single):
        prefix = _scope(scope, namespace)
        _text(identity, "Chunk identity" if single else "Document identity")
        # The joined statement sees one database snapshot, including source version/TTL.
        condition = "c.chunk_id=%s" if single else "c.document_id=%s"
        async with self._transaction():
            rows = await self._execute(
                "SELECT c.document_id,c.chunk_id,c.version,c.text,c.source_uri,c.metadata,c.expires_at "
                "FROM ralf_knowledge_chunks c JOIN ralf_knowledge_documents d "
                "ON c.workspace=d.workspace AND c.principal=d.principal AND c.namespace=d.namespace "
                "AND c.document_id=d.document_id AND c.version=d.version "
                "WHERE c.workspace=%s AND c.principal=%s AND c.namespace=%s "
                f"AND {condition} AND d.deleted=FALSE AND (d.expires_at IS NULL OR d.expires_at>%s) "
                "ORDER BY c.position",
                (*prefix, identity, time.time()),
                fetch="all",
            )
            return [self._chunk(row, scope, namespace) for row in rows]

    async def chunks(self, scope, namespace, document_id):
        return await self._read_chunks(scope, namespace, document_id, single=False)

    async def get_chunk(self, scope, namespace, chunk_id):
        chunks = await self._read_chunks(scope, namespace, chunk_id, single=True)
        return chunks[0] if chunks else None

    async def delete(self, scope, namespace, document_id, *, expected_version):
        prefix = _scope(scope, namespace)
        _text(document_id, "Document identity")
        _version(expected_version, "Expected document version")
        async with self._transaction(("document", *prefix, document_id)):
            row = await self._execute(
                "SELECT version FROM ralf_knowledge_documents "
                "WHERE workspace=%s AND principal=%s AND namespace=%s AND document_id=%s",
                (*prefix, document_id),
                fetch="one",
            )
            actual = row[0] if row else 0
            if actual != expected_version:
                raise KnowledgeVersionConflict("Knowledge document version conflict")
            await self._execute(
                "INSERT INTO ralf_knowledge_documents "
                "(workspace,principal,namespace,document_id,version,text,source_uri,metadata,expires_at,deleted) "
                "VALUES (%s,%s,%s,%s,%s,'','','{}',NULL,TRUE) "
                "ON CONFLICT (workspace,principal,namespace,document_id) DO UPDATE SET "
                "version=EXCLUDED.version,text='',source_uri='',metadata='{}',expires_at=NULL,deleted=TRUE",
                (*prefix, document_id, actual + 1),
            )
            await self._remove_chunks(prefix, document_id)
            return actual + 1

    async def lexical(self, scope, namespace, query):
        prefix = _scope(scope, namespace)
        if not isinstance(query, RetrievalQuery):
            raise ValidationError("Knowledge retrieval requires RetrievalQuery")
        tokens = sorted(_tokens(query.text))
        if not tokens:
            return RetrievalResult((), "lexical", 0)
        async with self._transaction():
            rows = await self._execute(
                "SELECT c.document_id,c.chunk_id,c.version,c.text,c.source_uri,c.metadata,c.expires_at,"
                "COUNT(*) AS score FROM ralf_knowledge_terms t JOIN ralf_knowledge_chunks c "
                "ON t.workspace=c.workspace AND t.principal=c.principal AND t.namespace=c.namespace "
                "AND t.chunk_id=c.chunk_id JOIN ralf_knowledge_documents d "
                "ON c.workspace=d.workspace AND c.principal=d.principal AND c.namespace=d.namespace "
                "AND c.document_id=d.document_id AND c.version=d.version "
                "WHERE c.workspace=%s AND c.principal=%s AND c.namespace=%s AND t.term=ANY(%s) "
                "AND d.deleted=FALSE AND (d.expires_at IS NULL OR d.expires_at>%s) "
                "GROUP BY c.workspace,c.principal,c.namespace,c.chunk_id "
                "ORDER BY score DESC,c.document_id,c.chunk_id LIMIT %s",
                (*prefix, tokens, time.time(), query.limit),
                fetch="all",
            )
            return _bounded_result(
                [_retrieved(self._chunk(row[:7], scope, namespace), row[7]) for row in rows],
                query,
                "lexical",
            )
