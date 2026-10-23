"""Explicit offline reference using an independent persistent source.

No built-in KnowledgeStore/Retriever participates in this adapter. Its lexical
selection is only a contract/wiring example, not a semantic relevance baseline.
"""

import asyncio
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .retrieval import Chunk, RetrievalQuery, RetrievalResult, RetrievedChunk
from .types import Scope, canonical


class ReferenceKnowledgeSource:
    """An application-owned SQLite document source, outside the SDK store ports."""

    def __init__(self, path):
        self.path = str(Path(path).resolve())
        self._original_path = self.path
        self._closed = False
        self._dependents = []
        self._file_descriptor = None
        self._file_unavailable = False
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS sources (workspace TEXT, principal TEXT, "
                "namespace TEXT, document_id TEXT, version INTEGER, text TEXT, "
                "source_uri TEXT, metadata TEXT, expires_at REAL, deleted INTEGER, "
                "PRIMARY KEY(workspace,principal,namespace,document_id));"
                "CREATE TABLE IF NOT EXISTS audit (kind TEXT PRIMARY KEY,count INTEGER);"
            )
        finally:
            connection.close()
        descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            value = os.fstat(descriptor)
            self._file_identity = value.st_dev, value.st_ino
            self._check_file()
        except BaseException:
            os.close(descriptor)
            raise
        self._file_descriptor = descriptor

    def _check_file(self):
        if self._file_unavailable:
            raise DefinitionMismatch("The original reference source file is unavailable")
        try:
            value = os.stat(self._original_path, follow_symlinks=False)
        except OSError:
            self._file_unavailable = True
            raise DefinitionMismatch("The original reference source file is unavailable") from None
        if not stat.S_ISREG(value.st_mode) or (value.st_dev, value.st_ino) != self._file_identity:
            self._file_unavailable = True
            raise DefinitionMismatch("The actual reference source file changed")

    @contextmanager
    def _connection(self):
        # Protect this known source's physical file, without reflecting arbitrary
        # external Python clients or introducing another execution authority.
        self._check_file()
        connection = sqlite3.connect(self._original_path)
        try:
            self._check_file()
            with connection:
                yield connection
                self._check_file()
        finally:
            connection.close()
        self._check_file()

    def _check(self):
        if self.path != self._original_path:
            raise DefinitionMismatch("The reference source resource changed")
        if self._closed:
            raise ValidationError("The reference source is closed")
        self._check_file()

    def count(self, kind):
        self._check()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO audit VALUES (?,1) ON CONFLICT(kind) DO UPDATE SET count=count+1",
                (kind,),
            )

    def put(
        self, scope, namespace, document_id, text, *, source_uri="", metadata=None, expires_at=None
    ):
        self._check()
        # Public Chunk performs the same finite metadata/expiry/value checks.
        record = Chunk(
            document_id,
            document_id + ":0",
            1,
            text,
            source_uri,
            {} if metadata is None else metadata,
            expires_at,
            scope,
            namespace,
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prefix = (scope.workspace, scope.principal, namespace, document_id)
            previous = connection.execute(
                "SELECT version FROM sources WHERE workspace=? AND principal=? "
                "AND namespace=? AND document_id=?",
                prefix,
            ).fetchone()
            version = 1 if previous is None else previous[0] + 1
            connection.execute(
                "INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?,?,0)",
                (
                    *prefix,
                    version,
                    record.text,
                    record.source_uri,
                    canonical(record.metadata),
                    record.expires_at,
                ),
            )
        return version

    def delete(self, scope, namespace, document_id):
        self._check()
        with self._connection() as connection:
            connection.execute(
                "UPDATE sources SET version=version+1,deleted=1 WHERE "
                "workspace=? AND principal=? AND namespace=? AND document_id=?",
                (scope.workspace, scope.principal, namespace, document_id),
            )

    def expire(self, scope, namespace, document_id):
        self._check()
        with self._connection() as connection:
            connection.execute(
                "UPDATE sources SET expires_at=? WHERE "
                "workspace=? AND principal=? AND namespace=? AND document_id=?",
                (time.time() - 1, scope.workspace, scope.principal, namespace, document_id),
            )

    def read(self, scope, namespace):
        self._check()
        if not isinstance(scope, Scope) or not isinstance(namespace, str) or not namespace.strip():
            raise ValidationError("Reference access requires Scope and namespace")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT document_id,version,text,source_uri,metadata,expires_at "
                "FROM sources WHERE workspace=? AND principal=? AND namespace=? "
                "AND deleted=0 ORDER BY document_id",
                (scope.workspace, scope.principal, namespace),
            ).fetchall()
        return tuple(
            Chunk(
                row[0],
                row[0] + ":0",
                row[1],
                row[2],
                row[3],
                json.loads(row[4]),
                row[5],
                scope,
                namespace,
            )
            for row in rows
        )

    def audit(self):
        # Audit is intentionally available after close for lifecycle evidence.
        with self._connection() as connection:
            counts = dict(connection.execute("SELECT kind,count FROM audit"))
        return {
            "retrieval": counts.get("retrieval", 0),
            "validation": counts.get("validation", 0),
            "retrieve_calls": counts.get("retrieval", 0),
            "validate_calls": counts.get("validation", 0),
            "source_checks": counts.get("source_checks", 0),
            "close_calls": counts.get("close", 0),
            "model_calls": counts.get("model", 0),
            "backend_switches": counts.get("backend_switches", 0),
        }

    def close(self):
        if not self._closed or self._dependents:
            try:
                while self._dependents:
                    self._dependents[-1].close()
                    self._dependents.pop()
                if not self._closed:
                    try:
                        self.count("close")
                    except DefinitionMismatch:
                        # Never write an audit to a replacement file.
                        pass
            finally:
                if self._file_descriptor is not None:
                    os.close(self._file_descriptor)
                    self._file_descriptor = None
                self._closed = True

    async def aclose(self):
        self.close()


