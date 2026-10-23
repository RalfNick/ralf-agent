"""Public entrypoints must run a new application under the canonical namespace."""

import importlib.util
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_new_module_runs_the_cli_and_preserves_runtime_directory(tmp_path):
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "relf_agent", "--version"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Relf-Agent 0.1.0a6"
    assert list(tmp_path.iterdir()) == []


def test_console_entrypoints_resolve_to_one_real_package():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert "relf" in scripts and "ralf" not in scripts
    for name, target in scripts.items():
        assert name == "relf" or name.startswith("relf-")
        module, function = target.split(":")
        assert module.startswith("relf_agent.")
        assert importlib.util.find_spec(module) is not None
        imported = __import__(module, fromlist=[function])
        assert callable(getattr(imported, function))


def test_new_cli_generates_a_standalone_application_that_can_run(tmp_path):
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    project = tmp_path / "application"
    created = subprocess.run(
        [sys.executable, "-m", "relf_agent", "init", str(project)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert created.returncode == 0, created.stderr
    started = subprocess.run(
        [sys.executable, "-m", "agent_app", "--ticket", "INC-001"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert started.returncode == 0, started.stderr
    assert "waiting_approval" in started.stdout


def test_operation_hints_select_the_new_command():
    spec = importlib.util.find_spec("relf_agent")
    assert spec is not None, "canonical package is missing"
    from relf_agent.cli_views import command_hint

    assert shlex.split(command_hint(".ralf/run.sqlite", None, "status", "run-1"))[0] == "relf"
