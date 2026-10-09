import hashlib
import importlib
import importlib.util
from dataclasses import asdict

import pytest

from ralf_agent import Document, DocumentRecord, Scope
from ralf_agent.errors import ValidationError
from ralf_agent.types import digest


def api():
    assert importlib.util.find_spec("ralf_agent.ingestion_types"), (
        "Missing replaceable ingestion DTOs"
    )
    return importlib.import_module("ralf_agent.ingestion_types")


def components():
    api()
    return importlib.import_module("ralf_agent.document_parsing"), importlib.import_module(
        "ralf_agent.chunking"
    )


def test_parser_keeps_utf8_markdown_and_detaches_source_metadata():
    dto = api()
    parsing, _ = components()
    metadata = {"tags": ["runbook"]}
    source = dto.SourceDocument(
        "guide", "# 指南\r\n\n池耗尽".encode(), "text/markdown", "book://guide", metadata
    )
    metadata["tags"].append("changed")
    source.metadata["tags"].clear()
    parsed = parsing.TextDocumentParser().parse(source)
    assert parsed.document == Document(
        "guide", "# 指南\r\n\n池耗尽", "book://guide", {"tags": ["runbook"]}
    )
    assert parsed.source_sha256 == hashlib.sha256(source.data).hexdigest()


@pytest.mark.parametrize("data,media", [(b"\xff", "text/plain"), (b"pdf", "application/pdf")])
def test_default_parser_rejects_invalid_encoding_and_undeclared_format(data, media):
    dto = api()
    parsing, _ = components()
    with pytest.raises(ValidationError):
        parsing.TextDocumentParser().parse(dto.SourceDocument("a", data, media))


def test_default_chunker_preserves_legacy_text_identifiers_and_metadata():
    dto = api()
    parsing, chunking = components()
    parsed = parsing.TextDocumentParser().parse(
        dto.SourceDocument("a", b"abcdefghijklmnop", metadata={"kind": "ops"})
    )
    spans = chunking.CharacterChunker(size=8, overlap=2).split(parsed)
    prepared = dto.PreparedIngestion(
        dto.SourceDocument("a", b"abcdefghijklmnop", metadata={"kind": "ops"}),
        parsed,
        spans,
        {"parser": {"v": "1"}, "chunker": {"v": "1"}},
        expected_version=0,
    )
    record = DocumentRecord(
        "a",
        "abcdefghijklmnop",
        metadata={"kind": "ops"},
        version=1,
        expires_at=None,
        scope=Scope(),
        namespace="books",
    )
    actual = prepared.chunks(record)
    assert [c.text for c in actual] == ["abcdefgh", "ghijklmn", "mnop"]
    assert [c.chunk_id for c in actual] == [digest(["a", 1, start]) for start in [0, 6, 12]]
    assert [c.metadata for c in actual] == [{"kind": "ops"}] * 3
    from ralf_agent.retrieval import _make_chunks

    assert [asdict(c) for c in actual] == [asdict(c) for c in _make_chunks(record, 8, 2)]


def test_paragraph_chunker_preserves_content_positions_with_bounded_long_paragraph():
    dto = api()
    parsing, chunking = components()
    parsed = parsing.TextDocumentParser().parse(dto.SourceDocument("a", b"abcd\n\nefghijkl"))
    spans = chunking.ParagraphChunker(size=6).split(parsed)
    assert [(s.start, s.end) for s in spans] == [(0, 6), (6, 12), (12, 14)]
    assert "".join(parsed.document.text[s.start : s.end] for s in spans) == "abcd\n\nefghijkl"


@pytest.mark.parametrize("span", [(False, 1), (0, 0), (-1, 3), (0, 100)])
def test_invalid_offsets_refused_before_preparation(span):
    dto = api()
    parsing, _ = components()
    source = dto.SourceDocument("a", b"abc")
    parsed = parsing.TextDocumentParser().parse(source)
    with pytest.raises(ValidationError):
        dto.PreparedIngestion(
            source, parsed, [dto.ChunkSpan(*span)], {"v": "1"}, expected_version=0
        )


def test_gap_and_duplicate_starts_are_rejected_and_views_are_immutable():
    dto = api()
    parsing, _ = components()
    source = dto.SourceDocument("a", b"abcdef")
    parsed = parsing.TextDocumentParser().parse(source)
    for spans in [
        [dto.ChunkSpan(0, 2), dto.ChunkSpan(3, 6)],
        [dto.ChunkSpan(0, 4), dto.ChunkSpan(0, 6)],
    ]:
        with pytest.raises(ValidationError):
            dto.PreparedIngestion(source, parsed, spans, {"v": "1"}, expected_version=0)
    prepared = dto.PreparedIngestion(
        source, parsed, [dto.ChunkSpan(0, 6)], {"v": "1"}, expected_version=0
    )
    view = prepared.to_dict()
    view["document"]["text"] = "changed"
    assert prepared.document["text"] == "abcdef"
    with pytest.raises(AttributeError):
        prepared.expected_version = 3


