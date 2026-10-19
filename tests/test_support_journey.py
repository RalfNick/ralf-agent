"""One business example advances by adding existing capabilities, not new APIs."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "support_journey.py"


def run_example(directory, stage, command, *options, expected=0):
    result = subprocess.run(
        [
            sys.executable,
            str(EXAMPLE),
            stage,
            "--data-dir",
            str(directory),
            "--command-id",
            command,
            *options,
        ],
        cwd=directory.parent,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == expected, result.stderr or result.stdout
    return json.loads(result.stdout)


@pytest.mark.parametrize("stage", ["agent", "session", "rag", "memory", "workflow"])
def test_support_ticket_stages_run_and_duplicate_commands_reuse_receipts(tmp_path, stage):
    directory = tmp_path / "journey"
    first = run_example(directory, stage, "first")
    assert first["state"] == "succeeded"
    assert first["result"]["ticket"]["ticket_id"] == "INC-001"
    assert first["model_calls"] >= 2
    again = run_example(directory, stage, "first")
    assert again["run_id"] == first["run_id"]
    assert again["result"] == first["result"]
    assert again["model_calls"] == 0
    if stage in {"rag", "memory", "workflow"}:
        assert first["result"]["knowledge"][0]["document_id"] == "cache-recovery"
    if stage in {"memory", "workflow"}:
        assert first["result"]["facts"]["response-style"] == "concise"


def test_session_second_process_reads_the_previous_turn(tmp_path):
    directory = tmp_path / "session"
    first = run_example(directory, "session", "turn-1")
    second = run_example(directory, "session", "turn-2", "--input", "What should we check next?")
    assert first["result"]["session_records"] == 0
    assert second["result"]["session_records"] >= 1
    assert second["run_id"] != first["run_id"]


def test_live_provider_does_not_fall_back_without_credentials(tmp_path):
    directory = tmp_path / "live"
    result = run_example(
        directory,
        "agent",
        "live-1",
        "--provider",
        "deepseek-chat",
        "--model",
        "test-model",
        expected=2,
    )
    assert result["error"] == "validation_error"
    assert not directory.exists()
