import json
import sys

from relf_agent.starter import create_starter
from tests.test_ingestion_starter import subprocess_result


def test_installed_context_starter_artifacts_and_factory_restart(tmp_path):
    project = tmp_path / "context-app"
    generated = create_starter(project, template="context")
    main = [sys.executable, "-m", "agent_app"]
    queued = json.loads(
        subprocess_result(
            [*main, "--input", "pool timeout", "--command-id", "one", "--submit-only"], cwd=project
        )
    )
    assert queued["state"] == "queued"
    resumed = json.loads(
        subprocess_result(
            [
                sys.executable,
                "-m",
                "relf_agent.cli",
                "--db",
                ".ralf/runs.sqlite",
                "--factory",
                generated.factory,
                "resume",
                queued["run_id"],
            ],
            cwd=project,
        )
    )
    assert resumed["state"] == "succeeded"
    assert resumed["result"]["row_count"] == 256 and resumed["result"]["sample_count"] == 3
    assert resumed["result"]["artifact"]["byte_length"] > 12000
    assert (project / ".ralf/runs.sqlite.artifacts.sqlite").exists()
    repeated = json.loads(
        subprocess_result([*main, "--input", "pool timeout", "--command-id", "one"], cwd=project)
    )
    assert repeated["run_id"] == queued["run_id"] and repeated["result"] == resumed["result"]
