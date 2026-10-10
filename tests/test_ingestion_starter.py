import json
import sys

import pytest

from ralf_agent.starter import create_starter


def subprocess_result(arguments, *, cwd):
    import os
    import subprocess
    from pathlib import Path

    import ralf_agent

    package_root = Path(ralf_agent.__file__).resolve().parent.parent
    # Only the package under test is placed on the path. Installed verification
    # therefore uses the wheel, even when the host also has an editable SDK.
    result = subprocess.run(
        [str(x) for x in arguments],
        cwd=cwd,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(package_root)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_standalone_ingest_query_receipt_replay_and_reopen(tmp_path):
    project = tmp_path / "ingest-app"
    generated = create_starter(project, template="ingest")
    assert generated.factory == "agent_app.runtime:create_engine"
    assert generated.template == "ingest"
    main = [sys.executable, "-m", "agent_app"]
    empty = json.loads(
        subprocess_result(
            [*main, "query", "--query", "pool timeout", "--command-id", "empty"], cwd=project
        )
    )
    assert empty["state"] == "succeeded" and empty["result"]["grounded"] is False
    source = tmp_path / "runbook.md"
    source.write_text(
        "# Pool timeout\n\nInspect the connection pool before changing configuration.\n",
        encoding="utf8",
    )
    cmd = [
        *main,
        "ingest",
        source,
        "--document-id",
        "pool-guide",
        "--command-id",
        "ingest-first",
        "--expected-version",
        "0",
    ]
    first = json.loads(subprocess_result(cmd, cwd=project))
    assert first["status"] == "knowledge_committed" and first["document_version"] == 1
    assert json.loads(subprocess_result(cmd, cwd=project)) == first
    submitted = json.loads(
        subprocess_result(
            [*main, "query", "--query", "pool timeout", "--command-id", "answer", "--submit-only"],
            cwd=project,
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
            cwd=project,
        )
    )
    assert resumed["state"] == "succeeded" and resumed["result"]["grounded"] is True
    citation = resumed["result"]["citations"][0]
    assert citation["document_id"] == "pool-guide" and citation["version"] == 1
    assert citation["source_uri"] == source.resolve().as_uri()
    assert "Inspect the connection pool" in citation["excerpt"]


@pytest.mark.parametrize(
    "name,data",
    [
        ("unsupported.xlsx", b"office"),
        ("bad.pdf", b"pdf"),
        ("bad.md", b"\xff"),
        ("large.txt", b"a" * (1024 * 1024 + 1)),
        ("bad.html", b"<![foo]><p>text</p>"),
        ("bad.docx", b"not a ZIP package"),
    ],
    ids=[
        "unsupported",
        "malformed-pdf",
        "invalid-utf8",
        "too-large",
        "malformed-html",
        "malformed-docx",
    ],
)
def test_ingest_starter_rejects_bad_user_source_without_writing(tmp_path, name, data):
    project = tmp_path / "app"
    create_starter(project, template="ingest")
    source = tmp_path / name
    source.write_bytes(data)
    # subprocess_result requires success; inspect the explicit application exit here.
    import os
    import subprocess
    from pathlib import Path

    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(Path(__import__("ralf_agent").__file__).resolve().parent.parent),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_app",
            "ingest",
            str(source),
            "--document-id",
            "guide",
            "--command-id",
            "bad",
            "--expected-version",
            "0",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stderr)["code"] == "validation_error"


def test_standalone_html_ingest_query_and_receipt_replay(tmp_path):
    project = tmp_path / "html-app"
    create_starter(project, template="ingest")
    source = tmp_path / "runbook.html"
    source.write_text(
        "<h1>Pool timeout</h1><script>not evidence</script><p>Inspect connections.</p>"
    )
    main = [sys.executable, "-m", "agent_app"]
    cmd = [
        *main,
        "ingest",
        source,
        "--document-id",
        "html-guide",
        "--command-id",
        "html-first",
        "--expected-version",
        "0",
    ]
    receipt = json.loads(subprocess_result(cmd, cwd=project))
    assert receipt["status"] == "knowledge_committed"
    assert json.loads(subprocess_result(cmd, cwd=project)) == receipt
    result = json.loads(
        subprocess_result(
            [*main, "query", "--query", "pool timeout", "--command-id", "answer-html"], cwd=project
        )
    )
    assert result["state"] == "succeeded" and result["result"]["grounded"] is True
    citation = result["result"]["citations"][0]
    assert citation["document_id"] == "html-guide" and citation["version"] == 1
    assert citation["source_uri"] == source.resolve().as_uri()
    assert (
        "Inspect connections" in citation["excerpt"] and "not evidence" not in citation["excerpt"]
    )


def test_standalone_docx_ingest_query_and_original_receipt_replay(tmp_path):
    from tests.docx_fixture import docx, xml

    project = tmp_path / "docx-app"
    create_starter(project, template="ingest")
    source = tmp_path / "runbook.docx"
    source.write_bytes(docx(xml()))
    main = [sys.executable, "-m", "agent_app"]
    cmd = [
        *main,
        "ingest",
        source,
        "--document-id",
        "docx-guide",
        "--command-id",
        "docx-first",
        "--expected-version",
        "0",
    ]
    receipt = json.loads(subprocess_result(cmd, cwd=project))
    assert receipt["status"] == "knowledge_committed"
    assert json.loads(subprocess_result(cmd, cwd=project)) == receipt
    result = json.loads(
        subprocess_result(
            [*main, "query", "--query", "pool timeout", "--command-id", "answer-docx"], cwd=project
        )
    )
    assert result["state"] == "succeeded" and result["result"]["grounded"] is True
    citation = result["result"]["citations"][0]
    assert citation["document_id"] == "docx-guide" and citation["version"] == 1
    assert citation["source_uri"] == source.resolve().as_uri()
    assert "Inspect connections" in citation["excerpt"]


def test_standalone_pdf_ingest_query_and_original_receipt_replay(tmp_path):
    pytest.importorskip("pypdf", minversion="6.20")
    from tests.pdf_fixture import pdf

    project = tmp_path / "pdf-app"
    create_starter(project, template="ingest")
    source = tmp_path / "runbook.pdf"
    source.write_bytes(pdf())
    main = [sys.executable, "-m", "agent_app"]
    cmd = [
        *main,
        "ingest",
        source,
        "--document-id",
        "pdf-guide",
        "--command-id",
        "pdf-first",
        "--expected-version",
        "0",
    ]
    receipt = json.loads(subprocess_result(cmd, cwd=project))
    assert receipt["status"] == "knowledge_committed"
    assert json.loads(subprocess_result(cmd, cwd=project)) == receipt
    result = json.loads(
        subprocess_result(
            [*main, "query", "--query", "pool timeout", "--command-id", "answer-pdf"], cwd=project
        )
    )
    assert result["state"] == "succeeded" and result["result"]["grounded"] is True
    citation = result["result"]["citations"][0]
    assert citation["document_id"] == "pdf-guide" and citation["version"] == 1
    assert citation["source_uri"] == source.resolve().as_uri()
    assert "Inspect connections" in citation["excerpt"]
