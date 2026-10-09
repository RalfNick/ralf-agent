import ast
import subprocess
import sys
from pathlib import Path

from ralf_agent.starter import create_starter


def test_default_temporal_starter_is_packaged_and_requires_explicit_service(tmp_path):
    project = tmp_path / "application"
    result = create_starter(project, template="temporal")
    assert result.template == "temporal" and result.factory is None
    source = (project / "agent_app/runtime.py").read_text()
    ast.parse(source)
    assert "LocalEngine" not in source and "orchestration_release" in source
    process = subprocess.run(
        [sys.executable, "-m", "agent_app", "status", "--run-id", "missing"],
        cwd=project,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert process.returncode == 2 and "RALF_TEMPORAL_ADDRESS" in process.stderr
    assert not (project / ".ralf").exists()
