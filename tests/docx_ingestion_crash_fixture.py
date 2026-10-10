"""Exit in a native DOCX knowledge transaction or after its commit."""

import asyncio
import os
import sys

from docx_fixture import MIME, docx, xml

from ralf_agent import (
    DocxDocumentParser,
    IngestionCoordinator,
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
        await IngestionCoordinator(store, parser=DocxDocumentParser()).ingest(
            Scope(),
            "docs",
            SourceDocument("guide", docx(xml()), MIME, "book://guide"),
            command_id="first",
            expected_version=0,
        )
    raise AssertionError("Expected process loss")


if __name__ == "__main__":
    asyncio.run(main())
