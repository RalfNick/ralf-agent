import json
import sys

from ralf_agent.starter import create_starter
from tests.test_ingestion_starter import subprocess_result


def test_offline_memory_starter_replays_after_process_restart(tmp_path):
    project = tmp_path / "memory-app"
    create_starter(project, template="memory")
    command = [sys.executable, "-m", "agent_app", "--command-id", "one"]
    first = json.loads(subprocess_result(command, cwd=project))
    second = json.loads(subprocess_result(command, cwd=project))
    assert first["task"]["state"] == "succeeded"
    assert first["memory"]["status"] == second["memory"]["status"] == "completed"
    assert first["task"]["run_id"] == second["task"]["run_id"]
    assert second["memory"]["facts"][0]["duplicate"]
    assert first["memory"]["extraction_run_id"] is None