class ReferenceSQLiteRetriever:
    """Structural synchronous Retriever with scoped source revalidation."""

    def __init__(self, source):
        if not isinstance(source, ReferenceKnowledgeSource):
            raise ValidationError("The reference adapter requires its own source")
        self.source = source
        self._original_source = source
        self.source_path = source.path
        self._fault = None
        self._identity_version = "1"

    @property
    def identity(self):
        return {
            "kind": "external-sqlite-reference",
            "version": self._identity_version,
            "source": self.source_path,
        }

    def _check(self):
        if self.source is not self._original_source or self.source.path != self.source_path:
            raise DefinitionMismatch("The actual reference backend changed")
        self.source._check()
        if self._fault == "backend-error":
            raise RuntimeError("Private reference backend failure")
        if self._fault == "authorization-denied":
            raise AuthorizationDenied("Reference source access denied")

    def retrieve(self, scope, namespace, query):
        self._check()
        if not isinstance(query, RetrievalQuery):
            raise ValidationError("Reference retrieval requires RetrievalQuery")
        self.source.count("retrieval")
        terms = set(re.findall(r"\w+", query.text.casefold()))
        selected = []
        for item in self.source.read(scope, namespace):
            if item.expires_at is not None and item.expires_at <= time.time():
                continue
            score = len(terms & set(re.findall(r"\w+", item.text.casefold())))
            if not score:
                continue
            candidate = RetrievedChunk(
                **{field: getattr(item, field) for field in Chunk.__dataclass_fields__},
                score=float(score),
            )
            if (
                len(selected) < query.limit
                and len(canonical([asdict(x) for x in [*selected, candidate]])) <= query.max_chars
            ):
                selected.append(candidate)
        self._check()
        used = len(canonical([asdict(item) for item in selected])) if selected else 0
        return RetrievalResult(tuple(selected), "offline-lexical-reference", used)

    def validate(self, scope, namespace, items):
        self._check()
        self.source.count("validation")
        current = {item.chunk_id: item for item in self.source.read(scope, namespace)}
        fields = tuple(Chunk.__dataclass_fields__)
        for item in items:
            self.source.count("source_checks")
            source = current.get(getattr(item, "chunk_id", None))
            if (
                not isinstance(item, Chunk)
                or source is None
                or any(getattr(source, field) != getattr(item, field) for field in fields)
                or (item.expires_at is not None and item.expires_at <= time.time())
            ):
                raise ValidationError("The original reference source is unavailable or changed")
        self._check()
        return True if self._fault == "invalid-validation-return" else None


class AsyncReferenceSQLiteRetriever(ReferenceSQLiteRetriever):
    """Actual await boundaries for lifecycle, expiry and drift contract probes."""

    def __init__(self, source):
        super().__init__(source)
        self._pauses = {}

    async def _paused(self, operation):
        pause = self._pauses.get(operation)
        if pause is None:
            await asyncio.sleep(0)
        else:
            entered, release = pause
            entered.set()
            await release.wait()
        self._check()

    async def retrieve(self, scope, namespace, query):
        result = super().retrieve(scope, namespace, query)
        await self._paused("retrieve")
        return result

    async def validate(self, scope, namespace, items):
        result = super().validate(scope, namespace, items)
        await self._paused("validate")
        return result


