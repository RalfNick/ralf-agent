import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from relf_agent import Scope, SQLiteKnowledgeStore
from relf_agent.ingestion import IngestionCoordinator
from relf_agent.ingestion_types import SourceDocument
from relf_agent.postgres import PostgresKnowledgeStore
from relf_agent.retrieval import RetrievalQuery


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("mode", ["before", "after"])
def test_process_loss_commits_all_knowledge_evidence_or_none(tmp_path, backend, mode):
    dsn = os.environ.get("RALF_TEST_POSTGRES_DSN")
    if backend == "postgres" and not dsn:
        pytest.skip("Set RALF_TEST_POSTGRES_DSN for actual PostgreSQL crash tests")
    scope = Scope("ingest-crash-" + uuid.uuid4().hex, "owner")
    path = tmp_path / "knowledge.sqlite"
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    if dsn:
        env["RALF_TEST_POSTGRES_DSN"] = dsn
    crashed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.ingestion_crash_fixture",
            backend,
            mode,
            str(path),
            scope.workspace,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert crashed.returncode == 79 and "crash-window-reached" in crashed.stdout, crashed.stderr

    async def run():
        from relf_agent.memory import memory_call

        store = (
            SQLiteKnowledgeStore(path)
            if backend == "sqlite"
            else await PostgresKnowledgeStore.connect(dsn, backend_id="crash-pg")
        )
        try:
            if backend == "postgres":
                await store.initialize()
            original = await memory_call(store.ingestion_receipt, scope, "docs", "first")
            record = await memory_call(store.get, scope, "docs", "guide")
            chunks = await memory_call(store.chunks, scope, "docs", "guide")
            result = await memory_call(store.lexical, scope, "docs", RetrievalQuery("timeout"))
            if mode == "before":
                assert original is None and record is None and chunks == [] and result.items == ()
            else:
                assert original.document_version == record.version == 1
                assert original.chunk_ids == [c.chunk_id for c in chunks] and len(result.items) == 1
            receipt = await IngestionCoordinator(store).ingest(
                scope,
                "docs",
                SourceDocument("guide", b"pool timeout diagnosis"),
                command_id="first",
                expected_version=0,
            )
            assert (
                receipt.document_version
                == (await memory_call(store.get, scope, "docs", "guide")).version
                == 1
            )
            if original:
                assert receipt == original
        finally:
            if backend == "sqlite":
                store.close()
            else:
                for table in (
                    "ralf_knowledge_terms",
                    "ralf_knowledge_chunks",
                    "ralf_knowledge_documents",
                    "ralf_knowledge_ingestions",
                ):
                    await store.connection.execute(
                        f"DELETE FROM {table} WHERE workspace=%s", (scope.workspace,)
                    )
                await store.aclose()

    asyncio.run(run())
