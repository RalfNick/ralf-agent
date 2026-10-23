"""Immutable bounded values for source parsing and atomic knowledge ingestion."""

import hashlib
from dataclasses import asdict, dataclass, field

from .errors import ValidationError
from .orchestration_types import _JsonValue
from .retrieval import (
    Chunk,
    Document,
    DocumentRecord,
    _expiry,
    _integer,
    _MetadataView,
    _scope,
    _text,
)
from .types import Scope, canonical, digest

MAX_SOURCE_BYTES = 1024 * 1024
MAX_PARSED_CHARS = 1024 * 1024
MAX_CHUNKS = 4096
MAX_METADATA_CHARS = 65536
INGESTION_CAPACITY = 4096


def _sha(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValidationError("Invalid source digest")
    return value


@dataclass(frozen=True)
class SourceDocument(_MetadataView):
    document_id: str
    data: bytes
    media_type: str = "text/plain"
    source_uri: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        _text(self.document_id, "Document identity")
        _text(self.media_type, "Media type")
        _text(self.source_uri, "Source URI", empty=True)
        if not isinstance(self.data, bytes) or len(self.data) > MAX_SOURCE_BYTES:
            raise ValidationError("Source requires bytes within the 1MiB limit")
        self._validate_metadata()
        if len(canonical(self.metadata)) > MAX_METADATA_CHARS:
            raise ValidationError("Source metadata exceeds the limit")

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()

    def request(self, expected_version, expires_at=None):
        _integer(expected_version, "Expected version")
        if expected_version >= 2**63 - 1:
            raise ValidationError("Expected version exceeds the storage range")
        return {
            "document_id": self.document_id,
            "source_sha256": self.sha256,
            "source_bytes": len(self.data),
            "media_type": self.media_type,
            "source_uri": self.source_uri,
            "metadata": self.metadata,
            "expected_version": expected_version,
            "expires_at": _expiry(expires_at),
        }


@dataclass(frozen=True)
class ParsedDocument:
    document: Document
    source_sha256: str

    def __post_init__(self):
        if not isinstance(self.document, Document) or isinstance(self.document, DocumentRecord):
            raise ValidationError("Parser must return an unversioned Document")
        _sha(self.source_sha256)
        if (
            len(self.document.text) > MAX_PARSED_CHARS
            or len(canonical(self.document.metadata)) > MAX_METADATA_CHARS
        ):
            raise ValidationError("Parsed document exceeds the limit")


@dataclass(frozen=True)
class ChunkSpan(_MetadataView):
    start: int
    end: int
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        _integer(self.start, "Chunk start")
        _integer(self.end, "Chunk end", minimum=1)
        if self.end <= self.start:
            raise ValidationError("Chunk end must follow start")
        self._validate_metadata()
        if len(canonical(self.metadata)) > MAX_METADATA_CHARS:
            raise ValidationError("Chunk metadata exceeds the limit")


def _spans(text, spans):
    if (
        not isinstance(spans, (list, tuple))
        or len(spans) > MAX_CHUNKS
        or any(not isinstance(s, ChunkSpan) for s in spans)
    ):
        raise ValidationError("Chunker must return a completed bounded sequence of ChunkSpan")
    end, start, volume = 0, -1, 0
    for span in spans:
        if (
            span.start <= start
            or span.end > len(text)
            or span.end <= end
            or text[end : span.start].strip()
        ):
            raise ValidationError("Invalid chunk coverage or source position")
        start, end = span.start, span.end
        volume += span.end - span.start
    if text[end:].strip() or volume > 4 * MAX_PARSED_CHARS:
        raise ValidationError("Chunk coverage is incomplete or exceeds the limit")
    return tuple(spans)


def _chunk_metadata(document, spans):
    if any(s.metadata for s in spans) and "_chunk" in document.metadata:
        raise ValidationError("Document metadata collides with chunk metadata")
    if (
        len(canonical(document.metadata)) * len(spans)
        + sum(len(canonical(s.metadata)) for s in spans)
        > 4 * MAX_PARSED_CHARS
    ):
        raise ValidationError("Expanded chunk metadata exceeds the limit")


class PreparedIngestion(_JsonValue):
    def __init__(self, source, parsed, spans, pipeline, *, expected_version, expires_at=None):
        if not isinstance(source, SourceDocument) or not isinstance(parsed, ParsedDocument):
            raise ValidationError("Ingestion requires source and completed parsed document")
        doc = parsed.document
        if (
            parsed.source_sha256 != source.sha256
            or doc.document_id != source.document_id
            or doc.source_uri != source.source_uri
        ):
            raise ValidationError("Parser changed source identity")
        spans = _spans(doc.text, spans)
        if not isinstance(pipeline, dict) or not pipeline:
            raise ValidationError("Ingestion requires a fixed component identity")
        _chunk_metadata(doc, spans)
        request = source.request(expected_version, expires_at)
        self._data_json = canonical(
            {
                "version": "1",
                "request": request,
                "request_digest": digest(request),
                "document": asdict(doc),
                "spans": [asdict(s) for s in spans],
                "pipeline": pipeline,
                "expected_version": expected_version,
                "expires_at": request["expires_at"],
                "source_sha256": parsed.source_sha256,
                "parsed_digest": digest(asdict(doc)),
            }
        )

    def chunks(self, record):
        if (
            not isinstance(record, DocumentRecord)
            or record.version != self.expected_version + 1
            or asdict(Document(record.document_id, record.text, record.source_uri, record.metadata))
            != self.document
        ):
            raise ValidationError("Prepared content differs from the committed document")
        return [
            Chunk(
                record.document_id,
                digest([record.document_id, record.version, s["start"]]),
                record.version,
                record.text[s["start"] : s["end"]],
                record.source_uri,
                {**record.metadata, **({"_chunk": s["metadata"]} if s["metadata"] else {})},
                record.expires_at,
                record.scope,
                record.namespace,
            )
            for s in self.spans
        ]

    def validate(self):
        try:
            value = self.to_dict()
            if (
                set(value)
                != {
                    "version",
                    "request",
                    "request_digest",
                    "document",
                    "spans",
                    "pipeline",
                    "expected_version",
                    "expires_at",
                    "source_sha256",
                    "parsed_digest",
                }
                or value["version"] != "1"
            ):
                raise ValidationError("Invalid prepared ingestion fields")
            document = Document(**value["document"])
            ParsedDocument(document, value["source_sha256"])
            spans = _spans(document.text, [ChunkSpan(**span) for span in value["spans"]])
            _chunk_metadata(document, spans)
            request = value["request"]
            if not isinstance(request, dict) or set(request) != {
                "document_id",
                "source_sha256",
                "source_bytes",
                "media_type",
                "source_uri",
                "metadata",
                "expected_version",
                "expires_at",
            }:
                raise ValidationError("Invalid source request fields")
            _integer(value["expected_version"], "Expected version")
            _text(request["document_id"], "Document identity")
            _text(request["source_uri"], "Source URI", empty=True)
            if (
                not isinstance(request["metadata"], dict)
                or len(canonical(request["metadata"])) > MAX_METADATA_CHARS
            ):
                raise ValidationError("Invalid source metadata")
            _integer(request["expected_version"], "Expected version")
            _integer(request["source_bytes"], "Source bytes")
            _sha(request["source_sha256"])
            _text(request["media_type"], "Media type")
            if (
                request["source_bytes"] > MAX_SOURCE_BYTES
                or request["expected_version"] >= 2**63 - 1
                or value["source_sha256"] != request["source_sha256"]
                or value["expected_version"] != request["expected_version"]
                or _expiry(value["expires_at"]) != _expiry(request["expires_at"])
                or document.document_id != request["document_id"]
                or document.source_uri != request["source_uri"]
                or digest(request) != value["request_digest"]
                or digest(asdict(document)) != value["parsed_digest"]
                or not isinstance(value["pipeline"], dict)
                or not value["pipeline"]
            ):
                raise ValidationError("Inconsistent prepared ingestion identity")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Invalid prepared ingestion") from exc


class IngestionReceipt(_JsonValue):
    def __init__(
        self,
        *,
        scope,
        namespace,
        command_id,
        backend_id,
        document_id,
        document_version,
        request_digest,
        source_sha256,
        parsed_digest,
        pipeline,
        chunk_ids,
        locations,
        status="knowledge_committed",
        version="1",
    ):
        if not isinstance(scope, dict) or set(scope) != {"workspace", "principal"}:
            raise ValidationError("Invalid receipt scope")
        _scope(Scope(**scope), namespace)
        for name, value in [
            ("Command ID", command_id),
            ("Backend ID", backend_id),
            ("Document ID", document_id),
        ]:
            _text(value, name)
        _integer(document_version, "Document version", minimum=1)
        for value in (request_digest, source_sha256, parsed_digest):
            _sha(value)
        if (
            status != "knowledge_committed"
            or version != "1"
            or not isinstance(pipeline, dict)
            or not pipeline
        ):
            raise ValidationError("Invalid ingestion receipt")
        if (
            not isinstance(chunk_ids, (list, tuple))
            or not isinstance(locations, (list, tuple))
            or len(chunk_ids) != len(locations)
            or len(chunk_ids) > MAX_CHUNKS
            or any(not isinstance(k, str) for k in chunk_ids)
            or len(set(chunk_ids)) != len(chunk_ids)
        ):
            raise ValidationError("Invalid receipt chunk identities")
        start, end = -1, 0
        for chunk_id, location in zip(chunk_ids, locations, strict=True):
            if (
                not isinstance(location, dict)
                or set(location) != {"chunk_id", "start", "end", "unit"}
                or location["chunk_id"] != chunk_id
                or location["unit"] != "parsed_character"
            ):
                raise ValidationError("Invalid receipt source location")
            ChunkSpan(location["start"], location["end"])
            if (
                chunk_id != digest([document_id, document_version, location["start"]])
                or location["start"] <= start
                or location["end"] <= end
                or location["end"] > MAX_PARSED_CHARS
            ):
                raise ValidationError("Inconsistent receipt chunk identity or location")
            start, end = location["start"], location["end"]
        self._data_json = canonical(
            dict(
                version=version,
                status=status,
                scope=scope,
                namespace=namespace,
                command_id=command_id,
                backend_id=backend_id,
                document_id=document_id,
                document_version=document_version,
                request_digest=request_digest,
                source_sha256=source_sha256,
                parsed_digest=parsed_digest,
                pipeline=pipeline,
                chunk_ids=chunk_ids,
                locations=locations,
            )
        )

    @classmethod
    def from_dict(cls, value):
        try:
            return cls(**value)
        except (TypeError, KeyError) as exc:
            raise ValidationError("Invalid ingestion receipt") from exc

    def __eq__(self, other):
        return isinstance(other, IngestionReceipt) and self.to_dict() == other.to_dict()


def make_receipt(backend_id, scope, namespace, command_id, prepared):
    # Prepared values expose detached JSON views. Decode once before traversing
    # spans, rather than materializing the full source for every chunk.
    value = prepared.to_dict()
    document_id = value["document"]["document_id"]
    version = value["expected_version"] + 1
    spans = value["spans"]
    chunk_ids = [digest([document_id, version, s["start"]]) for s in spans]
    return IngestionReceipt(
        scope=asdict(scope),
        namespace=namespace,
        command_id=command_id,
        backend_id=backend_id,
        document_id=document_id,
        document_version=version,
        request_digest=value["request_digest"],
        source_sha256=value["source_sha256"],
        parsed_digest=value["parsed_digest"],
        pipeline=value["pipeline"],
        chunk_ids=chunk_ids,
        locations=[
            {
                "chunk_id": chunk_id,
                "start": span["start"],
                "end": span["end"],
                "unit": "parsed_character",
            }
            for chunk_id, span in zip(chunk_ids, spans, strict=True)
        ],
    )