def test_empty_document_has_no_chunks_and_finite_expiry_is_required():
    dto = api()
    parsing, chunking = components()
    source = dto.SourceDocument("a", b"")
    parsed = parsing.TextDocumentParser().parse(source)
    spans = chunking.CharacterChunker().split(parsed)
    assert spans == ()
    with pytest.raises(ValidationError):
        dto.PreparedIngestion(
            source, parsed, spans, {"v": "1"}, expected_version=0, expires_at=float("nan")
        )


@pytest.mark.parametrize(
    "damage", ["version-bool", "request-fields", "expanded-metadata", "chunk-collision"]
)
def test_atomic_prepared_validation_rechecks_all_bounded_fields(damage):
    dto = api()
    parsing, chunking = components()
    from ralf_agent.types import canonical

    source = dto.SourceDocument("a", b"abc")
    parsed = parsing.TextDocumentParser().parse(source)
    prepared = dto.PreparedIngestion(
        source, parsed, chunking.CharacterChunker().split(parsed), {"v": "1"}, expected_version=0
    )
    value = prepared.to_dict()
    if damage == "version-bool":
        value["expected_version"] = False
    elif damage == "request-fields":
        value["request"]["unknown"] = "extra"
        value["request_digest"] = digest(value["request"])
    else:
        value["document"]["metadata"] = (
            {"large": "a" * 60000} if damage == "expanded-metadata" else {"_chunk": {"original": 1}}
        )
        value["parsed_digest"] = digest(value["document"])
        value["spans"] = (
            [{"start": 0, "end": 3, "metadata": {"part": "one"}}]
            if damage == "chunk-collision"
            else [{"start": 0, "end": 3, "metadata": {}}] * 80
        )
        if damage == "expanded-metadata":
            # Use valid monotonic spans so volume, not coverage, rejects input.
            value["document"]["text"] = "a" * 240
            value["parsed_digest"] = digest(value["document"])
            value["spans"] = [
                {"start": i * 3, "end": (i + 1) * 3, "metadata": {}} for i in range(80)
            ]
    object.__setattr__(prepared, "_data_json", canonical(value))
    with pytest.raises(ValidationError):
        prepared.validate()


def test_large_paragraph_input_has_complete_bounded_positions():
    dto = api()
    parsing, chunking = components()
    text = "x\n\n" * 100000
    parsed = parsing.TextDocumentParser().parse(dto.SourceDocument("a", text.encode()))
    spans = chunking.ParagraphChunker(size=1000).split(parsed)
    assert len(spans) < dto.MAX_CHUNKS
    assert "".join(text[s.start : s.end] for s in spans) == text


def test_receipt_generation_does_not_decode_source_once_per_chunk(monkeypatch):
    dto = api()
    parsing, chunking = components()
    original = dto.PreparedIngestion.to_dict
    reads = []

    def observe(value):
        reads.append(1)
        return original(value)

    monkeypatch.setattr(dto.PreparedIngestion, "to_dict", observe)
    counts = []
    for count in (16, 128):
        source = dto.SourceDocument("a", b"x" * (count * 16))
        parsed = parsing.TextDocumentParser().parse(source)
        prepared = dto.PreparedIngestion(
            source,
            parsed,
            chunking.CharacterChunker(size=16, overlap=0).split(parsed),
            {"v": "1"},
            expected_version=0,
        )
        reads.clear()
        receipt = dto.make_receipt("memory", Scope(), "docs", "first", prepared)
        counts.append(len(reads))
        assert len(receipt.chunk_ids) == count
    assert counts[1] <= counts[0] + 4, "Full-source decoding must be independent of chunk count"


@pytest.mark.parametrize("damage", ["wrong-id", "order", "range"])
def test_receipt_refuses_inconsistent_chunk_identity_and_source_locations(damage):
    dto = api()
    parsing, chunking = components()
    source = dto.SourceDocument("a", b"abcdef")
    parsed = parsing.TextDocumentParser().parse(source)
    prepared = dto.PreparedIngestion(
        source,
        parsed,
        chunking.CharacterChunker(size=3, overlap=0).split(parsed),
        {"v": "1"},
        expected_version=0,
    )
    value = dto.make_receipt("memory", Scope(), "docs", "first", prepared).to_dict()
    if damage == "wrong-id":
        value["chunk_ids"][0] = value["locations"][0]["chunk_id"] = "fake"
    elif damage == "order":
        value["chunk_ids"].reverse()
        value["locations"].reverse()
    else:
        value["locations"][1]["end"] = dto.MAX_PARSED_CHARS + 1
    with pytest.raises(ValidationError):
        dto.IngestionReceipt.from_dict(value)
