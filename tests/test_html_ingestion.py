import asyncio
import hashlib

import pytest

from relf_agent import IngestionCoordinator, Scope, SourceDocument, SQLiteKnowledgeStore
from relf_agent.errors import ValidationError
from relf_agent.retrieval import RetrievalQuery


def parser():
    import relf_agent

    assert hasattr(relf_agent, "HtmlDocumentParser"), "Missing native HTML document parser"
    return relf_agent.HtmlDocumentParser()


def test_html_extraction_keeps_provenance_and_excludes_noncontent():
    source = SourceDocument(
        "guide",
        b"""<!DOCTYPE html><html><head><title>ignore title</title><script>head secret</script></head>
        <body><h1>Pool &amp; timeout</h1><p>Inspect <strong>connections</strong> first.</p>
        <script>script secret</script><style>style secret</style><template>template secret</template>
        <iframe src="https://invalid.example">frame secret</iframe><object>object secret</object>
        <p hidden>hidden secret</p><p aria-hidden="true">aria secret</p><!--comment secret-->
        <p>Use &#x4E2D;&#x6587;.<br>Then retry.</p></body></html>""",
        "text/html",
        "https://invalid.example/runbook",
        {"tags": ["ops"]},
    )
    parsed = parser().parse(source)
    assert (
        parsed.document.text == "Pool & timeout\nInspect connections first.\nUse 中文.\nThen retry."
    )
    assert parsed.document.document_id == "guide"
    assert parsed.document.source_uri == source.source_uri
    assert parsed.document.metadata == {"tags": ["ops"]}
    assert parsed.source_sha256 == hashlib.sha256(source.data).hexdigest()


@pytest.mark.parametrize(
    "html,want",
    [
        ("<p>one</p><p>two</p>", "one\ntwo"),
        ("a<b>b</b>c &lt;x&gt;", "abc <x>"),
        ("<div hidden><img><span>secret</span></div><p>answer</p>", "answer"),
        ("<div aria-hidden='FALSE'>answer</div>", "answer"),
        ("<div>one<span> two</div>three", "one two\nthree"),
        ("<script>never disclosed", ""),
        ("<p>one</p><style/>two", "one\ntwo"),
        ("<p>   </p><!--empty-->", ""),
        (
            "<p>pool</p><img src='https://invalid.example/never'><a href='https://invalid.example'>link</a>",
            "pool\nlink",
        ),
    ],
)
def test_html_fragments_have_stable_plain_text(html, want):
    assert parser().parse(SourceDocument("a", html.encode(), "text/html")).document.text == want


@pytest.mark.parametrize(
    "source",
    [SourceDocument("a", b"\xff", "text/html"), SourceDocument("a", b"<p>text</p>", "text/plain")],
)
def test_html_invalid_encoding_or_media_type_rejected(source):
    with pytest.raises(ValidationError):
        parser().parse(source)


@pytest.mark.parametrize("html", ["<div>" * 257, "<br>" * 65537], ids=["depth", "events"])
def test_html_structure_limits_fail_before_knowledge_commit(tmp_path, html):
    async def run():
        with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            with pytest.raises(ValidationError):
                await IngestionCoordinator(store, parser=parser()).ingest(
                    Scope(),
                    "docs",
                    SourceDocument("a", html.encode(), "text/html"),
                    command_id="invalid",
                    expected_version=0,
                )
            assert store.get(Scope(), "docs", "a") is None
            assert store.ingestion_receipt(Scope(), "docs", "invalid") is None

    asyncio.run(run())


