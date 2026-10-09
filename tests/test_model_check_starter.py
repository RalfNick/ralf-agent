import json
import subprocess
import sys

from ralf_agent.starter import create_starter


def test_model_check_starter_runs_without_checkout_and_keeps_evidence(tmp_path):
    project = tmp_path / "app"
    create_starter(project, template="model-check")
    process = subprocess.run(
        [sys.executable, "-m", "agent_app"], cwd=project, text=True, capture_output=True, check=True
    )
    result = json.loads(process.stdout)
    assert result["passed"] == 5 and result["offline"] is True and result["model_quality"] is None
    assert len(list((project / ".ralf/model-check").glob("*.sqlite"))) == 5


def test_model_check_console_default_does_not_read_keys_or_call_models(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "DO_NOT_USE_FIXTURE")
    process = subprocess.run(
        [sys.executable, "-m", "ralf_agent.model_check_cli"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(process.stdout)
    assert result["status"] == "not_run" and result["calls"] == 0
    assert list(tmp_path.iterdir()) == []
