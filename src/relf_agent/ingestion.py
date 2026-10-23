"""Explicit bounded parsing and atomic knowledge ingestion, with borrowed stores."""

import copy
import inspect
from dataclasses import asdict

from .chunking import CharacterChunker
from .document_parsing import TextDocumentParser
from .errors import DefinitionMismatch, IdempotencyConflict, ValidationError
from .ingestion_types import IngestionReceipt, ParsedDocument, PreparedIngestion, SourceDocument
from .memory import memory_call
from .ports import is_sync_callable
from .retrieval import _scope, _text
from .task_controls import _binding
from .tools import _callable_identity
from .types import canonical, digest


def _identity(component, method):
    identity = copy.deepcopy(getattr(component, "identity", None))
    if (
        not isinstance(identity, dict)
        or not identity
        or not is_sync_callable(getattr(component, method, None))
    ):
        raise ValidationError(f"{method} requires a pure synchronous component and identity")
    canonical(identity)
    return {
        "identity": identity,
        "implementation_digest": digest(_callable_identity(getattr(component, method))),
    }


def _lazy(value):
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()


class IngestionCoordinator:
    def __init__(self, store, *, parser=None, chunker=None):
        self.store = store
        self._backend = _text(getattr(store, "backend_id", None), "Knowledge backend identity")
        self._store_bindings = []
        for method in ("ingest", "ingestion_receipt"):
            callback = getattr(store, method, None)
            if not callable(callback):
                raise ValidationError("Knowledge store must implement atomic ingestion")
            self._store_bindings.append((method, _binding(callback)))
        self.parser = TextDocumentParser() if parser is None else parser
        self.chunker = (
            CharacterChunker(
                size=getattr(store, "chunk_size", 1000), overlap=getattr(store, "overlap", 100)
            )
            if chunker is None
            else chunker
        )
        self._pipeline = self._current_pipeline()
        self._components = [
            ("parser", self.parser, "parse", _binding(self.parser.parse)),
            ("chunker", self.chunker, "split", _binding(self.chunker.split)),
        ]
        self._store = store

    def _current_pipeline(self):
        return {
            "version": "1",
            "parser": _identity(self.parser, "parse"),
            "chunker": _identity(self.chunker, "split"),
        }

    @property
    def identity(self):
        return {**copy.deepcopy(self._pipeline), "backend_id": self._backend}

    def _check_store(self):
        if (
            self.store is not self._store
            or self.store.backend_id != self._backend
            or any(
                not callable(getattr(self.store, name, None))
                or _binding(getattr(self.store, name)) != binding
                for name, binding in self._store_bindings
            )
        ):
            raise DefinitionMismatch("Knowledge ingestion backend changed")

    def _check(self):
        self._check_store()
        if any(
            getattr(self, attribute) is not component
            or not callable(getattr(component, method, None))
            or _binding(getattr(component, method)) != binding
            for attribute, component, method, binding in self._components
        ) or digest(self._current_pipeline()) != digest(self._pipeline):
            raise DefinitionMismatch("Parser/chunker registration changed")

    def _receipt(self, value, scope, namespace, command_id, request):
        if not isinstance(value, IngestionReceipt):
            _lazy(value)
            raise ValidationError("Atomic store must return IngestionReceipt")
        value = IngestionReceipt.from_dict(value.to_dict())
        if (
            value.scope != asdict(scope)
            or value.namespace != namespace
            or value.command_id != command_id
            or value.backend_id != self._backend
        ):
            raise ValidationError("Ingestion receipt does not match scoped request")
        if value.request_digest != digest(request):
            raise IdempotencyConflict("Ingestion command identifies different content")
        if (
            value.document_id != request["document_id"]
            or value.document_version != request["expected_version"] + 1
            or value.source_sha256 != request["source_sha256"]
        ):
            raise ValidationError("Ingestion receipt source identity is inconsistent")
        return value

    async def ingest(
        self, scope, namespace, source, *, command_id, expected_version, expires_at=None
    ):
        _scope(scope, namespace)
        _text(command_id, "Ingestion command ID")
        if not isinstance(source, SourceDocument):
            raise ValidationError("Ingestion requires SourceDocument")
        source = SourceDocument(
            source.document_id, source.data, source.media_type, source.source_uri, source.metadata
        )
        request = source.request(expected_version, expires_at)
        self._check_store()
        previous = await memory_call(self.store.ingestion_receipt, scope, namespace, command_id)
        self._check_store()
        if previous is not None:
            return self._receipt(previous, scope, namespace, command_id, request)
        self._check()
        parsed = self.parser.parse(copy.deepcopy(source))
        if not isinstance(parsed, ParsedDocument):
            _lazy(parsed)
            raise ValidationError("Parser must return completed ParsedDocument")
        parsed = ParsedDocument(copy.deepcopy(parsed.document), parsed.source_sha256)
        self._check()
        spans = self.chunker.split(copy.deepcopy(parsed))
        if not isinstance(spans, (tuple, list)):
            _lazy(spans)
            raise ValidationError("Chunker must return completed spans")
        prepared = PreparedIngestion(
            source,
            parsed,
            spans,
            self._pipeline,
            expected_version=expected_version,
            expires_at=expires_at,
        )
        self._check()
        receipt = await memory_call(
            self.store.ingest, scope, namespace, prepared, command_id=command_id
        )
        self._check()
        return self._receipt(receipt, scope, namespace, command_id, request)