def test_html_ingestion_reopen_replays_receipt_and_preserves_parsed_chunk_offsets(tmp_path):
    source = SourceDocument(
        "a", b"<h1>Pool timeout</h1><p>Inspect connections.</p>", "text/html", "book://a"
    )

    async def run():
        path = tmp_path / "knowledge.sqlite"
        with SQLiteKnowledgeStore(path, chunk_size=12, overlap=2) as store:
            receipt = await IngestionCoordinator(store, parser=parser()).ingest(
                Scope(),
                "docs",
                source,
                command_id="s",
                expected_version=0,
            )
            doc = store.get(Scope(), "docs", "a")
            assert doc.text == "Pool timeout\nInspect connections."
            chunks = store.chunks(Scope(), "docs", "a")
            assert all(
                chunk.text == doc.text[loc["start"] : loc["end"]]
                for chunk, loc in zip(chunks, receipt.locations, strict=True)
            )
            assert len(store.lexical(Scope(), "docs", RetrievalQuery("timeout")).items) == 1
        with SQLiteKnowledgeStore(path, chunk_size=12, overlap=2) as store:

            class NeverParse:
                identity = {"kind": "receipt-recovery", "version": "1"}

                def parse(self, source):
                    raise AssertionError("Committed source must not be parsed again")

            restored = await IngestionCoordinator(store, parser=NeverParse()).ingest(
                Scope(),
                "docs",
                source,
                command_id="s",
                expected_version=0,
            )
            assert restored == receipt
            assert store.get(Scope(), "docs", "a").version == 1

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["before", "after"])
def test_html_process_death_preserves_atomic_source_chunks_terms_receipt(tmp_path, mode):
    import os
    import subprocess
    import sys
    from pathlib import Path

    import relf_agent

    path = tmp_path / "knowledge.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("html_ingestion_crash_fixture.py")),
            str(path),
            mode,
        ],
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(relf_agent.__file__).resolve().parent.parent),
        },
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 79, result.stderr

    async def run():
        with SQLiteKnowledgeStore(path) as store:
            receipt = store.ingestion_receipt(Scope(), "docs", "first")
            doc = store.get(Scope(), "docs", "guide")
            chunks = store.chunks(Scope(), "docs", "guide")
            refs = store.lexical(Scope(), "docs", RetrievalQuery("timeout"))
            if mode == "before":
                assert receipt is None and doc is None and chunks == [] and not refs.items
            else:
                assert receipt.document_version == doc.version == 1
                assert doc.text == "Pool timeout\nInspect connections."
                assert receipt.chunk_ids == [chunk.chunk_id for chunk in chunks]
                assert len(refs.items) == 1
            source = SourceDocument(
                "guide",
                b"<h1>Pool timeout</h1><p>Inspect connections.</p>",
                "text/html",
                "book://guide",
            )
            restored = await IngestionCoordinator(store, parser=parser()).ingest(
                Scope(),
                "docs",
                source,
                command_id="first",
                expected_version=0,
            )
            assert store.get(Scope(), "docs", "guide").version == restored.document_version == 1
            if receipt is not None:
                assert restored == receipt

    asyncio.run(run())


@pytest.mark.parametrize(
    "html,want",
    [
        ("<pre>if x:\n    do_thing()\n    done()</pre>", "if x:\n    do_thing()\n    done()"),
        (
            "<h1>Example</h1><pre><code>  first\n    second</code></pre><p>Next</p>",
            "Example\n  first\n    second\nNext",
        ),
        ("<pre>  first\r\n    second</pre>", "  first\r\n    second"),
    ],
    ids=["python", "nested-code", "crlf-indent"],
)
def test_html_preformatted_code_preserves_meaningful_whitespace(html, want):
    assert parser().parse(SourceDocument("a", html.encode(), "text/html")).document.text == want


@pytest.mark.parametrize("changed", ["policy", "helper"])
def test_html_changed_extraction_behavior_cannot_keep_registered_pipeline(
    tmp_path, monkeypatch, changed
):
    import relf_agent.html_parsing as html
    from relf_agent.errors import DefinitionMismatch

    async def run():
        with SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite") as store:
            coordinator = IngestionCoordinator(store, parser=parser())
            if changed == "policy":
                monkeypatch.setattr(html, "_SKIP", frozenset())
            else:
                monkeypatch.setattr(html._TextExtractor, "handle_data", lambda self, data: None)
            with pytest.raises(DefinitionMismatch):
                await coordinator.ingest(
                    Scope(),
                    "docs",
                    SourceDocument("a", b"<p>body</p>", "text/html"),
                    command_id="s",
                    expected_version=0,
                )
            assert (
                store.get(Scope(), "docs", "a") is None
                and store.ingestion_receipt(Scope(), "docs", "s") is None
            )

    asyncio.run(run())


def test_html_malformed_marked_declaration_has_typed_error():
    with pytest.raises(ValidationError):
        parser().parse(SourceDocument("a", b"<![foo]><p>text</p>", "text/html"))


@pytest.mark.parametrize("tag", ["<![if]>", "<![CDATA[]]>"], ids=["conditional", "cdata"])
def test_html_unknown_declarations_count_toward_parser_budget(tag):
    with pytest.raises(ValidationError):
        parser().parse(SourceDocument("a", (tag * 65537).encode(), "text/html"))


def test_html_self_closing_callback_is_counted_once():
    assert parser().parse(SourceDocument("a", b"<img/>" * 65536, "text/html")).document.text == ""
    with pytest.raises(ValidationError):
        parser().parse(SourceDocument("a", b"<img/>" * 65537, "text/html"))


def test_html_unmatched_closing_block_does_not_change_evidence():
    assert parser().parse(SourceDocument("a", b"a</p>b", "text/html")).document.text == "ab"
