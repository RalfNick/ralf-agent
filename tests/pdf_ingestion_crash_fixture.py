"""Exit in a optional PDF knowledge transaction or after its commit."""

import asyncio
import os
import sys

from pdf_fixture import pdf

from relf_agent import (
    IngestionCoordinator,
    PdfDocumentParser,
    Scope,
    SourceDocument,
    SQLiteKnowledgeStore,
)


async def main():
    path, mode = sys.argv[1:]
    with SQLiteKnowledgeStore(path) as store:
        if mode == "before":
            original = store._put

            def put(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(79)

            store._put = put
        else:
            original = store.ingest

            def ingest(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(79)

            store.ingest = ingest
        await IngestionCoordinator(store, parser=PdfDocumentParser()).ingest(
            Scope(),
            "docs",
            SourceDocument("guide", pdf(), "application/pdf", "book://guide"),
            command_id="first",
            expected_version=0,
        )
    raise AssertionError("Expected process loss")


if __name__ == "__main__":
    asyncio.run(main())
