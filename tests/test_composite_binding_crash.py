"""Actual process death preserves selected graph/nested releases and effects."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["graph", "nested"])
@pytest.mark.parametrize(
    "window", ["model_response_recorded", "tool_receipt_recorded", "external_commit"]
)
def test_bound_process_recovery_preserves_model_and_business_effect(tmp_path, kind, window):
    fixture = Path(__file__).with_name("parallel_crash_fixture.py")
    for mode, expected in (("crash", 77), ("resume", 0)):
        process = subprocess.run(
            [sys.executable, str(fixture), str(tmp_path), window, mode, kind],
            env={"PATH": os.defpath},
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert process.returncode == expected, process.stderr
        if mode == "resume":
            result = json.loads(process.stdout)
            assert result["state"] == "succeeded"
            assert result["kernel"] == "local-bindings-2"
            assert result["result"] == {"n0": {"i": 0}, "n1": {"i": 1}}
            assert result["effects"] == 2
            assert result["model_calls"] == (5 if window == "model_response_recorded" else 4)
