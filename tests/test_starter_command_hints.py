import os
import shlex
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from relf_agent.cli_views import render_result
from relf_agent.starter import create_starter


@pytest.mark.parametrize(
    "template",
    [
        "parallel",
        "mcp",
        "cli",
        "context",
        "memory",
        "observable",
        "user-input",
        "model-check",
        "ingest",
        "hybrid",
        "adapter-contracts",
        "session-contracts",
        "facts-contracts",
        "model-contracts",
        "memory-index",
    ],
)
def test_generated_text_start_command_is_accepted_by_real_parser(tmp_path, template):
    project = create_starter(tmp_path / "application with spaces", template=template)
    rendered = render_result(asdict(project))
    commands = [
        shlex.split(line.strip()) for line in rendered.splitlines() if line.startswith("  ")
    ]
    starts = [command for command in commands if command[:3] == ["python", "-m", "agent_app"]]
    assert starts
    # Execute the generated module and its real parser, then stop before any
    # tool, external model or optional service can be started.
    script = """
import argparse, runpy, sys
original = argparse.ArgumentParser.parse_args
def parse(self, *args, **kwargs):
    original(self, *args, **kwargs)
    raise SystemExit(0)
argparse.ArgumentParser.parse_args = parse
sys.argv = ['agent_app', *sys.argv[1:]]
runpy.run_module('agent_app', run_name='__main__')
"""
    for start in starts:
        result = subprocess.run(
            [sys.executable, "-c", script, *start[3:]],
            cwd=project.directory,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            },
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