class OfflineKnowledgeFixture:
    """Explicit independently implemented, offline K01–K12 management fixture."""

    def prepare(self, case_id, workspace):
        source = ReferenceKnowledgeSource(Path(workspace) / "external-source.sqlite")
        try:
            return self._prepare(case_id, workspace, source)
        except BaseException:
            # No Session has returned, so the role has no owner to clean up.
            source.close()
            raise

    def _prepare(self, case_id, workspace, source):
        from .knowledge_adapter_contract import (
            KnowledgeContractPause,
            KnowledgeContractResource,
            KnowledgeContractSession,
            KnowledgeContractSource,
        )

        adapter = AsyncReferenceSQLiteRetriever(source)
        sources = []
        expiry = time.time() + 0.8 if case_id == "K07" else None
        for scope in (Scope("contract", "owner"), Scope("contract", "foreign")):
            for namespace in ("manuals", "operations"):
                source.put(
                    scope,
                    namespace,
                    "cache",
                    "cache timeout inspect connection pool " + namespace,
                    source_uri="reference://" + namespace + "/cache",
                    metadata={"category": namespace},
                    expires_at=expiry,
                )
                sources.append(
                    KnowledgeContractSource(
                        scope,
                        namespace,
                        RetrievalQuery("cache", limit=3, max_chars=4000),
                        source.read(scope, namespace),
                    )
                )

        def mutate(item, operation):
            if operation == "replace":
                source.put(
                    item.scope,
                    item.namespace,
                    item.document_id,
                    "cache revised source",
                    source_uri=item.source_uri,
                    metadata=item.metadata,
                )
            elif operation == "delete":
                source.delete(item.scope, item.namespace, item.document_id)
            elif operation == "expire":
                source.expire(item.scope, item.namespace, item.document_id)
            else:
                raise ValidationError("Unsupported reference source mutation")

        alternate = None
        original_retrieve = adapter.retrieve

        def fault(kind):
            nonlocal alternate
            if kind == "backend-swap":
                source.count("backend_switches")
                alternate = ReferenceKnowledgeSource(Path(workspace) / "other-source.sqlite")
                source._dependents.append(alternate)
                adapter.source = alternate
            elif kind == "reset":
                adapter.source = source
                adapter._fault = None
                adapter._identity_version = "1"
                adapter.retrieve = original_retrieve
                if alternate is not None:
                    alternate.close()
                    alternate = None
            elif kind == "identity-drift":
                adapter._identity_version = "changed"
            elif kind == "method-drift":

                async def replacement(scope, namespace, query):
                    return await original_retrieve(scope, namespace, query)

                adapter.retrieve = replacement
            elif kind in {"backend-error", "authorization-denied", "invalid-validation-return"}:
                adapter._fault = kind
            else:
                raise ValidationError("Unsupported reference backend fault")

        def pause(operation):
            if operation not in {"validate", "retrieve"}:
                raise ValidationError("Unsupported reference pause")
            entered, release = asyncio.Event(), asyncio.Event()
            adapter._pauses[operation] = (entered, release)

            async def wait_entered():
                await entered.wait()

            return KnowledgeContractPause(wait_entered, release.set)

        return KnowledgeContractSession(
            retriever=adapter,
            sources=tuple(sources),
            resources=(KnowledgeContractResource(source),),
            mutate_source=mutate,
            inject_fault=fault,
            pause=pause,
            audit=lambda: {
                key: value
                for key, value in source.audit().items()
                if key not in {"retrieval", "validation"}
            },
        )


def offline_knowledge_fixture():
    """Select the independent offline example explicitly; construction does no I/O."""
    return OfflineKnowledgeFixture()


class ReferenceReader:
    """Deterministic source-copying Provider for wiring, never a quality model."""

    def __init__(self, source):
        self.source = source

    @property
    def identity(self):
        return {
            "kind": "external-reference-reader",
            "version": "1",
            "source": self.source._original_path,
        }

    async def complete(self, messages, tools):
        from .providers import ModelResponse

        self.source.count("model")
        references = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str) and content.startswith("Reference memory;"):
                references.extend(
                    reference
                    for reference in json.loads(content.partition("\n")[2])
                    if isinstance(reference, dict) and "_knowledge" in reference
                )
        if not references:
            return ModelResponse(output={"answer": "No available reference", "sources": []})
        return ModelResponse(
            output={
                "answer": references[0]["value"]["text"],
                "sources": [
                    {
                        "source_uri": reference["value"]["source_uri"],
                        "document_id": reference["value"]["document_id"],
                        "version": reference["version"],
                        "text_digest": reference["_knowledge"]["text_digest"],
                    }
                    for reference in references
                ],
            }
        )


def register_reference_components(registry, source, *, asynchronous=False, owned=True):
    """Register application factories; declarations never import or execute code."""
    from .retrieval import KnowledgeContext

    if type(asynchronous) is not bool or type(owned) is not bool:
        raise ValidationError("Reference ownership and assembly mode require booleans")

    def validate(config):
        if (
            set(config) - {"namespace"}
            or not isinstance(config.get("namespace", "manuals"), str)
            or not config.get("namespace", "manuals").strip()
        ):
            raise ValidationError("Reference factory requires only a non-empty namespace")

    def provider_config(config):
        if config:
            raise ValidationError("Reference reader accepts no configuration fields")

    def knowledge(config, context):
        selected = context.own(source) if owned else source
        return KnowledgeContext(
            ReferenceSQLiteRetriever(selected), namespace=config.get("namespace", "manuals")
        )

    async def async_knowledge(config, context):
        selected = context.own_async(source) if owned else source
        await asyncio.sleep(0)
        return KnowledgeContext(
            AsyncReferenceSQLiteRetriever(selected), namespace=config.get("namespace", "manuals")
        )

    (registry.register_async if asynchronous else registry.register)(
        "knowledge",
        "external-reference",
        async_knowledge if asynchronous else knowledge,
        validator=validate,
    )
    registry.register(
        "provider",
        "external-reference-reader",
        lambda config, context: ReferenceReader(source),
        validator=provider_config,
    )
