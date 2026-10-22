"""Manual release workflows keep qualification and publication separate."""

import ast
import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    path = ROOT / ".github/workflows" / name
    assert path.is_file(), f"missing manual release workflow: {name}"
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize(
    "name", ["alpha3-stage-candidate.yml", "alpha3-release-gate.yml", "pypi-publish.yml"]
)
def test_release_workflows_are_manual_and_pin_actions(name):
    spec = workflow(name)
    assert set(spec["on"]) == {"workflow_dispatch"}
    assert "id-token" not in spec["permissions"]
    for job in spec["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["ref"] == "${{ github.sha }}"
                assert step["with"]["persist-credentials"] is False


def test_native_gate_produces_a_qualified_artifact_only_after_original_gate():
    spec = workflow("alpha3-release-gate.yml")
    assert spec["permissions"] == {"contents": "read", "actions": "read"}
    job = spec["jobs"]["native-amd64"]
    assert job["if"] == "github.repository == 'RalfNick/relf-agent'"
    commands = [step.get("run", "") for step in job["steps"]]
    gate_index = next(
        i for i, command in enumerate(commands) if "tools/run_release_gate_linux.py" in command
    )
    gate = commands[gate_index]
    assert "--require-native" in gate and "--platform linux/amd64" in gate
    assert "--manifest tools/release_gate_manifest.alpha3.json" in gate
    upload = next(
        i
        for i, step in enumerate(job["steps"])
        if "qualified" in step.get("with", {}).get("name", "")
    )
    assert upload > gate_index
    assert "if" not in job["steps"][upload]
    assert "matrix" not in job


def test_pypi_publication_uses_only_checked_bytes_and_scoped_oidc():
    spec = workflow("pypi-publish.yml")
    verify = spec["jobs"]["verify"]
    publish = spec["jobs"]["publish"]
    assert "id-token" not in verify.get("permissions", {})
    checks = "\n".join(step.get("run", "") for step in verify["steps"])
    assert "tools/check_alpha3_publication.py" in checks
    assert "--run-attempt" in checks and "--checkout-sha" in checks
    assert "twine check --strict" in checks
    assert publish["needs"] == "verify"
    assert publish["environment"]["name"] == "${{ inputs.index }}"
    assert publish["permissions"]["id-token"] == "write"
    assert not any(
        step.get("uses", "").startswith("actions/checkout@") for step in publish["steps"]
    )
    steps = publish["steps"]
    upload = next(
        i
        for i, step in enumerate(steps)
        if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@")
    )
    assert any("hashlib.sha256" in step.get("run", "") for step in steps[:upload])
    assert steps[upload]["with"]["packages-dir"] == "${{ runner.temp }}/pypi-upload/"
    assert "skip-existing" not in steps[upload]["with"]
    assert not any(
        "python -m build" in step.get("run", "")
        for job in spec["jobs"].values()
        for step in job["steps"]
    )


@pytest.mark.parametrize(
    "name", ["alpha3-stage-candidate.yml", "alpha3-release-gate.yml", "pypi-publish.yml"]
)
def test_release_embedded_scripts_parse_without_running_or_publishing(name):
    for job in workflow(name)["jobs"].values():
        for step in job["steps"]:
            script = step.get("run")
            if script:
                result = subprocess.run(
                    ["bash", "-n"], input=script, text=True, capture_output=True
                )
                assert result.returncode == 0, result.stderr
                for code in re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", script, re.S):
                    ast.parse(code)
