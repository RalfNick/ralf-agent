import asyncio
import hashlib
from io import BytesIO

import pytest

from ralf_agent import IngestionCoordinator, Scope, SourceDocument, SQLiteKnowledgeStore
from ralf_agent.errors import ValidationError
from ralf_agent.retrieval import RetrievalQuery
from tests.pdf_fixture import form_pdf, pdf

pypdf = pytest.importorskip("pypdf", minversion="6.20")


def parser():
    import ralf_agent

    assert hasattr(ralf_agent, "PdfDocumentParser"), "Missing optional PDF parser"
    return ralf_agent.PdfDocumentParser()


@pytest.mark.parametrize("compressed", [False, True])
def test_pdf_real_text_preserves_source_and_page_order(compressed):
    source = SourceDocument(
        "guide",
        pdf(
            (
                b"BT /F1 12 Tf 72 720 Td (Pool timeout) Tj ET",
                b"BT /F1 12 Tf 72 720 Td (Inspect connections.) Tj ET",
            ),
            compressed=compressed,
        ),
        "application/pdf",
        "book://guide",
        {"tags": ["ops"]},
    )
    parsed = parser().parse(source)
    assert parsed.document.text == "Pool timeout\nInspect connections."
    assert parsed.document.document_id == "guide" and parsed.document.source_uri == "book://guide"
    assert parsed.document.metadata == {"tags": ["ops"]}
    assert parsed.source_sha256 == hashlib.sha256(source.data).hexdigest()


@pytest.mark.parametrize(
    "data",
    [
        b"not PDF",
        pdf((b"",)),
        pdf(tuple(b"" for _ in range(65))),
        pdf((b"a" * (8 * 1024 * 1024 + 1),), compressed=True),
        pdf((b"BT /F1 12 Tf (" + b"a" * (1024 * 1024 + 1) + b") Tj ET",), compressed=True),
    ],
    ids=["malformed", "no-text", "pages", "stream-limit", "text-limit"],
)
def test_pdf_invalid_or_oversized_has_no_knowledge_commit(tmp_path, data):
    async def run():
        with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            with pytest.raises(ValidationError):
                await IngestionCoordinator(store, parser=parser()).ingest(
                    Scope(),
                    "docs",
                    SourceDocument("guide", data, "application/pdf"),
                    command_id="bad",
                    expected_version=0,
                )
            assert store.get(Scope(), "docs", "guide") is None
            assert store.ingestion_receipt(Scope(), "docs", "bad") is None
            assert store.chunks(Scope(), "docs", "guide") == []
            assert not store.lexical(Scope(), "docs", RetrievalQuery("timeout")).items

    asyncio.run(run())


def test_pdf_encrypted_source_is_rejected_without_password(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.append(pypdf.PdfReader(BytesIO(pdf())))
    writer.encrypt("private-test-only")
    buffer = BytesIO()
    writer.write(buffer)
    test_pdf_invalid_or_oversized_has_no_knowledge_commit(tmp_path, buffer.getvalue())


def test_pdf_reopen_reuses_original_receipt_without_reparse(tmp_path):
    source = SourceDocument("guide", pdf(), "application/pdf", "book://guide")

    async def run():
        path = tmp_path / "knowledge.sqlite"
        with SQLiteKnowledgeStore(path) as store:
            receipt = await IngestionCoordinator(store, parser=parser()).ingest(
                Scope(), "docs", source, command_id="first", expected_version=0
            )
            assert store.get(Scope(), "docs", "guide").text == "Pool timeout\nInspect connections."
        with SQLiteKnowledgeStore(path) as store:

            class NeverParse:
                identity = {"kind": "receipt-reuse", "version": "1"}

                def parse(self, source):
                    raise AssertionError("Committed PDF must not be reparsed")

            restored = await IngestionCoordinator(store, parser=NeverParse()).ingest(
                Scope(), "docs", source, command_id="first", expected_version=0
            )
            assert restored == receipt and store.get(Scope(), "docs", "guide").version == 1

    asyncio.run(run())


def test_pdf_does_not_modify_caller_library_configuration():
    pypdf = pytest.importorskip("pypdf")
    with pypdf.apply_configuration(zlib_maximum_output_length=1, jbig2dec_binary="/do-not-execute"):
        before = pypdf.get_configuration()
        assert (
            parser()
            .parse(SourceDocument("guide", pdf(compressed=True), "application/pdf"))
            .document.text
            == "Pool timeout\nInspect connections."
        )
        assert pypdf.get_configuration() is before


def test_pdf_helper_change_after_registration_is_refused_before_commit(tmp_path, monkeypatch):
    import ralf_agent.pdf_parsing as parsing
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            coordinator = IngestionCoordinator(store, parser=parser())
            monkeypatch.setattr(parsing.PdfDocumentParser, "_check", lambda self: None)
            with pytest.raises(DefinitionMismatch):
                await coordinator.ingest(
                    Scope(),
                    "docs",
                    SourceDocument("guide", pdf(), "application/pdf"),
                    command_id="changed",
                    expected_version=0,
                )
            assert store.get(Scope(), "docs", "guide") is None
            assert store.ingestion_receipt(Scope(), "docs", "changed") is None

    asyncio.run(run())


def test_pdf_dependency_change_during_commit_does_not_confirm_old_pipeline(tmp_path, monkeypatch):
    from ralf_agent.errors import DefinitionMismatch

    async def run():
        with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            original = store.ingest

            async def changed(*args, **kwargs):
                receipt = original(*args, **kwargs)
                monkeypatch.setattr(pypdf, "PdfReader", lambda *args, **kwargs: None)
                return receipt

            store.ingest = changed
            coordinator = IngestionCoordinator(store, parser=parser())
            with pytest.raises(DefinitionMismatch):
                await coordinator.ingest(
                    Scope(),
                    "docs",
                    SourceDocument("guide", pdf(), "application/pdf"),
                    command_id="first",
                    expected_version=0,
                )
            assert store.ingestion_receipt(Scope(), "docs", "first").document_version == 1
            monkeypatch.undo()
            restored = await coordinator.ingest(
                Scope(),
                "docs",
                SourceDocument("guide", pdf(), "application/pdf"),
                command_id="first",
                expected_version=0,
            )
            assert restored.document_version == store.get(Scope(), "docs", "guide").version == 1

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["before", "after"])
def test_pdf_process_loss_preserves_atomic_knowledge_and_receipt(tmp_path, mode):
    import os
    import subprocess
    import sys
    from pathlib import Path

    import ralf_agent
    from ralf_agent.retrieval import RetrievalQuery

    path = tmp_path / "knowledge.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("pdf_ingestion_crash_fixture.py")),
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
            hits = store.lexical(Scope(), "docs", RetrievalQuery("timeout"))
            if mode == "before":
                assert previous is None and record is None and chunks == [] and not hits.items
            else:
                assert previous.document_version == record.version == 1 and hits.items
                assert previous.chunk_ids == [c.chunk_id for c in chunks]
                assert all(
                    c.text == record.text[loc["start"] : loc["end"]]
                    for c, loc in zip(chunks, previous.locations, strict=True)
                )
            restored = await IngestionCoordinator(store, parser=parser()).ingest(
                Scope(),
                "docs",
                SourceDocument("guide", pdf(), "application/pdf", "book://guide"),
                command_id="first",
                expected_version=0,
            )
            assert restored.document_version == store.get(Scope(), "docs", "guide").version == 1
            if previous:
                assert restored == previous

    asyncio.run(run())


