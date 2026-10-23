import json
import sys
import time

import pytest

from relf_agent.errors import ValidationError
from relf_agent.starter import create_starter

from .test_starter import installed_wheel as _installed_wheel
from .test_starter import subprocess_result

installed_wheel = _installed_wheel


def test_cli_generates_an_editable_standalone_rag_template(tmp_path):
    destination = tmp_path / "knowledge-agent"
    project = json.loads(
        subprocess_result(
            [sys.executable, "-m", "relf_agent.cli", "init", destination, "--template", "rag"],
            cwd=tmp_path,
        )
    )
    assert project["module"] == "agent_app"
    assert project["factory"] == "agent_app.runtime:create_engine"
    assert (destination / "agent_app" / "runtime.py").is_file()


def test_unknown_template_is_a_typed_error_and_creates_nothing(tmp_path):
    destination = tmp_path / "unknown"
    with pytest.raises(ValidationError):
        create_starter(destination, template="unavailable")
    assert not destination.exists()


def test_rag_template_preserves_existing_user_files(tmp_path):
    destination = tmp_path / "protected"
    destination.mkdir()
    existing = destination / ".settings"
    existing.write_text("keep this", encoding="utf-8")
    with pytest.raises(ValidationError):
        create_starter(destination, template="rag")
    assert existing.read_text(encoding="utf-8") == "keep this"
    assert list(destination.iterdir()) == [existing]


@pytest.mark.parametrize("retired", ["deleted", "expired"])
def test_generated_rag_initializer_respects_retired_seed_documents(tmp_path, retired):
    from relf_agent import Scope
    from relf_agent.retrieval import Document, SQLiteKnowledgeStore

    destination = tmp_path / "rag"
    create_starter(destination, template="rag")
    database = destination / ".ralf" / "runs.sqlite"
    entry = [sys.executable, "-m", "agent_app", "--db", database, "--query", "缓存"]
    first = json.loads(subprocess_result(entry, cwd=destination))
    assert first["result"]["grounded"] is True
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
    again = json.loads(
        subprocess_result([*entry, "--command-id", "after-retiring-seed"], cwd=destination)
    )
    assert again["state"] == "succeeded"
    assert again["result"]["grounded"] is False and again["result"]["citations"] == []
    with SQLiteKnowledgeStore(str(database) + ".knowledge.sqlite") as knowledge:
        assert knowledge.get(Scope(), "runbooks", "cache-recovery") is None


@pytest.mark.parametrize(
    "query,document_id",
    [
        ("缓存连接失败怎么恢复", "cache-recovery"),
        ("postgres connection refused", "postgres-recovery"),
        ("quantum entanglement teleportation", None),
    ],
)
def test_installed_wheel_rag_app_retrieves_and_recovers_without_repository_imports(
    tmp_path, installed_wheel, query, document_id
):
    python, ralf = installed_wheel
    destination = tmp_path / "standalone-rag"
    generated = json.loads(
        subprocess_result([ralf, "init", destination, "--template", "rag"], cwd=tmp_path)
    )
    database = destination / ".ralf" / "runs.sqlite"
    entry = [python, "-m", generated["module"], "--db", database, "--query", query]
    submitted = json.loads(subprocess_result([*entry, "--submit-only"], cwd=destination))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # A local, uninstalled app needs its explicit import path when the caller
    # leaves the project directory. No repository path or PYTHONPATH is supplied.
    resume_from_elsewhere = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from relf_agent.cli import main; raise SystemExit(main(sys.argv[2:]))"
    )
    resumed = json.loads(
        subprocess_result(
            [
                python,
                "-c",
                resume_from_elsewhere,
                destination,
                "--db",
                database,
                "--factory",
                generated["factory"],
                "resume",
                submitted["run_id"],
            ],
            cwd=elsewhere,
        )
    )
    assert resumed["state"] == "succeeded", resumed
    result = resumed["result"]
    assert result["grounded"] is (document_id is not None)
    if document_id is None:
        assert result["citations"] == [] and "No supporting evidence" in result["answer"]
    else:
        assert document_id in {citation["document_id"] for citation in result["citations"]}
        read_documents = """
import json
import sys
from relf_agent import Scope
from relf_agent.retrieval import SQLiteKnowledgeStore

with SQLiteKnowledgeStore(sys.argv[1]) as knowledge:
    print(json.dumps([
        {"document_id": document_id, "version": record.version,
         "source_uri": record.source_uri, "text": record.text}
        for document_id in ("cache-recovery", "postgres-recovery", "cafeteria-hours")
        for record in [knowledge.get(Scope(), "runbooks", document_id)]
    ], ensure_ascii=False))
"""
        actual_documents = json.loads(
            subprocess_result(
                [python, "-c", read_documents, str(database) + ".knowledge.sqlite"], cwd=elsewhere
            )
        )
        by_id = {document["document_id"]: document for document in actual_documents}
        for citation in result["citations"]:
            actual = by_id[citation["document_id"]]
            assert citation["version"] == actual["version"] == 1
            assert citation["source_uri"] == actual["source_uri"]
            assert citation["excerpt"] in actual["text"]
            assert citation["excerpt"] in result["answer"]
    replay = json.loads(subprocess_result(entry, cwd=destination))
    assert replay["run_id"] == submitted["run_id"] and replay["result"] == result
    observed = json.loads(
        subprocess_result([ralf, "--db", database, "inspect", submitted["run_id"]], cwd=elsewhere)
    )
    assert observed["run_id"] == submitted["run_id"]
