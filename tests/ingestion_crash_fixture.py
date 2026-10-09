"""Terminate inside a real knowledge transaction or immediately after commit."""

import asyncio
import os
import sys

from ralf_agent import Scope, SQLiteKnowledgeStore
from ralf_agent.ingestion import IngestionCoordinator
from ralf_agent.ingestion_types import SourceDocument
from ralf_agent.postgres import PostgresKnowledgeStore


def crash():
    print("crash-window-reached", flush=True)
    os._exit(79)


async def run():
    backend, mode, path, workspace = sys.argv[1:]
    if backend == "sqlite":
        store = SQLiteKnowledgeStore(path)
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
    else:

        class Store(PostgresKnowledgeStore):
            async def _write_document(self, *args, **kwargs):
                await super()._write_document(*args, **kwargs)
                if mode == "before":
                    crash()

            async def ingest(self, *args, **kwargs):
                receipt = await super().ingest(*args, **kwargs)
                if mode == "after":
                    crash()
                return receipt

        store = await Store.connect(os.environ["RALF_TEST_POSTGRES_DSN"], backend_id="crash-pg")
        await store.initialize()
    await IngestionCoordinator(store).ingest(
        Scope(workspace, "owner"),
        "docs",
        SourceDocument("guide", b"pool timeout diagnosis"),
        command_id="first",
        expected_version=0,
    )
    raise AssertionError("Expected process loss")


if __name__ == "__main__":
    asyncio.run(run())
