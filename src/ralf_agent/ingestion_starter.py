"""Package-contained user document ingestion and offline grounded Agent template."""

_INGEST_MAIN = r"""
def main(argv=None):
    from pathlib import Path
    from ralf_agent import HtmlDocumentParser, IngestionCoordinator, SourceDocument
    from ralf_agent.errors import ValidationError

    parser = argparse.ArgumentParser(description="Ingest your UTF-8 text/Markdown/HTML, then query stored evidence offline.")
    parser.add_argument("--db", default=".ralf/runs.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("file")
    ingest.add_argument("--document-id", required=True)
    ingest.add_argument("--command-id", required=True)
    ingest.add_argument("--expected-version", type=int, required=True)
    query = sub.add_parser("query")
    query.add_argument("--query", required=True)
    query.add_argument("--command-id", required=True)
    query.add_argument("--submit-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            path = Path(args.file).expanduser().resolve()
            if path.suffix.lower() not in {".txt", ".md", ".markdown", ".html", ".htm"}:
                raise ValidationError("Use a UTF-8 .txt, .md, .markdown, .html or .htm source")
            try:
                with path.open("rb") as file:
                    data = file.read(1024 * 1024 + 1)
            except OSError as exc:
                raise ValidationError("Cannot read the selected source file") from exc
            source = SourceDocument(args.document_id, data,
                media_type=("text/html" if path.suffix.lower() in {".html", ".htm"}
                    else "text/plain" if path.suffix.lower() == ".txt" else "text/markdown"),
                source_uri=path.as_uri())
            database = str(Path(args.db).expanduser().resolve()) + ".knowledge.sqlite"
            with SQLiteKnowledgeStore(database) as store:
                receipt = asyncio.run(IngestionCoordinator(store, parser=(HtmlDocumentParser()
                    if source.media_type == "text/html" else None)).ingest(Scope(), "runbooks", source,
                    command_id=args.command_id, expected_version=args.expected_version))
                print(json.dumps(receipt.to_dict(), ensure_ascii=False, allow_nan=False))
        else:
            with create_engine(args.db) as engine:
                handle = engine.submit(agent_spec(), {"query": args.query}, command_id=args.command_id)
                snapshot = engine.status(handle.run_id) if args.submit_only else asyncio.run(engine.drive(handle.run_id))
                print(json.dumps({"run_id":snapshot.run_id,"state":snapshot.state,"pending":snapshot.pending,
                    "result":snapshot.result,"submission":asdict(handle.receipt)}, ensure_ascii=False, allow_nan=False))
        return 0
    except RalfError as exc:
        print(json.dumps({"code":exc.code,"message":str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
"""


def ingestion_files(rag_runtime, rag_files):
    # Reuse the stable evidence Provider/output Schema, without changing the
    # original RAG template or inserting fixture documents into user knowledge.
    runtime = rag_runtime[
        rag_runtime.index("import argparse") : rag_runtime.index("def main(argv=None):")
    ]
    runtime = (
        runtime[: runtime.index("SEED_DOCUMENTS =")]
        + runtime[runtime.index("class EvidenceProvider:") :]
    )
    runtime = runtime.replace("        seed_documents(knowledge_store, scope)\n", "")
    runtime = runtime.replace("import hashlib\n", "")
    return {
        **rag_files,
        "agent_app/runtime.py": '"""User-owned document ingestion and offline evidence query."""\n'
        + runtime
        + _INGEST_MAIN,
        "README.md": """# My document Agent

Install ralf-agent and run from this application directory. The default corpus
is empty. Explicitly select your own UTF-8 text/Markdown/HTML file (maximum 1MiB):

```sh
python -m agent_app ingest /absolute/path/runbook.md --document-id runbook --command-id ingest-first --expected-version 0
python -m agent_app query --query 'pool timeout' --command-id answer-first
```

Text/Markdown stays unchanged. HTML extracts normalized text, excludes script/style/
head/template/frame/object/noscript and hidden/aria-hidden=true subtrees; preformatted
code retains newlines and indentation. It never
fetches URLs or evaluates scripts. It does not render CSS or sanitize HTML for display.
The character Chunker follows the store
settings, and SQLite atomically saves document/chunks/lexical terms and the
knowledge_committed receipt. Repeating identical ingestion returns the original
receipt, including after later edits/deletion. To update, use a NEW command ID
and the current expected document version; content changes under an old command
ID conflict. Receipts contain original parser/chunker identities, raw-source
SHA256, parsed digest, chunk IDs and parsed-character locations. Paths identify
explicitly selected source files; the SDK never fetches source URIs.

The offline Provider copies lexical evidence and cites document/version/source.
No credentials, model calls, embeddings, vectors or seeded documents are used.
An unsupported question returns grounded=false. This demonstrates integration,
not semantic or real-model answer quality. The database is .ralf/runs.sqlite;
knowledge lives in .ralf/runs.sqlite.knowledge.sqlite. Use --db BEFORE the
subcommand when selecting another database.

```sh
python -m agent_app query --query 'pool timeout' --command-id queued --submit-only
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

Keep the same app definition/Provider/retriever for Run recovery. Replace parser
or Chunker through IngestionCoordinator's structural sync ports; use the atomic
IngestionKnowledgeStore/AsyncIngestionKnowledgeStore for another database.
PostgreSQL supports the same receipt contract. Vector indexing is a separate,
explicit VectorRetriever.index_document call after knowledge commit; the receipt
does not claim vector readiness or a distributed transaction. Hosts own storage
clients. See the SDK document-ingestion guide for bounds and recovery contracts.
""",
    }
