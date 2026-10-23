import json
import sys
import time

import pytest

from relf_agent import Scope, SQLiteStore

from .test_component_example import process

FACTORY = "examples.knowledge_agent:create_engine"


@pytest.mark.parametrize(
    "query,document_id",
    [
        ("缓存连接失败怎么恢复", "cache-recovery"),
        ("postgres connection refused", "postgres-recovery"),
    ],
)
def test_example_retrieves_real_local_evidence_and_cli_recovers_from_another_cwd(
    tmp_path, query, document_id
):
    database = tmp_path / "runs.sqlite"
    submitted = json.loads(
        process(
            [
                sys.executable,
                "-m",
                "examples.knowledge_agent",
                "--db",
                database,
                "--query",
                query,
                "--submit-only",
            ],
            cwd=tmp_path,
        )
    )
    another = tmp_path / "another-working-directory"
    another.mkdir()
    done = json.loads(
        process(
            [
                sys.executable,
                "-m",
                "relf_agent",
                "--db",
                database,
                "--factory",
                FACTORY,
                "resume",
                submitted["run_id"],
            ],
            cwd=another,
        )
    )
    assert done["state"] == "succeeded", done
    output = done["result"]
    assert output["grounded"] is True and output["citations"]
    assert document_id in {citation["document_id"] for citation in output["citations"]}
    from relf_agent.retrieval import SQLiteKnowledgeStore

    with SQLiteKnowledgeStore(str(database) + ".knowledge.sqlite") as knowledge:
        for citation in output["citations"]:
            record = knowledge.get(Scope(), "runbooks", citation["document_id"])
            assert citation["version"] == record.version == 1
            assert citation["source_uri"] == record.source_uri
            assert citation["excerpt"] in record.text
            assert citation["excerpt"] in output["answer"]
    with SQLiteStore(database, readonly=True) as store:
        run = store.run(done["run_id"])
    assert len(run["actions"]) == 1 and run["actions"][0]["kind"] == "model"
    snapshot = run["actions"][0]["snapshot"]
    assert any("knowledge:" in message.get("content", "") for message in snapshot)


def test_example_refuses_to_answer_without_retrieved_evidence(tmp_path):
    done = json.loads(
        process(
            [
                sys.executable,
                "-m",
                "examples.knowledge_agent",
                "--db",
                tmp_path / "runs.sqlite",
                "--query",
                "quantum entanglement teleportation",
            ],
            cwd=tmp_path,
        )
    )
    assert done["state"] == "succeeded"
    assert done["result"]["grounded"] is False
    assert done["result"]["citations"] == []
    assert "No supporting evidence" in done["result"]["answer"]


def test_factory_initialization_never_overwrites_an_updated_document(tmp_path):
    from examples.knowledge_agent import create_engine
    from relf_agent.retrieval import Document, SQLiteKnowledgeStore

    database = tmp_path / "runs.sqlite"
    with create_engine(database):
        pass
    with SQLiteKnowledgeStore(str(database) + ".knowledge.sqlite") as knowledge:
        knowledge.put(
            Scope(),
            "runbooks",
            Document(
                "cache-recovery", "使用者更新后的缓存恢复文档", source_uri="local://user/cache"
            ),
            expected_version=1,
        )
    with create_engine(database):
        pass
    with SQLiteKnowledgeStore(str(database) + ".knowledge.sqlite") as knowledge:
        document = knowledge.get(Scope(), "runbooks", "cache-recovery")
        assert document.version == 2
        assert document.text == "使用者更新后的缓存恢复文档"
        assert document.source_uri == "local://user/cache"


@pytest.mark.parametrize("retired", ["deleted", "expired"])
def test_seed_initialization_respects_retired_documents_without_blocking_startup(tmp_path, retired):
    from examples.knowledge_agent import create_engine
    from relf_agent.retrieval import Document, SQLiteKnowledgeStore

    database = tmp_path / "runs.sqlite"
    with create_engine(database):
        pass
    with SQLiteKnowledgeStore(str(database) + ".knowledge.sqlite") as knowledge:
        current = knowledge.get(Scope(), "runbooks", "cache-recovery")
        if retired == "deleted":
            knowledge.delete(
                Scope(), "runbooks", "cache-recovery", expected_version=current.version
            )
        else:
            knowledge.put(
                Scope(),
                "runbooks",
                Document("cache-recovery", current.text, source_uri=current.source_uri),
                expected_version=current.version,
                expires_at=time.time() - 1,
            )
    done = json.loads(
        process(
            [sys.executable, "-m", "examples.knowledge_agent", "--db", database, "--query", "缓存"],
            cwd=tmp_path,
        )
    )
    assert done["state"] == "succeeded" and done["result"]["grounded"] is False
    assert done["result"]["citations"] == []
    with SQLiteKnowledgeStore(str(database) + ".knowledge.sqlite") as knowledge:
        assert knowledge.get(Scope(), "runbooks", "cache-recovery") is None
