"""Exit in a native SQLite HTML commit window without introducing a new authority."""

import asyncio
import os
import sys

from ralf_agent import (
    HtmlDocumentParser,
    IngestionCoordinator,
    Scope,
    SourceDocument,
    SQLiteKnowledgeStore,
)


def crash():
    os._exit(79)


async def main():
    path, mode = sys.argv[1:]
    with SQLiteKnowledgeStore(path) as store:
        if mode == "before":
            original = store._put

            def put(*args, **kwargs):
                original(*args, **kwargs)
                crash()

            store._put = put
        else:
            original = store.ingest

            def ingest(*args, **kwargs):
                original(*args, **kwargs)
                crash()

            store.ingest = ingest
        await IngestionCoordinator(store, parser=HtmlDocumentParser()).ingest(
            Scope(),
            "docs",
            SourceDocument(
                "guide",
                b"<h1>Pool timeout</h1><p>Inspect connections.</p>",
                "text/html",
                "book://guide",
            ),
            command_id="first",
            expected_version=0,
        )
    raise AssertionError("Expected process loss")


if __name__ == "__main__":
    asyncio.run(main())
