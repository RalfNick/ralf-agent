import json
import subprocess
import sys

from .test_cli import ROOT, subprocess_env


def test_offline_evaluation_reports_real_run_and_effect_metrics():
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples/evaluate.py")],
        env=subprocess_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["scope"] == "offline-runtime-regression"
    assert report["passed"] == report["total"] == 3
    assert all(case["business_writes"] == 1 for case in report["cases"])
    assert all(
        case["tool_sequence"] == ["read_ticket", "apply_change", "verify_change"]
        for case in report["cases"]
    )
