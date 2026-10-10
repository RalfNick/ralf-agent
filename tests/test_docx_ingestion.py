import asyncio
import hashlib

import pytest

from ralf_agent import IngestionCoordinator, Scope, SourceDocument, SQLiteKnowledgeStore
from ralf_agent.errors import ValidationError
from ralf_agent.retrieval import RetrievalQuery
from tests.docx_fixture import BODY, CONTENT_TYPES, MIME, RELS, STRICT, WORD, docx, xml


def parser():
    import ralf_agent

    assert hasattr(ralf_agent, "DocxDocumentParser"), "Missing native DOCX parser"
    return ralf_agent.DocxDocumentParser()


@pytest.mark.parametrize("namespace", [WORD, STRICT], ids=["transitional", "strict"])
def test_docx_extracts_body_preserving_spacing_and_original_source(namespace):
    source = SourceDocument(
        "guide", docx(xml(namespace=namespace)), MIME, "book://guide", {"tags": ["ops"]}
    )
    parsed = parser().parse(source)
    assert parsed.document.text == "Pool timeout\n  Inspect connections.\tRetry\nThen stop."
    assert parsed.document.document_id == "guide" and parsed.document.source_uri == "book://guide"
    assert parsed.document.metadata == {"tags": ["ops"]}
    assert parsed.source_sha256 == hashlib.sha256(source.data).hexdigest()


def test_docx_table_cells_rows_and_content_controls_are_ordered_text():
    body = """<w:sdt><w:sdtPr/><w:sdtContent><w:p><w:r><w:t>Guide</w:t></w:r></w:p></w:sdtContent></w:sdt>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cause</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Action</w:t></w:r></w:p></w:tc></w:tr>
    <w:tr><w:tc><w:p><w:r><w:t>Pool timeout</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Inspect</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"""
    assert (
        parser().parse(SourceDocument("a", docx(xml(body)), MIME)).document.text
        == "Guide\nCause\tAction\nPool timeout\tInspect"
    )


def test_docx_excludes_deleted_hidden_field_instructions_and_embedded_objects():
    body = """<w:p><w:del><w:r><w:t>deleted secret</w:t></w:r></w:del>
    <w:r><w:rPr><w:vanish/></w:rPr><w:t>hidden secret</w:t></w:r>
    <w:r><w:instrText>field secret</w:instrText><w:t>displayed field</w:t></w:r>
    <w:r><w:object><w:t>object secret</w:t></w:object></w:r>
    <w:r><w:drawing><w:t>drawing secret</w:t></w:drawing></w:r>
    <w:r><w:rPr><w:vanish w:val="false"/></w:rPr><w:t xml:space="preserve"> visible</w:t></w:r></w:p>"""
    assert (
        parser().parse(SourceDocument("a", docx(xml(body)), MIME)).document.text
        == "displayed field visible"
    )


@pytest.mark.parametrize(
    "data",
    [
        b"not ZIP",
        docx(None),
        docx(xml(), content_types=None),
        docx(xml(), relationships=None),
        docx(
            xml(),
            content_types=CONTENT_TYPES.replace(b"document.main+xml", b"macroEnabled.main+xml"),
        ),
        docx(
            xml(),
            relationships=RELS.replace(
                b'Target="word/document.xml"',
                b'Target="https://invalid.example/document" TargetMode="External"',
            ),
        ),
        docx(b"\xff"),
        docx(b"<broken>"),
        docx(xml(namespace="urn:unexpected")),
        docx(b'<!DOCTYPE x [<!ENTITY x "expanded">]>' + xml()),
        docx(xml(), extras=[("../outside", b"untrusted")]),
        docx(xml(), extras=[("unused/" + str(i), b"") for i in range(254)]),
        docx(xml(), extras=[("media/large", b"a" * (8 * 1024 * 1024))]),
        docx(xml("<w:p><w:r><w:t>" + "a" * (1024 * 1024 + 1) + "</w:t></w:r></w:p>")),
        docx(xml("<w:sdt>" * 257 + "</w:sdt>" * 257)),
        docx(xml("<w:p/>" * 65537)),
    ],
    ids=[
        "not-zip",
        "missing-main",
        "missing-types",
        "missing-rels",
        "macro-main",
        "external-main",
        "invalid-utf8",
        "invalid-xml",
        "namespace",
        "dtd",
        "path",
        "members",
        "expanded",
        "parsed-chars",
        "depth",
        "elements",
    ],
)
def test_docx_invalid_or_oversized_source_has_no_knowledge_commit(tmp_path, data):
    async def run():
        with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            with pytest.raises(ValidationError):
                await IngestionCoordinator(store, parser=parser()).ingest(
                    Scope(),
                    "docs",
                    SourceDocument("a", data, MIME),
                    command_id="bad",
                    expected_version=0,
                )
            assert (
                store.get(Scope(), "docs", "a") is None
                and store.ingestion_receipt(Scope(), "docs", "bad") is None
            )

    asyncio.run(run())


