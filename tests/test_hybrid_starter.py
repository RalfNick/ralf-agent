import json
import sys

from ralf_agent.starter import create_starter

from .test_ingestion_starter import subprocess_result


def test_installed_hybrid_starter_explicit_index_query_and_resume(tmp_path):
    app = tmp_path / "hybrid"
    generated = create_starter(app, template="hybrid")
    assert generated.template == "hybrid"
    book = tmp_path / "runbook.md"
    book.write_text("# Pool timeout\nInspect the connection pool.\n", encoding="utf8")
    main = [sys.executable, "-m", "agent_app"]
    empty = json.loads(
        subprocess_result(
            [*main, "query", "--query", "pool timeout", "--command-id", "empty"], cwd=app
        )
    )
    assert empty["result"]["grounded"] is False
    ingest = [
        *main,
        "ingest",
        book,
        "--document-id",
        "pool",
        "--command-id",
        "first",
        "--expected-version",
        "0",
    ]
    first = json.loads(subprocess_result(ingest, cwd=app))
    assert first["status"] == "knowledge_committed"
    indexed = json.loads(subprocess_result([*main, "index", "--document-id", "pool"], cwd=app))
    assert indexed["status"] == "index_call_completed" and indexed["document_id"] == "pool"
    assert json.loads(subprocess_result(ingest, cwd=app)) == first
    submitted = json.loads(
        subprocess_result(
            [*main, "query", "--query", "pool timeout", "--command-id", "answer", "--submit-only"],
            cwd=app,
        )
    )
    resumed = json.loads(
        subprocess_result(
            [
                sys.executable,
                "-m",
                "ralf_agent.cli",
                "--db",
                ".ralf/runs.sqlite",
                "--factory",
                generated.factory,
                "resume",
                submitted["run_id"],
            ],
            cwd=app,
        )
    )
    assert resumed["state"] == "succeeded" and resumed["result"]["grounded"] is True
    assert all(
        c["document_id"] == "pool" and c["version"] == 1 for c in resumed["result"]["citations"]
    )
    assert (app / ".ralf/runs.sqlite.vectors.sqlite").is_file()