@pytest.mark.parametrize(
    "data",
    [
        form_pdf(invocations=129),
        form_pdf(form_content=b"a" * (8 * 1024 * 1024 + 1), compressed=True),
        form_pdf(cyclic=True),
        form_pdf(missing=True),
    ],
    ids=["form-invocations", "form-stream", "form-cycle", "missing-form"],
)
def test_pdf_incomplete_form_evidence_is_refused_before_commit(tmp_path, data):
    test_pdf_invalid_or_oversized_has_no_knowledge_commit(tmp_path, data)


def test_pdf_small_form_retains_complete_text():
    assert (
        parser()
        .parse(SourceDocument("guide", form_pdf(invocations=2), "application/pdf"))
        .document.text
        == "Pool timeout\nInspect connections.\nInspect connections."
    )


@pytest.mark.parametrize(
    "settings", [("A", "z", ""), ("", "", "ABC")], ids=["rtl-range", "rtl-special"]
)
def test_pdf_changed_rtl_settings_refuse_registered_pipeline_without_host_reset(tmp_path, settings):
    import pypdf._text_extraction as extraction

    from ralf_agent.errors import DefinitionMismatch

    before = (
        extraction.CUSTOM_RTL_MIN,
        extraction.CUSTOM_RTL_MAX,
        extraction.CUSTOM_RTL_SPECIAL_CHARS,
    )

    async def run():
        try:
            with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
                coordinator = IngestionCoordinator(store, parser=parser())
                extraction.set_custom_rtl(*settings)
                with pytest.raises(DefinitionMismatch):
                    await coordinator.ingest(
                        Scope(),
                        "docs",
                        SourceDocument("guide", pdf(), "application/pdf"),
                        command_id="changed",
                        expected_version=0,
                    )
                assert store.get(Scope(), "docs", "guide") is None
                assert store.ingestion_receipt(Scope(), "docs", "changed") is None
                assert (
                    extraction.CUSTOM_RTL_MIN,
                    extraction.CUSTOM_RTL_MAX,
                    extraction.CUSTOM_RTL_SPECIAL_CHARS,
                ) == settings
        finally:
            extraction.set_custom_rtl(*before)

    asyncio.run(run())


def test_pdf_rtl_change_during_commit_refuses_confirmation_and_preserves_receipt(tmp_path):
    import pypdf._text_extraction as extraction

    from ralf_agent.errors import DefinitionMismatch

    before = (
        extraction.CUSTOM_RTL_MIN,
        extraction.CUSTOM_RTL_MAX,
        extraction.CUSTOM_RTL_SPECIAL_CHARS,
    )

    async def run():
        try:
            with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
                original = store.ingest

                async def changed(*args, **kwargs):
                    receipt = original(*args, **kwargs)
                    extraction.set_custom_rtl("A", "z")
                    return receipt

                store.ingest = changed
                coordinator = IngestionCoordinator(store, parser=parser())
                with pytest.raises(DefinitionMismatch):
                    await coordinator.ingest(
                        Scope(),
                        "docs",
                        SourceDocument("guide", pdf(), "application/pdf"),
                        command_id="first",
                        expected_version=0,
                    )
                assert store.ingestion_receipt(Scope(), "docs", "first").document_version == 1
                extraction.set_custom_rtl(*before)
                restored = await coordinator.ingest(
                    Scope(),
                    "docs",
                    SourceDocument("guide", pdf(), "application/pdf"),
                    command_id="first",
                    expected_version=0,
                )
                assert restored.document_version == store.get(Scope(), "docs", "guide").version == 1
        finally:
            extraction.set_custom_rtl(*before)

    asyncio.run(run())


def test_pdf_malformed_form_text_is_refused_before_parent_can_swallow_error(tmp_path):
    data = form_pdf(form_content=b"BT /F1 12 Tf (bad) 0 Td (Form evidence) Tj ET")
    test_pdf_invalid_or_oversized_has_no_knowledge_commit(tmp_path, data)