def test_docx_reopen_reuses_original_receipt_without_reparse_and_has_valid_chunk_locations(
    tmp_path,
):
    source = SourceDocument("guide", docx(xml()), MIME, "book://guide")

    async def run():
        path = tmp_path / "knowledge.sqlite"
        with SQLiteKnowledgeStore(path, chunk_size=20, overlap=2) as store:
            receipt = await IngestionCoordinator(store, parser=parser()).ingest(
                Scope(), "docs", source, command_id="s", expected_version=0
            )
            doc = store.get(Scope(), "docs", "guide")
            chunks = store.chunks(Scope(), "docs", "guide")
            assert all(
                c.text == doc.text[loc["start"] : loc["end"]]
                for c, loc in zip(chunks, receipt.locations, strict=True)
            )
            assert store.lexical(Scope(), "docs", RetrievalQuery("timeout")).items
        with SQLiteKnowledgeStore(path, chunk_size=20, overlap=2) as store:

            class NeverParse:
                identity = {"kind": "receipt-reuse", "version": "1"}

                def parse(self, source):
                    raise AssertionError("Committed DOCX must not be reparsed")

            restored = await IngestionCoordinator(store, parser=NeverParse()).ingest(
                Scope(), "docs", source, command_id="s", expected_version=0
            )
            assert restored == receipt and store.get(Scope(), "docs", "guide").version == 1

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["before", "after"])
def test_docx_process_loss_keeps_all_knowledge_evidence_atomic(tmp_path, mode):
    import os
    import subprocess
    import sys
    from pathlib import Path

    import ralf_agent

    path = tmp_path / "knowledge.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("docx_ingestion_crash_fixture.py")),
            str(path),
            mode,
        ],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(ralf_agent.__file__).resolve().parent.parent),
        },
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 79, result.stderr

    async def run():
        with SQLiteKnowledgeStore(path) as store:
            previous = store.ingestion_receipt(Scope(), "docs", "first")
            record, chunks = (
                store.get(Scope(), "docs", "guide"),
                store.chunks(Scope(), "docs", "guide"),
            )
            result = store.lexical(Scope(), "docs", RetrievalQuery("timeout"))
            if mode == "before":
                assert previous is None and record is None and chunks == [] and not result.items
            else:
                assert previous.document_version == record.version == 1 and result.items
                assert previous.chunk_ids == [c.chunk_id for c in chunks]
            restored = await IngestionCoordinator(store, parser=parser()).ingest(
                Scope(),
                "docs",
                SourceDocument("guide", docx(xml()), MIME, "book://guide"),
                command_id="first",
                expected_version=0,
            )
            assert restored.document_version == store.get(Scope(), "docs", "guide").version == 1
            if previous:
                assert restored == previous

    asyncio.run(run())


@pytest.mark.parametrize("change", ["policy", "helper"])
def test_docx_registered_behavior_changes_fail_before_commit(tmp_path, monkeypatch, change):
    import ralf_agent.docx_parsing as parsing
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            coordinator = IngestionCoordinator(store, parser=parser())
            if change == "policy":
                monkeypatch.setattr(parsing, "_SKIP", frozenset())
            else:
                monkeypatch.setattr(parsing, "_inline", lambda *args: "replacement")
            with pytest.raises(DefinitionMismatch):
                await coordinator.ingest(
                    Scope(),
                    "docs",
                    SourceDocument("a", docx(xml()), MIME),
                    command_id="changed",
                    expected_version=0,
                )
            assert (
                store.get(Scope(), "docs", "a") is None
                and store.ingestion_receipt(Scope(), "docs", "changed") is None
            )

    asyncio.run(run())


def test_docx_duplicate_parts_and_wrong_media_are_rejected():
    with pytest.warns(UserWarning, match="Duplicate name"):
        data = docx(xml(), extras=[("word/document.xml", xml(BODY))])
    with pytest.raises(ValidationError):
        parser().parse(SourceDocument("a", data, MIME))
    with pytest.raises(ValidationError):
        parser().parse(SourceDocument("a", docx(xml()), "application/pdf"))


def test_docx_nul_truncated_member_is_rejected_before_commit(tmp_path):
    data = docx(None, extras=[("word/document.xmlXtail", xml())]).replace(
        b"word/document.xmlXtail", b"word/document.xml\x00tail"
    )
    with pytest.raises(ValidationError):
        parser().parse(SourceDocument("a", data, MIME))
    test_docx_invalid_or_oversized_source_has_no_knowledge_commit(tmp_path, data)


@pytest.mark.parametrize("wrapper", ["sdt", "customXml"])
def test_docx_table_wrapped_rows_and_cells_retain_text(wrapper):
    def wrap(content):
        if wrapper == "sdt":
            return f"<w:sdt><w:sdtPr/><w:sdtContent>{content}</w:sdtContent></w:sdt>"
        return f"<w:customXml>{content}</w:customXml>"

    first = wrap("<w:tc><w:p><w:r><w:t>Cause</w:t></w:r></w:p></w:tc>")
    row = wrap(f"<w:tr>{first}<w:tc><w:p><w:r><w:t>Inspect</w:t></w:r></w:p></w:tc></w:tr>")
    assert (
        parser().parse(SourceDocument("a", docx(xml(f"<w:tbl>{row}</w:tbl>")), MIME)).document.text
        == "Cause\tInspect"
    )


def test_docx_moved_source_is_excluded_and_saved_destination_retained():
    body = """<w:p><w:moveFrom><w:r><w:t>old secret</w:t></w:r></w:moveFrom>
    <w:moveTo><w:r><w:t>moved text</w:t></w:r></w:moveTo></w:p>"""
    assert parser().parse(SourceDocument("a", docx(xml(body)), MIME)).document.text == "moved text"


def test_docx_explicit_nonbreaking_and_soft_hyphens_retain_text():
    body = "<w:p><w:r><w:t>non</w:t><w:noBreakHyphen/><w:t>breaking soft</w:t><w:softHyphen/><w:t>hyphen</w:t></w:r></w:p>"
    assert (
        parser().parse(SourceDocument("a", docx(xml(body)), MIME)).document.text
        == "non\u2011breaking soft\u00adhyphen"
    )
