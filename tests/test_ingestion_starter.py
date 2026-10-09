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
    [("unsupported.pdf", b"pdf"), ("bad.md", b"\xff"), ("large.txt", b"a" * (1024 * 1024 + 1))],
    ids=["unsupported", "invalid-utf8", "too-large"],
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
